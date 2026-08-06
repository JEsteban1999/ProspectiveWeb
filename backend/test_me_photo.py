"""Tests for the logged-in user's own profile photo (Feature 11)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_mephoto_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine, SessionLocal
from services.db_models import User
from services.auth_service import get_password_hash

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _make_user(username: str, photo: bool) -> None:
    db = SessionLocal()
    u = User(username=username, full_name="Foto Test", role="medico", is_active=True,
             status="active", hashed_password=get_password_hash("secret12345"))
    if photo:
        p = Path(_tmp) / f"{username}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)  # minimal PNG-ish blob
        u.photo_path = str(p)
    db.add(u)
    db.commit()
    db.close()


def _token(username: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": "secret12345"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestMePhoto:
    def test_me_reports_has_photo_true(self):
        _make_user("withphoto", photo=True)
        tok = _token("withphoto")
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert me.status_code == 200
        assert me.json()["has_photo"] is True

    def test_me_photo_served(self):
        _make_user("withphoto2", photo=True)
        tok = _token("withphoto2")
        r = client.get("/api/auth/me/photo", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert len(r.content) > 8

    def test_no_photo_flag_false_and_404(self):
        _make_user("nophoto", photo=False)
        tok = _token("nophoto")
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert me.json()["has_photo"] is False
        r = client.get("/api/auth/me/photo", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 404

    def test_photo_requires_auth(self):
        r = client.get("/api/auth/me/photo")
        assert r.status_code in (401, 403)
