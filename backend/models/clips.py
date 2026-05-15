"""Surgical clip planning models.

Matches prospective/models/clip_library.py and prospective/ui/widgets/clip_panel.py.
Step 5 — Planificación › Planificación clips.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .detection import Position3D


class ClipLibraryItem(BaseModel):
    """A surgical clip model from the device library."""

    id: str
    name: str = Field(..., description="Commercial name (e.g. 'Yasargil FT740T')")
    manufacturer: str
    length_mm: float = Field(..., description="Blade length (mm). Typical: 5–20 mm")
    angle_deg: float = Field(
        0.0, description="Clip angle (0 = straight, 90 = right-angle)"
    )
    is_fenestrated: bool = Field(
        False, description="True for fenestrated clips used on vessel bifurcations"
    )
    closing_force_g: float = Field(
        ..., description="Closing force in grams (typical: 80–200 g)"
    )
    compatible_applier: str = Field(
        ..., description="Required applier instrument model"
    )


class ClipPlacement(BaseModel):
    """One clip placed on the aneurysm neck."""

    clip_id: str = Field(..., description="ID of the clip from the library")
    position: Position3D = Field(..., description="Clip jaw centre in patient space (mm)")
    normal: list[float] = Field(
        ..., description="Clip blade normal vector [nx, ny, nz] — perpendicular to blade"
    )
    rotation_deg: float = Field(
        0.0, ge=-180.0, le=180.0,
        description="Rotation around the normal axis (degrees)"
    )


class ClipPlanRequest(BaseModel):
    """Request to add or update a clip in the planning."""

    session_id: str
    placements: list[ClipPlacement] = Field(
        ..., description="All clips to place (replaces the current plan)"
    )
    trajectory_entry: Position3D | None = Field(
        None, description="Surgical approach entry point in patient space (mm)"
    )
    trajectory_target: Position3D | None = Field(
        None, description="Surgical approach target point in patient space (mm)"
    )


class ClipPlanResult(BaseModel):
    """Result of a clip placement plan."""

    clips_mesh_url: str = Field(
        ..., description="URL of the combined clips mesh (.vtp) for 3D display"
    )
    trajectory_mesh_url: str | None = Field(
        None, description="URL of the trajectory cylinder mesh (.vtp)"
    )
    neck_coverage_pct: float = Field(
        ..., ge=0.0, le=100.0,
        description="Percentage of the neck cross-section occluded by the clips"
    )
    collision_detected: bool = Field(
        False,
        description="True if any clip intersects a vessel wall or another clip"
    )
    warning: str | None = Field(
        None, description="Warning when collision or poor coverage is detected"
    )


class ClipRecommendation(BaseModel):
    """Clip recommendation from the Clip Recommender assistant."""

    clip_id: str
    clip_name: str
    score: float = Field(..., description="Recommendation score (higher = better fit)")
    reason: str = Field(..., description="One-line clinical rationale for this clip")
    suggested_placement: ClipPlacement | None = Field(
        None, description="Pre-computed suggested placement, if available"
    )
