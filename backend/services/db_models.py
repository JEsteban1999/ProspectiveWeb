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


# ── Study ──────────────────────────────────────────────────────────────────── #

class Study(Base):
    __tablename__ = "studies"

    id          = Column(Integer, primary_key=True, index=True)
    patient_id  = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    dicom_path  = Column(Text, nullable=False, default="")
    modality    = Column(String(16), nullable=False, default="CT")
    description = Column(Text, nullable=False, default="")
    acquired_at = Column(String(10), nullable=False, default="")  # YYYY-MM-DD
    created_at  = Column(DateTime, nullable=False, default=func.now())

    patient  = relationship("Patient", back_populates="studies")
    sessions = relationship("PlanningSession", back_populates="study")

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def __repr__(self) -> str:
        return f"<Study id={self.id} modality={self.modality!r}>"


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
    # Both study_id and patient_id can be set independently
    study_id     = Column(Integer, ForeignKey("studies.id"),  nullable=True, index=True)
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

    def __repr__(self) -> str:
        return f"<PlanningSession id={self.id} session_id={self.session_id!r}>"
