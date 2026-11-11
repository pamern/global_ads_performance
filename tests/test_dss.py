"""Focused DSS tests; database integration is explicitly opt-in and rolls back."""

import contextlib
import copy
import io
import json
import os
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
from uuid import uuid4

import numpy as np
import pandas as pd

from dss.engine import (
    PLATFORMS,
    TOL,
    baseline_for,
    build_hull,
    evaluate,
    funnel_mask,
    grid_allocations,
    inside_support,
    rank_candidates,
    run_engine,
    select,
    sensitivity,
    validate_input,
    validate_output,
)
from dss.storage import (
    ROOT,
    TABLE_COLUMNS,
    connect,
    database_role,
    ensure_schema,
    persist,
    provenance,
    read_input,
    settings,
)


def csv_monthly():
    frame = pd.read_csv(
        ROOT / "data/raw/global_ads_performance_dataset.csv", parse_dates=["date"]
    ).drop_duplicates()
    frame = frame.loc[frame.date.dt.year.eq(2024)].copy()
    frame["Platform"] = frame.platform.str.replace(" Ads", "", regex=False)
    frame["Month"] = frame.date.dt.to_period("M").dt.to_timestamp()
    frame = (
        frame.groupby(["Month", "Platform"])[
            ["ad_spend", "revenue", "impressions", "conversions"]
        ]
        .sum()
        .reset_index()
        .rename(
            columns={
                "ad_spend": "AdSpend",
                "revenue": "Revenue",
                "impressions": "Impressions",
                "conversions": "Conversions",
            }
        )
    )
    for measure in ["Revenue", "Impressions", "Conversions"]:
        frame[measure + "PerDollar"] = frame[measure] / frame.AdSpend
    return frame


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = csv_monthly()
        cls.history = validate_input(cls.frame)
        cls.result = run_engine(cls.frame)

    def test_grid_simplex_and_hull(self):
        grid = grid_allocations()
        self.assertEqual(len(grid), (101 * 102) // 2)
        self.assertEqual(len(np.unique(grid, axis=0)), len(grid))
        np.testing.assert_allclose(grid.sum(axis=1), 1)
        self.assertTrue((grid >= 0).all())
        hull = build_hull(self.history, np.arange(12))
        shares = self.history.spend / self.history.spend.sum(axis=1, keepdims=True)
        self.assertTrue(inside_support(shares, hull).all())
        self.assertFalse(inside_support(np.eye(3), hull).all())

    def test_baseline_pooled_trailing_three(self):
        baseline, budget = baseline_for(self.history, np.arange(8))
        recent = self.history.spend[5:8]
        np.testing.assert_allclose(baseline, recent.sum(axis=0) / recent.sum())
        self.assertAlmostEqual(budget, recent.sum() / 3)

    def test_input_rejects_missing_duplicate_invalid_and_bad_rates(self):
        for kind in ["missing", "duplicate", "negative", "zero", "nan", "rate", "date"]:
            frame = self.frame.copy()
            if kind == "missing":
                frame = frame.iloc[:-1]
            elif kind == "duplicate":
                frame = pd.concat([frame, frame.iloc[:1]])
            elif kind == "date":
                frame.loc[0, "Month"] = pd.Timestamp("2024-01-02")
            else:
                column = "RevenuePerDollar" if kind == "rate" else "AdSpend"
                frame[column] = frame[column].astype(float)
                frame.loc[0, column] = {
                    "negative": -1,
                    "zero": 0,
                    "nan": np.nan,
                    "rate": 1234,
                }[kind]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_input(frame)

    def test_simulation_and_funnel(self):
        base, budget = baseline_for(self.history, np.arange(12))
        mix = np.array([[0.3, 0.3, 0.4]])
        outcomes, uplifts = evaluate(self.history, mix, [0, 1], base, budget)
        for metric in outcomes:
            expected = budget * (self.history.rates[metric][[0, 1]] @ mix[0])
            reference = budget * (self.history.rates[metric][[0, 1]] @ base)
            np.testing.assert_allclose(outcomes[metric][0], expected)
            np.testing.assert_allclose(uplifts[metric][0], expected / reference - 1)
        self.assertEqual(
            funnel_mask(
                {
                    "impression": np.array([[0, 0], [0, -0.01]]),
                    "conversion": np.array([[0, 0], [0, 0]]),
                }
            ).tolist(),
            [True, False],
        )

    def test_maximin_median_tie_break(self):
        allocations = np.eye(3)
        uplifts = {
            "revenue": np.array([[0.1, 0.2, 0.5], [0.1, 0.3, 0.4], [0, 1, 2]]),
            "impression": np.zeros((3, 3)),
            "conversion": np.zeros((3, 3)),
        }
        ranking = rank_candidates(allocations, uplifts)
        np.testing.assert_equal(ranking.iloc[0][PLATFORMS].to_numpy(), allocations[1])

    def test_baseline_fallback(self):
        # An empty supported grid has no eligible candidate, as in the POC fallback.
        base, _, selected, _, supported, eligible = select(
            self.history, np.arange(12), np.empty((0, 3))
        )
        self.assertEqual((supported, eligible), (0, 0))
        np.testing.assert_equal(base, selected)

    def test_degenerate_hull_is_explicit_error(self):
        history = copy.deepcopy(self.history)
        history.spend[:] = [1, 1, 1]
        with self.assertRaisesRegex(ValueError, "suy biến"):
            build_hull(history, np.arange(6))

    def test_no_future_data_in_selection(self):
        original = self.result
        frame = self.frame.copy()
        # Change July and all later economics and shares without touching Jan–Jun.
        mask = frame.Month >= pd.Timestamp("2024-07-01")
        frame.loc[mask, "AdSpend"] *= 1.7
        frame.loc[mask & frame.Platform.eq("Google"), "Revenue"] *= 3
        for measure in ["Revenue", "Impressions", "Conversions"]:
            frame[measure + "PerDollar"] = frame[measure] / frame.AdSpend
        altered = run_engine(frame)
        for strategy in ["baseline", "dss", "prev", "simple5", "matched_simple"]:

            def july(result):
                return [
                    r
                    for r in result["allocations"]
                    if r["evaluation"] == "2024-07-01" and r["strategy"] == strategy
                ]

            self.assertEqual(july(original), july(altered))
        a = next(
            r
            for r in original["validation"]
            if r["test_month"] == "2024-07-01" and r["strategy"] == "dss"
        )
        b = next(
            r
            for r in altered["validation"]
            if r["test_month"] == "2024-07-01" and r["strategy"] == "dss"
        )
        self.assertNotAlmostEqual(a["revenue_uplift"], b["revenue_uplift"])

    def test_sensitivity_formula(self):
        baseline, budget = baseline_for(self.history, np.arange(12))
        allocation = np.array([0.25, 0.35, 0.4])
        break_even, rows = sensitivity(self.history, baseline, allocation, budget)
        rates = (self.history.rates["revenue"][-3:] * self.history.spend[-3:]).sum(
            axis=0
        )
        rates /= self.history.spend[-3:].sum(axis=0)
        scaled = allocation > baseline + TOL
        gain = allocation @ rates - baseline @ rates
        if gain > TOL:
            self.assertAlmostEqual(
                break_even, 100 * gain / (allocation[scaled] @ rates[scaled])
            )
        linear = rows[0]
        self.assertAlmostEqual(
            linear["candidate_revenue"], budget * (allocation @ rates)
        )
        self.assertAlmostEqual(linear["baseline_revenue"], budget * (baseline @ rates))
        none, _ = sensitivity(self.history, baseline, baseline, budget)
        self.assertIsNone(none)

    def test_output_integrity(self):
        validate_output(self.result)
        bad = copy.deepcopy(self.result)
        bad["allocations"][0]["share"] += 0.01
        with self.assertRaises(ValueError):
            validate_output(bad)
        bad = copy.deepcopy(self.result)
        bad["scenarios"][0]["revenue"] = float("inf")
        with self.assertRaises(ValueError):
            validate_output(bad)
        bad = copy.deepcopy(self.result)
        bad["summary"]["moved_budget"] += 100
        with self.assertRaises(ValueError):
            validate_output(bad)


class PocParityTests(unittest.TestCase):
    def test_execute_notebook_code_and_compare_computed_results(self):
        # Re-execute POC formulas; never assert saved notebook outputs as constants.
        notebook = json.loads(
            (ROOT / "notebooks/02_dss_allocation_poc.ipynb").read_text()
        )
        namespace = {}
        with contextlib.redirect_stdout(io.StringIO()):
            for cell in notebook["cells"]:
                if cell["cell_type"] == "code":
                    exec(compile("".join(cell["source"]), "<POC>", "exec"), namespace)
        result = run_engine(csv_monthly())
        summary = result["summary"]
        full = pd.DataFrame(result["allocations"]).query("evaluation == 'full'")
        for name, expected in [
            ("baseline", namespace["x0"]),
            ("selected", namespace["candidate"]),
        ]:
            shares = (
                full.query("strategy == @name")
                .set_index("platform")
                .loc[PLATFORMS, "share"]
            )
            np.testing.assert_allclose(shares, expected, rtol=1e-12, atol=TOL)
        self.assertEqual(summary["supported_candidates"], len(namespace["candidates"]))
        self.assertEqual(
            summary["eligible_candidates"], int(namespace["eligible"].sum())
        )
        self.assertAlmostEqual(
            summary["break_even_deterioration_pct"], namespace["break_even_pct"]
        )
        pd.testing.assert_frame_equal(
            pd.DataFrame(result["sensitivity"]),
            namespace["beta_sensitivity"],
            atol=TOL,
            rtol=1e-12,
        )
        validation = pd.DataFrame(result["validation"])
        for _, expected in namespace["oot_validation"].iterrows():
            actual = validation[
                (validation.test_month == expected.test_month + "-01")
                & (validation.strategy == "dss")
            ].iloc[0]
            for metric in ["revenue", "impression", "conversion"]:
                self.assertAlmostEqual(
                    actual[metric + "_uplift"], expected["actual_" + metric + "_uplift"]
                )
        for _, expected in namespace["oot_benchmark_comparison"].iterrows():
            for label in ["dss", "prev", "simple5", "matched_simple"]:
                actual = validation[
                    (validation.test_month == expected.test_month + "-01")
                    & (validation.strategy == label)
                ].iloc[0]
                for metric in ["revenue_uplift", "moved_share", "uplift_per_1pp_moved"]:
                    self.assertAlmostEqual(
                        actual[metric], expected[label + "_" + metric]
                    )


class ConfigurationTests(unittest.TestCase):
    def test_local_does_not_use_dev_url(self):
        with (
            patch.dict(
                os.environ, {"DATABASE_URL": "postgresql://u:p@remote/db"}, clear=True
            ),
            patch("dss.storage.load_dotenv"),
        ):
            config = settings("local")
        self.assertEqual(config.connection["host"], "127.0.0.1")
        self.assertEqual(config.connection["port"], 55432)
        self.assertEqual(
            (config.input_schema, config.input_table), ("mart", "DssMonthly")
        )

    def test_target_guards(self):
        with (
            patch("dss.storage.load_dotenv"),
            patch("src.database.load_dotenv"),
            patch.dict(os.environ, clear=True),
        ):
            with self.assertRaises(ValueError):
                settings("other")
            with self.assertRaises(ValueError):
                settings("dev")
            with (
                patch.dict(os.environ, {"LOCAL_PGHOST": "remote"}),
                self.assertRaises(ValueError),
            ):
                settings("local")
            with (
                patch.dict(
                    os.environ, {"DATABASE_URL": "postgresql://u:p@127.0.0.1/db"}
                ),
                self.assertRaises(ValueError),
            ):
                settings("dev")

    def test_dev_uses_url_and_tls(self):
        with (
            patch("dss.storage.load_dotenv"),
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://user:secret@example.supabase.co:6543/postgres",
                },
                clear=True,
            ),
        ):
            config = settings("dev")
        self.assertEqual(config.connection["host"], "example.supabase.co")
        self.assertEqual(config.connection["sslmode"], "require")
        self.assertEqual(config.connection["port"], 6543)

    def test_pooler_role_mapping_is_limited_to_supabase_dev(self):
        config = settings("local")
        connection = dict(
            config.connection,
            host="aws-0-region.pooler.supabase.com",
            user="postgres.project-ref",
        )
        self.assertEqual(
            database_role(replace(config, target="dev", connection=connection)),
            "postgres",
        )
        self.assertEqual(
            database_role(replace(config, connection=connection)),
            "postgres.project-ref",
        )
        connection["host"] = "other.example.com"
        self.assertEqual(
            database_role(replace(config, target="dev", connection=connection)),
            "postgres.project-ref",
        )

    def test_dev_server_identity_accepts_cidr_and_rejects_loopback(self):
        config = settings("local")
        config = replace(
            config,
            target="dev",
            connection=dict(
                config.connection,
                host="aws-0-region.pooler.supabase.com",
                user="postgres.project-ref",
                dbname="postgres",
            ),
        )
        for address, message in [
            ("2001:db8::1/128", "Chưa có"),
            ("127.0.0.1/32", "server local"),
            ("::1/128", "server local"),
        ]:
            identity = Mock()
            identity.fetchone.return_value = ("postgres", "postgres", address)
            missing = Mock()
            missing.fetchone.return_value = (None,)
            conn = Mock()
            conn.execute.side_effect = [identity, missing]
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(ValueError, message),
                patch(
                    "psycopg.sql.Identifier.as_string",
                    return_value='"mart"."DssMonthly"',
                ),
            ):
                read_input(conn, config)

    def test_fingerprint_reproducible_and_changes_with_input_target(self):
        config = settings("local")
        rows = [{"Platform": "Google", "AdSpend": "1.00"}]
        run, _ = provenance(config, rows)
        self.assertEqual(run, provenance(config, rows)[0])
        self.assertNotEqual(run, provenance(config, [{"AdSpend": "2.00"}])[0])
        self.assertNotEqual(run, provenance(replace(config, target="dev"), rows)[0])


