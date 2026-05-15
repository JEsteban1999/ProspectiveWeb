"""Stent planning models."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .detection import Position3D


class StentParams(BaseModel):
    """Parameters that define how the stent is placed."""

    stent_id: str = Field(
        ...,
        description="Identifier of the stent model from the device library",
    )
    diameter_mm: float = Field(
        ..., ge=1.0, le=10.0,
        description="Stent nominal diameter (mm). Typical range: 2.5–5.0 mm",
    )
    length_mm: float = Field(
        ..., ge=5.0, le=50.0,
        description="Stent deployed length (mm). Typical range: 15–35 mm",
    )
    position: Position3D = Field(
        ..., description="Stent center position in patient space (mm)"
    )
    rotation_deg: float = Field(
        0.0, ge=-180.0, le=180.0,
        description="Rotation around the vessel axis (degrees)",
    )


class PlanRequest(BaseModel):
    """Request to compute a stent deployment plan."""

    session_id: str
    stent: StentParams


class PlanResult(BaseModel):
    """Result of a stent deployment plan."""

    stent_mesh_url: str = Field(
        ...,
        description="URL of the deployed stent mesh (.vtp) for 3D visualization",
    )
    coverage_pct: float = Field(
        ..., ge=0.0, le=100.0,
        description=(
            "Percentage of the aneurysm neck area covered by the stent mesh. "
            "Target: ≥ 30% for flow diverter effect. Typical: 30–70%."
        ),
    )
    neck_diameter_covered_mm: float = Field(
        ...,
        description="Length of the neck diameter effectively covered by the stent (mm)",
    )
    deployed: bool = Field(
        True, description="False if the requested parameters are geometrically incompatible"
    )
    warning: str | None = Field(
        None,
        description="Warning shown when coverage is low or stent size mismatches the vessel",
    )


class StentLibraryItem(BaseModel):
    """A single stent model available in the device library."""

    id: str
    name: str = Field(..., description="Commercial name of the stent")
    manufacturer: str
    min_diameter_mm: float
    max_diameter_mm: float
    available_lengths_mm: list[float]
    type: str = Field(
        ..., description="Stent type: 'flow_diverter' | 'coil_assist' | 'neck_bridge'"
    )
