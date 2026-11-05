"""Run DSS against one explicit PostgreSQL target, without invoking dbt."""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dss.engine import run_engine
from dss.storage import (
    TABLE_COLUMNS,
    connect,
    persist,
    provenance,
    read_input,
    settings,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["local", "dev"], default="local")
    args = parser.parse_args()
    try:
        config = settings(args.target)
        with connect(config) as conn:
            # Read a coherent snapshot; atomic writes roll back on any exception.
            conn.execute("set transaction isolation level serializable")
            rows = read_input(conn, config)
            result = run_engine(pd.DataFrame(rows))
            run_id, metadata = provenance(config, rows)
            reused = persist(conn, config, run_id, metadata, rows, result)
        full = [r for r in result["allocations"] if r["evaluation"] == "full"]
        print(
            json.dumps(
                dict(
                    status="success",
                    target=config.target,
                    run_id=str(run_id),
                    reused=reused,
                    input=f"{config.input_schema}.{config.input_table}",
                    input_rows=len(rows),
                    allocations=full,
                    summary=result["summary"],
                    output_schema=config.output_schema,
                    output_tables=["runs", *TABLE_COLUMNS, "executions"],
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (ValueError, KeyError) as exc:
        print(f"DSS {args.target}: {exc}", file=sys.stderr)
    except psycopg.Error as exc:
        # Never print a connection string or database error containing row payloads.
        print(
            f"DSS {args.target}: PostgreSQL {type(exc).__name__} "
            f"(SQLSTATE {exc.sqlstate or 'connection'}). "
            "Kiểm tra server, cấu hình target và quyền schema; "
            "transaction đã rollback.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
