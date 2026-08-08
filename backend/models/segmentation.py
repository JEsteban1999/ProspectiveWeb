"""Segmentation request / result models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AutoThresholdResult(BaseModel):
    """Auto-computed thresholds suggested to the user before segmentation."""

    lower: float = Field(..., description="Lower iso-surface threshold (HU or raw units)")
    upper: float = Field(..., description="Upper iso-surface threshold (HU or raw units)")
    strategy: Literal[
        "dsa",                # DSA subtraction detected (p99 < 0, max >> 0)
        "xa_band_pass",       # 3DRA wide WW > 2000 → p90–p99 band
        "xa_wc_ww",           # 3DRA narrow WW → calibrated WC/WW formula
        "xa_window_mismatch", # 3DRA whose WC/WW is a display preset → p99–p99.9 band
        "xa_raw16",           # 3DRA raw 16-bit (no HU rescale) → p99–p99.9 band
        "ct_stats",           # CTA with contrast → WC-based formula clamped to [150, 500] HU
        "ct_wc_ww",           # CT fallback → WC/WW derivation
        "mr_percentile",      # MR → p90–p99 of non-background voxels
        "wc_ww",              # Generic fallback
    ] = Field(..., description="Strategy used to compute the thresholds")
    is_dsa: bool = Field(
        False,
        description="True when DSA subtraction was detected (background ≈ -1024 HU)",
    )
    hint: str = Field(
        ...,
        description=(
            "Human-readable explanation of the chosen strategy, "
            "shown as a tip in the segmentation panel"
        ),
    )
    voxel_fraction: float | None = Field(
        None,
        description=(
            "Fraction of voxels captured by [lower, upper] in the full volume (0–1). "
            "Null when the DICOM volume has not been loaded yet. "
            "Values > 0.15 usually indicate the threshold is too permissive."
        ),
    )


class SegmentRequest(BaseModel):
    """Parameters sent by the user to launch the segmentation pipeline."""

    session_id: str
    series_id: str
    lower: float = Field(..., description="Lower iso-surface threshold (HU)")
    upper: float = Field(..., description="Upper iso-surface threshold (HU)")
    smoothing: int = Field(
        3, ge=0, le=10,
        description="Smoothing level 0–10 (combines Laplacian smoothing + decimation)",
    )
    cleanup: int = Field(
        3, ge=0, le=10,
        description="Cleanup level 0–10 (removes disconnected mesh fragments)",
    )


class SuggestedBand(BaseModel):
    """Adaptive starting band derived from the volume's own intensity histogram.

    A single universal rule (percentile-based) — not a per-modality preset — so
    the sliders start in the right place for ANY scale (CT HU, 3DRA raw, MR).
    """

    lower: float = Field(..., description="Suggested lower threshold (starting band)")
    upper: float = Field(..., description="Suggested upper threshold (starting band)")
    vmin: float = Field(..., description="Robust minimum for the slider range (p0.5)")
    vmax: float = Field(..., description="Robust maximum for the slider range (p99.9)")


class PreviewRequest(BaseModel):
    """Fast coarse-mesh preview while the user tunes the thresholds."""

    lower: float
    upper: float
    cleanup: int = Field(7, ge=0, le=10, description="Cleanup level 0–10 (top-N isolation)")
    downsample: int = Field(3, ge=1, le=6, description="Volume stride for the coarse preview")


class PreviewResult(BaseModel):
    mesh_url: str = Field(..., description="URL of the coarse preview mesh (.vtp), cache-busted")
    vertices: int
    voxel_fraction: float = Field(..., description="Fraction of voxels in [lower, upper] (0–1)")


class SegmentResult(BaseModel):
    """Mesh produced by the segmentation pipeline."""

    mesh_url: str = Field(
        ...,
        description=(
            "URL of the segmented mesh file (.vtp) relative to the API base. "
            "Loaded directly by vtk.js in the browser."
        ),
    )
    voxel_fraction: float | None = Field(
        None,
        description="Fraction of voxels captured by the applied thresholds (0–1). Null until real segmentation runs.",
    )
    strategy: str = Field(..., description="Strategy that produced the auto-thresholds")
    is_dsa: bool = Field(False, description="True when DSA mode was active")
    vertices: int = Field(..., description="Number of vertices in the output mesh")
    faces: int = Field(..., description="Number of triangular faces in the output mesh")
