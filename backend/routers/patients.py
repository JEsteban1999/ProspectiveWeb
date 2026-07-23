"""Patient and study management router — real SQLite CRUD (Session D)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import PatientCreate, PatientSummary, StudySummary
from services.database import get_db
from services.auth_service import get_current_user
from services.db_models import Patient, Study, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/patients", tags=["patients"])


# ── Mappers ────────────────────────────────────────────────────────────────── #

def _patient_to_summary(p: Patient) -> PatientSummary:
    return PatientSummary(
        id=p.id,
        full_name=p.full_name,
        hospital_id=p.hospital_id,
        dob=p.dob,
        sex=p.sex,
        institution=p.institution,
        study_count=p.study_count,
        created_at=p.created_at,
    )


def _study_to_summary(s: Study) -> StudySummary:
    return StudySummary(
        id=s.id,
        patient_id=s.patient_id,
        dicom_path=s.dicom_path,
        modality=s.modality,
        description=s.description,
        acquired_at=s.acquired_at,
        session_count=s.session_count,
    )


# ── GET /patients ──────────────────────────────────────────────────────────── #

@router.get(
    "",
    response_model=list[PatientSummary],
    summary="List all patients",
    description=(
        "Returns all patient records.  "
        "When authenticated, patients are filtered to those created by the "
        "current user (or all patients for admins).  "
        "Works without authentication for development convenience."
    ),
)
async def list_patients(
    db:           Annotated[Session,    Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> list[PatientSummary]:
    query = db.query(Patient)

    # Admins see everything; other authenticated users see only their patients
    if current_user is not None and current_user.role != "admin":
        query = query.filter(Patient.created_by == current_user.id)

    patients = query.order_by(Patient.created_at.desc()).all()
    return [_patient_to_summary(p) for p in patients]


# ── POST /patients ─────────────────────────────────────────────────────────── #

@router.post(
    "",
    response_model=PatientSummary,
    status_code=201,
    summary="Register a new patient",
    description="Creates a patient record. Authentication is recommended (records the creator).",
)
async def create_patient(
    req:          PatientCreate,
    db:           Annotated[Session,    Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> PatientSummary:
    # Enforce a unique medical-record number (historia clínica). Enforced at the
    # application layer rather than a DB constraint so it does not require a
    # dedup migration of pre-existing rows; empty HC is allowed (unknown).
    hc = (req.hospital_id or "").strip()
    if hc:
        existing = db.query(Patient).filter(Patient.hospital_id == hc).first()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un paciente con la historia clínica '{hc}'.",
            )

    patient = Patient(
        surname                    = req.surname,
        given_name                 = req.given_name,
        hospital_id                = req.hospital_id,
        dob                        = req.dob,
        sex                        = req.sex,
        institution                = req.institution,
        ocupacion                  = req.ocupacion,
        antecedentes_patologicos   = req.antecedentes_patologicos,
        antecedentes_toxicologicos = req.antecedentes_toxicologicos,
        antecedentes_quirurgicos   = req.antecedentes_quirurgicos,
        antecedentes_alergicos     = req.antecedentes_alergicos,
        antecedentes_farmacologicos= req.antecedentes_farmacologicos,
        notes                      = req.notes,
        created_by                 = current_user.id if current_user else None,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    logger.info(
        "Patient created — id=%d surname=%s creator=%s",
        patient.id, patient.surname,
        current_user.username if current_user else "anonymous",
    )
    return _patient_to_summary(patient)


# ── GET /patients/{patient_id}/studies ────────────────────────────────────── #

@router.get(
    "/{patient_id}/studies",
    response_model=list[StudySummary],
    summary="List DICOM studies for a patient",
)
async def list_studies(
    patient_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> list[StudySummary]:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    studies = (
        db.query(Study)
        .filter(Study.patient_id == patient_id)
        .order_by(Study.acquired_at.desc())
        .all()
    )
    return [_study_to_summary(s) for s in studies]
