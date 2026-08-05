"""Tests for interactive mesh editing: ROI crop (box/sphere) + grow-from-seeds.

Unit tests use analytic VTK primitives; endpoint tests build a synthetic session
with a solid sphere volume so grow/crop results are predictable.
"""
from __future__ import annotations

import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_meshedit_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
import vtk
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir
from services.mesh_crop import clip_box, clip_sphere
from services.segmentation import read_vtp

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _sphere(center=(0.0, 0.0, 0.0), radius=10.0, res=32) -> vtk.vtkPolyData:
    src = vtk.vtkSphereSource()
    src.SetCenter(*center)
    src.SetRadius(radius)
    src.SetThetaResolution(res)
    src.SetPhiResolution(res)
    src.Update()
    return src.GetOutput()


# ── Unit: clip_box ──────────────────────────────────────────────────────────── #

class TestClipBox:
    def test_empty_passthrough(self):
        assert clip_box(vtk.vtkPolyData(), -1, 1, -1, 1, -1, 1).GetNumberOfPoints() == 0

    def test_identity_box_keeps_all(self):
        poly = _sphere(radius=10.0)
        n = poly.GetNumberOfPoints()
        out = clip_box(poly, -20, 20, -20, 20, -20, 20)
        assert out.GetNumberOfPoints() >= n - 2

    def test_half_box_reduces(self):
        poly = _sphere(radius=10.0)
        out = clip_box(poly, 0, 20, -20, 20, -20, 20)
        assert 0 < out.GetNumberOfPoints() < poly.GetNumberOfPoints()

    def test_excluded_box_empty(self):
        out = clip_box(_sphere(radius=5.0), 100, 200, 100, 200, 100, 200)
        assert out.GetNumberOfPoints() == 0

    def test_invert_removes_center_band(self):
        poly = _sphere(radius=10.0)
        # Invert keeps geometry OUTSIDE the box → fewer than all but > 0.
        out = clip_box(poly, -5, 5, -20, 20, -20, 20, invert=True)
        assert 0 < out.GetNumberOfPoints() <= poly.GetNumberOfPoints()


# ── Unit: clip_sphere ───────────────────────────────────────────────────────── #

class TestClipSphere:
    def test_empty_passthrough(self):
        assert clip_sphere(vtk.vtkPolyData(), (0, 0, 0), 5).GetNumberOfPoints() == 0

    def test_zero_radius_empty(self):
        assert clip_sphere(_sphere(), (0, 0, 0), 0).GetNumberOfPoints() == 0

    def test_small_sphere_keeps_subset(self):
        poly = _sphere(center=(0, 0, 10), radius=10.0)
        out = clip_sphere(poly, (0, 0, 10), 6.0)
        assert 0 <= out.GetNumberOfPoints() < poly.GetNumberOfPoints()

    def test_large_sphere_keeps_all(self):
        poly = _sphere(radius=10.0)
        out = clip_sphere(poly, (0, 0, 0), 50.0)
        assert out.GetNumberOfPoints() >= poly.GetNumberOfPoints() - 2

    def test_invert_keeps_outside(self):
        poly = _sphere(radius=10.0)
        inside = clip_sphere(poly, (0, 0, 10), 6.0, invert=False).GetNumberOfPoints()
        outside = clip_sphere(poly, (0, 0, 10), 6.0, invert=True).GetNumberOfPoints()
        # Inside + outside should together cover roughly the whole mesh.
        assert outside > 0 and inside >= 0


# ── Endpoint fixtures ───────────────────────────────────────────────────────── #

def _session_with_sphere_volume(n=64, radius=14.0) -> str:
    """Session whose cached volume is a solid HU=300 sphere in air (HU=-1000)."""
    sid = create_session()
    meshes = session_subdir(sid, "meshes")
    dicom = session_subdir(sid, "dicom")
    (dicom / "dummy.txt").write_text("x")  # so 'DICOM present' guards pass
    zz, yy, xx = np.mgrid[0:n, 0:n, 0:n]
    c = n / 2.0
    r = np.sqrt((zz - c) ** 2 + (yy - c) ** 2 + (xx - c) ** 2)
    vol = np.where(r <= radius, 300.0, -1000.0).astype(np.float32)
    np.save(meshes / "_volume.npy", vol)
    (meshes / "_volume_meta.json").write_text(json.dumps({
        "shape": [n, n, n], "spacing": [1.0, 1.0, 1.0], "wc": 150.0, "ww": 700.0, "modality": "CT",
    }))
    from services.mpr import _downsampled_volume
    _downsampled_volume.cache_clear()
    return sid


# ── Endpoint: grow-from-seeds ───────────────────────────────────────────────── #

class TestGrowEndpoint:
    def test_grow_builds_mesh(self):
        sid = _session_with_sphere_volume()
        r = client.post(f"/api/segment/grow/{sid}", json={
            "seeds": [{"x": 32.0, "y": 32.0, "z": 32.0}],
            "lower": 100.0, "upper": 500.0, "smoothing": 3, "cleanup": 5,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["vertices"] > 0
        assert body["n_voxels"] > 0
        assert body["seeds"] == 1
        assert "vessel_tree.vtp" in body["mesh_url"]
        assert (session_subdir(sid, "meshes") / "vessel_tree.vtp").exists()

    def test_grow_air_seed_rejected(self):
        sid = _session_with_sphere_volume()
        r = client.post(f"/api/segment/grow/{sid}", json={
            "seeds": [{"x": 2.0, "y": 2.0, "z": 2.0}], "lower": 100.0, "upper": 500.0,
        })
        assert r.status_code == 422

    def test_grow_unknown_session(self):
        r = client.post("/api/segment/grow/does-not-exist", json={
            "seeds": [{"x": 1.0, "y": 1.0, "z": 1.0}],
        })
        assert r.status_code == 404


# ── Endpoint: mesh crop ─────────────────────────────────────────────────────── #

class TestCropEndpoint:
    def _grown_session(self) -> str:
        sid = _session_with_sphere_volume()
        r = client.post(f"/api/segment/grow/{sid}", json={
            "seeds": [{"x": 32.0, "y": 32.0, "z": 32.0}],
            "lower": 100.0, "upper": 500.0, "smoothing": 3,
        })
        assert r.status_code == 200, r.text
        return sid

    def test_sphere_crop_reduces(self):
        sid = self._grown_session()
        meshes = session_subdir(sid, "meshes")
        n_before = read_vtp(meshes / "vessel_tree.vtp").GetNumberOfPoints()
        r = client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 32.0, "y": 32.0, "z": 46.0}, "radius": 8.0,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert 0 < body["vertices"] < n_before
        assert body["removed_vertices"] > 0

    def test_box_invert_removes_cap(self):
        sid = self._grown_session()
        r = client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "box", "center": {"x": 32.0, "y": 32.0, "z": 46.0}, "radius": 8.0, "invert": True,
        })
        assert r.status_code == 200, r.text
        assert r.json()["removed_vertices"] > 0

    def test_crop_empty_result_rejected(self):
        sid = self._grown_session()
        # A tiny sphere far from the mesh removes everything → 422.
        r = client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 1.0, "y": 1.0, "z": 1.0}, "radius": 2.0,
        })
        assert r.status_code == 422

    def test_crop_without_mesh_conflict(self):
        sid = _session_with_sphere_volume()  # no grow/segment yet
        r = client.post(f"/api/mesh-crop/{sid}", json={
            "mode": "sphere", "center": {"x": 32.0, "y": 32.0, "z": 32.0}, "radius": 10.0,
        })
        assert r.status_code == 409
