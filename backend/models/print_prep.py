"""Models for 3D-print mesh preparation (Feature 7)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PrintBed(BaseModel):
    name: str
    x_mm: float
    y_mm: float
    z_mm: float


class PrintPrepRequest(BaseModel):
    """Prepare the working vessel mesh for 3D printing."""

    target_size_mm: float = Field(
        80.0, ge=0.0, le=400.0,
        description="Max dimension after uniform scaling (mm). 0 = keep original size.",
    )
    smooth_iterations: int = Field(20, ge=0, le=200, description="Laplacian smoothing iterations")
    smooth_relaxation: float = Field(0.1, ge=0.0, le=1.0, description="Smoothing relaxation factor")
    fill_holes: bool = Field(True, description="Fill holes before smoothing")
    hole_size: float = Field(5.0, ge=0.0, le=50.0, description="Max hole perimeter to fill (mm)")
    subdivide: bool = Field(False, description="One level of linear subdivision (denser mesh)")
    bed_x_mm: float = Field(0.0, ge=0.0, description="Print bed X (mm); 0 = unlimited")
    bed_y_mm: float = Field(0.0, ge=0.0, description="Print bed Y (mm); 0 = unlimited")
    bed_z_mm: float = Field(0.0, ge=0.0, description="Print bed Z (mm); 0 = unlimited")


class PrintPrepResult(BaseModel):
    stl_url: str = Field(..., description="URL of the print-ready STL")
    scale_factor: float
    dimensions_mm: list[float] = Field(..., description="[dx, dy, dz] after scaling")
    volume_cm3: float
    surface_area_cm2: float
    is_watertight: bool
    open_edge_count: int
    fits_in_bed: bool = Field(..., description="Whether the model fits the requested bed")
    warnings: list[str] = Field(default_factory=list)
