"""Regression tests for the audit fixes (2026-07):

* upload no longer rejects studies with > 1000 files
* medical-record number (historia clínica) is unique → 409 on duplicate
* the MPR display window falls back to the data range when the DICOM tag
  window (e.g. a DSA 0/1000 preset) does not cover the pixel intensities
* the real inter-slice z-spacing matches SimpleITK on the sample corpus
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.mpr import _display_window

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)

_CORPUS = Path(r"C:\UniNavarra\Proyectos\Prospective\ProspectiveWeb\Archivos DICOM\DICOM")


# ── upload: > 1000 files must not be rejected by the multipart cap ──────────── #

def test_upload_accepts_more_than_1000_files():
    # 1001 tiny non-DICOM parts: the point is that the multipart parser no longer
    # raises "Too many files" at 1000. scan_series finds no DICOM → 200 + empty.
    files = [("files", (f"f{i}.dcm", b"x", "application/octet-stream")) for i in range(1001)]
    r = client.post("/api/upload", files=files)
    # The point: no 400 "Too many files. Maximum number of files is 1000".
    assert r.status_code == 200, r.text
    assert r.json()["total_files"] == 1001


# ── patients: duplicate historia clínica is rejected ───────────────────────── #

def test_duplicate_hospital_id_conflicts():
    hc = "HC-UNIQUE-TEST-001"
    r1 = client.post("/api/patients", json={"surname": "Uno", "hospital_id": hc})
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/patients", json={"surname": "Dos", "hospital_id": hc})
    assert r2.status_code == 409
    assert hc in r2.json()["detail"]


def test_empty_hospital_id_allows_multiple():
    r1 = client.post("/api/patients", json={"surname": "SinHC-A", "hospital_id": ""})
    r2 = client.post("/api/patients", json={"surname": "SinHC-B", "hospital_id": ""})
    assert r1.status_code == 201 and r2.status_code == 201


# ── MPR display window fallback ────────────────────────────────────────────── #

def test_display_window_derives_when_tag_misses_data():
    # DSA-like: background near -1024, tiny bright vessel tail; tag preset 0/1000
    # sits in the empty gap and covers almost no voxels.
    rng = np.random.default_rng(0)
    bg = rng.normal(-900, 120, 200_000).astype("float32")
    vessels = rng.uniform(2000, 12000, 1_000).astype("float32")
    vol = np.concatenate([bg, vessels])
    wc, ww = _display_window(vol, 0.0, 1000.0)
    inside = float(np.mean((vol >= wc - ww / 2) & (vol <= wc + ww / 2)))
    assert inside > 0.9  # derived window now covers the data


def test_display_window_keeps_sensible_tag():
    rng = np.random.default_rng(1)
    ct = rng.normal(40, 150, 200_000).astype("float32")
    wc, ww = _display_window(ct, 40.0, 400.0)
    assert (wc, ww) == (40.0, 400.0)  # radiological CT window preserved


# ── DSA threshold no longer starves the mesh (interim, calibrated on case 9) ─ #

def test_dsa_threshold_targets_vessel_body_not_cores():
    """A subtracted-DSA-like volume should threshold at ~the brightest 0.4% of
    voxels (vessel body), not the old p99.9 (0.1% cores) that starved the mesh."""
    from services.thresholds import compute_auto_thresholds, voxel_fraction

    rng = np.random.default_rng(7)
    bg = rng.normal(-950, 90, 2_000_000).astype("float32")   # subtracted background
    vessels = rng.uniform(300, 9000, 12_000).astype("float32")  # bright vessel tail
    vol = np.concatenate([bg, vessels])
    lower, upper, strategy = compute_auto_thresholds(vol, "XA", 0.0, 1000.0)
    assert strategy == "dsa"
    frac = voxel_fraction(vol, lower, upper)
    # ~0.4% target, clearly richer than the old 0.1%
    assert 0.25 < frac * 100 < 0.6, f"voxel fraction {frac*100:.3f}% out of band"


@pytest.mark.skipif(not _CORPUS.exists(), reason="sample DICOM corpus not present")
def test_case9_detects_end_to_end():
    """Reference DSA study (case 9) must produce >=1 aneurysm candidate through
    the real upload -> thresholds -> segment -> detect pipeline."""
    d = _CORPUS / "ANKYRAS/case 9/ANGIOGRAFIA CEREBRAL/XA ACI DERECHA VAS"
    if not d.exists():
        pytest.skip("missing case 9")
    from services.dicom_loader import scan_series
    paths = [p for p in d.rglob("*") if p.is_file()]
    files = [("files", (p.name, p.read_bytes(), "application/dicom")) for p in paths]
    up = client.post("/api/upload", files=files).json()
    sid, ser = up["session_id"], up["series"][0]["series_id"]
    th = client.get(f"/api/thresholds/{sid}").json()
    assert th["strategy"] == "dsa"
    client.post("/api/segment", json={
        "session_id": sid, "series_id": ser,
        "lower": th["lower"], "upper": th["upper"], "smoothing": 3, "cleanup": 3,
    })
    dt = client.post(f"/api/detect/{sid}", json={}).json()
    assert len(dt.get("candidates", [])) >= 1, "case 9 detected no aneurysm candidate"


# ── z-spacing: upload preview matches the volume SimpleITK loads ───────────── #

@pytest.mark.skipif(not _CORPUS.exists(), reason="sample DICOM corpus not present")
@pytest.mark.parametrize("rel", [
    "ANKYRAS/case 9/ANGIOGRAFIA CEREBRAL/XA ACI DERECHA VAS",
    "ANKYRAS/case 2/ANGIOGRAFIA CEREBRAL COMPLETA/XA",
])
def test_scan_series_zspacing_matches_load(rel):
    from services.dicom_loader import scan_series, load_series
    d = _CORPUS / rel
    if not d.exists():
        pytest.skip(f"missing {rel}")
    s = scan_series(d)[0]
    dcm = load_series(s["series_uid"], d)
    assert abs(s["spacing_z"] - dcm.spacing[0]) < 0.05
