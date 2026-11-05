"""Explicit target configuration and atomic PostgreSQL result persistence."""

import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import psycopg
import yaml
from dotenv import load_dotenv
from psycopg import sql
from psycopg.types.json import Jsonb

from dss.engine import PARAMETERS, validate_output
from src.database import _database_url

ROOT = Path(__file__).resolve().parents[1]
MARKER = "nexora-python-dss-v1"
TABLE_KEYS = {
    "allocations": ["evaluation", "strategy", "platform"],
    "scenarios": ["evaluation", "strategy", "state_month"],
    "validation": ["test_month", "strategy"],
    "sensitivity": ["beta"],
    "history": ["month", "platform"],
}


def columns(spec, kind="double precision"):
    return {name: kind for name in spec.split()}


TABLE_COLUMNS = {
    "allocations": {
        **columns("evaluation strategy platform", "text"),
        **columns("share budget"),
    },
    "scenarios": {
        **columns("evaluation strategy", "text"),
        **columns("state_month", "date"),
        **columns(
            "revenue impression conversion revenue_uplift "
            "impression_uplift conversion_uplift"
        ),
    },
    "validation": {
        **columns("test_month train_end", "date"),
        **columns("strategy", "text"),
        **columns(
            "training_months supported_candidates eligible_candidates", "integer"
        ),
        **columns("found inside_support pass_funnel", "boolean"),
        **columns(
            "budget moved_share moved_budget revenue_uplift impression_uplift "
            "conversion_uplift uplift_per_1pp_moved"
        ),
    },
    "sensitivity": columns("beta candidate_revenue baseline_revenue revenue_uplift"),
    "history": {
        **columns("month", "date"),
        **columns("platform", "text"),
        **columns("hull_vertex", "boolean"),
        **columns(
            "spend revenue impressions conversions revenue_per_dollar "
            "impressions_per_dollar conversions_per_dollar historical_share"
        ),
    },
}
SUMMARY_COLUMNS = {
    **columns(
        "grid_candidates supported_candidates eligible_candidates paired_folds "
        "folds_dss_beats_matched",
        "integer",
    ),
    **columns("candidate_found selector_value concavity_positive", "boolean"),
    **columns("decision_status", "text"),
    **columns(
        "simulation_budget moved_share moved_budget worst_revenue_uplift "
        "median_revenue_uplift best_revenue_uplift historical_win_rate "
        "worst_impression_uplift worst_conversion_uplift break_even_deterioration_pct "
        "oot_win_rate oot_mean_uplift oot_median_uplift oot_worst_uplift "
        "matched_mean_uplift matched_median_uplift matched_worst_uplift "
        "mean_uplift_difference mean_dss_moved_share mean_matched_moved_share"
    ),
}


@dataclass
class Settings:
    target: str
    connection: dict
    input_schema: str
    input_table: str
    output_schema: str


def settings(target="local"):
    if target not in {"local", "dev"}:
        raise ValueError("Target phải là local hoặc dev.")
    # Same .env convention as src.database; shell variables always take precedence.
    load_dotenv(ROOT / ".env", override=False)
    config = yaml.safe_load((ROOT / "config/project.yaml").read_text())
    dss = config["dss"]
    input_schema = config["database"]["schemas"]["mart"]
    output_schema = dss["output_schemas"][target]
    protected = set(config["database"]["schemas"].values()) | {
        "mapping",
        "public",
        "information_schema",
    }
    if output_schema in protected or output_schema.startswith("pg_"):
        raise ValueError("DSS output schema phải tách biệt warehouse/system schemas.")
    if target == "local":
        # Defaults are read from the existing dbt profile rather than duplicated.
        from jinja2 import Environment, StrictUndefined

        def env_var(name, default=None):
            value = os.getenv(name, default)
            if value is None:
                raise ValueError(f"Thiếu biến môi trường {name}.")
            return value

        rendered = (
            Environment(undefined=StrictUndefined)
            .from_string((ROOT / "dbt-modeling/profiles.yml").read_text())
            .render(env_var=env_var)
        )
        profile = yaml.safe_load(rendered)["nexora"]["outputs"]["local"]
        connection = {
            key: profile[key] for key in ["host", "port", "user", "password", "dbname"]
        }
        if connection["host"] not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Local chỉ cho phép loopback; không truy cập Supabase.")
        # Pin localhost to loopback; avoid DNS resolving to a remote endpoint.
        if connection["host"] == "localhost":
            connection["host"] = "127.0.0.1"
    else:
        url = _database_url()
        if not url.host or not url.database or not url.username or not url.password:
            raise ValueError("Dev cần DATABASE_URL đủ host/database/user/password.")
        host = url.host.lower()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if loopback or host.endswith(".localhost"):
            raise ValueError("Dev không được trỏ về PostgreSQL local.")
        connection = dict(
            host=url.host,
            port=url.port or 5432,
            dbname=url.database,
            user=url.username,
            password=url.password,
            sslmode="require",
        )
    if (
        not connection["dbname"]
        or not connection["user"]
        or not 1 <= int(connection["port"]) <= 65535
    ):
        raise ValueError("Database/user/port không hợp lệ.")
    connection["port"] = int(connection["port"])
    connection["connect_timeout"] = 10
    connection["application_name"] = "nexora_dss_" + target
    return Settings(target, connection, input_schema, dss["input_table"], output_schema)


