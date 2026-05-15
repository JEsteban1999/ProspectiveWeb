"""WebSocket progress event model."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StepName = Literal[
    "uploading",
    "reading_dicom",
    "computing_thresholds",
    "segmenting",
    "cleaning_mesh",
    "smoothing_mesh",
    "detecting_aneurysm",
    "computing_morphometry",
    "detecting_perforators",
    "planning_stent",
    "done",
    "error",
]


class ProgressEvent(BaseModel):
    """Emitted over the WebSocket /api/progress/{session_id} during processing."""

    event: Literal["progress", "done", "error"] = Field(
        ..., description="Event type"
    )
    step: StepName = Field(..., description="Current processing step")
    pct: int = Field(..., ge=0, le=100, description="Overall completion percentage")
    message: str = Field(
        ..., description="Human-readable status message shown in the progress bar"
    )
    detail: str | None = Field(
        None,
        description="Optional technical detail (e.g. elapsed time, voxel count)",
    )
