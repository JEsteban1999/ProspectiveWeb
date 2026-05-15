"""DICOM upload and series metadata models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SpacingXYZ(BaseModel):
    x: float = Field(..., description="In-plane pixel spacing X (mm)")
    y: float = Field(..., description="In-plane pixel spacing Y (mm)")
    z: float = Field(..., description="Slice thickness / spacing Z (mm)")


class SeriesInfo(BaseModel):
    """Metadata returned after uploading and reading a DICOM series."""

    session_id: str = Field(..., description="Unique session identifier (UUID)")
    series_id: str = Field(..., description="DICOM Series Instance UID")
    description: str = Field(..., description="Series description from DICOM header")
    modality: str = Field(..., description="DICOM Modality tag (CT, XA, MR, …)")
    slices: int = Field(..., description="Number of slices in the volume")
    spacing: SpacingXYZ = Field(..., description="Voxel spacing in mm (x, y, z)")
    window_center: float = Field(..., description="DICOM WindowCenter (HU)")
    window_width: float = Field(..., description="DICOM WindowWidth (HU)")
    is_projection: bool = Field(
        False,
        description=(
            "True when the series appears to be a 2D projection "
            "(< 10 slices or spacing_z > 4 × spacing_xy). "
            "3D segmentation will not be meaningful."
        ),
    )
    projection_warning: str | None = Field(
        None,
        description="Human-readable warning message when is_projection is True",
    )
    size_mb: float = Field(..., description="Estimated volume size in RAM (MB)")


class UploadResult(BaseModel):
    """Returned immediately after the DICOM upload is accepted."""

    session_id: str = Field(..., description="Session ID to use in all subsequent calls")
    series: list[SeriesInfo] = Field(
        ..., description="One entry per DICOM series found in the uploaded files"
    )
    total_files: int = Field(..., description="Number of DICOM files received")
