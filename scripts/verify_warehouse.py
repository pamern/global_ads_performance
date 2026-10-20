"""Compare complete Raw, Fact and dimension snapshots across a dbt rebuild."""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database import _database_url


def pascal(value):
    return "".join(part.capitalize() for part in value.split("_"))


ROOT = Path(__file__).resolve().parents[1]
MEASURES = ["impressions", "clicks", "conversions", "ad_spend", "revenue"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["local", "dev"], default="local")
    args = parser.parse_args()
    if args.target == "local":
        host = os.getenv("LOCAL_PGHOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit("Local must use loopback.")
        connection = psycopg.connect(
            host=host,
            port=os.getenv("LOCAL_PGPORT", "55432"),
            user=os.getenv("LOCAL_PGUSER", "nexora"),
            password=os.getenv("LOCAL_PGPASSWORD", ""),
            dbname=os.getenv("LOCAL_PGDATABASE", "nexora"),
        )
    else:
        url = _database_url().set(drivername="postgresql")
        connection = psycopg.connect(
            url.render_as_string(hide_password=False),
            sslmode="require",
            connect_timeout=10,
        )
    tables = [
        "FctAdPerformance",
        "DimDate",
        "DimPlatform",
        "DimCampaignType",
        "DimIndustry",
        "DimCountry",
    ]

    def snapshot():
        with connection.transaction():
            connection.execute(
                "set transaction isolation level repeatable read read only"
            )
            raw = connection.execute(
                "select to_jsonb(r)::text from raw.global_ads_performance r"
            ).fetchall()
            warehouse = {
                t: connection.execute(f'select * from mart."{t}" order by 1').fetchall()
                for t in tables
            }
            totals = {}
            for label, relation in [
                ("raw", "raw.global_ads_performance"),
                ("fact", 'mart."FctAdPerformance"'),
            ]:
                totals[label] = connection.execute(
                    "select count(*), "
                    + ", ".join(
                        f'sum("{m}"::numeric)'
                        if label == "raw"
                        else f'sum("{pascal(m)}"::numeric)'
                        for m in MEASURES
                    )
                    + f" from {relation}"
                ).fetchone()
            return Counter(raw), warehouse, totals

    with connection:
        before = snapshot()
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/dbt_warehouse.py"),
                "build",
                "--target",
                args.target,
            ],
            check=True,
        )
        after = snapshot()
        results = json.loads(
            (ROOT / "dbt-modeling/target/run_results.json").read_text()
        )
        tests = Counter(
            r["status"]
            for r in results["results"]
            if r["unique_id"].startswith(("test.", "unit_test."))
        )
        report = {
            "target": args.target,
            "tests": dict(tests),
            "raw_unchanged": before[0] == after[0],
            "all_mart_rows_and_ids_stable": before[1] == after[1],
            "reconciliation_equal": after[2]["raw"] == after[2]["fact"],
            "columns": ["row_count", *MEASURES],
            "totals": after[2],
            "dimension_counts": {
                t: len(rows) for t, rows in after[1].items() if t.startswith("Dim")
            },
        }
        output = ROOT / f"dbt-modeling/docs/verification_{args.target}.json"
        output.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(json.dumps(report, indent=2, default=str))
        if not all(
            report[k]
            for k in [
                "raw_unchanged",
                "all_mart_rows_and_ids_stable",
                "reconciliation_equal",
            ]
        ):
            raise SystemExit("Warehouse verification failed.")


if __name__ == "__main__":
    main()
