"""Tests for admin-created active users (POST /api/auth/users)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_admincreate_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine, SessionLocal
from services.db_models import User
from services.auth_service import get_password_hash

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _seed(username: str, role: str) -> None:
    db = SessionLocal()
    if not db.query(User).filter(User.username == username).first():
        db.add(User(username=username, full_name=role.title(), role=role, is_active=True,
                    status="active", hashed_password=get_password_hash("secret12345")))
        db.commit()
    db.close()


def _token(username: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": "secret12345"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _admin_headers() -> dict:
    _seed("adm", "admin")
    return {"Authorization": f"Bearer {_token('adm')}"}


class TestAdminCreate:
    def test_creates_active_user_that_can_login(self):
        H = _admin_headers()
        r = client.post("/api/auth/users", headers=H, data={
            "username": "created1", "password": "claveSegura1", "full_name": "Dra. Nueva",
            "role": "medico", "specialty": "Neurocirugía", "hospital": "Hospital X",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["is_active"] is True
        assert body["status"] == "active"
        assert body["role"] == "medico"
        # can log in immediately (no approval)
        li = client.post("/api/auth/login", json={"username": "created1", "password": "claveSegura1"})
        assert li.status_code == 200

    def test_role_respected(self):
        H = _admin_headers()
        r = client.post("/api/auth/users", headers=H, data={
            "username": "resi1", "password": "claveSegura1", "full_name": "Res", "role": "residente",
        })
        assert r.status_code == 201
        assert r.json()["role"] == "residente"

    def test_duplicate_username_400(self):
        H = _admin_headers()
        client.post("/api/auth/users", headers=H, data={"username": "dup", "password": "claveSegura1", "full_name": "A"})
        r = client.post("/api/auth/users", headers=H, data={"username": "dup", "password": "claveSegura1", "full_name": "B"})
        assert r.status_code == 400

    def test_short_password_400(self):
        H = _admin_headers()
        r = client.post("/api/auth/users", headers=H, data={"username": "shortpw", "password": "123", "full_name": "A"})
        assert r.status_code == 400

    def test_non_admin_forbidden(self):
        _seed("viewer9", "viewer")
        H = {"Authorization": f"Bearer {_token('viewer9')}"}
        r = client.post("/api/auth/users", headers=H, data={"username": "z", "password": "claveSegura1", "full_name": "Z"})
        assert r.status_code == 403

    def test_requires_auth(self):
        from conftest import anonymous_client
        r = anonymous_client(app).post(
            "/api/auth/users",
            data={"username": "z", "password": "claveSegura1", "full_name": "Z"},
        )
        assert r.status_code in (401, 403)
