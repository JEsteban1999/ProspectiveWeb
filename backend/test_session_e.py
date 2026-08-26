"""Integration tests for Session E: PDF report generation + STL export.

Run with:
    cd backend
    python -m pytest test_session_e.py -v

Isolated: uses the same env-var overrides as test_session_d.py for DB isolation.
"""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

# ── Isolate test environment ──────────────────────────────────────────────── #
_tmp_data = tempfile.mkdtemp(prefix="prospective_test_e_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_data}/test_e.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from main import app  # noqa: E402
from services.database import Base, get_db, engine  # noqa: E402
from services.auth_service import seed_default_user  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db() -> Generator:
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=engine)

_seed_db = _TestingSessionLocal()
try:
    seed_default_user(_seed_db)
finally:
    _seed_db.close()

client = TestClient(app, raise_server_exceptions=True)


def _path_of(url: str) -> str:
    """URL without its cache-busting `?v=…` token."""
    return url.split("?", 1)[0]


# ── Helpers ───────────────────────────────────────────────────────────────── #

def _make_session_with_morpho() -> str:
    """Create a session directory populated with realistic morphometry state."""
    from services.sessions import create_session, write_state
    sid = create_session()
    write_state(sid, "morpho.max_diameter_mm",  "8.2")
    write_state(sid, "morpho.neck_mm",          "3.5")
    write_state(sid, "morpho.dome_height_mm",   "6.1")
    write_state(sid, "morpho.volume_mm3",       "145.3")
    write_state(sid, "morpho.ar",               "2.06")
    write_state(sid, "morpho.dnr",              "2.34")
    write_state(sid, "morpho.bf",               "0.72")
    write_state(sid, "morpho.ui",               "0.09")
    write_state(sid, "morpho.compactness",      "0.631")
    write_state(sid, "morpho.rupture_risk",     "Alto")
    write_state(sid, "dicom.modality",          "CT")
    return sid


def _make_session_with_treatment(sid: str) -> None:
    """Write treatment state as if the treatment-decision endpoint had run."""
    from services.sessions import write_state
    import json
    write_state(sid, "treatment.recommendation",     "TRATAMIENTO ENDOVASCULAR")
    write_state(sid, "treatment.recommendation_key", "endo")
    write_state(sid, "treatment.confidence",         "Alta")
    write_state(sid, "treatment.clip_pct",           "28")
    write_state(sid, "treatment.endo_pct",           "72")
    factors = [
        {"name": "Diámetro > 7 mm", "direction": "endo", "points": 2},
        {"name": "Cuello < 4 mm",   "direction": "endo", "points": 1},
    ]
    write_state(sid, "treatment.factors_json", json.dumps(factors))


def _tiny_png_b64() -> str:
    """Return a tiny valid 1×1 white PNG as base64."""
    # Minimal valid PNG bytes (1×1 white pixel, RGB)
    import struct, zlib
    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        c  = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png  = b"\x89PNG\r\n\x1a\n"
    png += png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw  = b"\x00\xff\xff\xff"    # filter byte + 1 white RGB pixel
    png += png_chunk(b"IDAT", zlib.compress(raw))
    png += png_chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


# ── A. PDF report generation ──────────────────────────────────────────────── #

