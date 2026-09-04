"""Thin psycopg2 connection pool over DATABASE_URL.

All queries here target the `feedback` schema only -- this service must never
touch tables outside it on W's shared instance.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool

_pool: "psycopg2.pool.SimpleConnectionPool | None" = None


def init_pool(minconn: int = 1, maxconn: int = 10) -> None:
    global _pool
    if _pool is not None:
        return
    database_url = os.environ["DATABASE_URL"]
    _pool = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, dsn=database_url)


@contextmanager
def get_conn():
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


@contextmanager
def get_cursor(dict_rows: bool = True):
    with get_conn() as conn:
        cursor_factory = psycopg2.extras.RealDictCursor if dict_rows else None
        cur = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cur
        finally:
            cur.close()
