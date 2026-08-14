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


class TestStentReachesTheReport:
    """A deployed stent used to stop at session state: the PDF and the DICOM SR
    both dropped it, so the report showed clips and coils but never the stent.
    """

    def _straight_stent_session(self) -> str:
        sid = _session_with_volume()
        for k, v in [("morpho.max_diameter_mm", "7.5"), ("morpho.neck_mm", "3.2")]:
            write_state(sid, k, v)
        st = client.get("/api/stents").json()[0]
        r = client.post("/api/plan", json={"session_id": sid, "stent": {
            "stent_id": st["id"], "diameter_mm": st["min_diameter_mm"],
            "length_mm": st["available_lengths_mm"][0],
            "position": {"x": 0, "y": 0, "z": 0}, "rotation_deg": 0,
        }})
        assert r.status_code == 200, r.text
        return sid

    def test_straight_stent_appears_in_report_data_and_pdf(self):
        sid = self._straight_stent_session()

        data = build_report_data_from_session(sid)
        assert data.stent is not None, "el informe no vería el stent desplegado"
        assert data.stent.kind == "straight"
        assert data.stent.name
        assert data.stent.diameter_mm > 0

        gen = ReportGenerator(data)
        section = gen._section_stent()
        assert section, "la sección de stent no se emite"
        assert "desviador de flujo" in section[0].text
        # …and it must actually reach the document, not just exist.
        titles = [f.text for f in gen._build_story() if hasattr(f, "text")]
        assert any("desviador de flujo" in t for t in titles),             "la sección de stent no se añade al documento"

        out = session_subdir(sid, "reports")
        out.mkdir(parents=True, exist_ok=True)
        assert ReportGenerator(data).generate(out / "r.pdf").stat().st_size > 1000

    def test_centerline_stent_coverage_is_labelled_as_a_fit_ratio(self):
        """The two planners store different quantities under `coverage_pct`;
        printing the centreline ratio as «cobertura del cuello» would read a
        1.01 fit as 101 % of neck covered."""
        from services.device_state import save_stent

        sid = _session_with_volume()
        save_stent(sid, {
            "name": "Stent guiado por centerline", "manufacturer": "",
            "diameter_mm": 3.25, "length_mm": 22.0,
            "coverage_pct": 101.0, "kind": "centerline",
        })

        data = build_report_data_from_session(sid)
        assert data.stent is not None and data.stent.kind == "centerline"

        section = ReportGenerator(data)._section_stent()
        assert "línea central" in section[0].text
        cells = [str(c) for row in section[1]._cellvalues for c in row]
        assert any("Ø stent / Ø vaso" in c for c in cells)
        assert "1.01" in cells              # ratio, not "101.0 %"
        assert not any("Cobertura del cuello" in c for c in cells)

    def test_empty_session_has_no_stent(self):
        assert build_report_data_from_session(create_session()).stent is None


class TestDicomSrCarriesDevices:
    def test_sr_includes_clips_coils_and_stent(self):
        import pydicom
        from services.device_state import save_stent

        sid = _session_with_volume()
        for k, v in [("morpho.max_diameter_mm", "7.5"), ("morpho.neck_mm", "3.2")]:
            write_state(sid, k, v)
        clip_id = clips_api()[0]["id"]
        client.post("/api/clips/plan", json={"session_id": sid, "placements": [
            {"clip_id": clip_id, "position": {"x": 1, "y": 2, "z": 3},
             "normal": [0, 0, 1], "rotation_deg": 0},
        ]})
        coil_id = coils_api()[0]["id"]
        client.post("/api/coils/plan", json={"session_id": sid, "placements": [
            {"coil_id": coil_id, "position": {"x": 0, "y": 0, "z": 0}, "packing_density": 0},
        ]})
        save_stent(sid, {"name": "Pipeline Flex", "manufacturer": "Medtronic",
                         "diameter_mm": 4.0, "length_mm": 20.0,
                         "coverage_pct": 32.0, "kind": "straight"})

        r = client.post("/api/report/dicom-sr", json={"session_id": sid})
        assert r.status_code == 200, r.text

        sr_path = session_subdir(sid, "reports") / f"{sid}_sr.dcm"
        text = str(pydicom.dcmread(sr_path))
        # Concept names render as their code meanings, so assert on the
        # containers' meanings plus the device names themselves.
        assert "Endovascular Device Plan" in text, "el SR no lleva el stent"
        assert "Pipeline Flex" in text
        assert "Clip Model" in text, "el SR no lleva los clips"
        assert "Coil Model" in text, "el SR no lleva los coils"
