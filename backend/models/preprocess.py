"""Models for optional DICOM volume preprocessing (Feature 10)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PreprocessRequest(BaseModel):
    clip_hu: bool = Field(True, description="Clamp HU outliers to [-1000, 3000]")
    resample_isotropic: bool = Field(False, description="Resample to cubic voxels")
    target_spacing_mm: float = Field(0.5, ge=0.2, le=2.0, description="Isotropic voxel size (mm)")
    smooth: bool = Field(False, description="Mild Gaussian denoising")
    smooth_sigma: float = Field(0.5, ge=0.1, le=2.0, description="Gaussian sigma")


class PreprocessResult(BaseModel):
    shape_before: list[int]
    shape_after: list[int]
    spacing_before: list[float]
    spacing_after: list[float]
    note: str = Field(..., description="What changed; downstream segmentation must be re-run")
