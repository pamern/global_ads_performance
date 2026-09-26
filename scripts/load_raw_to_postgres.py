"""Nạp CSV vào tầng raw: uv run python scripts/load_raw_to_postgres.py."""

import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import Text, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateSchema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import load_config, project_path, setup_logging
from src.database import get_engine

logger = logging.getLogger(__name__)


def main() -> int:
    """Giữ tên cột/giá trị gốc dạng TEXT; rollback toàn bộ nếu nạp lỗi.

    Dừng nếu bảng đã tồn tại để tránh nạp trùng hoặc ghi đè dữ liệu.
    """
    setup_logging()
    config = load_config()
    path = (
        project_path(config["paths"]["raw_data_dir"]) / config["files"]["raw_dataset"]
    )
    schema = config["database"]["schemas"]["raw"]
    table = config["database"]["tables"]["raw_ads"]
    engine = get_engine()
    total = 0
    logger.info("Bắt đầu nạp %s vào %s.%s", path.name, schema, table)
    try:
        with (
            pd.read_csv(
                path,
                encoding="utf-8-sig",
                dtype=str,
                keep_default_na=False,
                chunksize=5000,
            ) as chunks,
            engine.begin() as conn,
        ):
            if inspect(conn).has_table(table, schema=schema):
                logger.warning(
                    "Bảng %s.%s đã tồn tại. Dừng nạp để tránh trùng dữ liệu.",
                    schema,
                    table,
                )
                return 1
            conn.execute(CreateSchema(schema, if_not_exists=True))
            for index, chunk in enumerate(chunks):
                chunk.to_sql(
                    table,
                    conn,
                    schema=schema,
                    if_exists="fail" if index == 0 else "append",
                    index=False,
                    dtype=Text(),
                    chunksize=1000,
                )
                total += len(chunk)
                logger.info("Đã xử lý %s dòng (chưa commit)", total)
        logger.info("Đã nạp %s dòng vào %s.%s", total, schema, table)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SQLAlchemyError as exc:
        logger.error(
            "Nạp thất bại (%s). Kiểm tra kết nối, quyền và cấu trúc bảng.",
            type(exc).__name__,
        )
        raise SystemExit(1) from None
    except (OSError, ValueError) as exc:
        logger.error("Nạp thất bại: %s", exc)
        raise SystemExit(1) from None
