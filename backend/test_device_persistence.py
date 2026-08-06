"""Tests for placed-device persistence → report/session (Feature 4)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_devpersist_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir, write_state
from services.report_generator import build_report_data_from_session, ReportGenerator
from services.device_state import read_stent, read_clips, read_coils, save_clips, clear_devices
from services.clips import catalogue_to_api as clips_api
from services.coils import catalogue_to_api as coils_api

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _session_with_volume() -> str:
    sid = create_session()
    write_state(sid, "morpho.volume_mm3", "120.0")
    return sid


class TestPersistence:
    def test_clip_plan_persists_to_report(self):
        sid = _session_with_volume()
        clip_id = clips_api()[0]["id"]
        r = client.post("/api/clips/plan", json={"session_id": sid, "placements": [
            {"clip_id": clip_id, "position": {"x": 1, "y": 2, "z": 3}, "normal": [0, 0, 1], "rotation_deg": 15},
        ]})
        assert r.status_code == 200
        data = build_report_data_from_session(sid)
        assert len(data.clips) == 1
        assert data.clips[0].position_mm == (1.0, 2.0, 3.0)
        assert data.clips[0].orientation_deg == (0.0, 0.0, 15.0)
        assert data.clips[0].name  # non-empty catalogue name

    def test_coil_plan_persists_to_report(self):
        sid = _session_with_volume()
        coil_id = coils_api()[0]["id"]
        r = client.post("/api/coils/plan", json={"session_id": sid, "placements": [
            {"coil_id": coil_id, "position": {"x": 4, "y": 5, "z": 6}, "packing_density": 0},
            {"coil_id": coil_id, "position": {"x": 4, "y": 5, "z": 6}, "packing_density": 0},
        ]})
        assert r.status_code == 200
        data = build_report_data_from_session(sid)
        assert len(data.coils) == 2
        assert data.coils[0].diameter_mm > 0
        assert data.coils[0].manufacturer
        assert isinstance(data.coils[0].coil_type, str)  # JSON-safe (not an enum)

    def test_stent_plan_persists(self):
        sid = _session_with_volume()
        st = client.get("/api/stents").json()[0]
        r = client.post("/api/plan", json={"session_id": sid, "stent": {
            "stent_id": st["id"], "diameter_mm": st["min_diameter_mm"],
            "length_mm": st["available_lengths_mm"][0], "position": {"x": 0, "y": 0, "z": 0}, "rotation_deg": 0,
        }})
        assert r.status_code == 200
        stent = read_stent(sid)
        assert stent.get("name")
        assert stent.get("coverage_pct") is not None

    def test_pdf_builds_with_devices(self):
        sid = _session_with_volume()
        # Enough morphometry for a meaningful report body.
        for k, v in [("morpho.max_diameter_mm", "7.5"), ("morpho.neck_mm", "3.2"), ("morpho.dnr", "1.8")]:
            write_state(sid, k, v)
        clip_id = clips_api()[0]["id"]
        client.post("/api/clips/plan", json={"session_id": sid, "placements": [
            {"clip_id": clip_id, "position": {"x": 1, "y": 2, "z": 3}, "normal": [0, 0, 1], "rotation_deg": 0},
        ]})
        data = build_report_data_from_session(sid)
        out = session_subdir(sid, "reports")
        out.mkdir(parents=True, exist_ok=True)
        pdf = ReportGenerator(data).generate(out / "r.pdf")
        assert pdf.stat().st_size > 1000

    def test_empty_session_has_no_devices(self):
        sid = create_session()
        data = build_report_data_from_session(sid)
        assert data.clips == []
        assert data.coils == []

    def test_clear_devices(self):
        sid = create_session()
        save_clips(sid, [{"index": 0, "name": "X", "position": [0, 0, 0], "orientation": [0, 0, 0]}])
        assert len(read_clips(sid)) == 1
        clear_devices(sid)
        assert read_clips(sid) == []
        assert read_coils(sid) == []
