"""Postgres pool for the auth service. Touches the `auth` schema only."""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from psycopg2 import pool

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

_pool = None
_DIALECT = re.compile(r"^postgresql\+\w+://")


def init_pool(minconn: int = 1, maxconn: int = 5) -> None:
    global _pool
    if _pool is not None:
        return
    dsn = _DIALECT.sub("postgresql://", os.getenv("DATABASE_URL", ""))
    _pool = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, dsn=dsn)


@contextmanager
def get_cursor():
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        _pool.putconn(conn)
