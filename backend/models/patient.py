"""Patient, Study and Session models.

Matches prospective/db/models.py (Patient, Study, PlanningSession tables)
and prospective/ui/widgets/patient_manager.py.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    """Fields required to register a new patient."""

    surname: str = Field(..., description="Patient surname (pseudonymised)")
    given_name: str = Field("", description="Patient given name")
    hospital_id: str = Field("", description="Hospital / HIS identifier")
    dob: str = Field("", description="Date of birth YYYY-MM-DD")
    sex: str = Field("", description="Biological sex: M / F / O")
    institution: str = Field("", description="Referring hospital or institution")

    # Clinical / social history fields (from Nuevo Caso form)
    ocupacion: str = Field("", description="Patient occupation")
    antecedentes_patologicos: str = Field("", description="Past medical history")
    antecedentes_toxicologicos: str = Field("", description="Toxicological history")
    antecedentes_quirurgicos: str = Field("", description="Surgical history")
    antecedentes_alergicos: str = Field("", description="Allergy history")
    antecedentes_farmacologicos: str = Field("", description="Current medications")
    notes: str = Field("", description="Free-text clinical notes")


class PatientDetail(PatientCreate):
    """Full patient record (all editable fields) for the edit form."""

    id: int


class PatientSummary(BaseModel):
    """Compact patient record for list views."""

    id: int
    full_name: str
    hospital_id: str
    dob: str
    sex: str
    institution: str
    study_count: int = Field(0, description="Number of associated studies")
    created_at: datetime


class StudySummary(BaseModel):
    """One DICOM study linked to a patient."""

    id: int
    patient_id: int
    dicom_path: str
    modality: str = Field("", description="DICOM Modality tag")
    description: str = Field("", description="Study description from DICOM header")
    acquired_at: str = Field("", description="Acquisition date YYYY-MM-DD")
    session_count: int = Field(0, description="Number of planning sessions for this study")


class PatientSessionInfo(BaseModel):
    """One past planning session done on a patient, for the patient detail view."""

    session_id: str
    label: str = ""
    current_step: int = 0
    max_diameter_mm: float | None = None
    rupture_risk_label: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanningSessionSummary(BaseModel):
    """One saved planning session (.prospective file)."""

    id: int
    study_id: int
    file_path: str
    current_step: int = Field(
        0, description="Workflow step the session was saved at (0-based)"
    )
    created_at: datetime
    updated_at: datetime
    label: str = Field("", description="Optional user-assigned label for this session")
