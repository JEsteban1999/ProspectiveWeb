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
import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────── #

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Override with PROSPECTIVE_DB_URL so the test suite (and alternate deployments)
# can point at an isolated database instead of the shared dev file. Without this
# the tests wrote patients/sessions straight into data/prospective.db.
DATABASE_URL = os.environ.get("PROSPECTIVE_DB_URL") or f"sqlite:///{DATA_DIR / 'prospective.db'}"

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
    _migrate_user_columns()
    _migrate_study_columns()
    _migrate_session_columns()
    _migrate_imaging_studies()
    logger.info("Database initialised at %s", DATA_DIR / "prospective.db")


def _migrate_user_columns() -> None:
    """Add User columns introduced after the original schema (SQLite ADD COLUMN).

    create_all() never ALTERs existing tables, so databases created before the
    self-registration feature lack `status` and the professional-profile fields.
    SQLite supports lightweight `ALTER TABLE ADD COLUMN`; we add any that are
    missing so old prospective.db files keep working without a manual migration.
    """
    from sqlalchemy import text

    new_cols = {
        "status":          "VARCHAR(16) NOT NULL DEFAULT 'active'",
        "national_id":     "VARCHAR(64) NOT NULL DEFAULT ''",
        "professional_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "specialty":       "VARCHAR(100) NOT NULL DEFAULT ''",
        "university":      "VARCHAR(200) NOT NULL DEFAULT ''",
        "hospital":        "VARCHAR(200) NOT NULL DEFAULT ''",
        "position":        "VARCHAR(100) NOT NULL DEFAULT ''",
        "orcid":           "VARCHAR(64) NOT NULL DEFAULT ''",
        "photo_path":      "VARCHAR(300) NOT NULL DEFAULT ''",
        "cv_path":         "VARCHAR(300) NOT NULL DEFAULT ''",
    }
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        for col, ddl in new_cols.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                logger.info("Migrated users table: added column %s", col)


def _migrate_study_columns() -> None:
    """Add Study clinical-case columns (desktop 'Nuevo Caso' sections 3-5)."""
    from sqlalchemy import text

    new_cols = {
        "sintomas_positivos":    "TEXT NOT NULL DEFAULT ''",
        "dx_principal":          "VARCHAR(500) NOT NULL DEFAULT ''",
        "dx_secundario":         "VARCHAR(500) NOT NULL DEFAULT ''",
        "tipo_aneurisma":        "VARCHAR(200) NOT NULL DEFAULT ''",
        "tratamiento_propuesto": "TEXT NOT NULL DEFAULT ''",
        "region_anatomica":      "VARCHAR(300) NOT NULL DEFAULT ''",
        "lateralidad":           "VARCHAR(100) NOT NULL DEFAULT ''",
        "angiographer":          "VARCHAR(300) NOT NULL DEFAULT ''",
        "mod_tac":               "BOOLEAN NOT NULL DEFAULT 0",
        "mod_angio":             "BOOLEAN NOT NULL DEFAULT 0",
        "mod_rm":                "BOOLEAN NOT NULL DEFAULT 0",
        "mod_pangio":            "BOOLEAN NOT NULL DEFAULT 0",
        # Durable study archive (study gallery): where the DICOM lives and a
        # preview thumbnail, so the gallery never touches the DICOM itself.
        "storage_prefix":        "VARCHAR(300) NOT NULL DEFAULT ''",
        "thumb_key":             "VARCHAR(300) NOT NULL DEFAULT ''",
        "n_files":               "INTEGER NOT NULL DEFAULT 0",
        "n_slices":              "INTEGER NOT NULL DEFAULT 0",
        "size_mb":               "FLOAT NOT NULL DEFAULT 0",
    }
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(studies)"))}
        for col, ddl in new_cols.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE studies ADD COLUMN {col} {ddl}"))
                logger.info("Migrated studies table: added column %s", col)


def _migrate_session_columns() -> None:
    """Link planning sessions to the imaging study they actually analysed."""
    from sqlalchemy import text

    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(planning_sessions)"))}
        if "imaging_study_id" not in existing:
            conn.execute(text("ALTER TABLE planning_sessions ADD COLUMN imaging_study_id INTEGER"))
            logger.info("Migrated planning_sessions: added column imaging_study_id")


def _migrate_imaging_studies() -> None:
    """Move each case's archived DICOM into its own imaging_studies row.

    The archive used to hang off the clinical case (one image per case). Now a
    case can hold several acquisitions, so every already-archived case gets one
    imaging study carrying its archive, and its sessions are pointed at it.
    Idempotent: a case that already has imaging rows is skipped.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "imaging_studies" not in tables or "studies" not in tables:
            return
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(studies)"))}
        if "storage_prefix" not in cols:
            return

        rows = conn.execute(text(
            "SELECT s.id, s.patient_id, s.description, s.modality, s.acquired_at, "
            "       s.storage_prefix, s.thumb_key, s.n_files, s.n_slices, s.size_mb "
            "FROM studies s "
            "WHERE s.storage_prefix != '' "
            "  AND NOT EXISTS (SELECT 1 FROM imaging_studies i WHERE i.case_id = s.id)"
        )).fetchall()

        for r in rows:
            conn.execute(text(
                "INSERT INTO imaging_studies "
                "(case_id, patient_id, description, modality, acquired_at, "
                " storage_prefix, thumb_key, n_files, n_slices, size_mb, created_at) "
                "VALUES (:cid, :pid, :desc, :mod, :acq, :pref, :thumb, :nf, :ns, :mb, CURRENT_TIMESTAMP)"
            ), {
                "cid": r[0], "pid": r[1], "desc": r[2] or "Estudio", "mod": r[3] or "",
                "acq": r[4] or "", "pref": r[5], "thumb": r[6], "nf": r[7], "ns": r[8], "mb": r[9],
            })
            new_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
            # Sessions of that case were analysing these very images.
            conn.execute(text(
                "UPDATE planning_sessions SET imaging_study_id = :iid "
                "WHERE study_id = :cid AND imaging_study_id IS NULL"
            ), {"iid": new_id, "cid": r[0]})
            logger.info("Migrated case %s archive into imaging study %s", r[0], new_id)