def database_role(config):
    user = config.connection["user"]
    # Supabase shared pooler routes role.project_ref to the PostgreSQL role.
    # https://supabase.com/docs/guides/database/connecting-to-postgres
    if config.target == "dev" and config.connection["host"].endswith(
        ".pooler.supabase.com"
    ):
        return user.rsplit(".", 1)[0]
    return user


def read_input(conn, config):
    database, user, address = conn.execute(
        "select current_database(), current_user, inet_server_addr()::text"
    ).fetchone()
    if database != config.connection["dbname"] or user != database_role(config):
        raise ValueError("Database/user thực tế khác cấu hình; dừng trước khi ghi.")
    if config.target == "dev" and (
        address is None or ipaddress.ip_interface(address).ip.is_loopback
    ):
        raise ValueError("Dev đang kết nối server local; dừng trước khi ghi.")
    relation = sql.Identifier(config.input_schema, config.input_table)
    exists = conn.execute(
        "select to_regclass(%s)", (relation.as_string(conn),)
    ).fetchone()[0]
    if exists is None:
        raise ValueError(
            f"Chưa có {relation.as_string(conn)}. Chạy: "
            "uv run python scripts/dbt_warehouse.py "
            f"build --target {config.target} --select dss_monthly "
            "(cần upstream/BI Mart)."
        )
    cursor = conn.execute(
        sql.SQL('select * from {} order by "Month", "Platform"').format(relation)
    )
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def canonical(value):
    return json.dumps(
        value, default=str, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def provenance(config, rows):
    import numpy
    import pandas
    import scipy

    code = b"".join(p.read_bytes() for p in sorted((ROOT / "dss").glob("*.py")))
    code += (ROOT / "scripts/run_dss.py").read_bytes()
    metadata = dict(
        target=config.target,
        host=config.connection["host"],
        port=config.connection["port"],
        database=config.connection["dbname"],
        input_schema=config.input_schema,
        input_table=config.input_table,
        output_schema=config.output_schema,
        input_hash=hashlib.sha256(canonical(rows).encode()).hexdigest(),
        engine_hash=hashlib.sha256(code).hexdigest(),
        parameters=PARAMETERS,
        versions=dict(
            numpy=numpy.__version__, pandas=pandas.__version__, scipy=scipy.__version__
        ),
    )
    fingerprint = hashlib.sha256(canonical(metadata).encode()).hexdigest()
    return uuid5(NAMESPACE_URL, fingerprint), metadata


def relation(config, table):
    return sql.Identifier(config.output_schema, table)


def insert(conn, config, table, rows):
    if not rows:
        return
    names = list(rows[0])
    statement = sql.SQL("insert into {} ({}) values ({})").format(
        relation(config, table),
        sql.SQL(", ").join(map(sql.Identifier, names)),
        sql.SQL(", ").join(sql.Placeholder() for _ in names),
    )
    with conn.cursor() as cursor:
        cursor.executemany(statement, [[row[name] for name in names] for row in rows])


def ensure_schema(conn, config):
    # Serialize schema creation, idempotency checks and writes across executions.
    conn.execute(
        "select pg_advisory_xact_lock(hashtext(%s))", (MARKER + config.output_schema,)
    )
    existing = conn.execute(
        "select obj_description(oid, 'pg_namespace') "
        "from pg_namespace where nspname = %s",
        (config.output_schema,),
    ).fetchone()
    if existing is not None and existing[0] != MARKER:
        raise ValueError("Output schema đã có nhưng không thuộc NEXORA DSS; không sửa.")
    if existing is None:
        conn.execute(
            sql.SQL("create schema {}").format(sql.Identifier(config.output_schema))
        )
        conn.execute(
            sql.SQL("comment on schema {} is {}").format(
                sql.Identifier(config.output_schema), sql.Literal(MARKER)
            )
        )
    definitions = {
        "runs": {
            "run_id": "uuid primary key",
            "created_at": "timestamptz not null default now()",
            "target": "text not null",
            "metadata": "jsonb not null",
            "input_snapshot": "jsonb not null",
            **SUMMARY_COLUMNS,
        },
        **{
            name: {"run_id": "uuid not null", **cols}
            for name, cols in TABLE_COLUMNS.items()
        },
        "executions": {
            "execution_id": "uuid primary key",
            "run_id": "uuid not null",
            "executed_at": "timestamptz not null default now()",
            "reused": "boolean not null",
        },
    }
    for table, cols in definitions.items():
        fields = [
            sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(kind))
            for name, kind in cols.items()
        ]
        if table in TABLE_KEYS:
            keys = ["run_id", *TABLE_KEYS[table]]
            fields.append(
                sql.SQL("primary key ({})").format(
                    sql.SQL(", ").join(map(sql.Identifier, keys))
                )
            )
        if table != "runs":
            fields.append(
                sql.SQL("foreign key (run_id) references {} (run_id)").format(
                    relation(config, "runs")
                )
            )
        conn.execute(
            sql.SQL("create table if not exists {} ({})").format(
                relation(config, table), sql.SQL(", ").join(fields)
            )
        )
        actual = conn.execute(
            "select column_name from information_schema.columns "
            "where table_schema=%s and table_name=%s",
            (config.output_schema, table),
        ).fetchall()
        if {row[0] for row in actual} != set(cols):
            raise ValueError(
                f"Output {table} khác schema hiện tại; cần migration rõ ràng."
            )


