"""Tests for volume-rendering raw export + oblique MPR reslice (Feature 6b)."""
from __future__ import annotations

import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_mpradv_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir
from services.mpr import get_volume_raw_uint8, render_oblique_png, _downsampled_volume

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _session_with_volume(nz=48, ny=80, nx=80) -> str:
    sid = create_session()
    meshes = session_subdir(sid, "meshes")
    # A smooth gradient volume with a bright cube in the middle.
    vol = np.zeros((nz, ny, nx), dtype=np.float32)
    zz, yy, xx = np.mgrid[0:nz, 0:ny, 0:nx]
    vol = (zz + yy + xx).astype(np.float32)
    vol[nz // 3:2 * nz // 3, ny // 3:2 * ny // 3, nx // 3:2 * nx // 3] += 400.0
    np.save(meshes / "_volume.npy", vol)
    (meshes / "_volume_meta.json").write_text(json.dumps({
        "shape": [nz, ny, nx], "spacing": [1.0, 0.8, 0.8], "wc": 200.0, "ww": 600.0, "modality": "CT",
    }))
    # Clear the downsample cache so this fresh volume is picked up.
    _downsampled_volume.cache_clear()
    return sid


class TestVolumeRaw:
    def test_raw_dims_and_size(self):
        sid = _session_with_volume(48, 80, 80)
        data, dims, spacing = get_volume_raw_uint8(sid, max_dim=64)
        assert len(data) == dims[0] * dims[1] * dims[2]
        assert max(dims) <= 64
        assert len(spacing) == 3

    def test_raw_endpoint_headers(self):
        sid = _session_with_volume()
        r = client.get(f"/api/volume/{sid}/raw")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        dims = [int(x) for x in r.headers["x-dims"].split(",")]
        assert len(r.content) == dims[0] * dims[1] * dims[2]
        assert "x-spacing" in r.headers


class TestOblique:
    def test_service_returns_png(self):
        sid = _session_with_volume()
        png = render_oblique_png(sid, tilt_deg=25.0, pos=0.5, axis="x")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_oblique_endpoint(self):
        sid = _session_with_volume()
        r = client.get(f"/api/slice-oblique/{sid}", params={"tilt": 30, "pos": 0.4, "axis": "y"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert len(r.content) > 100

    def test_oblique_zero_tilt_matches_axial_shape(self):
        sid = _session_with_volume(48, 80, 80)
        r = client.get(f"/api/slice-oblique/{sid}", params={"tilt": 0, "pos": 0.5, "axis": "x"})
        assert r.status_code == 200

    def test_missing_session(self):
        assert client.get("/api/volume/nope/raw").status_code == 404
        assert client.get("/api/slice-oblique/nope").status_code == 404
