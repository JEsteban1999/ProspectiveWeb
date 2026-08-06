"""Surgical approach trajectory models."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .detection import Position3D


class TrajectoryRequest(BaseModel):
    """Entry → target surgical approach corridor (mesh/world space, mm)."""

    entry: Position3D = Field(..., description="Skin/craniotomy entry point (mm)")
    target: Position3D = Field(..., description="Aneurysm target point (mm)")


class TrajectoryResult(BaseModel):
    entry: list[float]
    target: list[float]
    depth_mm: float = Field(..., description="Approach depth = |target − entry|")
    angle_deg: float = Field(..., description="Incidence angle vs the aneurysm principal axis")
