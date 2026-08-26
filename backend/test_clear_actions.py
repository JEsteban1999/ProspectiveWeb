"""Tests for the «Limpiar» actions across the pipeline.

Every step that changes the 3D scene writes two things: geometry the viewer
draws and a state record the PDF report and the DICOM SR read back. Undoing a
step has to remove both — a device cleared from the viewer but left in the
report is a plan that contradicts itself, which is the failure these tests pin.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_clear_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import vtk
from fastapi.testclient import TestClient

from main import app
from services import mesh_backup
from services.clips import catalogue_to_api as clips_api
from services.coils import catalogue_to_api as coils_api
from services.database import Base, engine
from services.device_state import read_clips, read_coils, read_stent, save_stent
from services.report_generator import build_report_data_from_session
from services.segmentation import read_vtp, write_vtp
from services.sessions import create_session, read_state, session_subdir, write_state

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


def _place_clip(sid: str) -> None:
    r = client.post("/api/clips/plan", json={"session_id": sid, "placements": [
        {"clip_id": clips_api()[0]["id"], "position": {"x": 0, "y": 0, "z": 0},
         "normal": [0, 0, 1], "rotation_deg": 0},
    ]})
    assert r.status_code == 200, r.text


# ── Devices ────────────────────────────────────────────────────────────────── #

class TestClearDevices:
    def test_clearing_clips_removes_them_from_the_report(self):
        # The whole point: a cleared device must stop appearing in the PDF, not
        # just in the viewer.
        sid = _session_with_mesh()
        _place_clip(sid)
        assert build_report_data_from_session(sid).clips

        r = client.delete(f"/api/devices/{sid}?kind=clips")
        assert r.status_code == 200, r.text
        assert r.json()["cleared"] == ["clips"]
        assert read_clips(sid) == []
        assert build_report_data_from_session(sid).clips == []

    def test_clearing_one_family_leaves_the_others(self):
        sid = _session_with_mesh()
        _place_clip(sid)
        client.post("/api/coils/plan", json={"session_id": sid, "placements": [
            {"coil_id": coils_api()[0]["id"], "position": {"x": 0, "y": 0, "z": 0}, "packing_density": 0},
        ]})

        r = client.delete(f"/api/devices/{sid}?kind=clips")
        assert r.status_code == 200
        assert read_clips(sid) == []
        assert read_coils(sid), "clearing the clips must not touch the coils"
        assert r.json()["remaining"] == ["coils"]

    def test_clearing_removes_the_device_mesh_file(self):
        sid = _session_with_mesh()
        _place_clip(sid)
        mesh = session_subdir(sid, "meshes") / "clips_placed.vtp"
        assert mesh.exists()

        client.delete(f"/api/devices/{sid}?kind=clips")
        assert not mesh.exists(), "the viewer would keep drawing a device that is out of the plan"

    def test_clear_all_empties_every_family(self):
        sid = _session_with_mesh()
        _place_clip(sid)
        save_stent(sid, {"name": "X", "diameter_mm": 4.0, "kind": "straight"})

        r = client.delete(f"/api/devices/{sid}")
        assert r.status_code == 200
        assert r.json()["remaining"] == []
        assert read_clips(sid) == [] and read_stent(sid) == {}

    def test_clearing_nothing_is_not_an_error(self):
        # Idempotent: the panel must be able to offer «Limpiar» without first
        # proving something was placed.
        sid = _session_with_mesh()
        r = client.delete(f"/api/devices/{sid}")
        assert r.status_code == 200
        assert r.json()["meshes_removed"] == 0

    def test_unknown_kind_is_rejected(self):
        sid = _session_with_mesh()
        assert client.delete(f"/api/devices/{sid}?kind=grapa").status_code == 422

    def test_missing_session_is_404(self):
        assert client.delete("/api/devices/no-such-session").status_code == 404

    def test_listing_reports_placed_devices_with_their_meshes(self):
        # A resumed session has no client-side memory of what was placed; without
        # this the devices sat in the report but never came back on screen.
        sid = _session_with_mesh()
        _place_clip(sid)
        body = client.get(f"/api/devices/{sid}").json()
        assert body["remaining"] == ["clips"]
        assert body["mesh_urls"]["clips"].startswith("/data/")


# ── Centreline ─────────────────────────────────────────────────────────────── #

class TestClearCenterline:
    def test_clearing_removes_geometry_and_cached_points(self):
        sid = _session_with_mesh()
        meshes = session_subdir(sid, "meshes")
        (meshes / "centerline.vtp").write_bytes(b"stub")
        (meshes / "centerline_points.npz").write_bytes(b"stub")

        r = client.delete(f"/api/centerline/{sid}")
        assert r.status_code == 200, r.text
        assert r.json()["had_centerline"] is True
        assert not (meshes / "centerline.vtp").exists()
        assert not (meshes / "centerline_points.npz").exists()

    def test_a_centreline_stent_goes_with_the_centreline(self):
        # The stent is built from the centreline points; leaving it behind would
        # report a device following a centreline that no longer exists.
        sid = _session_with_mesh()
        meshes = session_subdir(sid, "meshes")
        (meshes / "centerline.vtp").write_bytes(b"stub")
        (meshes / "cl_stent.vtp").write_bytes(b"stub")
        save_stent(sid, {"name": "Pipeline", "diameter_mm": 4.0, "kind": "centerline"})

        client.delete(f"/api/centerline/{sid}")
        assert not (meshes / "cl_stent.vtp").exists()
        assert read_stent(sid) == {}

    def test_a_straight_stent_survives_clearing_the_centreline(self):
        sid = _session_with_mesh()
        (session_subdir(sid, "meshes") / "centerline.vtp").write_bytes(b"stub")
        save_stent(sid, {"name": "Enterprise", "diameter_mm": 4.0, "kind": "straight"})

        client.delete(f"/api/centerline/{sid}")
        assert read_stent(sid).get("kind") == "straight"

    def test_clearing_without_a_centreline_is_not_an_error(self):
        sid = _session_with_mesh()
        r = client.delete(f"/api/centerline/{sid}")
        assert r.status_code == 200
        assert r.json()["had_centerline"] is False


# ── Detection + morphometry ────────────────────────────────────────────────── #

class TestClearDetection:
    def test_clearing_drops_candidates_and_the_manual_neck_plane(self):
        # `morpho.plane_*` is reapplied by every later morphometry call, so a
        # plane left over from a mesh that has since been edited keeps measuring
        # against geometry that moved.
        sid = _session_with_mesh()
        meshes = session_subdir(sid, "meshes")
        write_vtp(_sphere(3.0), meshes / "aneurysm_cand_001.vtp")
        write_state(sid, "detect.n_candidates", "1")
        write_state(sid, "detect.best_vtp_name", "aneurysm_cand_001.vtp")
        write_state(sid, "morpho.plane_origin_x", "1.5")
        write_state(sid, "morpho.max_diameter_mm", "7.5")

        r = client.delete(f"/api/detect/{sid}")
        assert r.status_code == 200, r.text
        assert r.json()["candidate_meshes_removed"] == 1
        assert not (meshes / "aneurysm_cand_001.vtp").exists()
        assert read_state(sid, "detect.best_vtp_name", "") == ""
        assert read_state(sid, "morpho.plane_origin_x", "") == ""
        assert read_state(sid, "morpho.max_diameter_mm", "") == ""

    def test_clearing_nothing_is_not_an_error(self):
        sid = _session_with_mesh()
        r = client.delete(f"/api/detect/{sid}")
        assert r.status_code == 200
        assert r.json()["candidate_meshes_removed"] == 0


# ── Undoing mesh edits ─────────────────────────────────────────────────────── #

class TestMeshUndo:
    def test_a_crop_can_be_undone(self):
        sid = _session_with_mesh(radius=10.0)
        vessel = session_subdir(sid, "meshes") / "vessel_tree.vtp"
        before = read_vtp(vessel).GetNumberOfPoints()

        crop = client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 6.0, "invert": False,
        })
        assert crop.status_code == 200, crop.text
        assert crop.json()["undo_depth"] == 1
        assert read_vtp(vessel).GetNumberOfPoints() < before

        r = client.post(f"/api/mesh-restore/{sid}", json={"scope": "undo"})
        assert r.status_code == 200, r.text
        assert r.json()["vertices"] == before
        assert r.json()["undo_depth"] == 0
        assert read_vtp(vessel).GetNumberOfPoints() == before

    def test_restore_original_unwinds_several_crops_at_once(self):
        sid = _session_with_mesh(radius=10.0)
        vessel = session_subdir(sid, "meshes") / "vessel_tree.vtp"
        before = read_vtp(vessel).GetNumberOfPoints()
        for radius in (8.0, 6.0, 4.0):
            r = client.post(f"/api/mesh-crop/{sid}", json={
                "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0},
                "radius": radius, "invert": False,
            })
            assert r.status_code == 200, r.text
        assert mesh_backup.depth(sid) == 3

        r = client.post(f"/api/mesh-restore/{sid}", json={"scope": "original"})
        assert r.status_code == 200, r.text
        assert read_vtp(vessel).GetNumberOfPoints() == before
        assert r.json()["undo_depth"] == 0

    def test_undo_updates_the_vertex_count_the_panel_shows(self):
        sid = _session_with_mesh(radius=10.0)
        before = read_vtp(session_subdir(sid, "meshes") / "vessel_tree.vtp").GetNumberOfPoints()
        client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 6.0, "invert": False,
        })
        client.post(f"/api/mesh-restore/{sid}", json={"scope": "undo"})
        assert int(read_state(sid, "seg.n_vertices", "0")) == before

    def test_undo_with_no_history_is_a_clean_409(self):
        sid = _session_with_mesh()
        r = client.post(f"/api/mesh-restore/{sid}", json={"scope": "undo"})
        assert r.status_code == 409
        assert "deshacer" in r.json()["detail"].lower()

    def test_history_endpoint_reports_the_depth(self):
        sid = _session_with_mesh()
        empty = client.get(f"/api/mesh-restore/{sid}").json()
        assert empty["undo_depth"] == 0 and empty["redo_depth"] == 0
        assert empty["has_original"] is False and empty["steps"] == []

        client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 6.0, "invert": False,
        })
        body = client.get(f"/api/mesh-restore/{sid}").json()
        assert body["undo_depth"] == 1 and body["has_original"] is True
        # «quedan 3» said nothing about what they were; the step names do.
        assert [s["label"] for s in body["steps"]] == ["crop"]
        assert body["steps"][0]["title"] == "Recorte de malla"
        assert body["steps"][0]["vertices"] > 0

    def test_the_baseline_survives_the_snapshot_cap(self):
        # Past MAX_SNAPSHOTS the stack drops old entries, but never the baseline:
        # «Restaurar malla original» has to keep meaning the segmented mesh.
        sid = _session_with_mesh(radius=40.0)
        vessel = session_subdir(sid, "meshes") / "vessel_tree.vtp"
        before = read_vtp(vessel).GetNumberOfPoints()
        for i in range(mesh_backup.MAX_SNAPSHOTS + 3):
            r = client.post(f"/api/mesh-crop/{sid}", json={
                "mode": "sphere", "center": {"x": 40, "y": 0, "z": 0},
                "radius": 30.0 - i * 0.1, "invert": False,
            })
            assert r.status_code == 200, r.text
        assert mesh_backup.depth(sid) <= mesh_backup.MAX_SNAPSHOTS

        client.post(f"/api/mesh-restore/{sid}", json={"scope": "original"})
        assert read_vtp(vessel).GetNumberOfPoints() == before

    def test_missing_session_is_404(self):
        assert client.post("/api/mesh-restore/nope", json={"scope": "undo"}).status_code == 404

    def test_an_undone_edit_can_be_redone(self):
        # Stepping back one edit too far used to cost the whole crop again.
        sid = _session_with_mesh(radius=10.0)
        vessel = session_subdir(sid, "meshes") / "vessel_tree.vtp"
        full = read_vtp(vessel).GetNumberOfPoints()
        client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 6.0, "invert": False,
        })
        cropped = read_vtp(vessel).GetNumberOfPoints()

        undone = client.post(f"/api/mesh-restore/{sid}", json={"scope": "undo"}).json()
        assert undone["vertices"] == full
        assert undone["redo_depth"] == 1

        redone = client.post(f"/api/mesh-restore/{sid}", json={"scope": "redo"})
        assert redone.status_code == 200, redone.text
        assert redone.json()["vertices"] == cropped
        assert read_vtp(vessel).GetNumberOfPoints() == cropped

    def test_a_new_edit_drops_the_redo_branch(self):
        # Those states belong to a branch the user has just left.
        sid = _session_with_mesh(radius=10.0)
        for radius in (8.0, 6.0):
            client.post(f"/api/mesh-crop/{sid}", json={
                "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0},
                "radius": radius, "invert": False,
            })
        client.post(f"/api/mesh-restore/{sid}", json={"scope": "undo"})
        assert mesh_backup.redo_depth(sid) == 1

        client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 5.0, "invert": False,
        })
        assert mesh_backup.redo_depth(sid) == 0

    def test_redo_with_nothing_undone_is_a_clean_409(self):
        sid = _session_with_mesh()
        r = client.post(f"/api/mesh-restore/{sid}", json={"scope": "redo"})
        assert r.status_code == 409
        assert "rehacer" in r.json()["detail"].lower()


# ── Re-segmentación reversible ─────────────────────────────────────────────── #

class TestResegmentationIsUndoable:
    """Re-segmenting used to wipe the whole edit history.

    Twenty minutes of cropping and growing vanished the moment someone tried
    another threshold band — no warning, no way back. It is an edit like any
    other, so it snapshots first.
    """

    def test_segmentation_records_a_step_instead_of_wiping_the_history(self):
        sid = _session_with_mesh(radius=10.0)
        client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 6.0, "invert": False,
        })
        assert mesh_backup.depth(sid) == 1

        # Stand in for the segment router's own snapshot call.
        mesh_backup.snapshot(sid, "segment")
        assert mesh_backup.depth(sid) == 2
        assert [s.label for s in mesh_backup.history(sid)] == ["crop", "segment"]

    def test_the_refinement_survives_undoing_a_re_segmentation(self):
        sid = _session_with_mesh(radius=10.0)
        vessel = session_subdir(sid, "meshes") / "vessel_tree.vtp"
        client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 6.0, "invert": False,
        })
        refined = read_vtp(vessel).GetNumberOfPoints()

        # A re-segmentation replaces the refined mesh with a fresh one.
        mesh_backup.snapshot(sid, "segment")
        write_vtp(_sphere(20.0), vessel)
        assert read_vtp(vessel).GetNumberOfPoints() != refined

        r = client.post(f"/api/mesh-restore/{sid}", json={"scope": "undo"})
        assert r.status_code == 200, r.text
        assert r.json()["vertices"] == refined, "the crop must come back with it"

    def test_the_history_names_the_step_that_produced_each_state(self):
        sid = _session_with_mesh(radius=10.0)
        mesh_backup.snapshot(sid, "segment")
        client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 10, "y": 0, "z": 0}, "radius": 6.0, "invert": False,
        })
        titles = [s["title"] for s in client.get(f"/api/mesh-restore/{sid}").json()["steps"]]
        assert titles == ["Segmentación", "Recorte de malla"]
