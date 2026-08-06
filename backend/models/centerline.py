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


class CrossSectionRequest(BaseModel):
    """Request to analyse cross-sections along the previously-extracted centreline."""

    session_id: str
    n_samples: int = Field(
        40, ge=10, le=100,
        description="Number of cutting planes along the centreline (more = finer).",
    )


class ClStentRequest(BaseModel):
    """Deploy a virtual stent along the extracted centreline."""

    session_id: str
    stent_diameter_mm: float = Field(
        4.0, ge=1.0, le=10.0, description="Nominal stent outer diameter (mm)"
    )
    start_arc_mm: float | None = Field(
        None, ge=0.0, description="Arc-length start (mm). Omit for the centreline start."
    )
    end_arc_mm: float | None = Field(
        None, ge=0.0, description="Arc-length end (mm). Omit for the centreline end."
    )
    braid: bool = Field(True, description="Add helical braid wires for a flow-diverter look")
    braid_count: int = Field(6, ge=0, le=16, description="Braid wires per wind direction")


class ClStentResult(BaseModel):
    """Deployed centreline-guided stent mesh + fit metrics."""

    stent_mesh_url: str = Field(..., description="URL of the deployed stent tube mesh (.vtp)")
    length_mm: float = Field(..., description="Arc length of the deployed segment")
    nominal_diameter_mm: float = Field(..., description="Requested stent diameter")
    mean_vessel_diameter_mm: float = Field(..., description="Mean vessel Ø over the segment")
    coverage_ratio: float = Field(..., description="stent_r / vessel_r (1.0 = perfect fit; <1 undersized)")
    total_arc_mm: float = Field(..., description="Total centreline arc length (for range sliders)")
    warning: str | None = Field(None, description="Fit warning (over/undersized)")


class CrossSectionResult(BaseModel):
    """Cross-sectional diameter profile along the vessel + stenosis estimate."""

    arc_positions_mm: list[float] = Field(..., description="Sample positions along the centreline")
    diameters_mm: list[float] = Field(..., description="Equivalent-circle diameter at each position")
    mean_diameter_mm: float
    median_diameter_mm: float
    min_diameter_mm: float
    max_diameter_mm: float
    mean_area_mm2: float
    stenosis_ratio: float = Field(..., description="min_area / median_area (1.0 = uniform)")
    stenosis_pct: float = Field(..., description="(1 − ratio) × 100 — narrowing at the tightest point")
    stenosis_label: str = Field(..., description="'Sin estenosis' | 'Leve' | 'Significativa'")
    warning: str | None = None
