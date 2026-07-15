"""Vessel centerline extraction models."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .detection import Position3D


class CenterlineRequest(BaseModel):
    """Request to extract the medial-axis centreline between two vessel points."""

    session_id: str
    source: Position3D = Field(..., description="Start point on/inside the vessel (mm)")
    target: Position3D = Field(..., description="End point on/inside the vessel (mm)")
    voxel_size_mm: float = Field(
        0.8, ge=0.3, le=2.0,
        description="Voxelisation resolution (mm). Lower = more accurate but slower.",
    )


class CenterlineResult(BaseModel):
    """Centreline geometry metrics + tube mesh URL for the 3D viewer."""

    centerline_mesh_url: str = Field(
        ..., description="URL of the centreline tube mesh (.vtp), radius ≈ vessel caliber"
    )
    n_points: int = Field(..., description="Number of resampled centreline points")
    arc_length_mm: float = Field(..., description="Total path length along the centreline")
    chord_length_mm: float = Field(..., description="Straight-line source → target distance")
    tortuosity: float = Field(
        ..., description="arc / chord (1.0 = perfectly straight; ≥1.25 = high)"
    )
    tortuosity_index_pct: float = Field(
        ..., description="(arc − chord) / chord as a percentage"
    )
    mean_diameter_mm: float = Field(..., description="Mean vessel diameter along the path")
    min_diameter_mm: float = Field(..., description="Minimum vessel diameter (narrowest point)")
    max_diameter_mm: float = Field(..., description="Maximum vessel diameter (widest point)")
    warning: str | None = Field(
        None, description="Warning shown for high tortuosity or degenerate geometry"
    )
