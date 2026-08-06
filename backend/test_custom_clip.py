"""Tests for custom clip import + multi-clip planning (Feature 5)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_customclip_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import vtk
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir, write_state
from services.report_generator import build_report_data_from_session
from services.clips import catalogue_to_api

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _cube_stl_bytes(sid: str) -> bytes:
    cube = vtk.vtkCubeSource()
    cube.SetXLength(4); cube.SetYLength(2); cube.SetZLength(2)
    cube.Update()
    path = session_subdir(sid, "meshes") / "_cube.stl"
    w = vtk.vtkSTLWriter()
    w.SetFileName(str(path)); w.SetInputData(cube.GetOutput()); w.Write()
    return path.read_bytes()


class TestCustomClip:
    def test_upload_and_plan(self):
        sid = create_session()
        write_state(sid, "morpho.neck_mm", "3.5")
        stl = _cube_stl_bytes(sid)

        up = client.post(f"/api/clips/custom/{sid}", files={"file": ("miclip.stl", stl, "application/octet-stream")})
        assert up.status_code == 200, up.text
        cid = up.json()["clip_id"]
        assert cid == "custom:0"
        assert up.json()["name"] == "miclip.stl"
        assert (session_subdir(sid, "meshes") / "custom_clip_0.vtp").exists()

        # multi-clip plan mixing catalogue + custom
        cat = catalogue_to_api()[0]["id"]
        r = client.post("/api/clips/plan", json={"session_id": sid, "placements": [
            {"clip_id": cat, "position": {"x": 0, "y": 0, "z": 0}, "normal": [0, 0, 1], "rotation_deg": 0},
            {"clip_id": cid, "position": {"x": 5, "y": 0, "z": 0}, "normal": [0, 0, 1], "rotation_deg": 30},
        ]})
        assert r.status_code == 200

        data = build_report_data_from_session(sid)
        assert len(data.clips) == 2
        custom_entry = [c for c in data.clips if c.is_custom]
        assert len(custom_entry) == 1
        assert custom_entry[0].name == "miclip.stl"

    def test_bad_format_rejected(self):
        sid = create_session()
        r = client.post(f"/api/clips/custom/{sid}", files={"file": ("x.png", b"nope", "image/png")})
        assert r.status_code == 422

    def test_second_custom_gets_next_id(self):
        sid = create_session()
        stl = _cube_stl_bytes(sid)
        a = client.post(f"/api/clips/custom/{sid}", files={"file": ("a.stl", stl, "x")})
        b = client.post(f"/api/clips/custom/{sid}", files={"file": ("b.stl", stl, "x")})
        assert a.json()["clip_id"] == "custom:0"
        assert b.json()["clip_id"] == "custom:1"

    def test_unknown_session_404(self):
        r = client.post("/api/clips/custom/nope", files={"file": ("a.stl", b"x", "x")})
        assert r.status_code == 404
