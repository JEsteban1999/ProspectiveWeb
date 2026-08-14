"""PHASES score — computation, session recording and downstream reports.

The endpoint had no test coverage at all, which is how it went unnoticed that
the score was purely transient: it was computed, shown on screen and then lost,
so it never reached the PDF report or the DICOM SR.
"""
from __future__ import annotations

import pydicom
from fastapi.testclient import TestClient

from main import app
from services.report_generator import build_report_data_from_session, ReportGenerator
from services.sessions import create_session, session_subdir, write_state

client = TestClient(app, raise_server_exceptions=True)

_URL = "/api/phases"

# Greving et al. 2014, worked through by hand:
#   Japan +3, hypertension +1, age ≥70 +1, size 8.7 mm +3,
#   earlier SAH +4, ACA/PCOM/posterior +4  →  16 points
_HIGH = {
    "population": "japan", "hypertension": True, "age_years": 75,
    "size_mm": 8.7, "earlier_sah": True, "site": "aca_pcom_posterior",
}
# Everything at baseline except the size band → 3 points
_LOW = {
    "population": "other", "hypertension": False, "age_years": 60,
    "size_mm": 8.7, "earlier_sah": False, "site": "ica",
}


def _session_with_morpho() -> str:
    sid = create_session()
    write_state(sid, "morpho.max_diameter_mm", "8.7")
    write_state(sid, "morpho.volume_mm3", "111.4")
    write_state(sid, "morpho.rupture_risk", "Alto")
    return sid


# ── Score ───────────────────────────────────────────────────────────────── #

def test_score_matches_the_published_table():
    d = client.post(_URL, json=_HIGH).json()
    assert (d["population_pts"], d["hypertension_pts"], d["age_pts"],
            d["size_pts"], d["sah_pts"], d["site_pts"]) == (3, 1, 1, 3, 4, 4)
    assert d["total_score"] == 16
    assert d["risk_band"] == "high"

    d = client.post(_URL, json=_LOW).json()
    assert d["total_score"] == 3
    assert d["risk_band"] == "low"


def test_works_without_a_session():
    """The calculator must stay usable as a throw-away tool."""
    r = client.post(_URL, json=_LOW)
    assert r.status_code == 200
    assert r.json()["total_score"] == 3


def test_unknown_session_is_rejected():
    r = client.post(_URL, json={**_LOW, "session_id": "does-not-exist"})
    assert r.status_code == 404


# ── Recording ───────────────────────────────────────────────────────────── #

def test_score_is_recorded_in_the_session():
    sid = _session_with_morpho()
    api = client.post(_URL, json={**_HIGH, "session_id": sid}).json()

    ph = build_report_data_from_session(sid).phases
    assert ph, "el informe no vería el PHASES calculado"
    assert ph["total_score"] == api["total_score"]
    assert ph["risk_band"] == "high"
    # The inputs travel with the score: size auto-fills from the morphometry,
    # so a later re-measurement must not leave an unexplained number behind.
    assert ph["inputs"]["size_mm"] == 8.7
    assert ph["inputs"]["population"] == "japan"
    assert ph["points"]["site"] == 4


def test_recomputing_overwrites_the_recorded_score():
    sid = _session_with_morpho()
    client.post(_URL, json={**_HIGH, "session_id": sid})
    client.post(_URL, json={**_LOW, "session_id": sid})
    assert build_report_data_from_session(sid).phases["total_score"] == 3


# ── Downstream ──────────────────────────────────────────────────────────── #

def test_phases_reaches_the_pdf_with_its_breakdown():
    sid = _session_with_morpho()
    client.post(_URL, json={**_HIGH, "session_id": sid})

    gen = ReportGenerator(build_report_data_from_session(sid))
    section = gen._section_phases()
    assert section, "no se emite la sección PHASES"
    assert "PHASES" in section[0].text

    table = next(f for f in section if hasattr(f, "_cellvalues"))
    cells = [str(c) for row in table._cellvalues for c in row]
    assert any("Japón" in c for c in cells)          # input, not just points
    assert any("8.7 mm" in c for c in cells)
    assert any("75 años" in c for c in cells)

    titles = [f.text for f in gen._build_story() if hasattr(f, "text")]
    assert any("PHASES 16" in t and "17.0 %" in t for t in titles), \
        "el PHASES no llega al documento"

    out = session_subdir(sid, "reports")
    out.mkdir(parents=True, exist_ok=True)
    assert gen.generate(out / "r.pdf").stat().st_size > 1000


def test_pdf_omits_the_section_when_phases_was_never_run():
    sid = _session_with_morpho()
    gen = ReportGenerator(build_report_data_from_session(sid))
    assert gen._section_phases() == []


def test_phases_reaches_the_dicom_sr():
    sid = _session_with_morpho()
    client.post(_URL, json={**_HIGH, "session_id": sid})

    r = client.post("/api/report/dicom-sr", json={"session_id": sid})
    assert r.status_code == 200, r.text

    ds = pydicom.dcmread(session_subdir(sid, "reports") / f"{sid}_sr.dcm")
    text = str(ds)
    assert "PHASES Score Assessment" in text
    assert "PHASES Total Score" in text
    assert "PHASES 5-Year Rupture Risk" in text
