"""Tests for the adaptive band + real-time coarse-mesh preview + top-N cleanup."""
from __future__ import annotations

import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_segprev_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir, write_state
from services.segmentation import level_to_cleanup
from services import mpr as mprmod

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _wide_range_session() -> str:
    """A '3DRA-like' volume: background ~50, bone shell ~1500, bright vessel ~3200."""
    sid = create_session()
    n = 64
    zz, yy, xx = np.mgrid[0:n, 0:n, 0:n]
    r = np.sqrt((zz - 32) ** 2 + (yy - 32) ** 2 + (xx - 32) ** 2)
    vol = np.full((n, n, n), 50.0, np.float32)
    vol[r <= 20] = 1500.0
    vol[r <= 8] = 3200.0
    npy, meta = mprmod._cache_paths(sid)
    np.save(npy, vol)
    meta.write_text(json.dumps({"shape": [n, n, n], "spacing": [1, 1, 1], "wc": 150, "ww": 700, "modality": "XA"}))
    mprmod._downsampled_volume.cache_clear()
    return sid


def _wide_ww_3dra_session() -> "tuple[str, np.ndarray]":
    """Non-subtracted wide-WW 3DRA (like case 3): tissue fills the head, a thin
    bright vessel is the top ~2%. State carries modality=XA + wide WW so the
    band goes through the xa_band_pass branch, as it does after a real upload.
    Returns (sid, volume) so the test can measure the captured voxel fraction."""
    sid = create_session()
    rng = np.random.default_rng(5)
    n = 70
    vol = rng.normal(-400.0, 130.0, (n, n, n)).astype(np.float32)   # tissue bulk
    # ~2% of voxels are bright vessel (2200..5000), scattered.
    flat = vol.reshape(-1)
    k = int(flat.size * 0.02)
    idx = rng.choice(flat.size, k, replace=False)
    flat[idx] = rng.uniform(2200.0, 5000.0, k).astype(np.float32)
    npy, meta = mprmod._cache_paths(sid)
    np.save(npy, vol)
    meta.write_text(json.dumps({"shape": [n, n, n], "spacing": [1, 1, 1], "wc": -343.0, "ww": 7577.0, "modality": "XA"}))
    mprmod._downsampled_volume.cache_clear()
    write_state(sid, "dicom.modality", "XA")
    write_state(sid, "dicom.window_center", "-343.0")
    write_state(sid, "dicom.window_width", "7577.0")
    return sid, vol


class TestCleanupMapping:
    def test_switches_to_topn_at_level_5(self):
        assert level_to_cleanup(4)[0] == 0     # still size-based
        assert level_to_cleanup(5)[0] == 20    # top-N kicks in
        assert level_to_cleanup(7)[0] == 10
        assert level_to_cleanup(10)[0] == 3    # only the 3 largest


class TestSuggestedBand:
    def test_adapts_to_volume_scale(self):
        sid = _wide_range_session()
        r = client.get(f"/api/segment/suggested-band/{sid}")
        assert r.status_code == 200, r.text
        b = r.json()
        # slider range must reach the bright values (3200), not stop at a HU default
        assert b["vmax"] > 1500
        # suggested lower is well above background (50), adapted to the scale
        assert b["lower"] > 100
        assert b["upper"] >= b["lower"]

    def test_non_subtracted_3dra_starts_on_vessels_not_tissue(self):
        # Regresión case 3: antes la banda sugerida (p94) arrancaba dentro del
        # bloque de tejido y capturaba ~9% del volumen (la cabeza entera). Ahora
        # usa la banda por modalidad y captura una fracción pequeña (los vasos).
        from services.thresholds import voxel_fraction
        sid, vol = _wide_ww_3dra_session()
        b = client.get(f"/api/segment/suggested-band/{sid}").json()
        assert b["vmax"] > 2000.0                       # el slider alcanza los vasos
        assert b["upper"] >= b["lower"]
        # La banda sugerida captura ~vasos (<3%), no el bloque de tejido (~9%).
        frac = voxel_fraction(vol, b["lower"], b["upper"])
        assert frac < 0.03, (b, frac)
        # Y es mucho más selectiva que la vieja banda p90–p99.
        p90, p99 = float(np.percentile(vol, 90)), float(np.percentile(vol, 99))
        assert frac < voxel_fraction(vol, p90, p99)

    def test_fallback_without_volume(self):
        sid = create_session()  # no cached volume
        r = client.get(f"/api/segment/suggested-band/{sid}")
        assert r.status_code == 200
        assert r.json()["lower"] == 150.0  # CT-HU fallback

    def test_unknown_session_404(self):
        assert client.get("/api/segment/suggested-band/nope").status_code == 404


class TestPreview:
    def test_preview_builds_coarse_mesh(self):
        sid = _wide_range_session()
        r = client.post(f"/api/segment/preview/{sid}", json={"lower": 2500, "upper": 4000, "cleanup": 7, "downsample": 2})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["vertices"] > 0
        assert 0 < body["voxel_fraction"] < 0.1  # only the bright vessel core
        assert "preview_mesh.vtp" in body["mesh_url"]
        assert (session_subdir(sid, "meshes") / "preview_mesh.vtp").exists()

    def test_empty_band_422(self):
        sid = _wide_range_session()
        r = client.post(f"/api/segment/preview/{sid}", json={"lower": 9000, "upper": 9500, "cleanup": 7})
        assert r.status_code == 422

    def test_unknown_session_404(self):
        r = client.post("/api/segment/preview/nope", json={"lower": 100, "upper": 500})
        assert r.status_code == 404