@unittest.skipUnless(
    os.getenv("NEXORA_DSS_DB_TEST") == "1", "opt-in local PostgreSQL integration"
)
class DatabaseTests(unittest.TestCase):
    def test_atomic_write_idempotency_and_rollback(self):
        config = replace(
            settings("local"), output_schema="dss_test_" + uuid4().hex[:12]
        )
        with connect(config) as conn:
            rows = read_input(conn, config)
            result = run_engine(pd.DataFrame(rows))
            run_id, metadata = provenance(config, rows)
            # Check two writes, then roll back the complete test schema.
            with self.assertRaisesRegex(RuntimeError, "rollback test"):
                with conn.transaction():
                    self.assertFalse(
                        persist(conn, config, run_id, metadata, rows, result)
                    )
                    self.assertTrue(
                        persist(conn, config, run_id, metadata, rows, result)
                    )
                    for table in TABLE_COLUMNS:
                        from psycopg import sql

                        count = conn.execute(
                            sql.SQL("select count(*) from {}.{}").format(
                                sql.Identifier(config.output_schema),
                                sql.Identifier(table),
                            )
                        ).fetchone()[0]
                        self.assertEqual(count, len(result[table]))
                    raise RuntimeError("rollback test")
            exists = conn.execute(
                "select 1 from pg_namespace where nspname=%s", (config.output_schema,)
            ).fetchone()
            self.assertIsNone(exists)
            # Force an error midway through persistence, after DDL/runs/allocations.
            from dss.storage import insert as real_insert

            def fail_insert(connection, cfg, table, values):
                if table == "scenarios":
                    raise RuntimeError("mid-write failure")
                return real_insert(connection, cfg, table, values)

            with self.assertRaisesRegex(RuntimeError, "mid-write failure"):
                with (
                    conn.transaction(),
                    patch("dss.storage.insert", side_effect=fail_insert),
                ):
                    persist(conn, config, run_id, metadata, rows, result)
            exists = conn.execute(
                "select 1 from pg_namespace where nspname=%s", (config.output_schema,)
            ).fetchone()
            self.assertIsNone(exists)
            # A foreign schema must not be adopted as DSS output.
            with self.assertRaises(ValueError):
                ensure_schema(conn, replace(config, output_schema="public"))


if __name__ == "__main__":
    unittest.main()
