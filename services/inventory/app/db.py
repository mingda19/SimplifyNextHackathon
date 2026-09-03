"""Synchronous SQLAlchemy engine and request-scoped sessions."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield one SQLAlchemy session per request and always close it."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> None:
    """Raise if Postgres cannot execute a minimal query."""

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
