"""Quản lý kết nối và transaction PostgreSQL qua DATABASE_URL trong .env."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url

from src.common import PROJECT_ROOT


def get_engine() -> Engine:
    """Tạo SQLAlchemy engine dùng psycopg; kết nối khi bắt đầu truy vấn."""
    url = _database_url().set(drivername="postgresql+psycopg")
    return create_engine(url, connect_args={"connect_timeout": 10}, pool_pre_ping=True)


def _database_url() -> URL:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("Thiếu DATABASE_URL trong biến môi trường hoặc .env.")
    parsed_url = make_url(url)
    if parsed_url.get_backend_name() not in {"postgresql", "postgres"}:
        raise ValueError("DATABASE_URL phải là URL kết nối PostgreSQL.")
    return parsed_url


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """Dùng `with get_connection() as conn:` để thực thi SQL.

    Tự commit khi thành công, rollback khi có lỗi và luôn đóng kết nối.
    Biến môi trường hiện có được ưu tiên hơn giá trị trong .env.
    """
    url = _database_url().set(drivername="postgresql")
    with psycopg.connect(
        url.render_as_string(hide_password=False), connect_timeout=10
    ) as connection:
        yield connection
