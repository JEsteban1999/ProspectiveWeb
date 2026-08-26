"""Tests for the second UX pass: reversible re-segmentation, redo, and the
report state that used to survive the measurements it described.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_undo_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import vtk
from fastapi.testclient import TestClient

from main import app
from services import mesh_backup
from services.database import Base, engine
from services.report_generator import build_report_data_from_session
from services.segmentation import read_vtp, write_vtp
from services.sessions import (
    create_session, read_state, session_subdir, snapshot_session, write_state,
)

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _sphere(radius=10.0, res=16) -> vtk.vtkPolyData:
    src = vtk.vtkSphereSource()
    src.SetRadius(radius)
    src.SetThetaResolution(res)
    src.SetPhiResolution(res)
    src.Update()
    return src.GetOutput()


def _session_with_mesh(radius=10.0) -> str:
    sid = create_session()
    write_state(sid, "morpho.volume_mm3", "120.0")
    write_vtp(_sphere(radius), session_subdir(sid, "meshes") / "vessel_tree.vtp")
    return sid


def _crop(sid: str, radius: float = 6.0, cx: float = 10.0):
    """Crop around a point ON the sphere's surface, so a cap survives."""
    return client.post(f"/api/mesh-crop/{sid}", json={
        "mode": "sphere", "center": {"x": cx, "y": 0, "z": 0},
        "radius": radius, "invert": False,
    })


# ── El estado del informe sobrevivía a lo que describía ────────────────────── #

def _record_treatment(sid: str) -> None:
    write_state(sid, "treatment.recommendation", "CLIPAJE QUIRÚRGICO")
    write_state(sid, "treatment.recommendation_key", "clip")
    write_state(sid, "treatment.confidence", "alta")
    write_state(sid, "treatment.clip_pct", "70")
    write_state(sid, "treatment.endo_pct", "30")
    write_state(sid, "clinical.patient_age", "54")
    write_state(sid, "phases.json", '{"score": 7}')


class TestTreatmentIsClearable:
    def test_clearing_removes_it_from_the_report(self):
        sid = _session_with_mesh()
        _record_treatment(sid)
        assert build_report_data_from_session(sid).treatment

        r = client.delete(f"/api/treatment-decision/{sid}")
        assert r.status_code == 200, r.text
        assert not build_report_data_from_session(sid).treatment

    def test_clearing_takes_the_phases_score_with_it(self):
        # PHASES is a rupture risk built on the same morphometry.
        sid = _session_with_mesh()
        _record_treatment(sid)
        client.delete(f"/api/treatment-decision/{sid}")
        assert read_state(sid, "phases.json", "") == ""
        assert build_report_data_from_session(sid).phases == {}

    def test_clearing_the_morphometry_clears_the_recommendation(self):
        # The bug this pins: «Limpiar candidatos y morfometría» cleared the
        # recommendation on screen while the PDF kept printing it, so the report
        # recommended a treatment for an aneurysm it also reported as unmeasured.
        sid = _session_with_mesh()
        _record_treatment(sid)
        write_state(sid, "morpho.max_diameter_mm", "7.5")

        client.delete(f"/api/detect/{sid}")

        assert read_state(sid, "morpho.max_diameter_mm", "") == ""
        assert read_state(sid, "treatment.recommendation_key", "") == ""
        assert not build_report_data_from_session(sid).treatment

    def test_editing_the_mesh_clears_what_was_measured_on_it(self):
        # A crop invalidated the candidates on screen but not in the session, so
        # a report generated afterwards described the mesh as it was before.
        sid = _session_with_mesh()
        _record_treatment(sid)
        write_state(sid, "morpho.max_diameter_mm", "7.5")
        write_state(sid, "detect.n_candidates", "2")

        assert _crop(sid).status_code == 200

        assert read_state(sid, "detect.n_candidates", "0") == "0"
        assert read_state(sid, "morpho.max_diameter_mm", "") == ""
        assert read_state(sid, "treatment.recommendation_key", "") == ""

    def test_clearing_nothing_is_not_an_error(self):
        sid = _session_with_mesh()
        assert client.delete(f"/api/treatment-decision/{sid}").status_code == 200

    def test_missing_session_is_404(self):
        assert client.delete("/api/treatment-decision/no-such").status_code == 404


# ── Historial de la malla ──────────────────────────────────────────────────── #

class TestMeshHistory:
    def test_restoring_the_original_is_itself_reversible(self):
        # Every step walked back lands on the redo stack, so «Al inicio» is not
        # a one-way door.
        sid = _session_with_mesh(radius=10.0)
        vessel = session_subdir(sid, "meshes") / "vessel_tree.vtp"
        _crop(sid, 8.0)
        _crop(sid, 6.0)
        latest = read_vtp(vessel).GetNumberOfPoints()

        client.post(f"/api/mesh-restore/{sid}", json={"scope": "original"})
        assert mesh_backup.redo_depth(sid) == 2

        client.post(f"/api/mesh-restore/{sid}", json={"scope": "redo"})
        client.post(f"/api/mesh-restore/{sid}", json={"scope": "redo"})
        assert read_vtp(vessel).GetNumberOfPoints() == latest

    def test_the_history_survives_the_snapshot_cap_without_losing_the_baseline(self):
        sid = _session_with_mesh(radius=40.0)
        vessel = session_subdir(sid, "meshes") / "vessel_tree.vtp"
        original = read_vtp(vessel).GetNumberOfPoints()
        for i in range(mesh_backup.MAX_SNAPSHOTS + 3):
            assert _crop(sid, 30.0 - i * 0.1, cx=40.0).status_code == 200
        assert mesh_backup.depth(sid) <= mesh_backup.MAX_SNAPSHOTS

        client.post(f"/api/mesh-restore/{sid}", json={"scope": "original"})
        assert read_vtp(vessel).GetNumberOfPoints() == original

    def test_every_step_carries_its_own_vertex_count(self):
        sid = _session_with_mesh(radius=10.0)
        full = read_vtp(session_subdir(sid, "meshes") / "vessel_tree.vtp").GetNumberOfPoints()
        _crop(sid, 6.0)
        steps = client.get(f"/api/mesh-restore/{sid}").json()["steps"]
        assert steps[0]["vertices"] == full


class TestSavedSessionsStayLean:
    def test_a_save_keeps_only_the_last_steps_of_the_history(self):
        # Carrying all twelve snapshots multiplied the size of every save, in a
        # save path that already had to hard-link the DICOM to fit on disk.
        sid = _session_with_mesh(radius=20.0)
        for i in range(6):
            assert _crop(sid, 15.0 - i * 0.1, cx=20.0).status_code == 200
        assert mesh_backup.depth(sid) == 6
        client.post(f"/api/mesh-restore/{sid}", json={"scope": "undo"})
        assert mesh_backup.redo_depth(sid) == 1

        snapshot_session(sid)

        from services.sessions import SAVES_ROOT
        saved_meshes = SAVES_ROOT / sid / "meshes"
        kept = sorted((saved_meshes / "_undo").glob("*.vtp"))
        assert len(kept) == 2, "the newest couple of steps stay usable after resuming"
        assert not (saved_meshes / "_redo").exists(), "saving commits to a state"

    def test_the_live_session_keeps_its_full_history(self):
        # Pruning happens on the copy, never on the session being worked in.
        sid = _session_with_mesh(radius=20.0)
        for i in range(4):
            _crop(sid, 15.0 - i * 0.1, cx=20.0)
        snapshot_session(sid)
        assert mesh_backup.depth(sid) == 4
