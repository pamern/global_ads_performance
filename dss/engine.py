"""Pure DSS calculations, ported from notebook sections C–M, P–Q."""

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull, QhullError

PLATFORMS = ["Google", "Meta", "TikTok"]
TOL = 1e-10
BETAS = [1.0, 0.9, 0.8, 0.7]
MEASURES = {
    "revenue": ("Revenue", "RevenuePerDollar"),
    "impression": ("Impressions", "ImpressionsPerDollar"),
    "conversion": ("Conversions", "ConversionsPerDollar"),
}
PARAMETERS = {
    "year": 2024,
    "grid_step_pp": 1,
    "tolerance": TOL,
    "baseline_trailing_months": 3,
    "oot_first_test_position": 6,
    "concavity_betas": BETAS,
    "simple_benchmark_pp": 5,
    "selector_value_mean_difference": 0.001,
}


@dataclass
class History:
    frame: pd.DataFrame
    spend: np.ndarray
    rates: dict
    months: list


def validate_input(frame):
    """Require the complete POC panel, finite measures, and pooled rates."""
    required = ["Platform", "Month", "AdSpend"]
    required += [c for pair in MEASURES.values() for c in pair]
    if not set(required).issubset(frame.columns):
        raise ValueError(
            f"Input thiếu cột: {sorted(set(required) - set(frame.columns))}"
        )
    data = frame[required].copy()
    if data.isna().any().any():
        raise ValueError("Input có NULL; không tự điền hoặc bỏ dòng.")
    data["Month"] = pd.to_datetime(data["Month"], errors="raise")
    expected = set(
        product(pd.date_range("2024-01-01", periods=12, freq="MS"), PLATFORMS)
    )
    actual = set(zip(data["Month"], data["Platform"]))
    if len(data) != 36 or actual != expected:
        raise ValueError(
            "Input phải đủ 36 trạng thái duy nhất Platform × Month năm 2024."
        )
    numeric = [c for c in required if c not in ("Platform", "Month")]
    data[numeric] = data[numeric].astype(float)
    if (
        not np.isfinite(data[numeric].to_numpy()).all()
        or (data[numeric] < 0).any().any()
    ):
        raise ValueError("Measures/rates phải hữu hạn và không âm.")
    if (data["AdSpend"] <= 0).any():
        raise ValueError("AdSpend phải dương cho mọi trạng thái.")
    for measure, rate in MEASURES.values():
        if not np.allclose(
            data[rate], data[measure] / data["AdSpend"], rtol=1e-12, atol=TOL
        ):
            raise ValueError(f"{rate} không khớp ratio-of-sums.")
    data = data.sort_values(["Month", "Platform"]).reset_index(drop=True)

    def matrix(column):
        return data.pivot(index="Month", columns="Platform", values=column)[
            PLATFORMS
        ].to_numpy()

    rates = {metric: matrix(rate) for metric, (_, rate) in MEASURES.items()}
    # Zero baseline outcome makes uplift undefined; reject rather than hide it.
    if any((values.sum(axis=1) <= 0).any() for values in rates.values()):
        raise ValueError("Mỗi tháng cần tổng hiệu suất dương cho cả ba metrics.")
    return History(
        data,
        matrix("AdSpend"),
        rates,
        sorted(data["Month"].dt.strftime("%Y-%m-%d").unique().tolist()),
    )


def grid_allocations():
    return (
        np.array([(g, m, 100 - g - m) for g in range(101) for m in range(101 - g)])
        / 100
    )


def baseline_for(history, positions):
    recent = history.spend[np.asarray(positions)[-3:]]
    return recent.sum(axis=0) / recent.sum(), float(recent.sum(axis=1).mean())


def build_hull(history, positions):
    spend = history.spend[positions]
    shares = spend / spend.sum(axis=1, keepdims=True)
    try:
        return ConvexHull(shares[:, :2])
    except QhullError as exc:
        raise ValueError(
            "Historical shares suy biến; POC không định nghĩa hull thay thế."
        ) from exc


