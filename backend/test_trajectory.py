"""Tests for the surgical approach trajectory (Feature 3)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_traj_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, write_state
from services.report_generator import read_trajectory_state, build_report_data_from_session

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


class TestEndpoint:
    def test_save_returns_depth(self):
        sid = create_session()
        r = client.post(f"/api/trajectory/{sid}", json={
            "entry": {"x": 0, "y": 0, "z": 0}, "target": {"x": 3, "y": 4, "z": 0},
        })
        assert r.status_code == 200, r.text
        assert abs(r.json()["depth_mm"] - 5.0) < 0.05  # 3-4-5 triangle

    def test_state_roundtrip_and_clear(self):
        sid = create_session()
        client.post(f"/api/trajectory/{sid}", json={
            "entry": {"x": 1, "y": 2, "z": 3}, "target": {"x": 4, "y": 6, "z": 3},
        })
        tr = read_trajectory_state(sid)
        assert tr["entry"] == [1.0, 2.0, 3.0]
        assert tr["target"] == [4.0, 6.0, 3.0]
        assert abs(tr["depth_mm"] - 5.0) < 0.05

        r = client.delete(f"/api/trajectory/{sid}")
        assert r.status_code == 204
        assert read_trajectory_state(sid) == {}

    def test_angle_vs_principal_axis(self):
        sid = create_session()
        # Approach along +x; principal axis along +x → incidence angle 0°.
        write_state(sid, "morpho.axis_x", "1")
        write_state(sid, "morpho.axis_y", "0")
        write_state(sid, "morpho.axis_z", "0")
        client.post(f"/api/trajectory/{sid}", json={
            "entry": {"x": 0, "y": 0, "z": 0}, "target": {"x": 10, "y": 0, "z": 0},
        })
        assert read_trajectory_state(sid)["angle_deg"] < 1.0

    def test_report_data_includes_trajectory(self):
        sid = create_session()
        client.post(f"/api/trajectory/{sid}", json={
            "entry": {"x": 0, "y": 0, "z": 0}, "target": {"x": 0, "y": 0, "z": 12},
        })
        data = build_report_data_from_session(sid)
        assert data.trajectory  # non-empty
        assert data.trajectory["target"] == [0.0, 0.0, 12.0]
        assert abs(data.trajectory["depth_mm"] - 12.0) < 0.05

    def test_no_trajectory_empty(self):
        sid = create_session()
        assert read_trajectory_state(sid) == {}
        assert build_report_data_from_session(sid).trajectory == {}

    def test_unknown_session_404(self):
        r = client.post("/api/trajectory/nope", json={
            "entry": {"x": 0, "y": 0, "z": 0}, "target": {"x": 1, "y": 1, "z": 1},
        })
        assert r.status_code == 404
