"""Tests for the DICOM Structured Report endpoint (Feature 4)."""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_sr_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import pydicom
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, write_state, session_subdir

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)

_SR_SOP = "1.2.840.10008.5.1.4.1.1.88.33"


def _session_with_morpho() -> str:
    sid = create_session()
    write_state(sid, "morpho.volume_mm3", "120.4")
    write_state(sid, "morpho.surface_area_mm2", "210.5")
    write_state(sid, "morpho.max_diameter_mm", "7.5")
    write_state(sid, "morpho.neck_mm", "3.2")
    write_state(sid, "morpho.dome_height_mm", "5.8")
    write_state(sid, "morpho.dnr", "2.34")
    write_state(sid, "morpho.ar", "1.81")
    write_state(sid, "morpho.rupture_risk", "Moderado")
    return sid


class TestDicomSR:
    def test_missing_session(self):
        r = client.post("/api/report/dicom-sr", json={"session_id": "nope"})
        assert r.status_code == 404

    def test_no_morphometry(self):
        sid = create_session()
        r = client.post("/api/report/dicom-sr", json={"session_id": sid})
        assert r.status_code == 422

    def test_generates_valid_sr(self):
        sid = _session_with_morpho()
        r = client.post("/api/report/dicom-sr", json={"session_id": sid, "patient_name": "TEST^A"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["dicom_sr_url"] and d["dicom_sr_url"].endswith(".dcm")

        # The written file must be a valid, re-readable Comprehensive SR.
        path = session_subdir(sid, "reports") / f"{sid}_sr.dcm"
        assert path.exists()
        ds = pydicom.dcmread(str(path))
        assert ds.Modality == "SR"
        assert str(ds.SOPClassUID) == _SR_SOP
        assert ds.CompletionFlag == "COMPLETE"
        # Root → morphometry container with NUM items.
        morph = ds.ContentSequence[0]
        assert morph.ValueType == "CONTAINER"
        num_items = [it for it in morph.ContentSequence if it.ValueType == "NUM"]
        assert len(num_items) >= 5
        # Risk encoded as a CODE item.
        code_items = [it for it in morph.ContentSequence if it.ValueType == "CODE"]
        assert len(code_items) == 1
