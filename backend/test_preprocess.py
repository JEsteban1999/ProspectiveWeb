"""Tests for optional DICOM volume preprocessing (Feature 10)."""
from __future__ import annotations

import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_preproc_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir
from services.preprocess import preprocess_volume, subtract_bone
from services import mpr as mprmod

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _session_with_volume(nz=40, ny=64, nx=64, spacing=(2.0, 0.5, 0.5)) -> str:
    sid = create_session()
    vol = (np.random.rand(nz, ny, nx) * 200 + 50).astype(np.float32)
    vol[0, 0, 0] = 9000.0
    vol[1, 1, 1] = -5000.0
    npy, meta = mprmod._cache_paths(sid)
    np.save(npy, vol)
    meta.write_text(json.dumps({"shape": [nz, ny, nx], "spacing": list(spacing), "wc": 150, "ww": 700, "modality": "CT"}))
    mprmod._downsampled_volume.cache_clear()
    return sid


class TestService:
    def test_clip(self):
        vol = np.array([[[9000, -5000], [100, 200]]], dtype=np.float32)
        out, sp = preprocess_volume(vol, (1, 1, 1), clip_hu=True)
        assert out.max() <= 3000 and out.min() >= -1000

    def test_isotropic_resample_dims(self):
        vol = np.zeros((40, 64, 64), dtype=np.float32)
        out, sp = preprocess_volume(vol, (2.0, 0.5, 0.5), clip_hu=False, resample_isotropic=True, target_spacing_mm=1.0)
        assert sp == (1.0, 1.0, 1.0)
        assert out.shape == (80, 32, 32)

    def test_subtract_bone(self):
        vol = np.array([[[400.0, 100.0], [-1000.0, 350.0]]], dtype=np.float32)
        out = subtract_bone(vol, 300.0)
        assert out[0, 0, 0] == -1000.0  # 400 > 300 → removed
        assert out[0, 1, 1] == -1000.0  # 350 > 300 → removed
        assert out[0, 0, 1] == 100.0    # kept


class TestEndpoint:
    def test_resample_rewrites_cache(self):
        sid = _session_with_volume()
        r = client.post(f"/api/preprocess/{sid}", json={
            "clip_hu": True, "resample_isotropic": True, "target_spacing_mm": 1.0,
        })
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["spacing_after"] == [1.0, 1.0, 1.0]
        assert b["shape_after"] == [80, 32, 32]
        # MPR meta on disk reflects the new geometry
        meta = mprmod.ensure_volume_cached(sid)
        assert meta["shape"] == [80, 32, 32]
        vol = np.load(mprmod._cache_paths(sid)[0])
        assert vol.max() <= 3001 and vol.min() >= -1001

    def test_noop_selection_422(self):
        sid = _session_with_volume()
        r = client.post(f"/api/preprocess/{sid}", json={"clip_hu": False, "resample_isotropic": False, "smooth": False})
        assert r.status_code == 422

    def test_unknown_session_404(self):
        r = client.post("/api/preprocess/nope", json={"clip_hu": True})
        assert r.status_code == 404


# ── Regression: the HU clamp is a Hounsfield-only operation ─────────────────── #

def _session_with_xa_volume(nz=24, ny=48, nx=48) -> str:
    """A 3DRA/XA-like volume: contrast runs far past the CT HU ceiling."""
    sid = create_session()
    vol = np.full((nz, ny, nx), -1000.0, dtype=np.float32)
    vol[10:14, 20:28, 20:28] = 9000.0          # contrast column, way over 3000
    npy, meta = mprmod._cache_paths(sid)
    np.save(npy, vol)
    meta.write_text(json.dumps({
        "shape": [nz, ny, nx], "spacing": [1.0, 1.0, 1.0],
        "wc": 150, "ww": 700, "modality": "XA",
    }))
    mprmod._downsampled_volume.cache_clear()
    return sid


class TestHuClipIsHounsfieldOnly:
    """Regression: «Recorte de HU (−1000…3000)» shipped ticked by default and
    was applied to any modality. On a 3DRA/XA study — where intensities are not
    Hounsfield units and routinely exceed 3000 — it flattened the whole contrast
    column to a single value.
    """

    def test_modality_predicate(self):
        from services.preprocess import is_hounsfield
        assert is_hounsfield("CT") and is_hounsfield("cta")
        assert not is_hounsfield("XA")
        assert not is_hounsfield("MR")
        assert not is_hounsfield(None)

    def test_clip_alone_is_rejected_on_xa(self):
        sid = _session_with_xa_volume()
        r = client.post(f"/api/preprocess/{sid}", json={"clip_hu": True})
        assert r.status_code == 422
        assert "Hounsfield" in r.json()["detail"]

    def test_xa_contrast_survives_when_other_ops_run(self):
        sid = _session_with_xa_volume()
        r = client.post(f"/api/preprocess/{sid}", json={"clip_hu": True, "smooth": True})
        assert r.status_code == 200, r.text
        assert "omitido" in r.json()["note"]

        npy, _meta = mprmod._cache_paths(sid)
        mprmod._downsampled_volume.cache_clear()
        out = np.load(npy)
        assert out.max() > 3000.0, "el recorte aplanó el contraste de un volumen XA"

    def test_ct_volume_is_still_clipped(self):
        sid = _session_with_volume()
        r = client.post(f"/api/preprocess/{sid}", json={"clip_hu": True})
        assert r.status_code == 200, r.text
        assert "omitido" not in r.json()["note"]

        npy, _meta = mprmod._cache_paths(sid)
        mprmod._downsampled_volume.cache_clear()
        out = np.load(npy)
        assert out.max() <= 3000.0 and out.min() >= -1000.0
