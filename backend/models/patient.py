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
    """One study / clinical case linked to a patient (desktop 'Nuevo Caso')."""

    id: int
    patient_id: int
    dicom_path: str = ""
    modality: str = Field("", description="DICOM Modality tag")
    description: str = Field("", description="Study description")
    acquired_at: str = Field("", description="Fecha del caso YYYY-MM-DD")
    session_count: int = Field(0, description="Number of planning sessions for this study")

    # Clinical case data (sections 3-5 of the Nuevo Caso form)
    sintomas_positivos: str = ""
    dx_principal: str = ""
    dx_secundario: str = ""
    tipo_aneurisma: str = ""
    tratamiento_propuesto: str = ""
    region_anatomica: str = ""
    lateralidad: str = ""
    angiographer: str = ""
    mod_tac: bool = False
    mod_angio: bool = False
    mod_rm: bool = False
    mod_pangio: bool = False


class StudyCreate(BaseModel):
    """Clinical study/case data — add a Study to an existing patient (sections 3-5)."""

    study_date: str = Field("", description="Fecha del caso YYYY-MM-DD")
    sintomas_positivos: str = ""
    dx_principal: str = Field("", description="Diagnóstico principal")
    dx_secundario: str = ""
    tipo_aneurisma: str = ""
    tratamiento_propuesto: str = ""
    region_anatomica: str = ""
    lateralidad: str = ""
    angiographer: str = ""
    mod_tac: bool = False
    mod_angio: bool = False
    mod_rm: bool = False
    mod_pangio: bool = False


class CaseCreate(BaseModel):
    """Full 'Nuevo Caso' payload — creates a Patient + a Study in one call."""

    # ── Section 1-2: patient demographics + history ───────────────────────── #
    surname: str = Field("", description="Apellidos")
    given_name: str = Field("", description="Nombres")
    hospital_id: str = Field("", description="Cédula / NHC")
    dob: str = Field("", description="Fecha de nacimiento YYYY-MM-DD")
    sex: str = Field("", description="M / F / O")
    institution: str = Field("", description="Hospital")
    ocupacion: str = ""
    antecedentes_patologicos: str = ""
    antecedentes_toxicologicos: str = ""
    antecedentes_quirurgicos: str = ""
    antecedentes_alergicos: str = ""
    antecedentes_farmacologicos: str = ""
    notes: str = ""

    # ── Study: fecha del caso + sections 3-5 ──────────────────────────────── #
    study_date: str = Field("", description="Fecha del caso YYYY-MM-DD")
    sintomas_positivos: str = ""
    dx_principal: str = Field("", description="Diagnóstico principal")
    dx_secundario: str = ""
    tipo_aneurisma: str = ""
    tratamiento_propuesto: str = Field("", description="Comma-joined treatments")
    region_anatomica: str = ""
    lateralidad: str = ""
    angiographer: str = Field("", description="'marca | TIPO'")
    mod_tac: bool = False
    mod_angio: bool = False
    mod_rm: bool = False
    mod_pangio: bool = False


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


class StudyCard(BaseModel):
    """One study as shown in the study gallery (preview + who it belongs to).

    Carries the patient identity the gallery filters on (name / national ID) and
    the archive state, so the grid renders without extra requests per card.
    """

    id: int = Field(..., description="ImagingStudy id")
    case_id: int = Field(0, description="Clinical case this imaging belongs to")
    patient_id: int
    patient_name: str = ""
    hospital_id: str = Field("", description="Cédula / N.º de historia clínica")
    description: str = ""
    modality: str = ""
    acquired_at: str = Field("", description="Fecha del caso YYYY-MM-DD")
    dx_principal: str = ""
    created_at: datetime

    # Archive / preview
    archived: bool = Field(False, description="Whether the DICOM is in durable storage")
    has_thumbnail: bool = False
    n_files: int = 0
    n_slices: int = 0
    size_mb: float = 0.0

    # Pipeline progress (latest saved session for this study)
    session_count: int = 0
    last_step: int | None = Field(None, description="Step of the most recent session")
    max_diameter_mm: float | None = None
    rupture_risk_label: str | None = None
