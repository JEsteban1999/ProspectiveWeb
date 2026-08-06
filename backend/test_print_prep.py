"""Tests for 3D-print mesh preparation (Feature 7 / print_prep)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_printprep_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import vtk
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir
from services.segmentation import write_vtp
from services.mesh_prep import prepare_mesh_for_print, PRINT_BED_PRESETS

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _sphere(radius=30.0, res=40) -> vtk.vtkPolyData:
    s = vtk.vtkSphereSource()
    s.SetRadius(radius)
    s.SetThetaResolution(res)
    s.SetPhiResolution(res)
    s.Update()
    return s.GetOutput()


def _open_plane() -> vtk.vtkPolyData:
    p = vtk.vtkPlaneSource()
    p.SetXResolution(10)
    p.SetYResolution(10)
    p.Update()
    return p.GetOutput()


class TestService:
    def test_scales_to_target(self):
        res = prepare_mesh_for_print(_sphere(radius=30), target_size_mm=80.0)
        assert abs(max(res.dimensions_mm) - 80.0) < 1.0
        assert res.is_watertight is True
        assert res.volume_cm3 > 0

    def test_no_scale_when_target_zero(self):
        res = prepare_mesh_for_print(_sphere(radius=30), target_size_mm=0.0)
        assert res.scale_factor == 1.0
        assert 58 < max(res.dimensions_mm) < 62  # ~diameter 60

    def test_open_mesh_not_watertight(self):
        res = prepare_mesh_for_print(_open_plane(), target_size_mm=50.0, fill_holes=False)
        assert res.is_watertight is False
        assert res.open_edge_count > 0
        assert len(res.warnings) >= 1

    def test_empty_raises(self):
        try:
            prepare_mesh_for_print(vtk.vtkPolyData())
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestEndpoint:
    def _session_with_mesh(self, mesh) -> str:
        sid = create_session()
        write_vtp(mesh, session_subdir(sid, "meshes") / "vessel_tree.vtp")
        return sid

    def test_beds_endpoint(self):
        r = client.get("/api/print-prep/beds")
        assert r.status_code == 200
        assert len(r.json()) == len(PRINT_BED_PRESETS)
        assert any(b["name"] == "Prusa MK4" for b in r.json())

    def test_prep_fits_bed(self):
        sid = self._session_with_mesh(_sphere(radius=30))
        r = client.post(f"/api/print-prep/{sid}", json={
            "target_size_mm": 80, "bed_x_mm": 220, "bed_y_mm": 220, "bed_z_mm": 250,
        })
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["is_watertight"] is True
        assert b["fits_in_bed"] is True
        assert "_print.stl" in b["stl_url"]
        assert (session_subdir(sid, "exports") / f"{sid}_print.stl").exists()

    def test_prep_does_not_fit_small_bed(self):
        sid = self._session_with_mesh(_sphere(radius=30))
        r = client.post(f"/api/print-prep/{sid}", json={
            "target_size_mm": 200, "bed_x_mm": 145, "bed_y_mm": 145, "bed_z_mm": 185,
        })
        assert r.status_code == 200
        assert r.json()["fits_in_bed"] is False

    def test_prep_without_mesh_409(self):
        sid = create_session()
        r = client.post(f"/api/print-prep/{sid}", json={"target_size_mm": 80})
        assert r.status_code == 409

    def test_unknown_session_404(self):
        r = client.post("/api/print-prep/nope", json={"target_size_mm": 80})
        assert r.status_code == 404