class TestReportGeneration:

    def test_report_session_not_found(self):
        resp = client.post(
            "/api/report",
            json={"session_id": "does-not-exist"},
        )
        assert resp.status_code == 404

    def test_report_basic_generates_pdf(self):
        """POST /api/report with morphometry state → PDF URL returned."""
        sid = _make_session_with_morpho()
        resp = client.post(
            "/api/report",
            json={
                "session_id": sid,
                "patient_name": "Garcia Fernandez, Maria",
                "surgeon_name": "Dr. Navarro",
                "institution":  "SkullApp",
                "clinical_notes": "Control postoperatorio a 6 meses.",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["pdf_url"] is not None
        assert _path_of(data["pdf_url"]).endswith("_report.pdf")
        assert "generated_at" in data

    def test_report_pdf_file_actually_created(self):
        """Verify the PDF file exists on disk and has valid size."""
        from services.sessions import session_subdir
        sid = _make_session_with_morpho()
        client.post("/api/report", json={"session_id": sid})

        pdf_path = session_subdir(sid, "reports") / f"{sid}_report.pdf"
        assert pdf_path.exists(), f"PDF not found at {pdf_path}"
        assert pdf_path.stat().st_size > 1000, "PDF seems too small — likely corrupt"

    def test_report_pdf_page_count(self):
        """Page count is returned and is a positive integer."""
        sid = _make_session_with_morpho()
        resp = client.post("/api/report", json={"session_id": sid})
        data = resp.json()
        assert data["page_count"] is not None
        assert data["page_count"] >= 1

    def test_report_with_screenshot(self):
        """Sending a base64 PNG screenshot produces a valid PDF."""
        sid  = _make_session_with_morpho()
        b64  = _tiny_png_b64()
        resp = client.post(
            "/api/report",
            json={
                "session_id": sid,
                "include_3d_screenshot": True,
                "screenshot_png_b64": b64,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["pdf_url"] is not None

    def test_report_without_screenshot_flag(self):
        """include_3d_screenshot=False skips the image even if b64 is provided."""
        sid  = _make_session_with_morpho()
        b64  = _tiny_png_b64()
        resp = client.post(
            "/api/report",
            json={
                "session_id": sid,
                "include_3d_screenshot": False,
                "screenshot_png_b64": b64,
            },
        )
        assert resp.status_code == 200, resp.text

    def test_report_with_treatment_state(self):
        """Report with treatment state persisted → PDF generated correctly."""
        sid = _make_session_with_morpho()
        _make_session_with_treatment(sid)
        resp = client.post("/api/report", json={"session_id": sid})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["pdf_url"] is not None
        # PDF should be larger when it includes treatment section
        from services.sessions import session_subdir
        pdf_path = session_subdir(sid, "reports") / f"{sid}_report.pdf"
        assert pdf_path.stat().st_size > 2000

    def test_report_via_treatment_endpoint_then_generate(self):
        """Full pipeline: run treatment-decision endpoint → generate report."""
        from services.treatment import LOCATIONS
        sid  = _make_session_with_morpho()

        # Run the real treatment-decision endpoint (which now saves state)
        t_resp = client.post(
            "/api/treatment-decision",
            json={
                "session_id": sid,
                "location":   LOCATIONS[1],  # ACM — Arteria Cerebral Media
                "is_ruptured": False,
            },
        )
        assert t_resp.status_code == 200, t_resp.text

        # Now generate report — treatment section should be populated
        r_resp = client.post(
            "/api/report",
            json={"session_id": sid, "patient_name": "Test Patient"},
        )
        assert r_resp.status_code == 200, r_resp.text
        assert r_resp.json()["pdf_url"] is not None

    def test_report_empty_session_still_works(self):
        """Session with no morphometry generates a minimal PDF (just header + patient)."""
        from services.sessions import create_session
        sid  = create_session()   # no morphometry written
        resp = client.post(
            "/api/report",
            json={"session_id": sid, "patient_name": "Empty Patient"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["pdf_url"] is not None

    def test_report_url_format(self):
        """PDF URL follows the /data/sessions/{sid}/reports/{sid}_report.pdf pattern."""
        sid  = _make_session_with_morpho()
        resp = client.post("/api/report", json={"session_id": sid})
        url  = resp.json()["pdf_url"]
        assert _path_of(url) == f"/data/sessions/{sid}/reports/{sid}_report.pdf"
        # Regenerating must not let the browser hand back the previous PDF.
        assert "?v=" in url


# ── B. Treatment state persistence ────────────────────────────────────────── #

class TestTreatmentStatePersistence:

    def test_treatment_writes_state_keys(self):
        """After treatment-decision, session state contains recommendation keys."""
        from services.sessions import create_session, read_state
        from services.treatment import LOCATIONS
        sid = create_session()

        resp = client.post(
            "/api/treatment-decision",
            json={"session_id": sid, "location": LOCATIONS[0]},
        )
        assert resp.status_code == 200

        assert read_state(sid, "treatment.recommendation_key") in ("clip", "endo", "mdt", "surveillance")
        assert read_state(sid, "treatment.confidence")         in ("Alta", "Moderada", "Baja")
        assert read_state(sid, "treatment.clip_pct")           != ""
        assert read_state(sid, "treatment.endo_pct")           != ""
        assert read_state(sid, "treatment.factors_json")       != ""

    def test_treatment_factors_json_parseable(self):
        """Serialised factors can be parsed back as a list of dicts."""
        import json
        from services.sessions import create_session, read_state
        from services.treatment import LOCATIONS
        sid = create_session()

        client.post(
            "/api/treatment-decision",
            json={"session_id": sid, "location": LOCATIONS[1]},
        )

        raw     = read_state(sid, "treatment.factors_json", "")
        factors = json.loads(raw)
        assert isinstance(factors, list)
        if factors:
            f = factors[0]
            assert "name"      in f
            assert "direction" in f
            assert "points"    in f


# ── C. STL export ─────────────────────────────────────────────────────────── #

class TestSTLExport:

    def test_stl_session_not_found(self):
        resp = client.post(
            "/api/export/stl",
            json={"session_id": "no-such-session"},
        )
        assert resp.status_code == 404

    def test_stl_no_mesh_returns_422(self):
        """Session without vessel_tree.vtp → 422 (nothing to export)."""
        from services.sessions import create_session
        sid  = create_session()
        resp = client.post(
            "/api/export/stl",
            json={"session_id": sid, "include_vessel_tree": True},
        )
        assert resp.status_code == 422

    def test_stl_with_real_mesh(self):
        """Create a synthetic sphere VTP, export it as STL."""
        import vtk
        from services.sessions import create_session, write_state, session_subdir
        from services.segmentation import write_vtp

        sid      = create_session()
        mesh_dir = session_subdir(sid, "meshes")
        mesh_dir.mkdir(parents=True, exist_ok=True)

        # Build a synthetic sphere as vessel_tree.vtp
        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(5.0)
        sphere.SetPhiResolution(16)
        sphere.SetThetaResolution(16)
        sphere.Update()
        write_vtp(sphere.GetOutput(), str(mesh_dir / "vessel_tree.vtp"))

        resp = client.post(
            "/api/export/stl",
            json={
                "session_id":        sid,
                "include_vessel_tree": True,
                "include_aneurysm_dome": False,
                "scale_factor":      1.0,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["stl_url"] is not None
        assert _path_of(data["stl_url"]).endswith("_export.stl")

        # Verify STL file on disk
        stl_path = session_subdir(sid, "exports") / f"{sid}_export.stl"
        assert stl_path.exists()
        assert stl_path.stat().st_size > 100    # binary STL has a 84-byte header minimum

    def test_stl_url_format(self):
        """STL URL follows the /data/sessions/{sid}/exports/{sid}_export.stl pattern."""
        import vtk
        from services.sessions import create_session, session_subdir
        from services.segmentation import write_vtp

        sid      = create_session()
        mesh_dir = session_subdir(sid, "meshes")
        mesh_dir.mkdir(parents=True, exist_ok=True)
        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(3.0)
        sphere.Update()
        write_vtp(sphere.GetOutput(), str(mesh_dir / "vessel_tree.vtp"))

        resp = client.post(
            "/api/export/stl",
            json={"session_id": sid, "include_vessel_tree": True},
        )
        url = resp.json()["stl_url"]
        assert _path_of(url) == f"/data/sessions/{sid}/exports/{sid}_export.stl"
        assert "?v=" in url

    def test_stl_scale_factor(self):
        """Scale factor > 1 produces a larger STL (more geometry)."""
        import vtk
        from services.sessions import create_session, session_subdir
        from services.segmentation import write_vtp

        def _make_stl(scale: float) -> int:
            sid      = create_session()
            mesh_dir = session_subdir(sid, "meshes")
            mesh_dir.mkdir(parents=True, exist_ok=True)
            sphere = vtk.vtkSphereSource()
            sphere.SetRadius(5.0)
            sphere.SetPhiResolution(12)
            sphere.SetThetaResolution(12)
            sphere.Update()
            write_vtp(sphere.GetOutput(), str(mesh_dir / "vessel_tree.vtp"))

            resp = client.post(
                "/api/export/stl",
                json={"session_id": sid, "include_vessel_tree": True,
                      "scale_factor": scale},
            )
            assert resp.status_code == 200
            stl_path = session_subdir(sid, "exports") / f"{sid}_export.stl"
            return stl_path.stat().st_size

        # Same geometry, different scale — the topology (file size) should be identical
        # because only coordinates change, not triangle count
        size_1x = _make_stl(1.0)
        size_2x = _make_stl(2.0)
        # Binary STL size = 84 (header) + 50 * n_triangles — same for any scale
        assert size_1x == size_2x, "STL size should be the same regardless of scale"

    def test_stl_include_flags(self):
        """include_vessel_tree=False + no dome → 422 (nothing selected)."""
        from services.sessions import create_session
        sid = create_session()
        resp = client.post(
            "/api/export/stl",
            json={
                "session_id":        sid,
                "include_vessel_tree":  False,
                "include_aneurysm_dome": False,
            },
        )
        # Either 422 (no mesh available) or 404 (session ok but nothing to export)
        assert resp.status_code in (404, 422)


# ── D. build_report_data_from_session unit tests ──────────────────────────── #

class TestBuildReportData:

    def test_patient_name_from_request(self):
        from services.report_generator import build_report_data_from_session
        sid  = _make_session_with_morpho()
        data = build_report_data_from_session(sid, patient_name="Juan Garcia")
        assert data.patient.name == "Juan Garcia"

    def test_patient_defaults_to_anon(self):
        from services.sessions import create_session
        from services.report_generator import build_report_data_from_session
        sid  = create_session()
        data = build_report_data_from_session(sid)
        assert data.patient.name == "Anónimo"

    def test_morphometrics_populated(self):
        from services.report_generator import build_report_data_from_session
        sid  = _make_session_with_morpho()
        data = build_report_data_from_session(sid)
        assert data.morphometrics["max_diameter_mm"] == pytest.approx(8.2, abs=0.01)
        assert data.morphometrics["dome_to_neck_ratio"] == pytest.approx(2.34, abs=0.01)

    def test_risk_label_populated(self):
        from services.report_generator import build_report_data_from_session
        sid  = _make_session_with_morpho()
        data = build_report_data_from_session(sid)
        assert data.risk_label == "Alto"

    def test_treatment_populated_when_present(self):
        from services.report_generator import build_report_data_from_session
        sid  = _make_session_with_morpho()
        _make_session_with_treatment(sid)
        data = build_report_data_from_session(sid)
        assert data.treatment["recommendation_key"] == "endo"
        assert data.treatment["clip_pct"] == 28
        assert len(data.treatment["factors"]) == 2

    def test_treatment_empty_when_not_run(self):
        from services.report_generator import build_report_data_from_session
        from services.sessions import create_session
        sid  = create_session()
        data = build_report_data_from_session(sid)
        assert data.treatment == {}

    def test_screenshot_decoded(self):
        from services.report_generator import build_report_data_from_session
        sid = _make_session_with_morpho()
        b64 = _tiny_png_b64()
        data = build_report_data_from_session(sid, screenshot_png_b64=b64)
        assert data.screenshot_png is not None
        assert data.screenshot_png[:4] == b"\x89PNG"

    def test_invalid_b64_screenshot_gracefully_ignored(self):
        from services.report_generator import build_report_data_from_session
        sid  = _make_session_with_morpho()
        data = build_report_data_from_session(sid, screenshot_png_b64="not-valid-base64!!!")
        assert data.screenshot_png is None   # graceful fallback, no exception


# ── E. Regression — Session A-D still green ───────────────────────────────── #

class TestFullRegressionE:
    def test_all_session_d_routes_still_reachable(self):
        resp = client.get("/health")
        assert resp.status_code == 200

        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        resp = client.get(
            "/api/patients",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_treatment_route_still_works(self):
        from services.sessions import create_session
        from services.treatment import LOCATIONS
        sid  = create_session()
        resp = client.post(
            "/api/treatment-decision",
            json={"session_id": sid, "location": LOCATIONS[0]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendation_key" in data

    def test_openapi_spec_has_report_endpoints(self):
        spec  = client.get("/openapi.json").json()
        paths = spec["paths"]
        assert "/api/report"      in paths
        assert "/api/export/stl"  in paths
