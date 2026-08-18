"""The JWT signing key must never be reachable through the public /data mount.

Regression: `data/jwt_secret.txt` was served by the StaticFiles mount, so
`GET /data/jwt_secret.txt` handed anyone the HS256 key — enough to mint a valid
admin token and bypass authentication entirely.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_secret_")
os.environ.setdefault("PROSPECTIVE_DB_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")
os.environ["STUDY_FILES_ROOT"] = f"{_tmp}/study_files"

from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from services import auth_service
from services.database import Base, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def test_secret_file_is_not_inside_the_public_data_dir():
    """`main.py` mounts data/ as StaticFiles — anything there is world-readable."""
    parts = auth_service._SECRET_FILE.resolve().parts
    assert "data" not in parts, (
        f"la clave JWT vive bajo un directorio público: {auth_service._SECRET_FILE}"
    )


def test_secret_is_not_downloadable():
    """Belt and braces: ask the running app for the old path."""
    assert client.get("/data/jwt_secret.txt").status_code == 404


def test_no_key_material_left_under_data():
    """A leftover copy from before the migration is just as dangerous."""
    data_dir = Path(auth_service.__file__).resolve().parents[1] / "data"
    if not data_dir.is_dir():
        return
    leaked = [p.name for p in data_dir.glob("*secret*")] + [p.name for p in data_dir.glob("*.key")]
    assert not leaked, f"material de clave dentro del directorio público data/: {leaked}"
