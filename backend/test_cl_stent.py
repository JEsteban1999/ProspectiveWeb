"""Tests for centreline-guided stent deployment (Feature 1 / cl_stent)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_clstent_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir
from services.stent_deployment import deploy_stent_on_centerline

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _curved_centerline(n=40, radius=1.8):
    t = np.linspace(0, np.pi, n)
    pts = np.stack([20 * np.cos(t), 20 * np.sin(t), t * 3], axis=1)
    radii = np.full(n, radius)
    return pts.astype(np.float32), radii.astype(np.float32)


class TestService:
    def test_builds_tube_with_braids(self):
        pts, radii = _curved_centerline()
        res = deploy_stent_on_centerline(pts, radii, stent_diameter_mm=4.0, braid=True, braid_count=6)
        assert res.stent_poly_data.GetNumberOfPoints() > 0
        assert res.stent_poly_data.GetNumberOfPolys() > 0
        assert res.length_mm > 0
        assert res.total_arc_mm >= res.length_mm
        # coverage = stent_r / vessel_r = 2.0 / 1.8 ≈ 1.11
        assert 1.0 < res.coverage_ratio < 1.2

    def test_braids_add_geometry(self):
        # vtkTubeFilter emits triangle strips (not polys), so compare total cells.
        pts, radii = _curved_centerline()
        braided = deploy_stent_on_centerline(pts, radii, 4.0, braid=True, braid_count=6)
        plain = deploy_stent_on_centerline(pts, radii, 4.0, braid=False)
        assert braided.stent_poly_data.GetNumberOfCells() > plain.stent_poly_data.GetNumberOfCells()

    def test_short_segment_raises(self):
        pts, radii = _curved_centerline()
        try:
            deploy_stent_on_centerline(pts, radii, 4.0, start_arc_mm=1.0, end_arc_mm=1.2)
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestEndpoint:
    def _session_with_centerline(self) -> str:
        sid = create_session()
        pts, radii = _curved_centerline()
        np.savez(session_subdir(sid, "meshes") / "centerline_points.npz", points=pts, radii=radii)
        return sid

    def test_deploy_full(self):
        sid = self._session_with_centerline()
        r = client.post(f"/api/cl-stent/{sid}", json={"session_id": sid, "stent_diameter_mm": 3.5})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["length_mm"] > 0
        assert body["total_arc_mm"] > 0
        assert "cl_stent.vtp" in body["stent_mesh_url"]
        assert (session_subdir(sid, "meshes") / "cl_stent.vtp").exists()

    def test_deploy_subrange_shorter(self):
        sid = self._session_with_centerline()
        full = client.post(f"/api/cl-stent/{sid}", json={"session_id": sid, "stent_diameter_mm": 4.0}).json()
        total = full["total_arc_mm"]
        sub = client.post(f"/api/cl-stent/{sid}", json={
            "session_id": sid, "stent_diameter_mm": 4.0,
            "start_arc_mm": total * 0.25, "end_arc_mm": total * 0.75, "braid": False,
        })
        assert sub.status_code == 200
        assert sub.json()["length_mm"] < full["length_mm"]

    def test_oversize_warning(self):
        sid = self._session_with_centerline()
        r = client.post(f"/api/cl-stent/{sid}", json={"session_id": sid, "stent_diameter_mm": 6.0})
        assert r.status_code == 200
        assert r.json()["warning"] is not None  # 3.0 stent_r vs 1.8 vessel_r → oversized

    def test_short_segment_422(self):
        sid = self._session_with_centerline()
        r = client.post(f"/api/cl-stent/{sid}", json={
            "session_id": sid, "stent_diameter_mm": 4.0, "start_arc_mm": 1.0, "end_arc_mm": 1.2,
        })
        assert r.status_code == 422

    def test_no_centerline_409(self):
        sid = create_session()
        r = client.post(f"/api/cl-stent/{sid}", json={"session_id": sid})
        assert r.status_code == 409

    def test_unknown_session_404(self):
        r = client.post("/api/cl-stent/nope", json={"session_id": "nope"})
        assert r.status_code == 404
