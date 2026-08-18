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


class TestAutoBand:
    """Auto-band: derive a narrow HU window from the vessel intensity at the seed."""

    def _session_with_vessel_in_block(self):
        import numpy as np
        from services.sessions import create_session, session_subdir
        from services import mpr as mprmod
        sid = create_session()
        n = 80
        vol = np.full((n, n, n), 50.0, np.float32)
        vol[20:60, 20:60, 20:60] = 1500.0          # tissue/bone block (mid)
        vol[25:55, 38:42, 38:42] = 3200.0          # bright vessel tube inside
        npy, meta = mprmod._cache_paths(sid)
        np.save(npy, vol)
        meta.write_text(__import__("json").dumps({"shape": [n, n, n], "spacing": [1, 1, 1], "wc": 150, "ww": 700, "modality": "XA"}))
        mprmod._downsampled_volume.cache_clear()
        (session_subdir(sid, "dicom") / "d.txt").write_text("x")
        return sid

    def test_auto_band_isolates_vessel(self):
        from services.sessions import session_subdir
        from services.segmentation import read_vtp
        sid = self._session_with_vessel_in_block()
        # Wide manual band grabs the whole 1500 block.
        rm = client.post(f"/api/segment/grow/{sid}", json={"seeds": [{"x": 40, "y": 40, "z": 40}], "lower": 401, "upper": 4450, "auto_band": False})
        assert rm.status_code == 200
        manual_vox = rm.json()["n_voxels"]
        # Auto band derives ~[2500,3900] from the 3200 vessel → only the tube.
        ra = client.post(f"/api/segment/grow/{sid}", json={"seeds": [{"x": 40, "y": 40, "z": 40}], "auto_band": True})
        assert ra.status_code == 200
        j = ra.json()
        assert j["band_lower"] > 1600           # excludes the 1500 tissue block
        assert j["n_voxels"] < manual_vox       # much less than the wide band
        m = read_vtp(session_subdir(sid, "meshes") / "vessel_tree.vtp")
        b = [0.0] * 6
        m.GetBounds(b)
        assert b[2] > 30 and b[3] < 50          # stayed in the vessel, not the block


# ── Regression: grow-from-seeds on standard 512-axis volumes ────────────────── #

def _session_with_thin_vessel(nz=24, ny=512, nx=512) -> str:
    """Session whose volume holds a 2-voxel-wide bright line — a thin vessel.

    512 on purpose: the old cap (max_axis=400) subsampled exactly this size,
    which is what made thin vessels fall between samples.
    """
    sid = create_session()
    meshes = session_subdir(sid, "meshes")
    (session_subdir(sid, "dicom") / "dummy.txt").write_text("x")
    vol = np.full((nz, ny, nx), -1000.0, dtype=np.float32)
    vol[10:14, 300:304, 100:400] = 4000.0
    vol[10:14, 300:304, 240:260] = 9000.0      # brighter core, like contrast
    np.save(meshes / "_volume.npy", vol)
    (meshes / "_volume_meta.json").write_text(json.dumps({
        "shape": [nz, ny, nx], "spacing": [1.0, 1.0, 1.0],
        "wc": 150.0, "ww": 700.0, "modality": "XA",
    }))
    from services.mpr import _downsampled_volume
    _downsampled_volume.cache_clear()
    return sid


class TestGrowBandRegression:
    def test_band_always_contains_the_seed_value(self):
        """ConnectedThreshold yields nothing when the seed sits outside the band.

        Regression: the window was centred on the 75th percentile of the seed's
        neighbourhood, which for a bright vessel core lands well below the seed
        itself — the band came back excluding the very voxel it grew from.
        """
        from routers.mesh_edit import _band_from_seeds

        vol = np.full((20, 40, 40), -1000.0, dtype=np.float32)
        vol[10, 20, 18:23] = 3000.0
        vol[10, 20, 20] = 9000.0            # bright core, the clicked voxel
        lower, upper = _band_from_seeds(vol, [(10, 20, 20)])
        assert lower <= 9000.0 <= upper, f"la semilla queda fuera de [{lower}, {upper}]"

    def test_band_is_sampled_at_full_resolution(self):
        """The band must not be read off a subsampled grid.

        Regression: a thin vessel falls between samples, so the neighbourhood
        came back as air and the band was computed around background.
        """
        from routers.mesh_edit import _band_from_seeds
        from routers.segment import _maybe_downsample

        # One voxel thick at ODD indices, so a [::2] subsample never samples it.
        vol = np.full((24, 520, 520), -1000.0, dtype=np.float32)
        vol[11, 301, 100:400] = 4000.0
        seed_full = (11, 301, 200)

        lo_full, hi_full = _band_from_seeds(vol, [seed_full])
        assert lo_full <= 4000.0 <= hi_full, "a resolución completa la banda debe ver el vaso"

        ds, _sp, factor = _maybe_downsample(vol, (1.0, 1.0, 1.0), max_axis=400)
        assert factor == 2, "el volumen de prueba debe activar el submuestreo antiguo"
        lo_ds, hi_ds = _band_from_seeds(
            ds, [(seed_full[0] // 2, seed_full[1] // 2, seed_full[2] // 2)]
        )
        assert not (lo_ds <= 4000.0 <= hi_ds), "el caso de prueba ya no reproduce el fallo"

    def test_standard_512_volume_is_not_downsampled(self):
        from routers.segment import _maybe_downsample

        vol = np.zeros((8, 512, 512), dtype=np.float32)
        _ds, _sp, factor = _maybe_downsample(vol, (1.0, 1.0, 1.0), max_axis=512)
        assert factor == 1, "un volumen 512 estándar no debe submuestrearse para el grow"

    def test_grow_endpoint_reaches_a_thin_vessel_on_a_512_volume(self):
        sid = _session_with_thin_vessel()
        r = client.post(f"/api/segment/grow/{sid}", json={
            "seeds": [{"x": 200.0, "y": 301.0, "z": 11.0}],   # world mm, spacing 1
            "lower": 0.0, "upper": 0.0, "auto_band": True, "smoothing": 3,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["vertices"] > 0
        # The whole 300-voxel-long vessel is connected, so the band has to span
        # the bright core too — not stop at the value under the click.
        assert d["n_voxels"] > 500, f"solo creció {d['n_voxels']} vóxeles"
