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


class GrowRequest(BaseModel):
    """Region-grow a fresh vessel mesh from seed points placed on the volume."""

    seeds: list[Position3D] = Field(
        ..., min_length=1, description="Seed points in mesh/world space (mm)"
    )
    lower: float = Field(80.0, description="Lower HU bound for connected-threshold growing")
    upper: float = Field(600.0, description="Upper HU bound for connected-threshold growing")
    smoothing: int = Field(5, ge=0, le=10, description="Smoothing level 0–10")
    cleanup: int = Field(5, ge=0, le=10, description="Component cleanup level 0–10")


class GrowResult(BaseModel):
    mesh_url: str = Field(..., description="URL of the grown mesh (.vtp), cache-busted")
    vertices: int
    faces: int
    n_voxels: int = Field(..., description="Voxels in the grown region")
    fragments_removed: int = Field(..., description="Satellite components discarded")
    seeds: int = Field(..., description="Number of seeds used")
