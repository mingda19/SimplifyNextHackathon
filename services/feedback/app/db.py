"""Thin psycopg2 connection pool over DATABASE_URL.

All queries here target the `feedback` schema only -- this service must never
touch tables outside it on W's shared instance.
"""

from __future__ import annotations

import re
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool

from app.config import settings

_pool: "psycopg2.pool.SimpleConnectionPool | None" = None

# The shared DATABASE_URL uses the SQLAlchemy dialect suffix (postgresql+psycopg://)
# for the inventory service's SQLAlchemy/psycopg3 stack. This service talks to
# Postgres directly via psycopg2, which doesn't understand that suffix -- strip
# it rather than requiring a separately-formatted URL for this one service.
_DIALECT_SUFFIX_RE = re.compile(r"^postgresql\+\w+://")


def init_pool(minconn: int = 1, maxconn: int = 10) -> None:
    global _pool
    if _pool is not None:
        return
    dsn = _DIALECT_SUFFIX_RE.sub("postgresql://", settings.database_url)
    _pool = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, dsn=dsn)


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