def inside_support(allocations, hull):
    return np.all(
        allocations[:, :2] @ hull.equations[:, :2].T + hull.equations[:, 2] <= TOL,
        axis=1,
    )


def evaluate(history, allocations, positions, baseline, budget):
    outcomes, uplifts = {}, {}
    for metric, states in history.rates.items():
        rates = states[positions]
        outcomes[metric] = budget * (allocations @ rates.T)
        reference = budget * (rates @ baseline)
        if (reference <= 0).any():
            raise ValueError("Baseline outcome bằng 0; uplift không xác định.")
        uplifts[metric] = outcomes[metric] / reference - 1
    return outcomes, uplifts


def funnel_mask(uplifts):
    return (uplifts["impression"].min(axis=1) >= -TOL) & (
        uplifts["conversion"].min(axis=1) >= -TOL
    )


def rank_candidates(allocations, uplifts):
    mask = funnel_mask(uplifts)
    revenue = uplifts["revenue"][mask]
    table = pd.DataFrame(allocations[mask], columns=PLATFORMS)
    table["worst_revenue_uplift"] = revenue.min(axis=1)
    table["median_revenue_uplift"] = np.median(revenue, axis=1)
    return table.sort_values(
        ["worst_revenue_uplift", "median_revenue_uplift"], ascending=False
    )


def select(history, positions, grid):
    baseline, budget = baseline_for(history, positions)
    hull = build_hull(history, positions)
    candidates = grid[inside_support(grid, hull)]
    _, uplifts = evaluate(history, candidates, positions, baseline, budget)
    ranking = rank_candidates(candidates, uplifts)
    found = not ranking.empty
    allocation = ranking.iloc[0][PLATFORMS].to_numpy() if found else baseline.copy()
    return (
        baseline,
        budget,
        allocation,
        hull,
        len(candidates),
        int(funnel_mask(uplifts).sum()),
    )


def moved(allocation, baseline):
    return float(0.5 * np.abs(allocation - baseline).sum())


def sensitivity(history, baseline, allocation, budget):
    # Pooled Q4 economics, not the average of monthly rates.
    q4_spend = history.spend[-3:]
    revenue = history.rates["revenue"][-3:] * q4_spend
    rates = revenue.sum(axis=0) / q4_spend.sum(axis=0)
    up = allocation > baseline + TOL
    gain = allocation @ rates - baseline @ rates
    scaled_revenue = allocation[up] @ rates[up]
    break_even = (
        float(100 * gain / scaled_revenue)
        if gain > TOL and scaled_revenue > 0
        else None
    )
    reference = budget * baseline * rates
    rows = []
    for beta in BETAS:
        candidate_revenue = float((reference * (allocation / baseline) ** beta).sum())
        rows.append(
            dict(
                beta=beta,
                candidate_revenue=candidate_revenue,
                baseline_revenue=float(reference.sum()),
                revenue_uplift=candidate_revenue / float(reference.sum()) - 1,
            )
        )
    return break_even, rows


