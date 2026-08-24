"""Follow-up compares acquisitions, not pipeline runs.

Grouping by session made two runs of the SAME images look like two time points,
so a millimetre of segmentation noise read as growth. And it mixed clinical
cases: a second aneurysm in the same patient is a different lesion, not a later
measurement of the first.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

_tmp = tempfile.mkdtemp(prefix="prospective_long_")
os.environ.setdefault("PROSPECTIVE_DB_URL", f"sqlite:///{_tmp}/test.db")
os.environ["STUDY_FILES_ROOT"] = f"{_tmp}/study_files"

from fastapi.testclient import TestClient

from main import app
from services.database import SessionLocal
from services.db_models import ImagingStudy, Patient, PlanningSession, Study

client = TestClient(app)


def _fixture(n_runs_on_first: int = 1, second_case: bool = False):
    """Patient with one case and two acquisitions three months apart."""
    db = SessionLocal()
    try:
        p = Patient(surname="Seguimiento", given_name="Test",
                    hospital_id=f"HC-LONG-{uuid.uuid4().hex[:6]}")
        db.add(p); db.commit(); db.refresh(p)
        case = Study(patient_id=p.id, description="Aneurisma ACM", dx_principal="Aneurisma ACM")
        db.add(case); db.commit(); db.refresh(case)

        base = ImagingStudy(case_id=case.id, patient_id=p.id,
                            description="Basal", acquired_at="2026-01-10")
        ctrl = ImagingStudy(case_id=case.id, patient_id=p.id,
                            description="Control", acquired_at="2026-04-10")
        db.add_all([base, ctrl]); db.commit(); db.refresh(base); db.refresh(ctrl)

        now = datetime.now(timezone.utc)
        ids = {}
        # Several runs on the baseline: same images, slightly different numbers.
        for i in range(n_runs_on_first):
            sid = f"base-{uuid.uuid4().hex[:8]}"
            db.add(PlanningSession(
                session_id=sid, patient_id=p.id, study_id=case.id,
                imaging_study_id=base.id, current_step=3,
                max_diameter_mm=6.0 + i * 0.1, neck_mm=3.0, volume_mm3=100.0,
                ar=1.5, dnr=2.0, rupture_risk_label="Moderado",
                created_at=now - timedelta(days=90 - i), updated_at=now - timedelta(days=90 - i),
            ))
            ids["base"] = sid
        sid_c = f"ctrl-{uuid.uuid4().hex[:8]}"
        db.add(PlanningSession(
            session_id=sid_c, patient_id=p.id, study_id=case.id,
            imaging_study_id=ctrl.id, current_step=3,
            max_diameter_mm=8.0, neck_mm=3.4, volume_mm3=160.0,
            ar=1.9, dnr=2.4, rupture_risk_label="Alto",
            created_at=now, updated_at=now,
        ))
        ids["ctrl"] = sid_c

        if second_case:
            other = Study(patient_id=p.id, description="Otro aneurisma",
                          dx_principal="Aneurisma ACoA")
            db.add(other); db.commit(); db.refresh(other)
            img2 = ImagingStudy(case_id=other.id, patient_id=p.id,
                                description="Otro", acquired_at="2026-02-01")
            db.add(img2); db.commit(); db.refresh(img2)
            db.add(PlanningSession(
                session_id=f"other-{uuid.uuid4().hex[:8]}", patient_id=p.id,
                study_id=other.id, imaging_study_id=img2.id, current_step=3,
                max_diameter_mm=99.0, neck_mm=9.0, volume_mm3=999.0,
                ar=9.0, dnr=9.0, rupture_risk_label="Alto",
                created_at=now, updated_at=now,
            ))
        db.commit()
        return ids
    finally:
        db.close()


class TestOnePointPerAcquisition:
    def test_repeated_runs_on_one_acquisition_collapse(self):
        ids = _fixture(n_runs_on_first=3)
        r = client.get(f"/api/longitudinal/{ids['ctrl']}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["entries"]) == 2, (
            "tres ejecuciones sobre la basal más una del control deben dar DOS "
            f"puntos, no {len(data['entries'])}"
        )
        base_entry = data["entries"][0]
        assert base_entry["n_sessions"] == 3, "debe declarar cuántas ejecuciones resume"

    def test_points_are_ordered_by_acquisition_date_not_session_date(self):
        ids = _fixture()
        data = client.get(f"/api/longitudinal/{ids['ctrl']}").json()
        dates = [e["session_date"] for e in data["entries"]]
        assert dates == ["2026-01-10", "2026-04-10"], dates

    def test_growth_between_acquisitions_is_detected(self):
        ids = _fixture()
        data = client.get(f"/api/longitudinal/{ids['ctrl']}").json()
        d = {x["metric"]: x for x in data["deltas"]}
        assert d["max_diameter_mm"]["delta"] == 2.0
        assert data["growth_alert"] is True

    def test_a_different_case_is_not_mixed_in(self):
        """Another aneurysm in the same patient is a different lesion."""
        ids = _fixture(second_case=True)
        data = client.get(f"/api/longitudinal/{ids['ctrl']}").json()
        assert len(data["entries"]) == 2, "no debe traer el caso ajeno"
        assert all(e["max_diameter_mm"] < 50 for e in data["entries"])
        assert data["case_id"] is not None


class TestLegacySessions:
    def test_sessions_without_an_acquisition_still_appear(self):
        """Sessions saved before the imaging-study model must not vanish, and
        must not be merged with each other either."""
        db = SessionLocal()
        try:
            p = Patient(surname="Legado", hospital_id=f"HC-OLD-{uuid.uuid4().hex[:6]}")
            db.add(p); db.commit(); db.refresh(p)
            now = datetime.now(timezone.utc)
            sids = []
            for i in range(2):
                sid = f"legacy-{uuid.uuid4().hex[:8]}"
                db.add(PlanningSession(
                    session_id=sid, patient_id=p.id, current_step=3,
                    max_diameter_mm=5.0 + i, neck_mm=3.0, volume_mm3=90.0,
                    ar=1.4, dnr=1.9, rupture_risk_label="Bajo",
                    created_at=now - timedelta(days=10 - i * 10),
                    updated_at=now - timedelta(days=10 - i * 10),
                ))
                sids.append(sid)
            db.commit()
        finally:
            db.close()
        data = client.get(f"/api/longitudinal/{sids[1]}").json()
        assert len(data["entries"]) == 2
