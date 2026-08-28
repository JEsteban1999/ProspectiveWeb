"""Surgical clip planning models.

Matches prospective/models/clip_library.py and prospective/ui/widgets/clip_panel.py.
Step 5 — Planificación › Planificación clips.
"""
from __future__ import annotations

from typing import Literal

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


# ── Clip selection (criteria-based recommender) ───────────────────────────── #
# `ClipRecommendation` above is the original one-score-plus-one-sentence answer
# and stays for the existing endpoint. The models below carry the reasoning:
# what was judged, what the measurement was, and what to build when nothing in
# the inventory fits.


class ClipCriterion(BaseModel):
    """One judged aspect of a clip, with the measurement behind the verdict."""

    key: str = Field(..., description="coverage | fenestration | reach | shape | force | geometry")
    label: str = Field(..., description="Human label shown in the criteria matrix")
    verdict: Literal["ok", "warn", "fail"]
    detail: str = Field(..., description="The reason, including the number it came from")


class ClipFitCheck(BaseModel):
    """Result of posing the clip on the patient's measured neck plane."""

    collision: bool = Field(..., description="True when the best pose still touches a neighbouring structure")
    n_contacts: int = Field(0, description="Intersecting triangles in the best pose")
    span_mm: float = Field(0.0, description="Width of the clip across the neck plane (mm)")
    neck_coverage_pct: float = Field(0.0, ge=0.0, le=100.0)
    clean_rolls: int = Field(0, description="Approach angles, of those tried, that clear neighbouring vessels")
    n_rolls: int = Field(0, description="Approach angles tried")
    note: str = ""


class ClipCandidateOut(BaseModel):
    """A clip judged against this case."""

    clip_id: str
    clip_name: str
    manufacturer: str = ""
    shape: str = Field("", description="Recto | Curvo | Angulado 90° | Angulado 45° | Bayoneta | Fenestrado")
    blade_length_mm: float = 0.0
    closing_force_g: float = 0.0
    score: float = Field(0.0, ge=0.0, le=100.0, description="0 when any criterion failed")
    verdict: Literal["ok", "warn", "fail"] = "ok"
    headline: str = Field("", description="The single sentence to show under the clip name")
    coverage_ratio: float = 0.0
    safety_margin_mm: float = 0.0
    availability: Literal["stock", "made_to_order", "template"] = Field(
        "stock",
        description=(
            "'made_to_order' is a real design manufactured for the case — it "
            "competes like stock, but is not on a shelf today."
        ),
    )
    bend_angle_deg: float = Field(
        0.0,
        description=(
            "True bend angle. `shape` is a coarse class, so a family that bends "
            "in 15° steps would otherwise lose the angle that gets machined."
        ),
    )
    closing_force_min_g: float = 0.0
    closing_force_max_g: float = Field(
        0.0, description="Equal to the minimum when the force is a single value"
    )
    force_provisional: bool = Field(
        False, description="True when the force is a design band, not a characterised figure"
    )
    criteria: list[ClipCriterion] = Field(default_factory=list)
    fit: ClipFitCheck | None = Field(
        None, description="Present only for the candidates verified against the mesh"
    )


class ManufactureSpecOut(BaseModel):
    """The clip to have made, when the inventory cannot serve the case."""

    blade_length_mm: float
    blade_width_mm: float
    blade_height_mm: float
    spring_length_mm: float
    shape: str
    angle_deg: float
    closing_force_g: float
    fenestration_mm: float = Field(
        0.0, description="Inner window diameter (mm); 0 when a plain clip is specified"
    )
    neck_mm: float
    label: str = Field(..., description="One-line summary of the part to order")
    reasons: list[str] = Field(default_factory=list, description="Why no stock clip served")
    confidence_notes: list[str] = Field(
        default_factory=list, description="Assumptions a machinist still has to confirm"
    )
    stl_url: str | None = Field(
        None, description="Downloadable STL of the specified clip, once generated"
    )


class ClipCaseOut(BaseModel):
    """The measurements the selection was made from, echoed back for the panel."""

    neck_mm: float = 0.0
    dome_height_mm: float = 0.0
    max_diameter_mm: float = 0.0
    ar: float = 0.0
    dnr: float = 0.0
    parent_artery_mm: float = 0.0
    neck_source: str = "auto"
    neck_tilt_deg: float = 0.0
    region: str = ""
    laterality: str = ""
    aneurysm_type: str = ""


class CustomJawOut(BaseModel):
    """A made-to-order clip sized exactly to this case."""

    series: str
    angle_deg: float
    jaw_mm: float = Field(..., description="The jaw this neck wants (mm of useful grip)")
    nearest_drawn_mm: float = Field(
        ..., description="Closest jaw length that exists as drawn CAD"
    )
    label: str
    reason: str
    mesh_url: str | None = Field(None, description="Preview mesh (.vtp), once generated")
    stl_url: str | None = Field(None, description="STL to send out, once generated")


class ClipSelectionResult(BaseModel):
    """The complete answer for one case.

    `outcome` is never "nothing found": when the inventory cannot serve, the
    answer is a manufacturing specification.
    """

    outcome: Literal["stock", "marginal", "manufacture", "unmeasured"] = Field(
        ...,
        description=(
            "'stock' = at least one clip meets every criterion; "
            "'marginal' = usable clips exist but all carry a caveat, so a custom "
            "alternative is offered too; 'manufacture' = nothing in the inventory "
            "fits; 'unmeasured' = no reliable neck, so no selection is possible"
        ),
    )
    summary: str
    case: ClipCaseOut
    recommended: list[ClipCandidateOut] = Field(default_factory=list)
    rejected: list[ClipCandidateOut] = Field(
        default_factory=list,
        description="Near misses, each carrying the one criterion that disqualified it",
    )
    manufacture: ManufactureSpecOut | None = None
    custom_jaw: CustomJawOut | None = Field(
        None,
        description=(
            "Offered when the drawn jaw sizes only bracket what the case needs and "
            "the family is manufactured per case, so an exact jaw is a real option."
        ),
    )
    caveats: list[str] = Field(
        default_factory=list, description="What limits how much weight this selection can bear"
    )