def persist(conn, config, run_id, metadata, input_rows, result):
    """Caller owns a transaction; all DDL, results and execution log commit together."""
    validate_output(result)
    ensure_schema(conn, config)
    exists = conn.execute(
        sql.SQL("select target from {} where run_id=%s").format(
            relation(config, "runs")
        ),
        (run_id,),
    ).fetchone()
    if exists and exists[0] != config.target:
        raise ValueError("Run thuộc target khác; không ghi.")
    reused = exists is not None
    if not reused:
        insert(
            conn,
            config,
            "runs",
            [
                dict(
                    run_id=run_id,
                    target=config.target,
                    metadata=Jsonb(json.loads(canonical(metadata))),
                    input_snapshot=Jsonb(json.loads(canonical(input_rows))),
                    **result["summary"],
                )
            ],
        )
        for table in TABLE_COLUMNS:
            insert(
                conn,
                config,
                table,
                [dict(run_id=run_id, **row) for row in result[table]],
            )
    insert(
        conn,
        config,
        "executions",
        [dict(execution_id=uuid4(), run_id=run_id, reused=reused)],
    )
    # Verify full row counts even on reuse; never silently accept an incomplete run.
    for table in TABLE_COLUMNS:
        count = conn.execute(
            sql.SQL("select count(*) from {} where run_id=%s").format(
                relation(config, table)
            ),
            (run_id,),
        ).fetchone()[0]
        if count != len(result[table]):
            raise ValueError(f"Output thiếu/thừa dòng: {table}.")
    return reused


def connect(config):
    return psycopg.connect(**config.connection)
