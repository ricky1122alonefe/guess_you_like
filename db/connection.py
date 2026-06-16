"""PostgreSQL connection helpers."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)

DEFAULT_URL = "postgresql://odds:odds@127.0.0.1:5432/odds"
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


@contextmanager
def connect(*, autocommit: bool = False):
    conn = psycopg2.connect(get_database_url())
    conn.autocommit = autocommit
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def cursor(*, dict_rows: bool = True):
    row_factory = RealDictCursor if dict_rows else None
    with connect() as conn:
        with conn.cursor(cursor_factory=row_factory) as cur:
            cur.execute("SET TIME ZONE 'Asia/Shanghai'")
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise


def ensure_schema() -> None:
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with connect(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    log.info("数据库 schema 已就绪")


def ping() -> bool:
    try:
        with cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            return cur.fetchone()["ok"] == 1
    except Exception as exc:
        log.debug("DB ping failed: %s", exc)
        return False
