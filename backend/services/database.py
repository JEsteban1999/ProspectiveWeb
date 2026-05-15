"""SQLAlchemy database setup — Session D.

SQLite is used for local / single-server deployments.  Swap DATABASE_URL for
a PostgreSQL connection string (psycopg2 / asyncpg) for multi-user production.

Usage
-----
    from services.database import get_db, init_db
    # In FastAPI endpoint:
    db: Session = Depends(get_db)
    # In main.py startup:
    init_db()
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────── #

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'prospective.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},   # required for SQLite + threading
    echo=False,                                   # set True to log SQL
)

# Enable WAL mode for better concurrent read performance with SQLite
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── FastAPI dependency ─────────────────────────────────────────────────────── #

def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy Session; always close on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Lifecycle ──────────────────────────────────────────────────────────────── #

def init_db() -> None:
    """Create all tables (idempotent — safe to call on every startup)."""
    # Import models to register them with Base.metadata before create_all
    import services.db_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised at %s", DATA_DIR / "prospective.db")
