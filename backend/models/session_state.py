"""Session save / restore models.

Matches prospective/io/session.py (SessionData dataclass).
Allows the user to save progress and resume from any step.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .dicom import SeriesInfo


class SessionSaveRequest(BaseModel):
    """Request to persist the current session state."""

    session_id: str
    label: str = Field("", description="Optional user label for this saved session")
    patient_id: int | None = Field(
        None, description="Associate this session with a patient record"
    )
    study_id: int | None = Field(
        None, description="Clinical case this session belongs to"
    )
    imaging_study_id: int | None = Field(
        None, description="Imaging study (acquisition) this session analysed"
    )
    current_step: int = Field(
        0, ge=0, le=6,
        description="Current workflow step index (0-based: 0=Carga … 6=Informe)"
    )


class SessionSaveResult(BaseModel):
    """Confirmation of a successful session save."""

    file_path: str = Field(..., description="Server-side path of the saved .prospective file")
    download_url: str = Field(..., description="URL to download the session file")
    saved_at: datetime


class SessionRestoreResult(BaseModel):
    """Result of loading a saved session."""

    session_id: str = Field(..., description="New session_id for this restored session")
    current_step: int = Field(..., description="Step the session was saved at")
    label: str
    has_segmentation: bool
    has_detection: bool
    has_morphometry: bool
    has_plan: bool
    restored_at: datetime
    # Rehydration payload — lets the frontend repopulate the store without re-upload.
    mesh_url: str = Field("", description="URL of the restored vessel mesh (empty if none)")
    n_vertices: int = Field(0, description="Vertex count of the restored mesh")
    n_faces: int = Field(0, description="Face count of the restored mesh")
    modality: str = Field("", description="DICOM modality of the restored volume")
    patient_id: int | None = Field(None, description="Patient this session belongs to")
    study_id: int | None = Field(None, description="Clinical case this session belongs to")
    study_label: str = Field("", description="Human label of that case, for the breadcrumb")
    imaging_study_id: int | None = Field(
        None, description="Imaging study this session was analysing"
    )
    series: SeriesInfo | None = Field(
        None,
        description=(
            "Series of the restored volume. Without it the upload step shows an "
            "empty drop zone even though the viewer is already rendering the MPR."
        ),
    )
    centerline_mesh_url: str = Field(
        "",
        description=(
            "URL of the restored centreline (empty if the session had none). "
            "Without it the centreline-guided stent stays unavailable even "
            "though its geometry came back with the snapshot."
        ),
    )
    centerline_arc_mm: float = Field(
        0.0, description="Total arc length of the restored centreline (mm)"
    )


class SessionListItem(BaseModel):
    """One entry in the user's saved session list."""

    id: int
    session_id: str
    label: str
    current_step: int
    patient_name: str = ""
    created_at: datetime
    updated_at: datetime
    file_size_kb: float
