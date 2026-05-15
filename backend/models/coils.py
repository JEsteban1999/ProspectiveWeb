"""Endovascular coil embolization models.

Matches prospective/models/coil_library.py and prospective/ui/widgets/coil_panel.py.
Step 5 — Planificación › Embolización (Coils).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .detection import Position3D


class CoilLibraryItem(BaseModel):
    """An endovascular coil model from the device library."""

    id: str
    name: str = Field(..., description="Commercial name (e.g. 'Target 360 Nano')")
    manufacturer: str
    diameter_mm: float = Field(
        ..., description="Primary coil loop diameter (mm). Typical: 2–20 mm"
    )
    length_cm: float = Field(
        ..., description="Coil length when uncoiled (cm). Typical: 5–40 cm"
    )
    coil_type: str = Field(
        ..., description="Type: 'framing' | 'filling' | 'finishing' | 'flow_assist'"
    )
    is_detachable: bool = Field(
        True, description="True for electrolytically detachable coils (GDC-type)"
    )


class CoilPlacement(BaseModel):
    """One coil placed inside the aneurysm sac."""

    coil_id: str = Field(..., description="ID of the coil from the library")
    position: Position3D = Field(
        ..., description="Approximate coil centre in patient space (mm)"
    )
    packing_density: float = Field(
        ..., ge=0.0, le=1.0,
        description="Local packing density contribution from this coil (0–1)"
    )


class CoilPlanRequest(BaseModel):
    """Request to update the coil embolization plan."""

    session_id: str
    placements: list[CoilPlacement] = Field(
        ..., description="All coils placed inside the aneurysm sac"
    )


class CoilPlanResult(BaseModel):
    """Result of a coil embolization plan."""

    coils_mesh_url: str = Field(
        ..., description="URL of the coil bundle mesh (.vtp) for 3D display"
    )
    total_packing_density: float = Field(
        ..., ge=0.0, le=1.0,
        description=(
            "Overall packing density of the aneurysm sac (volume of coils / sac volume). "
            "Target: ≥ 0.20 (20%). Typical: 0.20–0.35."
        ),
    )
    estimated_occlusion_pct: float = Field(
        ..., ge=0.0, le=100.0,
        description=(
            "Estimated aneurysm occlusion percentage based on packing density. "
            "Raymond grade I (complete) requires > 95%."
        ),
    )
    warning: str | None = Field(
        None,
        description="Warning when packing density is below therapeutic threshold (< 20%)"
    )
