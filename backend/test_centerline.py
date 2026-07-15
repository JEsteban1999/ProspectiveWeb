"""Tests for the vessel centerline extraction endpoint (Feature 1)."""
from __future__ import annotations

import os
import tempfile

# Isolate DB before importing the app (the centerline endpoint itself needs no
# auth/DB, but importing main creates the engine).
_tmp = tempfile.mkdtemp(prefix="prospective_cl_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
import vtk
from fastapi.testclient import TestClient
from vtk.util.numpy_support import numpy_to_vtk

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir
from services.segmentation import write_vtp

Base.metadata.create_all(bind=engine)

client = TestClient(app, raise_server_exceptions=True)


def _straight_tube(z0: float, z1: float, radius: float = 2.0) -> vtk.vtkPolyData:
    """A capped straight tube along +Z enclosing volume (for enclosure tests)."""
    n = 20
    zs = np.linspace(z0, z1, n)
    pts = np.column_stack([np.zeros(n), np.zeros(n), zs]).astype(np.float64)

    vtk_pts = vtk.vtkPoints()
    vtk_pts.SetData(numpy_to_vtk(pts, deep=True))
    lines = vtk.vtkCellArray()
    lines.InsertNextCell(n)
    for i in range(n):
        lines.InsertCellPoint(i)
    line_pd = vtk.vtkPolyData()
    line_pd.SetPoints(vtk_pts)
    line_pd.SetLines(lines)

    tube = vtk.vtkTubeFilter()
    tube.SetInputData(line_pd)
    tube.SetRadius(radius)
    tube.SetNumberOfSides(24)
    tube.CappingOn()
    tube.Update()
    return tube.GetOutput()


def _session_with_vessel() -> str:
    sid = create_session()
    write_vtp(_straight_tube(0.0, 40.0, 2.0), session_subdir(sid, "meshes") / "vessel_tree.vtp")
    return sid


def _body(sx, sy, sz, tx, ty, tz, vs=0.8):
    return {
        "session_id": "ignored",
        "source": {"x": sx, "y": sy, "z": sz},
        "target": {"x": tx, "y": ty, "z": tz},
        "voxel_size_mm": vs,
    }


class TestCenterline:
    def test_missing_session(self):
        r = client.post("/api/centerline/nope", json=_body(0, 0, 2, 0, 0, 38))
        assert r.status_code == 404

    def test_no_vessel_mesh(self):
        sid = create_session()
        r = client.post(f"/api/centerline/{sid}", json=_body(0, 0, 2, 0, 0, 38))
        assert r.status_code == 409

    def test_straight_tube(self):
        sid = _session_with_vessel()
        r = client.post(f"/api/centerline/{sid}", json=_body(0, 0, 3, 0, 0, 37))
        assert r.status_code == 200, r.text
        d = r.json()
        # Straight tube → near-unit tortuosity, arc ≈ chord ≈ length.
        assert d["n_points"] >= 2
        assert d["tortuosity"] >= 0.99
        assert d["tortuosity"] < 1.15
        assert d["arc_length_mm"] >= d["chord_length_mm"] - 0.1
        assert d["arc_length_mm"] > 20.0
        # 2 mm radius tube → ~4 mm diameter (voxelisation tolerance).
        assert 2.5 <= d["mean_diameter_mm"] <= 5.5
        assert d["centerline_mesh_url"].startswith("/data/")

    def test_result_keys(self):
        sid = _session_with_vessel()
        r = client.post(f"/api/centerline/{sid}", json=_body(0, 0, 3, 0, 0, 37))
        for k in ("centerline_mesh_url", "n_points", "arc_length_mm", "chord_length_mm",
                  "tortuosity", "tortuosity_index_pct", "mean_diameter_mm",
                  "min_diameter_mm", "max_diameter_mm"):
            assert k in r.json(), f"missing {k}"


class TestCrossSection:
    def test_requires_centerline_first(self):
        sid = _session_with_vessel()
        r = client.post(f"/api/cross-section/{sid}", json={"session_id": "x", "n_samples": 30})
        assert r.status_code == 409  # centerline not extracted yet

    def test_straight_tube_profile(self):
        sid = _session_with_vessel()
        # Extract the centreline (writes centerline_points.npz) …
        assert client.post(f"/api/centerline/{sid}", json=_body(0, 0, 3, 0, 0, 37)).status_code == 200
        # … then analyse cross-sections along it.
        r = client.post(f"/api/cross-section/{sid}", json={"session_id": "x", "n_samples": 30})
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["diameters_mm"]) == len(d["arc_positions_mm"])
        assert len(d["diameters_mm"]) >= 4
        # Uniform 2 mm radius tube → ~4 mm diameter, negligible stenosis.
        assert 3.0 <= d["mean_diameter_mm"] <= 5.5
        assert d["stenosis_pct"] < 25.0
        assert d["stenosis_label"] == "Sin estenosis"

    def test_missing_session(self):
        r = client.post("/api/cross-section/nope", json={"session_id": "x", "n_samples": 30})
        assert r.status_code == 404