def run_engine(frame):
    history = validate_input(frame)
    grid = grid_allocations()
    positions = np.arange(12)
    baseline, budget, allocation, hull, supported, eligible = select(
        history, positions, grid
    )
    allocations, scenarios, validation = [], [], []

    def record(evaluation, strategy, mix, base, amount, state_positions):
        for platform, share in zip(PLATFORMS, mix):
            allocations.append(
                dict(
                    evaluation=evaluation,
                    strategy=strategy,
                    platform=platform,
                    share=float(share),
                    budget=float(amount * share),
                )
            )
        outcomes, uplifts = evaluate(
            history, mix[None, :], state_positions, base, amount
        )
        for j, position in enumerate(state_positions):
            row = dict(
                evaluation=evaluation,
                strategy=strategy,
                state_month=history.months[position],
            )
            for metric in MEASURES:
                row[metric] = float(outcomes[metric][0, j])
                row[f"{metric}_uplift"] = float(uplifts[metric][0, j])
            scenarios.append(row)
        return uplifts

    record("full", "baseline", baseline, baseline, budget, positions)
    full_uplifts = record("full", "selected", allocation, baseline, budget, positions)
    for test in range(6, 12):
        train = np.arange(test)
        base, amount, selected, support, count, passed = select(history, train, grid)
        # All benchmark choices use training data only.
        pooled_revenue = (history.rates["revenue"][train] * history.spend[train]).sum(
            axis=0
        )
        roas = pooled_revenue / history.spend[train].sum(axis=0)
        best, worst = roas.argmax(), roas.argmin()
        direction = np.zeros(3)
        if best != worst:
            direction[best], direction[worst] = 1, -1
        movement = moved(selected, base)
        simple5 = base + 0.05 * direction
        steps = np.arange(int(np.floor(movement * 100 + TOL)) + 1) / 100
        directional = base + steps[:, None] * direction
        directional = directional[
            (directional >= 0).all(axis=1) & inside_support(directional, support)
        ]
        _, directional_uplifts = evaluate(history, directional, train, base, amount)
        ranking = rank_candidates(directional, directional_uplifts)
        matched = ranking.iloc[0][PLATFORMS].to_numpy() if not ranking.empty else None
        previous = history.spend[test - 1] / history.spend[test - 1].sum()
        evaluation = history.months[test]
        record(evaluation, "baseline", base, base, amount, [test])
        for label, mix in [
            ("dss", selected),
            ("prev", previous),
            ("simple5", simple5),
            ("matched_simple", matched),
        ]:
            row = dict(
                test_month=evaluation,
                strategy=label,
                train_end=history.months[test - 1],
                training_months=test,
                budget=amount,
                supported_candidates=count,
                eligible_candidates=passed,
                found=bool(passed) if label == "dss" else mix is not None,
            )
            if mix is None:
                row.update(
                    inside_support=False,
                    pass_funnel=False,
                    moved_share=None,
                    moved_budget=None,
                    revenue_uplift=None,
                    impression_uplift=None,
                    conversion_uplift=None,
                    uplift_per_1pp_moved=None,
                )
            else:
                test_uplifts = record(evaluation, label, mix, base, amount, [test])
                _, training_uplifts = evaluate(
                    history, mix[None, :], train, base, amount
                )
                shift = moved(mix, base)
                row.update(
                    inside_support=bool(
                        (mix >= 0).all() and inside_support(mix[None, :], support)[0]
                    ),
                    pass_funnel=bool(funnel_mask(training_uplifts)[0]),
                    moved_share=shift,
                    moved_budget=amount * shift,
                    uplift_per_1pp_moved=(
                        float(test_uplifts["revenue"].item()) / (shift * 100)
                        if shift > TOL
                        else None
                    ),
                )
                row.update(
                    {
                        f"{metric}_uplift": float(values.item())
                        for metric, values in test_uplifts.items()
                    }
                )
            validation.append(row)
    break_even, stresses = sensitivity(history, baseline, allocation, budget)
    oot = pd.DataFrame(validation).pivot(
        index="test_month", columns="strategy", values="revenue_uplift"
    )
    paired = oot["matched_simple"].notna() & oot["dss"].notna()
    difference = oot.loc[paired, "dss"] - oot.loc[paired, "matched_simple"]
    mean_difference = float(difference.mean()) if paired.any() else None
    selector_value = bool(
        paired.sum() == 6
        and (difference > TOL).all()
        and mean_difference > PARAMETERS["selector_value_mean_difference"]
    )
    r = full_uplifts["revenue"][0]
    summary = dict(
        grid_candidates=len(grid),
        supported_candidates=supported,
        eligible_candidates=eligible,
        candidate_found=bool(eligible),
        simulation_budget=budget,
        moved_share=moved(allocation, baseline),
        moved_budget=budget * moved(allocation, baseline),
        worst_revenue_uplift=float(r.min()),
        median_revenue_uplift=float(np.median(r)),
        best_revenue_uplift=float(r.max()),
        historical_win_rate=float((r > 0).mean()),
        worst_impression_uplift=float(full_uplifts["impression"].min()),
        worst_conversion_uplift=float(full_uplifts["conversion"].min()),
        break_even_deterioration_pct=break_even,
        oot_win_rate=float((oot["dss"] > 0).mean()),
        oot_mean_uplift=float(oot["dss"].mean()),
        oot_median_uplift=float(oot["dss"].median()),
        oot_worst_uplift=float(oot["dss"].min()),
        matched_mean_uplift=float(oot["matched_simple"].mean())
        if paired.any()
        else None,
        matched_median_uplift=float(oot["matched_simple"].median())
        if paired.any()
        else None,
        matched_worst_uplift=float(oot["matched_simple"].min())
        if paired.any()
        else None,
        paired_folds=int(paired.sum()),
        folds_dss_beats_matched=int((difference > TOL).sum()),
        mean_uplift_difference=mean_difference,
        mean_dss_moved_share=float(
            pd.DataFrame(validation).query("strategy == 'dss'")["moved_share"].mean()
        ),
        mean_matched_moved_share=(
            float(
                pd.DataFrame(validation)
                .query("strategy == 'matched_simple'")["moved_share"]
                .mean()
            )
            if paired.any()
            else None
        ),
        selector_value=selector_value,
        concavity_positive=all(row["revenue_uplift"] > 0 for row in stresses),
        decision_status=(
            "baseline_fallback"
            if not eligible
            else "descriptive_candidate_incremental_value"
            if selector_value
            else "descriptive_candidate_limited_selector_value"
        ),
    )
    snapshot = []
    for i, month in enumerate(history.months):
        for j, platform in enumerate(PLATFORMS):
            source = history.frame.loc[
                (history.frame["Month"] == month)
                & (history.frame["Platform"] == platform)
            ].iloc[0]
            snapshot.append(
                dict(
                    month=month,
                    platform=platform,
                    spend=float(source["AdSpend"]),
                    revenue=float(source["Revenue"]),
                    impressions=float(source["Impressions"]),
                    conversions=float(source["Conversions"]),
                    revenue_per_dollar=float(source["RevenuePerDollar"]),
                    impressions_per_dollar=float(source["ImpressionsPerDollar"]),
                    conversions_per_dollar=float(source["ConversionsPerDollar"]),
                    historical_share=float(
                        history.spend[i, j] / history.spend[i].sum()
                    ),
                    hull_vertex=bool(i in hull.vertices),
                )
            )
    result = dict(
        summary=summary,
        allocations=allocations,
        scenarios=scenarios,
        validation=validation,
        sensitivity=stresses,
        history=snapshot,
    )
    validate_output(result)
    return result


