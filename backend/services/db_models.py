"""SQLAlchemy ORM models — Session D.

Tables
------
users            — clinician accounts (username / hashed_password / role)
patients         — pseudonymised patient records
studies          — DICOM study linked to a patient
planning_sessions — one saved planning workflow per study/session
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.orm import relationship

from services.database import Base


# ── User ───────────────────────────────────────────────────────────────────── #

class User(Base):
    __tablename__ = "users"

    # Account status (mirrors desktop User.STATUS_*)
    STATUS_PENDING  = "pending"
    STATUS_ACTIVE   = "active"
    STATUS_REJECTED = "rejected"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(64), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    full_name       = Column(String(128), nullable=False, default="")
    role            = Column(String(32), nullable=False, default="medico")
    # Allowed: admin | medico | residente | viewer
    institution     = Column(String(128), nullable=False, default="")
    is_active       = Column(Boolean, nullable=False, default=True)
    status          = Column(String(16), nullable=False, default=STATUS_ACTIVE)
    created_at      = Column(DateTime, nullable=False, default=func.now())

    # Professional profile (filled during self-registration, reviewed by admin)
    national_id     = Column(String(64),  nullable=False, default="")
    professional_id = Column(String(64),  nullable=False, default="")
    specialty       = Column(String(100), nullable=False, default="")
    university      = Column(String(200), nullable=False, default="")
    hospital        = Column(String(200), nullable=False, default="")
    position        = Column(String(100), nullable=False, default="")
    orcid           = Column(String(64),  nullable=False, default="")
    photo_path      = Column(String(300), nullable=False, default="")  # stored profile photo
    cv_path         = Column(String(300), nullable=False, default="")  # stored CV document

    patients = relationship("Patient", back_populates="creator", foreign_keys="Patient.created_by")

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role!r} status={self.status!r}>"


# ── Patient ────────────────────────────────────────────────────────────────── #

class Patient(Base):
    __tablename__ = "patients"

    id          = Column(Integer, primary_key=True, index=True)
    surname     = Column(String(128), nullable=False)
    given_name  = Column(String(128), nullable=False, default="")
    hospital_id = Column(String(64),  nullable=False, default="", index=True)
    dob         = Column(String(10),  nullable=False, default="")   # YYYY-MM-DD
    sex         = Column(String(4),   nullable=False, default="")   # M / F / O
    institution = Column(String(128), nullable=False, default="")

    # Clinical history fields (mirroring models/patient.py PatientCreate)
    ocupacion                    = Column(Text, nullable=False, default="")
    antecedentes_patologicos     = Column(Text, nullable=False, default="")
    antecedentes_toxicologicos   = Column(Text, nullable=False, default="")
    antecedentes_quirurgicos     = Column(Text, nullable=False, default="")
    antecedentes_alergicos       = Column(Text, nullable=False, default="")
    antecedentes_farmacologicos  = Column(Text, nullable=False, default="")
    notes                        = Column(Text, nullable=False, default="")

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())

    creator  = relationship("User", back_populates="patients", foreign_keys=[created_by])
    studies  = relationship("Study", back_populates="patient", cascade="all, delete-orphan")
    sessions = relationship("PlanningSession", back_populates="patient")

    @property
    def full_name(self) -> str:
        if self.given_name:
            return f"{self.surname}, {self.given_name}"
        return self.surname

    @property
    def study_count(self) -> int:
        return len(self.studies)

    def __repr__(self) -> str:
        return f"<Patient id={self.id} surname={self.surname!r}>"


# ── Study = CASO CLÍNICO ───────────────────────────────────────────────────── #
# Naming note: the table is historically called `studies`, but conceptually this
# row is a CLINICAL CASE (one episode: diagnosis, aneurysm type, planned
# treatment). The images of that episode live in `imaging_studies` — a case can
# hold several (CT + angiography + follow-up), mirroring how a hospital works and
# how DICOM is organised (Patient → Study → Series). `Case` is exported as an
# alias so new code can use the clinical name without a table rename.

class Study(Base):
    __tablename__ = "studies"

    id          = Column(Integer, primary_key=True, index=True)
    patient_id  = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    dicom_path  = Column(Text, nullable=False, default="")
    modality    = Column(String(16), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    acquired_at = Column(String(10), nullable=False, default="")  # fecha del caso YYYY-MM-DD
    created_at  = Column(DateTime, nullable=False, default=func.now())

    # ── Clinical case data (desktop "Nuevo Caso" — sections 3-5) ──────────── #
    sintomas_positivos    = Column(Text,         nullable=False, default="")
    dx_principal          = Column(String(500),  nullable=False, default="")
    dx_secundario         = Column(String(500),  nullable=False, default="")
    tipo_aneurisma        = Column(String(200),  nullable=False, default="")
    tratamiento_propuesto = Column(Text,         nullable=False, default="")  # comma-joined
    region_anatomica      = Column(String(300),  nullable=False, default="")
    lateralidad           = Column(String(100),  nullable=False, default="")
    angiographer          = Column(String(300),  nullable=False, default="")  # "marca | TIPO"
    # Which diagnostic-image modalities the case has (DICOM uploaded in the pipeline)
    mod_tac      = Column(Boolean, nullable=False, default=False)
    mod_angio    = Column(Boolean, nullable=False, default=False)
    mod_rm       = Column(Boolean, nullable=False, default=False)
    mod_pangio   = Column(Boolean, nullable=False, default=False)

    # ── Durable archive (LEGACY) ──────────────────────────────────────────── #
    # Kept so old rows keep working; new uploads are archived per ImagingStudy.
    storage_prefix = Column(String(300), nullable=False, default="")
    thumb_key      = Column(String(300), nullable=False, default="")
    n_files        = Column(Integer, nullable=False, default=0)
    n_slices       = Column(Integer, nullable=False, default=0)
    size_mb        = Column(Float,   nullable=False, default=0.0)

    patient  = relationship("Patient", back_populates="studies")
    sessions = relationship("PlanningSession", back_populates="study")
    imaging  = relationship(
        "ImagingStudy", back_populates="case",
        cascade="all, delete-orphan", order_by="ImagingStudy.created_at",
    )

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def __repr__(self) -> str:
        return f"<Case id={self.id} dx={self.dx_principal!r}>"


#: Clinical name for the row above — prefer `Case` in new code.
Case = Study


# ── ImagingStudy = ESTUDIO DE IMAGEN ───────────────────────────────────────── #

class ImagingStudy(Base):
    """One imaging acquisition of a clinical case (a CT, an angiography…).

    Holds the durable DICOM archive and its preview. A case can have several,
    which is what lets a single episode carry CT + angiography + a follow-up
    without inventing duplicate cases.
    """
    __tablename__ = "imaging_studies"

    id          = Column(Integer, primary_key=True, index=True)
    case_id     = Column(Integer, ForeignKey("studies.id"), nullable=False, index=True)
    patient_id  = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    description = Column(Text,        nullable=False, default="")
    modality    = Column(String(16),  nullable=False, default="")
    acquired_at = Column(String(10),  nullable=False, default="")   # YYYY-MM-DD
    created_at  = Column(DateTime,    nullable=False, default=func.now())

    # Durable archive — see services/storage.py. NEVER under data/ (public).
    storage_prefix = Column(String(300), nullable=False, default="")
    thumb_key      = Column(String(300), nullable=False, default="")
    n_files        = Column(Integer, nullable=False, default=0)
    n_slices       = Column(Integer, nullable=False, default=0)
    size_mb        = Column(Float,   nullable=False, default=0.0)

    case     = relationship("Study", back_populates="imaging")
    patient  = relationship("Patient")
    sessions = relationship("PlanningSession", back_populates="imaging_study")

    @property
    def archived(self) -> bool:
        return bool(self.storage_prefix)

    def __repr__(self) -> str:
        return f"<ImagingStudy id={self.id} case={self.case_id} {self.modality!r}>"


# ── PlanningSession ────────────────────────────────────────────────────────── #

class PlanningSession(Base):
    """One saved planning workflow snapshot.

    Linked to the UUID temp-directory via `session_id`.
    Morphometry fields are snapshotted at save-time for longitudinal queries
    without needing the temp directory to still exist.
    """
    __tablename__ = "planning_sessions"

    id           = Column(Integer, primary_key=True, index=True)
    session_id   = Column(String(64), unique=True, nullable=False, index=True)
    # study_id = the CLINICAL CASE; imaging_study_id = the images actually
    # analysed. Both nullable so a session can exist before being linked.
    study_id     = Column(Integer, ForeignKey("studies.id"),  nullable=True, index=True)
    imaging_study_id = Column(Integer, ForeignKey("imaging_studies.id"), nullable=True, index=True)
    patient_id   = Column(Integer, ForeignKey("patients.id"), nullable=True, index=True)
    label        = Column(String(256), nullable=False, default="")
    current_step = Column(Integer, nullable=False, default=0)

    # Morphometry snapshot for longitudinal comparison
    max_diameter_mm     = Column(Float, nullable=True)
    neck_mm             = Column(Float, nullable=True)
    dome_height_mm      = Column(Float, nullable=True)
    volume_mm3          = Column(Float, nullable=True)
    ar                  = Column(Float, nullable=True)   # Aspect Ratio
    dnr                 = Column(Float, nullable=True)   # Dome-to-Neck Ratio
    bf                  = Column(Float, nullable=True)   # Bottleneck Factor
    ui                  = Column(Float, nullable=True)   # Undulation Index
    rupture_risk_label  = Column(String(16), nullable=True)

    # Segmentation metadata
    seg_n_vertices  = Column(Integer, nullable=True)
    seg_n_faces     = Column(Integer, nullable=True)
    dicom_modality  = Column(String(16), nullable=True)

    file_size_kb = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    patient = relationship("Patient", back_populates="sessions")
    study   = relationship("Study",   back_populates="sessions")
    imaging_study = relationship("ImagingStudy", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<PlanningSession id={self.id} session_id={self.session_id!r}>"
