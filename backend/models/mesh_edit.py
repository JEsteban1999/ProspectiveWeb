"""Models for interactive mesh editing: ROI crop and grow-from-seeds."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .detection import Position3D


class MeshCropRequest(BaseModel):
    """Crop the working vessel mesh to (or away from) a box or sphere ROI.

    Coordinates are in the mesh/world space (mm) returned by 3D picking, the same
    space used for centreline source/target points.
    """

    mode: Literal["box", "sphere"] = Field(..., description="ROI shape")
    center: Position3D = Field(..., description="ROI centre (picked point), mm")
    radius: float = Field(
        10.0, gt=0.0, le=200.0,
        description="Sphere radius (mode='sphere'), mm",
    )
    half_size: Position3D | None = Field(
        None,
        description="Box half-extents per axis (mode='box'), mm. Omit to use `radius` as a cube half-side.",
    )
    invert: bool = Field(
        False,
        description="False = keep geometry INSIDE the ROI; True = remove it (keep the outside).",
    )


class MeshCropResult(BaseModel):
    mesh_url: str = Field(..., description="URL of the cropped mesh (.vtp), cache-busted")
    vertices: int = Field(..., description="Vertex count after cropping")
    faces: int = Field(..., description="Triangle count after cropping")
    removed_vertices: int = Field(..., description="Vertices removed by the crop")
    undo_depth: int = Field(
        0, description="Mesh edits that can still be undone after this one"
    )


class GrowRequest(BaseModel):
    """Region-grow a fresh vessel mesh from seed points placed on the volume."""

    seeds: list[Position3D] = Field(
        ..., min_length=1, description="Seed points in mesh/world space (mm)"
    )
    lower: float = Field(80.0, description="Lower HU bound for connected-threshold growing")
    upper: float = Field(600.0, description="Upper HU bound for connected-threshold growing")
    auto_band: bool = Field(
        False,
        description=(
            "Derive the HU band automatically from the intensity at the seeds — a "
            "narrow window around the vessel value that excludes bone/tissue. When "
            "true, `lower`/`upper` are ignored."
        ),
    )
    smoothing: int = Field(5, ge=0, le=10, description="Smoothing level 0–10")
    cleanup: int = Field(5, ge=0, le=10, description="Component cleanup level 0–10")


class GrowResult(BaseModel):
    mesh_url: str = Field(..., description="URL of the grown mesh (.vtp), cache-busted")
    vertices: int
    faces: int
    n_voxels: int = Field(..., description="Voxels in the grown region")
    fragments_removed: int = Field(..., description="Satellite components discarded")
    seeds: int = Field(..., description="Number of seeds used")
    band_lower: float = Field(0.0, description="Lower HU bound actually used (derived when auto_band)")
    band_upper: float = Field(0.0, description="Upper HU bound actually used")
    undo_depth: int = Field(
        0, description="Mesh edits that can still be undone after this one"
    )


class MeshRestoreRequest(BaseModel):
    """Step the working vessel mesh back or forward through the edit history."""

    scope: Literal["undo", "redo", "original"] = Field(
        "undo",
        description=(
            "'undo' restores the mesh as it was before the last edit (crop, grow "
            "or re-segmentation); 'redo' replays the last undone edit; 'original' "
            "goes back to the oldest state still kept — the first segmentation's "
            "output. All three are reversible."
        ),
    )


class MeshRestoreResult(BaseModel):
    mesh_url: str = Field(..., description="URL of the restored mesh (.vtp), cache-busted")
    vertices: int
    faces: int
    scope: Literal["undo", "redo", "original"]
    undo_depth: int = Field(..., description="Edits that can still be undone")
    redo_depth: int = Field(0, description="Undone edits that can be replayed")


class MeshHistoryStep(BaseModel):
    """One recoverable mesh state, as the panel lists it."""

    label: str = Field(..., description="Raw kind: 'segment' | 'crop' | 'grow' | 'edit'")
    title: str = Field(..., description="Human-readable name of the step")
    vertices: int = Field(..., description="Vertex count of that state")
    at: float = Field(..., description="Unix timestamp when it was recorded")


class MeshHistoryResult(BaseModel):
    """What the mesh-edit panel needs to drive its undo/redo controls."""

    undo_depth: int = Field(..., description="Edits that can be undone")
    redo_depth: int = Field(0, description="Undone edits that can be replayed")
    has_original: bool = Field(
        ..., description="True when an earlier mesh state can be restored"
    )
    steps: list[MeshHistoryStep] = Field(
        default_factory=list,
        description="The undo stack, oldest first — «quedan 3» alone said nothing about what they were",
    )
