"""ETL Pipeline tong hop: Tu dong tao Star Schema va nap du lieu vao PostgreSQL.

Chay doc lap bang lenh:
    python etl_pipeline.py
hoac:
    uv run python etl_pipeline.py
"""

import csv
import hashlib
import io
import logging
import os
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.schema import CreateSchema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ETL_Pipeline")

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "data" / "raw" / "global_ads_performance_dataset.csv"
CONFIG_THRESHOLDS = ROOT / "config" / "spend_thresholds.yaml"

DEFAULT_DB_URLS = [
    os.getenv("DATABASE_URL"),
    os.getenv("NEXORA_ETL_DATABASE_URL"),
    "postgresql://nexora_etl@127.0.0.1:55432/nexora_etl_local",
    "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
]


def get_db_engine():
    for url in DEFAULT_DB_URLS:
        if not url:
            continue
        try:
            engine = create_engine(url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Ket noi PostgreSQL thanh cong qua: %s", url.split("@")[-1])
            return engine
        except Exception:
            continue
    raise ConnectionError(
        "Khong the ket noi toi PostgreSQL! Hay chac chan PostgreSQL dang chay tren port 55432 hoac 5432."
    )


def decimal_ratio(num, den):
    if num is None or den is None:
        return None
    try:
        n, d = Decimal(str(num)), Decimal(str(den))
        if not n.is_finite() or not d.is_finite() or d == 0:
            return None
        return n / d
    except (InvalidOperation, ZeroDivisionError):
        return None


def chunk_list(items, size=1000):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class DataWarehouseModel:
    def __init__(self):
        self.metadata = MetaData()
        self.money = Numeric(18, 2)
        self.tables = {}
        self.dimensions = {}
        self._build_schema()

    def _build_schema(self):
        self.tables["source_file"] = Table(
            "source_file",
            self.metadata,
            Column("source_file_id", BigInteger, Identity(), primary_key=True),
            Column("dataset", Text, nullable=False),
            Column("sha256", String(64), nullable=False),
            Column("original_filename", Text, nullable=False),
            Column("headers", JSONB, nullable=False),
            Column("row_count", BigInteger, nullable=False),
            Column("byte_count", BigInteger, nullable=False),
            Column("received_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
            UniqueConstraint("dataset", "sha256"),
            schema="raw",
        )

        self.tables["source_row"] = Table(
            "ads_source_row",
            self.metadata,
            Column("source_file_id", BigInteger, ForeignKey("raw.source_file.source_file_id"), primary_key=True),
            Column("source_row_number", BigInteger, primary_key=True),
            Column("payload", JSONB, nullable=False),
            schema="raw",
        )

        self.tables["run"] = Table(
            "etl_run",
            self.metadata,
            Column("run_id", String(36), primary_key=True),
            Column("source_file_id", BigInteger, ForeignKey("raw.source_file.source_file_id")),
            Column("dataset", Text, nullable=False),
            Column("fingerprint", String(64), nullable=False),
            Column("status", String(16), nullable=False),
            Column("config_snapshot", JSONB, nullable=False),
            Column("started_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
            Column("finished_at", DateTime(timezone=True)),
            Column("summary", JSONB),
            Column("error_type", Text),
            schema="raw",
        )

        self.tables["typed"] = Table(
            "ads_typed",
            self.metadata,
            Column("run_id", String(36), ForeignKey("raw.etl_run.run_id"), primary_key=True),
            Column("source_file_id", BigInteger, primary_key=True),
            Column("source_row_number", BigInteger, primary_key=True),
            Column("date", Date, nullable=False),
            Column("platform", Text, nullable=False),
            Column("campaign_type", Text, nullable=False),
            Column("industry", Text, nullable=False),
            Column("country", Text, nullable=False),
            Column("impressions", BigInteger, nullable=False),
            Column("clicks", BigInteger, nullable=False),
            Column("ad_spend", self.money, nullable=False),
            Column("conversions", BigInteger, nullable=False),
            Column("revenue", self.money, nullable=False),
            ForeignKeyConstraint(
                ["source_file_id", "source_row_number"],
                ["raw.ads_source_row.source_file_id", "raw.ads_source_row.source_row_number"],
            ),
            schema="staging",
        )

        self.tables["issue"] = Table(
            "data_quality_issue",
            self.metadata,
            Column("issue_id", BigInteger, Identity(), primary_key=True),
            Column("run_id", String(36), ForeignKey("raw.etl_run.run_id"), nullable=False),
            Column("source_file_id", BigInteger),
            Column("source_row_number", BigInteger),
            Column("field", Text),
            Column("rule", Text, nullable=False),
            Column("severity", String(8), nullable=False),
            Column("detail", Text, nullable=False),
            schema="staging",
        )

        self.tables["validation"] = Table(
            "etl_validation",
            self.metadata,
            Column("validation_id", BigInteger, Identity(), primary_key=True),
            Column("run_id", String(36), ForeignKey("raw.etl_run.run_id"), nullable=False),
            Column("check_name", Text, nullable=False),
            Column("status", String(8), nullable=False),
            Column("expected", JSONB),
            Column("actual", JSONB),
            UniqueConstraint("run_id", "check_name"),
            schema="staging",
        )

        self.tables["enriched"] = Table(
            "ads_enriched",
            self.metadata,
            Column("run_id", String(36), ForeignKey("raw.etl_run.run_id"), primary_key=True),
            Column("source_file_id", BigInteger, primary_key=True),
            Column("source_row_number", BigInteger, primary_key=True),
            Column("spend_level", Text, nullable=False),
            Column("recalculated_kpis", JSONB, nullable=False),
            Column("source_kpis", JSONB, nullable=False),
            Column("low_bound", self.money),
            Column("high_bound", self.money),
            schema="intermediate",
        )

        self.dimensions["date"] = Table(
            "dim_date",
            self.metadata,
            Column("date_key", BigInteger, Identity(), primary_key=True),
            Column("date", Date, nullable=False, unique=True),
            Column("day", Integer, nullable=False),
            Column("month", Integer, nullable=False),
            Column("month_name", Text, nullable=False),
            Column("quarter", Integer, nullable=False),
            Column("year", Integer, nullable=False),
            Column("year_month", String(7), nullable=False),
            schema="mart",
        )

        for dim in ["platform", "campaign_type", "industry", "country"]:
            self.dimensions[dim] = Table(
                f"dim_{dim}",
                self.metadata,
                Column(f"{dim}_key", BigInteger, Identity(), primary_key=True),
                Column("name", Text, nullable=False, unique=True),
                schema="mart",
            )

        self.tables["fact"] = Table(
            "fact_ad_performance",
            self.metadata,
            Column("fact_id", BigInteger, Identity(), primary_key=True),
            Column("run_id", String(36), ForeignKey("raw.etl_run.run_id"), nullable=False),
            Column("source_file_id", BigInteger, nullable=False),
            Column("source_row_number", BigInteger, nullable=False),
            Column("date_key", BigInteger, ForeignKey("mart.dim_date.date_key"), nullable=False),
            Column("platform_key", BigInteger, ForeignKey("mart.dim_platform.platform_key"), nullable=False),
            Column("campaign_type_key", BigInteger, ForeignKey("mart.dim_campaign_type.campaign_type_key"), nullable=False),
            Column("industry_key", BigInteger, ForeignKey("mart.dim_industry.industry_key"), nullable=False),
            Column("country_key", BigInteger, ForeignKey("mart.dim_country.country_key"), nullable=False),
            Column("impressions", BigInteger, nullable=False),
            Column("clicks", BigInteger, nullable=False),
            Column("ad_spend", self.money, nullable=False),
            Column("conversions", BigInteger, nullable=False),
            Column("revenue", self.money, nullable=False),
            CheckConstraint("impressions >= 0"),
            CheckConstraint("clicks >= 0"),
            CheckConstraint("ad_spend >= 0"),
            CheckConstraint("conversions >= 0"),
            CheckConstraint("revenue >= 0"),
            UniqueConstraint("run_id", "source_file_id", "source_row_number"),
            schema="mart",
        )

        self.tables["publication"] = Table(
            "dataset_publication",
            self.metadata,
            Column("dataset", Text, primary_key=True),
            Column("published_run_id", String(36), ForeignKey("raw.etl_run.run_id"), nullable=False),
            Column("published_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
            schema="mart",
        )

    def create_database_objects(self, engine):
        with engine.begin() as conn:
            for schema in ["raw", "staging", "intermediate", "mart"]:
                conn.execute(CreateSchema(schema, if_not_exists=True))
            self.metadata.create_all(conn)

            conn.execute(text("DROP VIEW IF EXISTS mart.v_platform_month_current CASCADE;"))
            conn.execute(text("DROP VIEW IF EXISTS mart.v_ad_performance_analysis_current CASCADE;"))
            conn.execute(text("DROP VIEW IF EXISTS mart.v_fact_ad_performance_current CASCADE;"))

            conn.execute(text("""
                CREATE OR REPLACE VIEW mart.v_fact_ad_performance_current AS

                SELECT f.*
                FROM mart.fact_ad_performance f
                JOIN mart.dataset_publication p ON f.run_id = p.published_run_id
                WHERE p.dataset = 'global_ads_performance';
            """))

            conn.execute(text("""
                CREATE OR REPLACE VIEW mart.v_ad_performance_analysis_current AS
                SELECT
                    f.fact_id, f.run_id, f.source_row_number,
                    d_date.date, d_plat.name AS platform, d_camp.name AS campaign_type,
                    d_ind.name AS industry, d_cntr.name AS country,
                    f.impressions, f.clicks, f.ad_spend, f.conversions, f.revenue,
                    enr.spend_level, enr.recalculated_kpis, enr.source_kpis
                FROM mart.v_fact_ad_performance_current f
                JOIN mart.dim_date d_date ON f.date_key = d_date.date_key
                JOIN mart.dim_platform d_plat ON f.platform_key = d_plat.platform_key
                JOIN mart.dim_campaign_type d_camp ON f.campaign_type_key = d_camp.campaign_type_key
                JOIN mart.dim_industry d_ind ON f.industry_key = d_ind.industry_key
                JOIN mart.dim_country d_cntr ON f.country_key = d_cntr.country_key
                JOIN intermediate.ads_enriched enr
                  ON f.run_id = enr.run_id
                 AND f.source_file_id = enr.source_file_id
                 AND f.source_row_number = enr.source_row_number;
            """))

            conn.execute(text("""
                CREATE OR REPLACE VIEW mart.v_platform_month_current AS
                SELECT
                    run_id,
                    date_trunc('month', date)::date AS month_start,
                    platform,
                    COUNT(*)::bigint AS observations,
                    SUM(impressions)::bigint AS impressions,
                    SUM(clicks)::bigint AS clicks,
                    SUM(ad_spend)::numeric(18,2) AS ad_spend,
                    SUM(conversions)::bigint AS conversions,
                    SUM(revenue)::numeric(18,2) AS revenue,
                    (SUM(revenue)::numeric / NULLIF(SUM(ad_spend), 0)) AS revenue_per_unit_spend,
                    (SUM(conversions)::numeric / NULLIF(SUM(ad_spend), 0)) AS conversions_per_unit_spend,
                    (SUM(impressions)::numeric / NULLIF(SUM(ad_spend), 0)) AS impressions_per_unit_spend
                FROM mart.v_ad_performance_analysis_current
                GROUP BY run_id, date_trunc('month', date)::date, platform;
            """))


def extract_data(csv_path):
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Khong tim thay file CSV tai: {path}")
    content = path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    reader = csv.reader(io.StringIO(content.decode("utf-8"), newline=""))
    headers = next(reader)
    rows = [dict(zip(headers, row)) for row in reader if row]
    return {"name": path.name, "checksum": checksum, "headers": headers, "rows": rows, "byte_count": len(content)}


def transform_data(extracted, thresholds_path=None):
    thresholds_lookup = {}
    if thresholds_path and Path(thresholds_path).exists():
        with open(thresholds_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            for rec in cfg.get("records", []):
                key = (rec["country"].strip(), rec["industry"].strip())
                l_bound = rec.get("low_max", rec.get("low_bound"))
                h_bound = rec.get("medium_max", rec.get("high_bound"))
                thresholds_lookup[key] = (Decimal(str(l_bound)), Decimal(str(h_bound)))


    transformed_rows = []
    enriched_rows = []
    issues = []
    quantum = Decimal("0.01")
    seen_dims = Counter()

    for num, raw in enumerate(extracted["rows"], 1):
        try:
            row_date = datetime.strptime(raw["date"].strip(), "%Y-%m-%d").date()
            plat = raw["platform"].strip()
            camp = raw["campaign_type"].strip()
            ind = raw["industry"].strip()
            cntr = raw["country"].strip()

            imp = int(raw["impressions"].strip())
            clk = int(raw["clicks"].strip())
            spend = Decimal(raw["ad_spend"].strip()).quantize(quantum)
            conv = int(raw["conversions"].strip())
            rev = Decimal(raw["revenue"].strip()).quantize(quantum)

            if imp < 0 or clk < 0 or spend < 0 or conv < 0 or rev < 0:
                raise ValueError("Gia tri khong duoc am")

            ctr = decimal_ratio(clk, imp)
            cpc = decimal_ratio(spend, clk)
            cpa = decimal_ratio(spend, conv)
            roas = decimal_ratio(rev, spend)

            source_kpis = {
                "CTR": raw.get("CTR"),
                "CPC": raw.get("CPC"),
                "CPA": raw.get("CPA"),
                "ROAS": raw.get("ROAS"),
            }

            if "CTR" in raw and ctr is not None:
                src_ctr = Decimal(raw["CTR"])
                if abs(src_ctr - ctr) > Decimal("0.00005"):
                    issues.append({"source_row_number": num, "field": "CTR", "rule": "source_kpi_mismatch", "severity": "WARN", "detail": "CTR nguon lech dung sai"})

            dim_key = (row_date, plat, camp, ind, cntr)
            if seen_dims[dim_key]:
                issues.append({"source_row_number": num, "field": None, "rule": "repeated_dimensions", "severity": "INFO", "detail": "To hop 5 chieu xuat hien nhieu lan nhung khac so lieu"})
            seen_dims[dim_key] += 1

            t_val = thresholds_lookup.get((cntr, ind))
            if t_val is None:
                level = "Unclassified"
                low_b, high_b = None, None
            else:
                low_b, high_b = t_val
                level = "Low" if spend <= low_b else "Medium" if spend <= high_b else "High"

            item = {
                "source_row_number": num,
                "date": row_date,
                "platform": plat,
                "campaign_type": camp,
                "industry": ind,
                "country": cntr,
                "impressions": imp,
                "clicks": clk,
                "ad_spend": spend,
                "conversions": conv,
                "revenue": rev,
            }
            transformed_rows.append(item)

            enriched_rows.append({
                "source_row_number": num,
                "spend_level": level,
                "recalculated_kpis": {
                    "CTR": str(ctr) if ctr else None,
                    "CPC": str(cpc) if cpc else None,
                    "CPA": str(cpa) if cpa else None,
                    "ROAS": str(roas) if roas else None,
                },
                "source_kpis": source_kpis,
                "low_bound": low_b,
                "high_bound": high_b,
            })

        except Exception as e:
            issues.append({"source_row_number": num, "field": None, "rule": "invalid_row", "severity": "ERROR", "detail": str(e)})

    return {"rows": transformed_rows, "enriched": enriched_rows, "issues": issues}


def run_etl():
    print("=" * 65)
    print("      QUY TRINH ETL GLOBAL ADS PERFORMANCE -> POSTGRESQL")
    print("=" * 65)

    engine = get_db_engine()
    model = DataWarehouseModel()

    logger.info("Buoc 1: Kiem tra va tao Schema, Bang, Views trong PostgreSQL...")
    model.create_database_objects(engine)

    logger.info("Buoc 2: Extract - Doc du lieu CSV tu: %s", CSV_PATH)
    extracted = extract_data(CSV_PATH)
    total_raw = len(extracted["rows"])
    logger.info("-> Da doc %s dong quan sat tu file CSV", total_raw)

    logger.info("Buoc 3: Transform - Lam sach, ep kieu Decimal, gan Spend Level...")
    transformed = transform_data(extracted, CONFIG_THRESHOLDS)
    valid_rows = transformed["rows"]
    enriched_rows = transformed["enriched"]
    issues = transformed["issues"]
    logger.info("-> Hop le: %s | Loi loai bo: %s | Canh bao chat luong: %s", len(valid_rows), total_raw - len(valid_rows), len(issues))

    run_id = str(uuid.uuid4())
    dataset = "global_ads_performance"

    with engine.begin() as conn:
        logger.info("Buoc 4: Ghi nhan file nguon va luot chay (Run ID: %s)...", run_id)
        sf_table = model.tables["source_file"]
        existing_sf = conn.execute(
            select(sf_table.c.source_file_id).where((sf_table.c.dataset == dataset) & (sf_table.c.sha256 == extracted["checksum"]))
        ).scalar_one_or_none()

        if existing_sf:
            source_file_id = existing_sf
        else:
            source_file_id = conn.execute(
                pg_insert(sf_table).values(
                    dataset=dataset,
                    sha256=extracted["checksum"],
                    original_filename=extracted["name"],
                    headers=extracted["headers"],
                    row_count=total_raw,
                    byte_count=extracted["byte_count"],
                ).returning(sf_table.c.source_file_id)
            ).scalar_one()

            raw_records = [{"source_file_id": source_file_id, "source_row_number": i, "payload": r} for i, r in enumerate(extracted["rows"], 1)]
            for chunk in chunk_list(raw_records, 1000):
                conn.execute(model.tables["source_row"].insert(), chunk)

        conn.execute(
            model.tables["run"].insert().values(
                run_id=run_id,
                source_file_id=source_file_id,
                dataset=dataset,
                fingerprint=extracted["checksum"][:16],
                status="RUNNING",
                config_snapshot={"dataset": dataset, "valid_count": len(valid_rows)},
                started_at=func.now(),
            )
        )

        logger.info("Buoc 5: Dong bo cac bang Dimension (Star Schema)...")
        min_date = min(r["date"] for r in valid_rows)
        max_date = max(r["date"] for r in valid_rows)
        start_d, end_d = date(min_date.year, 1, 1), date(max_date.year, 12, 31)

        dim_date = model.dimensions["date"]
        existing_dates = set(conn.execute(select(dim_date.c.date).where(dim_date.c.date.between(start_d, end_d))).scalars().all())
        curr = start_d
        new_dates = []
        while curr <= end_d:
            if curr not in existing_dates:
                new_dates.append({
                    "date": curr, "day": curr.day, "month": curr.month,
                    "month_name": curr.strftime("%B"), "quarter": (curr.month - 1) // 3 + 1,
                    "year": curr.year, "year_month": f"{curr.year:04d}-{curr.month:02d}",
                })
            curr += timedelta(days=1)
        if new_dates:
            for chunk in chunk_list(new_dates, 1000):
                conn.execute(dim_date.insert(), chunk)
        date_map = dict(conn.execute(select(dim_date.c.date, dim_date.c.date_key)).all())

        dim_maps = {"date": date_map}
        for dim_name in ["platform", "campaign_type", "industry", "country"]:
            t_dim = model.dimensions[dim_name]
            names = {r[dim_name] for r in valid_rows}
            existing = set(conn.execute(select(t_dim.c.name).where(t_dim.c.name.in_(names))).scalars().all())
            missing = names - existing
            if missing:
                conn.execute(t_dim.insert(), [{"name": n} for n in sorted(missing)])
            dim_maps[dim_name] = dict(conn.execute(select(t_dim.c.name, t_dim.c[f"{dim_name}_key"])).all())

        logger.info("Buoc 6: Nap Staging, Enrichment va Bang Fact...")
        typed_records = [{"run_id": run_id, "source_file_id": source_file_id, **r} for r in valid_rows]
        for chunk in chunk_list(typed_records, 1000):
            conn.execute(model.tables["typed"].insert(), chunk)

        issue_records = [{"run_id": run_id, "source_file_id": source_file_id, **iss} for iss in issues]
        if issue_records:
            for chunk in chunk_list(issue_records, 1000):
                conn.execute(model.tables["issue"].insert(), chunk)

        enr_records = [{"run_id": run_id, "source_file_id": source_file_id, **enr} for enr in enriched_rows]
        for chunk in chunk_list(enr_records, 1000):
            conn.execute(model.tables["enriched"].insert(), chunk)

        fact_records = []
        for r in valid_rows:
            fact_records.append({
                "run_id": run_id,
                "source_file_id": source_file_id,
                "source_row_number": r["source_row_number"],
                "date_key": dim_maps["date"][r["date"]],
                "platform_key": dim_maps["platform"][r["platform"]],
                "campaign_type_key": dim_maps["campaign_type"][r["campaign_type"]],
                "industry_key": dim_maps["industry"][r["industry"]],
                "country_key": dim_maps["country"][r["country"]],
                "impressions": r["impressions"],
                "clicks": r["clicks"],
                "ad_spend": r["ad_spend"],
                "conversions": r["conversions"],
                "revenue": r["revenue"],
            })
        for chunk in chunk_list(fact_records, 1000):
            conn.execute(model.tables["fact"].insert(), chunk)

        logger.info("Buoc 7: Kiem tra doi chieu so lieu (Validation Checks)...")
        tot_spend = sum(r["ad_spend"] for r in valid_rows)
        tot_rev = sum(r["revenue"] for r in valid_rows)
        fact_count = conn.execute(select(func.count()).where(model.tables["fact"].c.run_id == run_id)).scalar()

        checks = [
            ("fact_count_matches", fact_count == len(valid_rows)),
            ("spend_balance", tot_spend == Decimal("11108749.09")),
            ("revenue_balance", tot_rev == Decimal("54183330.81")),
            ("no_duplicate_lineage", fact_count == len(set(r["source_row_number"] for r in valid_rows))),
        ]
        for cname, ok in checks:
            conn.execute(model.tables["validation"].insert().values(
                run_id=run_id, check_name=cname, status="PASS" if ok else "FAIL",
                expected={"valid": True}, actual={"pass": ok}
            ))
            if not ok:
                raise RuntimeError(f"Kiem tra {cname} that bai!")

        logger.info("Buoc 8: Xuat ban phien ban du lieu (Publication)...")
        pub_t = model.tables["publication"]
        conn.execute(
            pg_insert(pub_t).values(dataset=dataset, published_run_id=run_id, published_at=func.now())
            .on_conflict_do_update(index_elements=["dataset"], set_={"published_run_id": run_id, "published_at": func.now()})
        )
        conn.execute(
            model.tables["run"].update().where(model.tables["run"].c.run_id == run_id)
            .values(status="PUBLISHED", finished_at=func.now(), summary={"valid_rows": len(valid_rows), "total_spend": str(tot_spend), "total_revenue": str(tot_rev)})
        )

    print("\n" + "=" * 65)
    print("                 KET QUA XUAT DU LIEU (POSTGRESQL)")
    print("=" * 65)
    with engine.connect() as conn:
        fact_cnt = conn.execute(text("SELECT count(*) FROM mart.v_fact_ad_performance_current")).scalar()
        sums = conn.execute(text("""
            SELECT
                sum(impressions) as imp, sum(clicks) as clk,
                sum(ad_spend) as spend, sum(conversions) as conv, sum(revenue) as rev
            FROM mart.v_fact_ad_performance_current
        """)).mappings().one()
        dss_cnt = conn.execute(text("SELECT count(*) FROM mart.v_platform_month_current")).scalar()

        print("Trang thai:              DA CONG BO (PUBLISHED)")
        print(f"Run ID:                  {run_id}")
        print(f"So dong Fact hien hanh:  {fact_cnt:,} dong")
        print(f"Tong Impressions:        {sums['imp']:,}")
        print(f"Tong Clicks:             {sums['clk']:,}")
        print(f"Tong Ad Spend:           {sums['spend']:,.2f}")
        print(f"Tong Conversions:        {sums['conv']:,}")
        print(f"Tong Revenue:            {sums['rev']:,.2f}")
        print(f"View DSS (Thang x Kenh): {dss_cnt} nhom (mart.v_platform_month_current)")
        print("=" * 65)
        print("Cac bang va View da xuat san sang de PowerBI / Dashboard ket noi:")
        print("  1. mart.v_fact_ad_performance_current   (Fact chuan 1.800 dong)")
        print("  2. mart.v_ad_performance_analysis_current (Fact ghep san 5 Dimension)")
        print("  3. mart.v_platform_month_current        (Bang tong hop cho DSS)")
        print("  4. mart.dim_*                           (5 bang danh muc Platform, Country...)")
        print("=" * 65 + "\n")


if __name__ == "__main__":
    run_etl()
