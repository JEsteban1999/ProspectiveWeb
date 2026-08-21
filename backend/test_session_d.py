"""Integration tests for Session D: Auth + Patients + Sessions + Longitudinal.

Run with:
    cd backend
    python -m pytest test_session_d.py -v

These tests use an in-memory SQLite database (not the real data/prospective.db)
and a temporary session directory so they are fully isolated.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Isolate test DB and session storage before importing app ──────────────── #

_tmp_data = tempfile.mkdtemp(prefix="prospective_test_")
os.environ["SESSIONS_ROOT_OVERRIDE"] = _tmp_data   # picked up by sessions.py if supported

# Point database to in-memory SQLite for this test run
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_data}/test.db"

# Stable JWT secret for tests (avoids reading/writing data/jwt_secret.txt)
os.environ["JWT_SECRET"] = "test-secret-key-do-not-use-in-production"

# ── Now import app after env vars are set ────────────────────────────────── #
from main import app  # noqa: E402
from services.database import Base, get_db, engine  # noqa: E402
from services.auth_service import seed_default_user  # noqa: E402
from services.db_models import User  # noqa: E402

# ── Override: use test-isolated DB + auto-create tables ───────────────────── #

_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db() -> Generator:
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

# Create tables and seed admin once for the whole test session
Base.metadata.create_all(bind=engine)

_seed_db = _TestingSessionLocal()
try:
    seed_default_user(_seed_db)
finally:
    _seed_db.close()

# ── Client ────────────────────────────────────────────────────────────────── #

client = TestClient(app, raise_server_exceptions=True)


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _login(username: str = "admin", password: str = "admin123") -> str:
    """Return a valid Bearer token for the given credentials."""
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_session() -> str:
    """Create a real session directory (via the sessions service) and return its ID."""
    from services.sessions import create_session, write_state
    sid = create_session()
    # Write morphometry state so save endpoint can read it
    write_state(sid, "morpho.max_diameter_mm", "7.5")
    write_state(sid, "morpho.neck_mm", "3.2")
    write_state(sid, "morpho.dome_height_mm", "5.8")
    write_state(sid, "morpho.volume_mm3", "120.4")
    write_state(sid, "morpho.ar", "1.81")
    write_state(sid, "morpho.dnr", "2.34")
    write_state(sid, "morpho.bf", "0.65")
    write_state(sid, "morpho.ui", "0.12")
    write_state(sid, "morpho.rupture_risk", "Moderado")
    write_state(sid, "dicom.modality", "CT")
    return sid


# ── A. Auth tests ─────────────────────────────────────────────────────────── #

class TestAuth:
    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_login_success(self):
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self):
        # password min_length is 6 chars; use a valid-format but wrong password
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "WRONGPWD"},
        )
        assert resp.status_code == 401
        assert "detail" in resp.json()

    def test_login_unknown_user(self):
        resp = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "badpass"},
        )
        assert resp.status_code == 401

    def test_me_authenticated(self):
        token = _login()
        resp = client.get("/api/auth/me", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"
        assert "avatar_initials" in data          # field name in UserInfo model

    def test_me_unauthenticated(self):
        from conftest import anonymous_client
        resp = anonymous_client(app).get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_invalid_token(self):
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert resp.status_code == 401

    def test_token_format(self):
        token = _login()
        # JWT has 3 base64 parts separated by dots
        parts = token.split(".")
        assert len(parts) == 3, "Expected JWT with 3 parts"


# ── B. Patient CRUD tests ─────────────────────────────────────────────────── #

class TestPatients:
    def _create_patient(self, token: str, suffix: str = "") -> dict:
        resp = client.post(
            "/api/patients",
            json={
                "surname": f"Garcia{suffix}",
                "given_name": "Maria",
                "hospital_id": f"HN-{suffix or '001'}",
                "dob": "1975-03-21",
                "sex": "F",
                "institution": "SkullApp",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_create_patient_authenticated(self):
        token = _login()
        data = self._create_patient(token, "A")
        # PatientSummary returns full_name (Surname, GivenName format), not separate fields
        assert "GarciaA" in data["full_name"]
        assert data["id"] > 0

    def test_create_patient_unauthenticated(self):
        """Unauthenticated POST still works (anonymous creation allowed)."""
        resp = client.post(
            "/api/patients",
            json={
                "surname": "Anon",
                "given_name": "User",
                "hospital_id": "HN-anon",
                "dob": "1990-01-01",
                "sex": "M",
            },
        )
        assert resp.status_code == 201

    def test_list_patients_empty_initially(self):
        # Fresh override_get_db may still have patients from prior tests in same session
        token = _login()
        resp = client.get("/api/patients", headers=_auth(token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_patients_shows_created(self):
        token = _login()
        # Create a unique patient
        unique = f"UNIQUE{uuid.uuid4().hex[:6].upper()}"
        self._create_patient(token, unique)

        resp = client.get("/api/patients", headers=_auth(token))
        assert resp.status_code == 200
        # PatientSummary has full_name (Surname, GivenName format)
        names = [p["full_name"] for p in resp.json()]
        assert any(f"Garcia{unique}" in n for n in names)

    def test_patient_required_fields(self):
        """Missing required fields should return 422."""
        resp = client.post("/api/patients", json={})
        assert resp.status_code == 422

    def test_list_studies_empty(self):
        token = _login()
        patient = self._create_patient(token, "STU")
        pid = patient["id"]

        resp = client.get(f"/api/patients/{pid}/studies", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_studies_404(self):
        resp = client.get("/api/patients/999999/studies")
        assert resp.status_code == 404


# ── C. Session save / restore / list ─────────────────────────────────────── #

class TestSessionState:
    def test_save_session_basic(self):
        sid = _make_session()
        resp = client.post(
            "/api/sessions/save",
            json={"session_id": sid, "label": "Test save", "current_step": 3},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "saved_at" in data
        assert "file_path" in data

    def test_save_session_not_found(self):
        resp = client.post(
            "/api/sessions/save",
            json={"session_id": "nonexistent-uuid", "current_step": 1},
        )
        assert resp.status_code == 404

    def test_save_session_upsert(self):
        """Saving the same session twice should not create two DB rows."""
        sid = _make_session()
        client.post(
            "/api/sessions/save",
            json={"session_id": sid, "label": "First save", "current_step": 2},
        )
        client.post(
            "/api/sessions/save",
            json={"session_id": sid, "label": "Second save", "current_step": 3},
        )
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        matching = [s for s in resp.json() if s["session_id"] == sid]
        assert len(matching) == 1
        assert matching[0]["current_step"] == 3   # updated

    def test_list_sessions(self):
        sid = _make_session()
        client.post(
            "/api/sessions/save",
            json={"session_id": sid, "label": "Listed session", "current_step": 1},
        )
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = [s["session_id"] for s in data]
        assert sid in ids

    def test_restore_session(self):
        sid = _make_session()
        client.post(
            "/api/sessions/save",
            json={"session_id": sid, "label": "To restore", "current_step": 2},
        )
        resp = client.post(f"/api/sessions/{sid}/restore")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "session_id" in data
        assert data["session_id"] != sid     # new UUID assigned
        assert data["current_step"] == 2
        assert data["label"] == "To restore"

    def test_restore_brings_the_centerline_back(self):
        """The centreline files travel in the snapshot, so the restore must hand
        the frontend enough to rehydrate them.

        Regression: it did not, so «Stent CL» kept asking to extract a
        centreline that was already sitting in the session directory — a ~30 s
        recomputation for nothing.
        """
        import numpy as np
        from services.sessions import session_subdir

        sid = _make_session()
        meshes = session_subdir(sid, "meshes")
        meshes.mkdir(parents=True, exist_ok=True)
        # A 3-4-5 triangle path: arc = 5 + 5 = 10 mm, chord = 8 mm.
        pts = np.array([[0, 0, 0], [3, 4, 0], [6, 0, 0]], dtype=np.float32)
        np.savez(meshes / "centerline_points.npz",
                 points=pts, radii=np.full(3, 1.5, dtype=np.float32))
        (meshes / "centerline.vtp").write_bytes(b"<VTKFile/>")

        client.post("/api/sessions/save",
                    json={"session_id": sid, "label": "With centerline", "current_step": 3})
        data = client.post(f"/api/sessions/{sid}/restore").json()

        assert data["centerline_mesh_url"], "el frontend no puede rehidratar la línea central"
        assert "centerline.vtp" in data["centerline_mesh_url"]
        assert data["centerline_arc_mm"] == pytest.approx(10.0, abs=0.05)

    def test_restore_without_centerline_reports_none(self):
        sid = _make_session()
        client.post("/api/sessions/save",
                    json={"session_id": sid, "label": "No centerline", "current_step": 2})
        data = client.post(f"/api/sessions/{sid}/restore").json()
        assert data["centerline_mesh_url"] == ""
        assert data["centerline_arc_mm"] == 0.0

    def test_restore_session_morpho_state(self):
        """Restored session should have morphometry written to session state."""
        sid = _make_session()
        client.post(
            "/api/sessions/save",
            json={"session_id": sid, "label": "Morpho restore test", "current_step": 3},
        )
        restore_resp = client.post(f"/api/sessions/{sid}/restore")
        new_sid = restore_resp.json()["session_id"]

        # Check that the new session state contains the morphometry values
        from services.sessions import read_state
        assert read_state(new_sid, "morpho.max_diameter_mm") == "7.5"
        assert read_state(new_sid, "morpho.rupture_risk") == "Moderado"

    def test_restore_nonexistent_session(self):
        resp = client.post("/api/sessions/nonexistent-session/restore")
        assert resp.status_code == 404

    def test_snapshot_does_not_duplicate_the_dicom(self):
        """Regression: every save copied the whole study (~1.3 GB), filling the
        disk until "Guardar progreso" failed with WinError 112. The DICOM is
        write-once inside a session, so the snapshot hard-links it; the mesh and
        volume ARE rewritten by re-running a step, so those stay real copies.
        """
        import os
        from services.sessions import (
            create_session, session_subdir, snapshot_session, SAVES_ROOT,
        )

        sid = create_session()
        (session_subdir(sid, "dicom") / "IM_0001").write_bytes(b"d" * 2048)
        (session_subdir(sid, "meshes") / "vessel_tree.vtp").write_bytes(b"m" * 512)
        snapshot_session(sid)

        saved_dicom = SAVES_ROOT / sid / "dicom" / "IM_0001"
        saved_mesh  = SAVES_ROOT / sid / "meshes" / "vessel_tree.vtp"
        assert saved_dicom.read_bytes() == b"d" * 2048
        assert saved_mesh.read_bytes() == b"m" * 512
        if os.name == "nt":
            assert saved_dicom.stat().st_nlink > 1, "el DICOM debería enlazarse, no copiarse"
            assert saved_mesh.stat().st_nlink == 1, "la malla debe ser copia: se reescribe al rehacer un paso"

        # Re-running segmentation overwrites the live mesh — the snapshot must
        # keep the version that was saved.
        (session_subdir(sid, "meshes") / "vessel_tree.vtp").write_bytes(b"NUEVA")
        assert saved_mesh.read_bytes() == b"m" * 512

    def test_restore_carries_case_and_imaging_link(self):
        """Resuming must not forget WHAT was being planned.

        The session is tied to a clinical case (study_id) and to the acquisition
        it analysed (imaging_study_id). Without these in the restore payload the
        rehydrated session loses its breadcrumb and the next save would have to
        ask the user for the case again.
        """
        from services.database import SessionLocal
        from services.db_models import Patient, Study, ImagingStudy

        db = SessionLocal()
        try:
            p = Patient(surname="Reanuda", given_name="Caso",
                        hospital_id=f"HC-RES-{uuid.uuid4().hex[:6]}")
            db.add(p); db.commit(); db.refresh(p)
            case = Study(patient_id=p.id, description="Angio control",
                         dx_principal="Aneurisma de ACoA")
            db.add(case); db.commit(); db.refresh(case)
            img = ImagingStudy(case_id=case.id, patient_id=p.id, description="3D-RA")
            db.add(img); db.commit(); db.refresh(img)
            pid, case_id, img_id = p.id, case.id, img.id
        finally:
            db.close()

        sid = _make_session()
        r = client.post("/api/sessions/save", json={
            "session_id": sid, "label": "Con caso", "current_step": 3,
            "patient_id": pid, "study_id": case_id, "imaging_study_id": img_id,
        })
        assert r.status_code == 200, r.text

        data = client.post(f"/api/sessions/{sid}/restore").json()
        assert data["study_id"] == case_id
        assert data["imaging_study_id"] == img_id
        assert data["patient_id"] == pid
        # Diagnosis first — that is what the breadcrumb shows.
        assert data["study_label"] == "Aneurisma de ACoA"

    def test_restore_returns_the_series_of_the_restored_volume(self):
        """A resumed session must not look empty on the upload step.

        The snapshot brings the volume cache back, and the viewer renders it —
        but the series card stayed blank because the payload never carried it.
        """
        import numpy as np
        from services import mpr as mprmod
        from services.sessions import create_session, write_state

        sid = create_session()
        vol = np.zeros((12, 8, 6), np.float32)
        npy, meta = mprmod._cache_paths(sid)
        np.save(npy, vol)
        meta.write_text('{"shape": [12,8,6], "spacing": [0.5,0.4,0.3], '
                        '"wc": 300, "ww": 900, "modality": "XA"}')
        write_state(sid, "dicom.series_id", "1.2.3.4")
        write_state(sid, "dicom.description", "3D-RA Prop 4s")

        assert client.post("/api/sessions/save",
                           json={"session_id": sid, "current_step": 1}).status_code == 200
        s = client.post(f"/api/sessions/{sid}/restore").json()["series"]
        assert s is not None, "el restore debe devolver la serie"
        assert s["modality"] == "XA"
        assert s["slices"] == 12
        assert s["description"] == "3D-RA Prop 4s"
        # spacing is stored [z, y, x] and exposed as x/y/z — an easy place to
        # silently transpose the voxel size.
        assert (s["spacing"]["z"], s["spacing"]["y"], s["spacing"]["x"]) == (0.5, 0.4, 0.3)

    def test_durable_save_survives_ttl_purge_and_rehydrates_files(self):
        """The core of resumable sessions: a saved session's files (mesh + volume)
        survive deletion of the live dir (TTL purge) and are copied back into a
        fresh session on restore."""
        from services.sessions import create_session, write_state, session_subdir, delete_session

        sid = create_session()
        write_state(sid, "seg.n_vertices", "5577")
        write_state(sid, "seg.n_faces", "11285")
        write_state(sid, "dicom.modality", "XA")
        (session_subdir(sid, "meshes") / "vessel_tree.vtp").write_text("<VTKFile>fake mesh</VTKFile>")
        (session_subdir(sid, "meshes") / "_volume.npy").write_bytes(b"\x00\x01\x02volume")

        r = client.post("/api/sessions/save", json={"session_id": sid, "label": "durable", "current_step": 3})
        assert r.status_code == 200, r.text

        # Simulate the 24h TTL sweep wiping the live session dir.
        delete_session(sid)

        resp = client.post(f"/api/sessions/{sid}/restore")
        assert resp.status_code == 200, resp.text
        d = resp.json()
        new_sid = d["session_id"]
        assert new_sid != sid
        assert d["current_step"] == 3
        assert d["has_segmentation"] is True
        assert d["n_vertices"] == 5577
        assert d["modality"] == "XA"
        assert "vessel_tree.vtp" in d["mesh_url"] and new_sid in d["mesh_url"]
        # The actual files were rehydrated into the new live session.
        meshes = session_subdir(new_sid, "meshes")
        assert (meshes / "vessel_tree.vtp").read_text().startswith("<VTKFile>")
        assert (meshes / "_volume.npy").exists()

    def test_restore_without_durable_snapshot_conflicts(self):
        """A DB record whose files were saved before durable-save existed (or lost)
        → 409, not a silent empty restore."""
        from services.sessions import create_session, delete_saved_session
        sid = create_session()
        client.post("/api/sessions/save", json={"session_id": sid, "label": "x", "current_step": 1})
        delete_saved_session(sid)   # simulate a pre-durable / purged snapshot
        resp = client.post(f"/api/sessions/{sid}/restore")
        assert resp.status_code == 409

    def test_save_with_patient_link(self):
        token = _login()
        # Create patient
        p_resp = client.post(
            "/api/patients",
            json={
                "surname": "LinkTest",
                "given_name": "Patient",
                "hospital_id": "HN-LINK001",
                "dob": "1965-07-14",
                "sex": "M",
            },
            headers=_auth(token),
        )
        patient_id = p_resp.json()["id"]
        sid = _make_session()

        resp = client.post(
            "/api/sessions/save",
            json={
                "session_id": sid,
                "label": "Linked session",
                "current_step": 4,
                "patient_id": patient_id,
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200

        # Verify in list
        list_resp = client.get("/api/sessions")
        matching = [s for s in list_resp.json() if s["session_id"] == sid]
        assert len(matching) == 1
        # full_name is "Surname, GivenName" → "LinkTest, Patient"
        assert "LinkTest" in matching[0]["patient_name"]


# ── D. Longitudinal ───────────────────────────────────────────────────────── #

class TestLongitudinal:
    def test_longitudinal_no_db_record(self):
        """Session without DB record returns single-entry snapshot from state."""
        sid = _make_session()
        resp = client.get(f"/api/longitudinal/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["max_diameter_mm"] == pytest.approx(7.5, abs=0.01)
        assert data["deltas"] == []
        assert data["growth_alert"] is False
        assert "growth_alert_message" in data

    def test_longitudinal_no_session_at_all(self):
        """Completely unknown session_id returns empty result."""
        resp = client.get("/api/longitudinal/totally-unknown-session-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []

    def test_longitudinal_single_saved_session(self):
        """One DB session with patient_id → list with 1 entry, no deltas."""
        token = _login()
        p_resp = client.post(
            "/api/patients",
            json={
                "surname": "LongPatient1",
                "given_name": "Test",
                "hospital_id": "HN-LONG001",
                "dob": "1970-01-01",
                "sex": "F",
            },
            headers=_auth(token),
        )
        patient_id = p_resp.json()["id"]

        sid = _make_session()
        client.post(
            "/api/sessions/save",
            json={"session_id": sid, "current_step": 3, "patient_id": patient_id},
            headers=_auth(token),
        )

        resp = client.get(f"/api/longitudinal/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == patient_id
        assert len(data["entries"]) == 1
        assert data["deltas"] == []
        assert data["growth_alert"] is False

    def test_longitudinal_two_sessions_no_growth(self):
        """Two sessions with similar morphometry → no growth alert."""
        token = _login()
        p_resp = client.post(
            "/api/patients",
            json={
                "surname": "LongPatient2",
                "given_name": "Test",
                "hospital_id": "HN-LONG002",
                "dob": "1970-01-01",
                "sex": "M",
            },
            headers=_auth(token),
        )
        patient_id = p_resp.json()["id"]

        from services.sessions import create_session, write_state

        # Session 1: baseline
        sid1 = create_session()
        write_state(sid1, "morpho.max_diameter_mm", "7.0")
        write_state(sid1, "morpho.neck_mm", "3.0")
        write_state(sid1, "morpho.volume_mm3", "100.0")
        write_state(sid1, "morpho.ar", "1.5")
        write_state(sid1, "morpho.dnr", "2.0")
        write_state(sid1, "morpho.rupture_risk", "Bajo")

        client.post(
            "/api/sessions/save",
            json={"session_id": sid1, "current_step": 3, "patient_id": patient_id},
            headers=_auth(token),
        )

        # Session 2: almost no change
        sid2 = create_session()
        write_state(sid2, "morpho.max_diameter_mm", "7.3")   # +0.3mm < 1mm threshold
        write_state(sid2, "morpho.neck_mm", "3.1")
        write_state(sid2, "morpho.volume_mm3", "103.0")       # +3% < 20% threshold
        write_state(sid2, "morpho.ar", "1.55")                # +0.05 < 0.15 threshold
        write_state(sid2, "morpho.dnr", "2.1")
        write_state(sid2, "morpho.rupture_risk", "Bajo")

        client.post(
            "/api/sessions/save",
            json={"session_id": sid2, "current_step": 3, "patient_id": patient_id},
            headers=_auth(token),
        )

        resp = client.get(f"/api/longitudinal/{sid2}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 2
        assert len(data["deltas"]) == 3    # max_diameter, volume, ar
        assert data["growth_alert"] is False

    def test_longitudinal_two_sessions_growth_alert(self):
        """Two sessions with significant diameter growth → growth_alert=True."""
        token = _login()
        p_resp = client.post(
            "/api/patients",
            json={
                "surname": "LongPatient3",
                "given_name": "Alert",
                "hospital_id": "HN-LONG003",
                "dob": "1960-06-15",
                "sex": "F",
            },
            headers=_auth(token),
        )
        patient_id = p_resp.json()["id"]

        from services.sessions import create_session, write_state

        # Session 1: small aneurysm
        sid1 = create_session()
        write_state(sid1, "morpho.max_diameter_mm", "5.0")
        write_state(sid1, "morpho.neck_mm", "2.5")
        write_state(sid1, "morpho.volume_mm3", "65.0")
        write_state(sid1, "morpho.ar", "1.2")
        write_state(sid1, "morpho.dnr", "1.8")
        write_state(sid1, "morpho.rupture_risk", "Bajo")

        client.post(
            "/api/sessions/save",
            json={"session_id": sid1, "current_step": 3, "patient_id": patient_id},
            headers=_auth(token),
        )

        # Session 2: significant growth (+2.5mm diameter, +60% volume)
        sid2 = create_session()
        write_state(sid2, "morpho.max_diameter_mm", "7.5")   # +2.5mm > 1mm threshold
        write_state(sid2, "morpho.neck_mm", "3.0")
        write_state(sid2, "morpho.volume_mm3", "104.0")       # +60% >> 20% threshold
        write_state(sid2, "morpho.ar", "1.5")                 # +0.3 > 0.15 threshold
        write_state(sid2, "morpho.dnr", "2.2")
        write_state(sid2, "morpho.rupture_risk", "Moderado")

        client.post(
            "/api/sessions/save",
            json={"session_id": sid2, "current_step": 3, "patient_id": patient_id},
            headers=_auth(token),
        )

        resp = client.get(f"/api/longitudinal/{sid2}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 2
        assert data["growth_alert"] is True
        assert data["growth_alert_message"] is not None
        assert len(data["growth_alert_message"]) > 0

        # Verify delta values
        dia_delta = next(d for d in data["deltas"] if d["metric"] == "max_diameter_mm")
        assert dia_delta["delta"] == pytest.approx(2.5, abs=0.01)
        assert dia_delta["is_concerning"] is True
        assert "crecimiento" in dia_delta["trend"]

    def test_longitudinal_delta_trends(self):
        """Verify trend strings for stable, growing, and shrinking."""
        token = _login()
        p_resp = client.post(
            "/api/patients",
            json={
                "surname": "TrendTest",
                "given_name": "Delta",
                "hospital_id": "HN-TREND",
                "dob": "1980-04-20",
                "sex": "F",
            },
            headers=_auth(token),
        )
        patient_id = p_resp.json()["id"]

        from services.sessions import create_session, write_state

        sid1 = create_session()
        write_state(sid1, "morpho.max_diameter_mm", "6.0")
        write_state(sid1, "morpho.volume_mm3", "90.0")
        write_state(sid1, "morpho.ar", "1.4")
        write_state(sid1, "morpho.rupture_risk", "Bajo")
        client.post(
            "/api/sessions/save",
            json={"session_id": sid1, "current_step": 3, "patient_id": patient_id},
            headers=_auth(token),
        )

        sid2 = create_session()
        write_state(sid2, "morpho.max_diameter_mm", "6.0")   # stable
        write_state(sid2, "morpho.volume_mm3", "88.0")        # slight shrink (no alert)
        write_state(sid2, "morpho.ar", "1.4")                 # stable
        write_state(sid2, "morpho.rupture_risk", "Bajo")
        client.post(
            "/api/sessions/save",
            json={"session_id": sid2, "current_step": 3, "patient_id": patient_id},
            headers=_auth(token),
        )

        resp = client.get(f"/api/longitudinal/{sid2}")
        data = resp.json()
        dia_delta = next(d for d in data["deltas"] if d["metric"] == "max_diameter_mm")
        vol_delta = next(d for d in data["deltas"] if d["metric"] == "volume_mm3")
        # diameter unchanged → estable
        assert "estable" in dia_delta["trend"]
        # volume slightly down → reduccion
        assert "reduccion" in vol_delta["trend"] or "estable" in vol_delta["trend"]


# ── E. Regression: old endpoints still work ───────────────────────────────── #

class TestRegressionOldEndpoints:
    """Smoke-test endpoints from Sessions A, B, C to confirm nothing broke."""

    def test_treatment_endpoint(self):
        # Route is /api/treatment-decision; requires session_id + Spanish location string
        sid = _make_session()
        from services.treatment import LOCATIONS
        resp = client.post(
            "/api/treatment-decision",
            json={
                "session_id": sid,
                "neck_mm": 4.0,
                "max_diameter_mm": 12.0,
                "aspect_ratio": 2.1,
                "dnr": 3.5,
                "bottleneck_factor": 0.5,
                "undulation_index": 0.15,
                "location": LOCATIONS[0],   # "Desconocida / No especificada"
                "ruptured": False,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "recommendation" in data         # Spanish display string
        assert "recommendation_key" in data     # English short key
        assert data["recommendation_key"] in ("clip", "endo", "mdt")

    def test_clips_catalogue(self):
        resp = client.get("/api/clips")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        clip = data[0]
        assert "id" in clip              # field is 'id', not 'model'
        assert "length_mm" in clip

    def test_coils_catalogue(self):
        resp = client.get("/api/coils")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_clip_recommend(self):
        # Recommendations require a saved session: GET /api/clips/recommendations/{session_id}
        # Test with an invalid session → expect 404 (session not found) not 422/500
        resp = client.get("/api/clips/recommendations/no-such-session")
        assert resp.status_code == 404

    def test_coil_recommend(self):
        # /api/coils/plan requires a session_id body; invalid → 404/422
        resp = client.post("/api/coils/plan", json={"session_id": "no-such-session"})
        assert resp.status_code in (404, 422)

    def test_upload_endpoint_exists(self):
        """Verify the upload route is mounted (expect 422 without a real file)."""
        resp = client.post("/api/upload")
        assert resp.status_code in (400, 422)

    def test_segment_requires_session(self):
        resp = client.post("/api/segment/no-such-session")
        assert resp.status_code in (404, 422)

    def test_detect_requires_session(self):
        resp = client.post("/api/detect/no-such-session")
        assert resp.status_code == 404

    def test_morphometry_requires_session(self):
        resp = client.get("/api/morphometry/no-such-session")
        assert resp.status_code in (404, 422)

    def test_perforators_requires_session(self):
        resp = client.get("/api/perforators/no-such-session")
        assert resp.status_code in (404, 422)
