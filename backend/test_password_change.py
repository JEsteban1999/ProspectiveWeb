"""Password change and admin reset — the last parity gap with the desktop app.

The desktop has `auth_manager.change_password` plus an admin reset in
`user_manager`; the web had neither, so the seeded `admin/admin123` could never
be changed from the application.
"""
from __future__ import annotations

from conftest import anonymous_client
from fastapi.testclient import TestClient

from main import app
from services.auth_service import get_password_hash
from services.database import SessionLocal
from services.db_models import User

client = TestClient(app)


def _make_user(username: str, password: str, role: str = "medico") -> int:
    db = SessionLocal()
    try:
        db.query(User).filter(User.username == username).delete()
        u = User(username=username, hashed_password=get_password_hash(password),
                 full_name=username.title(), role=role, status="active", is_active=True)
        db.add(u); db.commit(); db.refresh(u)
        return u.id
    finally:
        db.close()


def _login(username: str, password: str):
    c = anonymous_client(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    return c, r


class TestChangeOwnPassword:
    def test_change_then_old_password_stops_working(self):
        _make_user("cambia", "claveVieja1")
        c, r = _login("cambia", "claveVieja1")
        assert r.status_code == 200

        assert c.post("/api/auth/change-password", json={
            "current_password": "claveVieja1", "new_password": "claveNueva9",
        }).status_code == 200

        assert _login("cambia", "claveVieja1")[1].status_code == 401
        assert _login("cambia", "claveNueva9")[1].status_code == 200

    def test_wrong_current_password_is_rejected(self):
        _make_user("noesa", "claveBuena1")
        c, _ = _login("noesa", "claveBuena1")
        r = c.post("/api/auth/change-password", json={
            "current_password": "meLaInvento", "new_password": "otraClave12",
        })
        assert r.status_code == 400
        # And the real password still works.
        assert _login("noesa", "claveBuena1")[1].status_code == 200

    def test_reusing_the_same_password_is_rejected(self):
        _make_user("misma", "claveIgual1")
        c, _ = _login("misma", "claveIgual1")
        r = c.post("/api/auth/change-password", json={
            "current_password": "claveIgual1", "new_password": "claveIgual1",
        })
        assert r.status_code == 400

    def test_short_password_is_rejected(self):
        _make_user("corta", "claveLarga1")
        c, _ = _login("corta", "claveLarga1")
        r = c.post("/api/auth/change-password", json={
            "current_password": "claveLarga1", "new_password": "corta",
        })
        assert r.status_code == 422

    def test_anonymous_cannot_change_a_password(self):
        r = anonymous_client(app).post("/api/auth/change-password", json={
            "current_password": "admin123", "new_password": "loQueSea12",
        })
        assert r.status_code == 401


class TestAdminReset:
    def test_admin_resets_a_forgotten_password(self):
        uid = _make_user("olvidadizo", "originalPass1")
        r = client.post(f"/api/auth/users/{uid}/reset-password",
                        json={"new_password": "resetPorAdmin1"})
        assert r.status_code == 200, r.text
        assert _login("olvidadizo", "resetPorAdmin1")[1].status_code == 200
        assert _login("olvidadizo", "originalPass1")[1].status_code == 401

    def test_non_admin_cannot_reset_anyone(self):
        uid = _make_user("victima", "sigueSiendoMia1")
        _make_user("curioso", "clavePropia1", role="medico")
        c, _ = _login("curioso", "clavePropia1")
        assert c.post(f"/api/auth/users/{uid}/reset-password",
                      json={"new_password": "secuestrada1"}).status_code == 403
        # Untouched.
        assert _login("victima", "sigueSiendoMia1")[1].status_code == 200

    def test_unknown_user_404(self):
        assert client.post("/api/auth/users/999999/reset-password",
                           json={"new_password": "daIgual12345"}).status_code == 404
