"""Patient and study management router — real SQLite CRUD (Session D)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import CaseCreate, PatientCreate, PatientDetail, PatientSessionInfo, PatientSummary, StudyCreate, StudySummary

# Study clinical-case fields copied from a CaseCreate payload.
_STUDY_CASE_FIELDS = (
    "sintomas_positivos", "dx_principal", "dx_secundario", "tipo_aneurisma",
    "tratamiento_propuesto", "region_anatomica", "lateralidad", "angiographer",
    "mod_tac", "mod_angio", "mod_rm", "mod_pangio",
)
from services.database import get_db
from services.auth_service import get_current_user
from services.db_models import Patient, PlanningSession, Study, User

# Patient demographic + history fields copied on create / update.
_PATIENT_FIELDS = (
    "surname", "given_name", "hospital_id", "dob", "sex", "institution",
    "ocupacion", "antecedentes_patologicos", "antecedentes_toxicologicos",
    "antecedentes_quirurgicos", "antecedentes_alergicos",
    "antecedentes_farmacologicos", "notes",
)


def _require_owner_or_admin(patient: Patient, user: User | None) -> None:
    """A non-admin authenticated user may only touch patients they created."""
    if user is not None and user.role != "admin" and patient.created_by != user.id:
        raise HTTPException(status_code=403, detail="No autorizado sobre este paciente.")

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
        sintomas_positivos=s.sintomas_positivos,
        dx_principal=s.dx_principal,
        dx_secundario=s.dx_secundario,
        tipo_aneurisma=s.tipo_aneurisma,
        tratamiento_propuesto=s.tratamiento_propuesto,
        region_anatomica=s.region_anatomica,
        lateralidad=s.lateralidad,
        angiographer=s.angiographer,
        mod_tac=s.mod_tac,
        mod_angio=s.mod_angio,
        mod_rm=s.mod_rm,
        mod_pangio=s.mod_pangio,
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


# ── POST /patients/case (Nuevo Caso: paciente + estudio) ───────────────────── #

@router.post(
    "/case",
    response_model=PatientSummary,
    status_code=201,
    summary="Create a full clinical case (patient + study)",
    description=(
        "Desktop 'Nuevo Caso' equivalent: creates a Patient (demographics + "
        "history) and a linked Study (clinical data, aneurysm characterisation, "
        "imaging modalities) in one call. DICOM is uploaded later in the pipeline."
    ),
)
async def create_case(
    req:          CaseCreate,
    db:           Annotated[Session,     Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> PatientSummary:
    # Validation mirrors the desktop dialog.
    if not (req.surname.strip() or req.given_name.strip()):
        raise HTTPException(status_code=422, detail="El nombre del paciente es obligatorio.")
    hc = (req.hospital_id or "").strip()
    if not hc:
        raise HTTPException(status_code=422, detail="La cédula / NHC es obligatoria.")
    if not req.dx_principal.strip():
        raise HTTPException(status_code=422, detail="El diagnóstico principal es obligatorio.")
    if db.query(Patient).filter(Patient.hospital_id == hc).first() is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe un paciente con la historia clínica '{hc}'.")

    patient = Patient(
        **{f: getattr(req, f) for f in _PATIENT_FIELDS},
        created_by=current_user.id if current_user else None,
    )
    db.add(patient)
    db.flush()   # assign patient.id before linking the study

    modality = ("CT" if req.mod_tac else "XA" if req.mod_angio
                else "MR" if req.mod_rm else "XA" if req.mod_pangio else "")
    study = Study(
        patient_id=patient.id,
        acquired_at=req.study_date,
        modality=modality,
        description=req.dx_principal,
        **{f: getattr(req, f) for f in _STUDY_CASE_FIELDS},
    )
    db.add(study)
    db.commit()
    db.refresh(patient)
    logger.info("Case created — patient=%d study=%d dx=%s", patient.id, study.id, req.dx_principal)
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


# ── POST /patients/{patient_id}/studies (add a study to an existing patient) ─ #

@router.post(
    "/{patient_id}/studies",
    response_model=StudySummary,
    status_code=201,
    summary="Add a clinical study/case to an existing patient",
)
async def create_study(
    patient_id:   int,
    req:          StudyCreate,
    db:           Annotated[Session,     Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> StudySummary:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    _require_owner_or_admin(patient, current_user)
    if not req.dx_principal.strip():
        raise HTTPException(status_code=422, detail="El diagnóstico principal es obligatorio.")

    modality = ("CT" if req.mod_tac else "XA" if req.mod_angio
                else "MR" if req.mod_rm else "XA" if req.mod_pangio else "")
    study = Study(
        patient_id=patient_id,
        acquired_at=req.study_date,
        modality=modality,
        description=req.dx_principal,
        **{f: getattr(req, f) for f in _STUDY_CASE_FIELDS},
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    logger.info("Study added — patient=%d study=%d", patient_id, study.id)
    return _study_to_summary(study)


# ── GET /patients/{patient_id} ─────────────────────────────────────────────── #

@router.get(
    "/{patient_id}",
    response_model=PatientDetail,
    summary="Get a patient's full record (for editing)",
)
async def get_patient(
    patient_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> PatientDetail:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return PatientDetail(id=patient.id, **{f: getattr(patient, f) for f in _PATIENT_FIELDS})


# ── PUT /patients/{patient_id} ─────────────────────────────────────────────── #

@router.put(
    "/{patient_id}",
    response_model=PatientSummary,
    summary="Update a patient",
    description="Updates a patient's demographics and clinical history.",
)
async def update_patient(
    patient_id:   int,
    req:          PatientCreate,
    db:           Annotated[Session,     Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> PatientSummary:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    _require_owner_or_admin(patient, current_user)

    # Medical-record number stays unique (excluding this patient).
    hc = (req.hospital_id or "").strip()
    if hc:
        clash = (
            db.query(Patient)
            .filter(Patient.hospital_id == hc, Patient.id != patient_id)
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un paciente con la historia clínica '{hc}'.",
            )

    for field in _PATIENT_FIELDS:
        setattr(patient, field, getattr(req, field))
    db.commit()
    db.refresh(patient)
    logger.info("Patient updated — id=%d surname=%s", patient.id, patient.surname)
    return _patient_to_summary(patient)


# ── DELETE /patients/{patient_id} ──────────────────────────────────────────── #

@router.delete(
    "/{patient_id}",
    status_code=204,
    summary="Delete a patient",
    description="Deletes a patient and its studies and planning sessions (cascade).",
)
async def delete_patient(
    patient_id:   int,
    db:           Annotated[Session,     Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> None:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    _require_owner_or_admin(patient, current_user)

    # Planning sessions carry a patient_id FK without cascade — remove them first
    # (studies are removed by the ORM cascade on Patient.studies).
    db.query(PlanningSession).filter(PlanningSession.patient_id == patient_id).delete()
    db.delete(patient)
    db.commit()
    logger.info("Patient deleted — id=%d", patient_id)


# ── GET /patients/{patient_id}/sessions ────────────────────────────────────── #

@router.get(
    "/{patient_id}/sessions",
    response_model=list[PatientSessionInfo],
    summary="List planning sessions done on a patient",
)
async def list_patient_sessions(
    patient_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> list[PatientSessionInfo]:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    sessions = (
        db.query(PlanningSession)
        .filter(PlanningSession.patient_id == patient_id)
        .order_by(PlanningSession.updated_at.desc())
        .all()
    )
    return [
        PatientSessionInfo(
            session_id=s.session_id,
            label=s.label,
            current_step=s.current_step,
            max_diameter_mm=s.max_diameter_mm,
            rupture_risk_label=s.rupture_risk_label,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]