def validate_output(result):
    """Reject partial/nonfinite or inconsistent results before persistence."""

    def finite(value):
        if isinstance(value, dict):
            return all(finite(v) for v in value.values())
        if isinstance(value, list):
            return all(finite(v) for v in value)
        return not isinstance(value, (float, np.floating)) or np.isfinite(value)

    if not finite(result):
        raise ValueError("Output có NaN/Infinity.")
    if len(result["history"]) != 36 or len(result["validation"]) != 24:
        raise ValueError("Output thiếu historical states hoặc OOT folds.")
    groups = pd.DataFrame(result["allocations"]).groupby(["evaluation", "strategy"])
    for (_, strategy), rows in groups:
        if set(rows["platform"]) != set(PLATFORMS) or len(rows) != 3:
            raise ValueError("Allocation thiếu/trùng platform.")
        if not np.isclose(rows["share"].sum(), 1, atol=TOL, rtol=0):
            raise ValueError("Tổng allocation khác 1.")
        # POC retains the unconstrained simple5 benchmark, including invalid boundaries.
        if strategy != "simple5" and not rows["share"].between(-TOL, 1 + TOL).all():
            raise ValueError("Allocation ngoài simplex.")
    for table, keys in [
        ("allocations", ["evaluation", "strategy", "platform"]),
        ("scenarios", ["evaluation", "strategy", "state_month"]),
        ("validation", ["test_month", "strategy"]),
        ("sensitivity", ["beta"]),
        ("history", ["month", "platform"]),
    ]:
        if pd.DataFrame(result[table]).duplicated(keys).any():
            raise ValueError(f"Output trùng grain: {table}")
    allocation_frame = pd.DataFrame(result["allocations"])
    scenario_frame = pd.DataFrame(result["scenarios"])
    validation_frame = pd.DataFrame(result["validation"])
    for (evaluation, strategy), rows in groups:
        amount = rows["budget"].sum()
        if not np.allclose(
            rows["budget"], amount * rows["share"], atol=1e-7, rtol=1e-12
        ):
            raise ValueError("Budget không khớp allocation shares.")
        state_rows = scenario_frame[
            (scenario_frame.evaluation == evaluation)
            & (scenario_frame.strategy == strategy)
        ]
        expected_states = 12 if evaluation == "full" else 1
        if len(state_rows) != expected_states:
            raise ValueError("Output thiếu/thừa simulated states.")
    for row in result["validation"]:
        if pd.Timestamp(row["train_end"]) >= pd.Timestamp(row["test_month"]):
            raise ValueError("Training phải kết thúc trước test month.")
        if row["strategy"] == "matched_simple" and row["found"]:
            dss = validation_frame[
                (validation_frame.test_month == row["test_month"])
                & (validation_frame.strategy == "dss")
            ].iloc[0]
            if row["moved_share"] > dss["moved_share"] + TOL:
                raise ValueError("Matched benchmark vượt DSS movement.")
        if row["strategy"] in ("dss", "matched_simple") and row["found"]:
            if not row["inside_support"] or not row["pass_funnel"]:
                raise ValueError("Selected/Matched candidate không feasible.")
    expected_pairs = set(zip(allocation_frame.evaluation, allocation_frame.strategy))
    actual_pairs = set(zip(scenario_frame.evaluation, scenario_frame.strategy))
    if actual_pairs != expected_pairs:
        raise ValueError("Scenario không có allocation tương ứng.")
    full = allocation_frame[allocation_frame.evaluation == "full"]
    baseline_rows = (
        full[full.strategy == "baseline"].set_index("platform").loc[PLATFORMS]
    )
    selected_rows = (
        full[full.strategy == "selected"].set_index("platform").loc[PLATFORMS]
    )
    selected_states = scenario_frame[
        (scenario_frame.evaluation == "full") & (scenario_frame.strategy == "selected")
    ]
    movement = moved(
        selected_rows["share"].to_numpy(), baseline_rows["share"].to_numpy()
    )
    revenue = selected_states["revenue_uplift"].to_numpy()
    derived = dict(
        simulation_budget=baseline_rows["budget"].sum(),
        moved_share=movement,
        moved_budget=baseline_rows["budget"].sum() * movement,
        worst_revenue_uplift=revenue.min(),
        median_revenue_uplift=np.median(revenue),
        best_revenue_uplift=revenue.max(),
        historical_win_rate=(revenue > 0).mean(),
    )
    for key, value in derived.items():
        if not np.isclose(result["summary"][key], value, rtol=1e-12, atol=TOL):
            raise ValueError(f"Summary không khớp detail: {key}.")
    baselines = scenario_frame[scenario_frame.strategy == "baseline"]
    if not np.allclose(
        baselines[[m + "_uplift" for m in MEASURES]], 0, atol=TOL, rtol=0
    ):
        raise ValueError("Baseline uplift phải bằng 0.")
