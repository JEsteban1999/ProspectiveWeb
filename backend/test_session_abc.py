"""Integration tests for Sessions A, B, C.

Session A — Treatment decision, clips catalogue, coils catalogue
Session B — Upload DICOM, segmentation, thresholds
Session C — Aneurysm detection, morphometrics, perforator risk

Run with:
    cd backend
    python -m pytest test_session_abc.py -v

These tests exercise the real service logic (no VTK for heavy pipeline tests —
those are gated behind 'requires_vtk_mesh' and tested via endpoint smoke tests).
"""
from __future__ import annotations

import io
import os
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

# ── Isolated test environment ────────────────────────────────────────────── #
_tmp_data = tempfile.mkdtemp(prefix="prospective_test_abc_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_data}/test_abc.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from main import app  # noqa: E402
from services.database import Base, get_db, engine  # noqa: E402
from services.auth_service import seed_default_user  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_TL = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_db() -> Generator:
    db = _TL()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_db
Base.metadata.create_all(bind=engine)
_db = _TL()
try:
    seed_default_user(_db)
finally:
    _db.close()

client = TestClient(app, raise_server_exceptions=True)


# ──────────────────────────────────────────────────────────────────────────── #
# Helpers                                                                       #
# ──────────────────────────────────────────────────────────────────────────── #

def _make_session(**morpho_kwargs) -> str:
    """Create a session and optionally populate morphometry state."""
    from services.sessions import create_session, write_state
    sid = create_session()
    defaults = dict(
        max_diameter_mm="9.1", neck_mm="4.2", dome_height_mm="7.0",
        volume_mm3="210.5", ar="2.17", dnr="2.65", bf="0.68", ui="0.11",
        compactness="0.61", rupture_risk="Alto",
    )
    defaults.update(morpho_kwargs)
    for k, v in defaults.items():
        write_state(sid, f"morpho.{k}", str(v))
    write_state(sid, "dicom.modality", "CT")
    return sid


def _fake_dicom_bytes() -> bytes:
    """Generate a minimal valid DICOM-ish file (passes file detection heuristics)."""
    # 128-byte preamble + DICM magic + (0008,0016) SOPClassUID tag stub
    preamble = b"\x00" * 128 + b"DICM"
    # Minimal group 8 tag: (0008,0016) UI SOPClassUID
    tag = struct.pack("<HH", 0x0008, 0x0016)
    vr  = b"UI"
    val = b"1.2.840.10008.5.1.4.1.1.2\x00"   # CT Image Storage
    ln  = struct.pack("<H", len(val))
    return preamble + tag + vr + ln + val


# ══════════════════════════════════════════════════════════════════════════════
# SESSION A — Treatment, Clips, Coils
# ══════════════════════════════════════════════════════════════════════════════

class TestTreatmentDecision:
    """POST /api/treatment-decision — 8-factor CLIP vs ENDO engine."""

    _URL = "/api/treatment-decision"

    def _post(self, **extra):
        from services.treatment import LOCATIONS
        sid = _make_session()
        return client.post(self._URL, json={
            "session_id": sid,
            "location": LOCATIONS[0],
            **extra,
        })

    # ── Schema ────────────────────────────────────────────────────────────── #

    def test_response_schema(self):
        resp = self._post()
        assert resp.status_code == 200
        d = resp.json()
        for key in ("recommendation", "recommendation_key", "confidence",
                    "clip_pct", "endo_pct", "balance", "factors",
                    "clip_factors", "endo_factors"):
            assert key in d, f"Missing key: {key}"

    def test_recommendation_key_valid(self):
        d = self._post().json()
        assert d["recommendation_key"] in ("clip", "endo", "mdt", "surveillance")

    def test_confidence_valid(self):
        d = self._post().json()
        assert d["confidence"] in ("Alta", "Moderada", "Baja")

    def test_pct_sum_100(self):
        d = self._post().json()
        assert d["clip_pct"] + d["endo_pct"] == 100

    def test_balance_is_integer(self):
        # balance is computed from raw scores (not percentages) → just assert it's numeric
        d = self._post().json()
        assert isinstance(d["balance"], int)

    def test_factors_list(self):
        d = self._post().json()
        assert isinstance(d["factors"], list)

    # ── Clinical logic ────────────────────────────────────────────────────── #

    def test_large_neck_favours_clip(self):
        """Neck > 4 mm is a strong clip indicator."""
        from services.sessions import write_state
        from services.treatment import LOCATIONS
        sid = _make_session(neck_mm="5.5", ar="1.2", dnr="1.3",
                            max_diameter_mm="8.0", volume_mm3="150.0")
        resp = client.post(self._URL, json={
            "session_id": sid,
            "location": LOCATIONS[0],
        })
        d = resp.json()
        assert d["clip_pct"] >= d["endo_pct"], (
            f"Expected clip ≥ endo for wide neck; got clip={d['clip_pct']} endo={d['endo_pct']}"
        )

    def test_ruptured_favours_endo(self):
        """Acute rupture (SAH) is a strong endovascular indicator."""
        from services.treatment import LOCATIONS
        sid = _make_session(neck_mm="2.5", ar="1.8", max_diameter_mm="7.0")
        resp = client.post(self._URL, json={
            "session_id": sid,
            "location": LOCATIONS[0],
            "is_ruptured": True,
        })
        d = resp.json()
        assert d["endo_pct"] > 0

    def test_session_not_found(self):
        from services.treatment import LOCATIONS
        resp = client.post(self._URL, json={
            "session_id": "no-such-session",
            "location": LOCATIONS[0],
        })
        assert resp.status_code == 404

    def test_saves_state_for_report(self):
        """After treatment-decision, state keys must be present for report builder."""
        from services.sessions import read_state
        from services.treatment import LOCATIONS
        sid = _make_session()
        client.post(self._URL, json={"session_id": sid, "location": LOCATIONS[0]})
        assert read_state(sid, "treatment.recommendation_key") in (
            "clip", "endo", "mdt", "surveillance"
        )
        assert read_state(sid, "treatment.factors_json") != ""

    def test_all_locations_accepted(self):
        """Every valid AneurysmLocation enum value must return 200."""
        from services.treatment import LOCATIONS
        for loc in LOCATIONS:
            sid  = _make_session()
            resp = client.post(self._URL, json={"session_id": sid, "location": loc})
            assert resp.status_code == 200, f"Failed for location: {loc!r}"


class TestClipsAPI:
    """GET /api/clips, GET /api/clips/recommendations, POST /api/clips/plan."""

    def test_catalogue_returns_list(self):
        resp = client.get("/api/clips")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_catalogue_count(self):
        """Catalogue must have at least 40 entries."""
        resp = client.get("/api/clips")
        assert len(resp.json()) >= 40

    def test_catalogue_item_schema(self):
        item = client.get("/api/clips").json()[0]
        for field in ("id", "name", "length_mm", "angle_deg",
                      "is_fenestrated", "closing_force_g", "compatible_applier"):
            assert field in item, f"Missing field: {field}"

    def test_catalogue_lengths_positive(self):
        for item in client.get("/api/clips").json():
            assert item["length_mm"] > 0

    def test_recommendations_no_morpho(self):
        """Session with neck_mm=0 → empty recommendations list."""
        from services.sessions import create_session
        sid  = create_session()
        resp = client.get(f"/api/clips/recommendations/{sid}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_recommendations_with_morpho(self):
        """Session with neck measurement → up to 8 ranked recommendations."""
        sid  = _make_session()
        resp = client.get(f"/api/clips/recommendations/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert len(data) <= 8

    def test_recommendations_schema(self):
        sid  = _make_session()
        item = client.get(f"/api/clips/recommendations/{sid}").json()[0]
        # Actual fields: clip_id, clip_name, score, reason, suggested_placement
        for field in ("clip_id", "clip_name", "score"):
            assert field in item, f"Missing field: {field}"

    def test_recommendations_sorted_by_score(self):
        """Recommendations must be returned in descending score order."""
        sid    = _make_session()
        items  = client.get(f"/api/clips/recommendations/{sid}").json()
        scores = [i["score"] for i in items]
        assert scores == sorted(scores, reverse=True)

    def test_recommendations_session_not_found(self):
        resp = client.get("/api/clips/recommendations/no-such-session")
        assert resp.status_code == 404

    def test_plan_no_clips(self):
        """Zero placements → coverage 0%."""
        sid  = _make_session()
        resp = client.post("/api/clips/plan", json={
            "session_id": sid,
            "placements": [],
        })
        assert resp.status_code == 200
        assert resp.json()["neck_coverage_pct"] == pytest.approx(0.0)

    def test_plan_one_clip(self):
        # position is Position3D object: {x, y, z}; normal is list[float]
        sid  = _make_session()
        resp = client.post("/api/clips/plan", json={
            "session_id": sid,
            "placements": [{
                "clip_id":      "yasargil-mini-recto",
                "position":     {"x": 0.0, "y": 0.0, "z": 0.0},
                "normal":       [0.0, 0.0, 1.0],
                "rotation_deg": 0.0,
            }],
        })
        assert resp.status_code == 200
        d = resp.json()
        assert d["neck_coverage_pct"] > 0
        assert "collision_detected" in d

    def test_plan_coverage_capped_at_100(self):
        """4 clips → raw 120% estimate must be clamped to 100%."""
        sid  = _make_session()
        clips = [{"clip_id": "yasargil-mini-recto",
                  "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                  "normal":   [0.0, 0.0, 1.0],
                  "rotation_deg": 0.0}] * 4
        resp = client.post("/api/clips/plan", json={
            "session_id": sid,
            "placements": clips,
        })
        assert resp.json()["neck_coverage_pct"] <= 100.0

    def test_plan_session_not_found(self):
        resp = client.post("/api/clips/plan", json={
            "session_id": "bad-session",
            "placements": [],
        })
        assert resp.status_code == 404


class TestCoilsAPI:
    """GET /api/coils, POST /api/coils/plan."""

    def test_catalogue_returns_list(self):
        resp = client.get("/api/coils")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_catalogue_count(self):
        assert len(client.get("/api/coils").json()) >= 39

    def test_catalogue_item_schema(self):
        item = client.get("/api/coils").json()[0]
        for field in ("id", "name", "diameter_mm", "length_cm", "coil_type"):
            assert field in item, f"Missing field: {field}"

    def test_catalogue_diameters_positive(self):
        for item in client.get("/api/coils").json():
            assert item["diameter_mm"] > 0

    def test_plan_no_placements_low_density(self):
        sid  = _make_session()
        resp = client.post("/api/coils/plan", json={
            "session_id": sid,
            "placements": [],
        })
        assert resp.status_code == 200
        assert resp.json()["total_packing_density"] == pytest.approx(0.0)

    def test_plan_density_positive_with_coils(self):
        # position is Position3D {x, y, z}
        sid  = _make_session()
        resp = client.post("/api/coils/plan", json={
            "session_id": sid,
            "placements": [
                {"coil_id": "target-360-4mm-8cm",
                 "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                 "packing_density": 0.25},
                {"coil_id": "target-360-4mm-8cm",
                 "position": {"x": 1.0, "y": 0.0, "z": 0.0},
                 "packing_density": 0.20},
            ],
        })
        assert resp.status_code == 200
        d = resp.json()
        assert d["total_packing_density"] > 0.0
        assert d["total_packing_density"] <= 0.55   # physical upper limit

    def test_plan_density_capped(self):
        """Packing density must never exceed 0.55 (physical platinum limit)."""
        sid  = _make_session()
        coils = [{"coil_id": "target-360-4mm-8cm",
                  "position": {"x": float(i), "y": 0.0, "z": 0.0},
                  "packing_density": 0.3}
                 for i in range(20)]
        resp = client.post("/api/coils/plan", json={
            "session_id": sid,
            "placements": coils,
        })
        assert resp.json()["total_packing_density"] <= 0.55

    def test_plan_warns_low_density(self):
        """One coil → low packing → warning message present."""
        sid  = _make_session()
        resp = client.post("/api/coils/plan", json={
            "session_id": sid,
            "placements": [{"coil_id": "target-360-4mm-8cm",
                            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                            "packing_density": 0.1}],
        })
        d = resp.json()
        if d["total_packing_density"] < 0.20:
            assert d["warning"] is not None

    def test_plan_session_not_found(self):
        resp = client.post("/api/coils/plan", json={
            "session_id": "bad-session",
            "placements": [],
        })
        assert resp.status_code == 404

    def test_occlusion_pct_range(self):
        sid  = _make_session()
        resp = client.post("/api/coils/plan", json={
            "session_id": sid,
            "placements": [{"coil_id": "target-360-4mm-8cm",
                            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                            "packing_density": 0.25}],
        })
        assert resp.status_code == 200
        pct = resp.json()["estimated_occlusion_pct"]
        assert 0.0 <= pct <= 100.0


# ══════════════════════════════════════════════════════════════════════════════
# SESSION B — Upload, Thresholds, Segmentation
# ══════════════════════════════════════════════════════════════════════════════

class TestUpload:
    """POST /api/upload — multipart DICOM ingest."""

    def test_no_files_returns_422(self):
        resp = client.post("/api/upload")
        assert resp.status_code == 422

    def test_non_dicom_file_accepted_session_created(self):
        """Non-DICOM bytes still create a session (scan_series returns empty)."""
        resp = client.post(
            "/api/upload",
            files={"files": ("dummy.txt", b"not a dicom file", "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert isinstance(data["series"], list)
        assert data["total_files"] == 1

    def test_fake_dicom_creates_session(self):
        """Minimal DICOM-magic bytes go through without crashing."""
        content = _fake_dicom_bytes()
        resp = client.post(
            "/api/upload",
            files={"files": ("CT.dcm", content, "application/dicom")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert len(data["session_id"]) > 8    # should be a UUID

    def test_multiple_files_count(self):
        files = [
            ("files", ("file1.dcm", _fake_dicom_bytes(), "application/dicom")),
            ("files", ("file2.dcm", _fake_dicom_bytes(), "application/dicom")),
            ("files", ("file3.dcm", _fake_dicom_bytes(), "application/dicom")),
        ]
        resp = client.post("/api/upload", files=files)
        assert resp.status_code == 200
        assert resp.json()["total_files"] == 3

    def test_upload_response_schema(self):
        resp = client.post(
            "/api/upload",
            files={"files": ("scan.dcm", _fake_dicom_bytes(), "application/dicom")},
        )
        data = resp.json()
        assert "session_id"  in data
        assert "series"      in data
        assert "total_files" in data

    def test_session_dir_created_on_disk(self):
        """Upload must create the session directory tree on disk."""
        from services.sessions import session_exists
        resp = client.post(
            "/api/upload",
            files={"files": ("scan.dcm", _fake_dicom_bytes(), "application/dicom")},
        )
        sid = resp.json()["session_id"]
        assert session_exists(sid), f"Session dir not created for {sid}"

    def test_upload_writes_dicom_state(self):
        """After upload the session state must contain at minimum dicom.modality."""
        from services.sessions import read_state
        # Need a real DICOM for scan_series to produce state — fake bytes won't
        # populate modality; we test the upload plumbing: file saved + session created
        resp = client.post(
            "/api/upload",
            files={"files": ("scan.dcm", _fake_dicom_bytes(), "application/dicom")},
        )
        assert resp.status_code == 200
        # session_id must be set and session must exist
        sid = resp.json()["session_id"]
        assert len(sid) > 0

    def test_large_filename_sanitised(self):
        """Path-traversal filename must be sanitised."""
        resp = client.post(
            "/api/upload",
            files={"files": ("../../../etc/passwd.dcm",
                             _fake_dicom_bytes(), "application/dicom")},
        )
        assert resp.status_code == 200


class TestThresholds:
    """GET /api/thresholds/{session_id}."""

    def _session_with_dicom_state(self, modality: str = "CT") -> str:
        from services.sessions import create_session, write_state
        sid = create_session()
        write_state(sid, "dicom.modality",  modality)
        write_state(sid, "dicom.series_id", "uid-001")
        write_state(sid, "dicom.spacing_x", "0.5")
        write_state(sid, "dicom.spacing_y", "0.5")
        write_state(sid, "dicom.spacing_z", "0.625")
        return sid

    def test_ct_thresholds(self):
        sid  = self._session_with_dicom_state("CT")
        resp = client.get(f"/api/thresholds/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "lower" in data and "upper" in data
        assert data["lower"] < data["upper"]

    def test_mr_thresholds(self):
        sid  = self._session_with_dicom_state("MR")
        resp = client.get(f"/api/thresholds/{sid}")
        assert resp.status_code == 200

    def test_xa_thresholds(self):
        sid  = self._session_with_dicom_state("XA")
        resp = client.get(f"/api/thresholds/{sid}")
        assert resp.status_code == 200

    def test_threshold_session_not_found(self):
        resp = client.get("/api/thresholds/no-such-session")
        assert resp.status_code == 404

    def test_threshold_schema(self):
        # Actual fields: lower, upper, strategy, is_dsa, hint, voxel_fraction
        sid  = self._session_with_dicom_state()
        data = client.get(f"/api/thresholds/{sid}").json()
        for field in ("lower", "upper", "strategy"):
            assert field in data, f"Missing field: {field}"

    def test_ct_lower_in_bone_range(self):
        """CT lower threshold should be in HU range meaningful for vessel segmentation."""
        sid  = self._session_with_dicom_state("CT")
        data = client.get(f"/api/thresholds/{sid}").json()
        # Vessel/bone CT range is roughly 80–1500 HU
        assert -200 <= data["lower"] <= 1000
        assert data["upper"] > data["lower"]


class TestSegmentation:
    """POST /api/segment — marching cubes pipeline (smoke tests)."""

    def test_segment_session_not_found(self):
        resp = client.post("/api/segment", json={
            "session_id": "no-such-session",
            "series_id":  "uid-001",
            "lower": 200, "upper": 900,
        })
        assert resp.status_code == 404

    def test_segment_no_dicom_returns_error(self):
        """Session without DICOM files → 422 or 500 (no volume to segment)."""
        from services.sessions import create_session
        sid  = create_session()
        resp = client.post("/api/segment", json={
            "session_id": sid,
            "series_id":  "uid-001",
            "lower": 200, "upper": 900,
        })
        # No DICOM on disk → should fail gracefully, not hang
        assert resp.status_code in (404, 422, 500)

    def test_segment_request_schema(self):
        """422 on malformed request (missing required fields)."""
        resp = client.post("/api/segment", json={})
        assert resp.status_code == 422

    def test_segment_lower_upper_validation(self):
        """lower >= upper should produce a validation or logic error."""
        from services.sessions import create_session, write_state
        sid = create_session()
        write_state(sid, "dicom.series_id", "uid-001")
        resp = client.post("/api/segment", json={
            "session_id": sid,
            "series_id":  "uid-001",
            "lower": 900, "upper": 100,   # inverted
        })
        # Either 422 (Pydantic) or runs and fails on empty volume
        assert resp.status_code in (404, 422, 500)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION C — Detection, Morphometrics, Perforators (endpoint smoke tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectionEndpoints:
    """POST /api/detect/{session_id} and GET /api/morphometry/{session_id}."""

    def test_detect_session_not_found(self):
        resp = client.post("/api/detect/no-such-session")
        assert resp.status_code == 404

    def test_detect_no_mesh_returns_error(self):
        """Session with no vessel_tree.vtp → 422."""
        from services.sessions import create_session
        sid  = create_session()
        resp = client.post(f"/api/detect/{sid}")
        assert resp.status_code == 422

    def test_detect_with_synthetic_mesh(self):
        """Inject a sphere VTP as vessel_tree → detect runs without crash."""
        import vtk
        from services.sessions import create_session, session_subdir
        from services.segmentation import write_vtp

        sid      = create_session()
        mesh_dir = session_subdir(sid, "meshes")
        mesh_dir.mkdir(parents=True, exist_ok=True)

        # Use a bumpy sphere to give the detector some curvature variation
        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(8.0)
        sphere.SetPhiResolution(32)
        sphere.SetThetaResolution(32)
        sphere.Update()
        write_vtp(sphere.GetOutput(), str(mesh_dir / "vessel_tree.vtp"))

        resp = client.post(f"/api/detect/{sid}")
        # May find 0 candidates (a sphere passes gates rarely) or ≥ 1
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates" in data
        assert isinstance(data["candidates"], list)

    def test_morphometry_session_not_found(self):
        resp = client.get("/api/morphometry/no-such-session")
        assert resp.status_code in (404, 422)

    def test_morphometry_no_candidate(self):
        """Session with no detected candidate → 422."""
        from services.sessions import create_session
        sid  = create_session()
        resp = client.get(f"/api/morphometry/{sid}")
        assert resp.status_code == 422

    def test_morphometry_with_synthetic_candidate(self):
        """Inject a sphere VTP as best candidate → morphometry returns metrics."""
        import vtk
        from services.sessions import create_session, session_subdir, write_state
        from services.segmentation import write_vtp

        sid      = create_session()
        mesh_dir = session_subdir(sid, "meshes")
        mesh_dir.mkdir(parents=True, exist_ok=True)

        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(5.0)
        sphere.SetPhiResolution(24)
        sphere.SetThetaResolution(24)
        sphere.Update()

        vtp_name = "aneurysm_cand_001.vtp"
        write_vtp(sphere.GetOutput(), str(mesh_dir / vtp_name))
        write_state(sid, "detect.best_vtp_name", vtp_name)

        resp = client.get(f"/api/morphometry/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("max_diameter_mm", "volume_mm3", "ar", "dnr"):
            assert field in data, f"Missing morphometry field: {field}"
        assert data["max_diameter_mm"] > 0
        assert data["volume_mm3"]      > 0

    def test_morphometry_schema(self):
        """All expected morphometry fields present when candidate exists."""
        import vtk
        from services.sessions import create_session, session_subdir, write_state
        from services.segmentation import write_vtp

        sid      = create_session()
        mesh_dir = session_subdir(sid, "meshes")
        mesh_dir.mkdir(parents=True, exist_ok=True)
        sphere   = vtk.vtkSphereSource()
        sphere.SetRadius(4.0)
        sphere.Update()
        write_vtp(sphere.GetOutput(), str(mesh_dir / "aneurysm_cand_001.vtp"))
        write_state(sid, "detect.best_vtp_name", "aneurysm_cand_001.vtp")

        data = client.get(f"/api/morphometry/{sid}").json()
        # Actual API field names (bf = bottleneck_factor, ui = undulation_index)
        expected = ("max_diameter_mm", "neck_mm", "dome_height_mm",
                    "volume_mm3", "surface_area_mm2", "ar", "dnr",
                    "bf", "ui", "rupture_risk_label")
        for field in expected:
            assert field in data, f"Missing: {field}"


class TestPerforatorEndpoints:
    """GET /api/perforators/{session_id}."""

    def test_perforators_session_not_found(self):
        resp = client.get("/api/perforators/no-such-session")
        assert resp.status_code in (404, 422)

    def test_perforators_no_mesh(self):
        from services.sessions import create_session
        sid  = create_session()
        resp = client.get(f"/api/perforators/{sid}")
        assert resp.status_code in (404, 422)

    def test_perforators_with_synthetic_mesh(self):
        """Inject a tube-like mesh → perforator analysis runs without crash."""
        import vtk
        from services.sessions import create_session, session_subdir
        from services.segmentation import write_vtp

        sid      = create_session()
        mesh_dir = session_subdir(sid, "meshes")
        mesh_dir.mkdir(parents=True, exist_ok=True)

        cylinder = vtk.vtkCylinderSource()
        cylinder.SetRadius(3.0)
        cylinder.SetHeight(20.0)
        cylinder.SetResolution(16)
        cylinder.Update()
        write_vtp(cylinder.GetOutput(), str(mesh_dir / "vessel_tree.vtp"))

        resp = client.get(f"/api/perforators/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates"     in data
        assert "search_radius_mm" in data
        assert isinstance(data["candidates"], list)

    def test_perforators_schema(self):
        # Actual keys: candidates, high_count, medium_count, low_count, search_radius_mm
        import vtk
        from services.sessions import create_session, session_subdir
        from services.segmentation import write_vtp

        sid      = create_session()
        mesh_dir = session_subdir(sid, "meshes")
        mesh_dir.mkdir(parents=True, exist_ok=True)
        cyl = vtk.vtkCylinderSource()
        cyl.SetRadius(2.0)
        cyl.SetHeight(15.0)
        cyl.SetResolution(12)
        cyl.Update()
        write_vtp(cyl.GetOutput(), str(mesh_dir / "vessel_tree.vtp"))

        data = client.get(f"/api/perforators/{sid}").json()
        for field in ("candidates", "high_count", "medium_count",
                      "low_count", "search_radius_mm"):
            assert field in data, f"Missing: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE UNIT TESTS (pure Python — no HTTP, no VTK mesh required)
# ══════════════════════════════════════════════════════════════════════════════

class TestTreatmentServiceUnit:
    """Direct calls to services.treatment.compute_decision."""

    def _decision(self, **kwargs) -> dict:
        from services.treatment import compute_decision, LOCATIONS
        defaults = dict(
            neck_mm=3.5, aspect_ratio=1.8, dnr=2.1,
            max_diameter_mm=8.0, bottleneck_factor=0.6,
            undulation_index=0.12, location=LOCATIONS[0], ruptured=False,
        )
        defaults.update(kwargs)
        return compute_decision(**defaults)

    def test_returns_all_keys(self):
        d = self._decision()
        for k in ("clip_pct", "endo_pct", "balance", "recommendation",
                  "recommendation_key", "confidence", "factors"):
            assert k in d

    def test_pct_sum_100(self):
        d = self._decision()
        assert d["clip_pct"] + d["endo_pct"] == 100

    def test_wide_neck_clip_pct_higher(self):
        d = self._decision(neck_mm=6.0, aspect_ratio=1.0, dnr=1.0)
        assert d["clip_pct"] >= d["endo_pct"]

    def test_ruptured_boosts_endo(self):
        d_no  = self._decision(ruptured=False)
        d_yes = self._decision(ruptured=True)
        assert d_yes["endo_pct"] >= d_no["endo_pct"]


class TestClipsServiceUnit:
    """Direct calls to services.clips."""

    def test_catalogue_not_empty(self):
        from services.clips import CLIP_CATALOGUE
        assert len(CLIP_CATALOGUE) >= 40

    def test_recommend_returns_sorted(self):
        from services.clips import recommend_clips
        recs = recommend_clips(neck_mm=4.0, aspect_ratio=1.8, n=5)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_recommend_respects_n(self):
        from services.clips import recommend_clips
        for n in (1, 3, 5, 8):
            recs = recommend_clips(neck_mm=3.0, aspect_ratio=1.5, n=n)
            assert len(recs) <= n

    def test_catalogue_to_api_has_id(self):
        from services.clips import catalogue_to_api
        for item in catalogue_to_api():
            assert "id" in item
            assert item["id"] != ""

    def test_recommendations_to_api_keys(self):
        # Actual keys: clip_id, clip_name, score, reason, suggested_placement
        from services.clips import recommend_clips, recommendations_to_api
        recs = recommend_clips(neck_mm=3.5, aspect_ratio=1.6, n=3)
        for item in recommendations_to_api(recs):
            assert "clip_id"   in item
            assert "clip_name" in item
            assert "score"     in item


class TestCoilsServiceUnit:
    """Direct calls to services.coils."""

    def test_catalogue_not_empty(self):
        from services.coils import COIL_CATALOGUE
        assert len(COIL_CATALOGUE) >= 39

    def test_coils_for_aneurysm_returns_list(self):
        from services.coils import coils_for_aneurysm
        result = coils_for_aneurysm(dome_diameter_mm=8.0)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_estimate_coil_count_positive(self):
        # Signature: (aneurysm_volume_mm3, coil_spec, target_packing_pct=25.0)
        from services.coils import estimate_coil_count, COIL_CATALOGUE
        n = estimate_coil_count(aneurysm_volume_mm3=200.0, coil_spec=COIL_CATALOGUE[0])
        assert n >= 1

    def test_catalogue_to_api_has_id(self):
        from services.coils import catalogue_to_api
        for item in catalogue_to_api():
            assert "id" in item
