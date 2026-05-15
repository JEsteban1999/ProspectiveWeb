"""Surgical clip library and planning router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models import ClipLibraryItem, ClipPlanRequest, ClipPlanResult, ClipRecommendation
from services.clips   import catalogue_to_api, recommend_clips, recommendations_to_api
from services.sessions import read_state, session_exists

router = APIRouter(prefix="/api", tags=["clips"])


def _load_float(session_id: str, key: str, default: float) -> float:
    try:
        raw = read_state(session_id, key, "")
        return float(raw) if raw else default
    except (ValueError, Exception):
        return default


@router.get(
    "/clips",
    response_model=list[ClipLibraryItem],
    summary="Get clip device library",
    description=(
        "Returns the full surgical clip library (40+ models across Yasargil, Sugita, "
        "Aesculap and Codman systems). Each entry includes blade length, shape, "
        "closing force, and the required applier."
    ),
)
async def get_clip_library() -> list[ClipLibraryItem]:
    return [ClipLibraryItem(**item) for item in catalogue_to_api()]


@router.get(
    "/clips/recommendations/{session_id}",
    response_model=list[ClipRecommendation],
    summary="Get clip recommendations from the Clip Recommender assistant",
    description=(
        "Scores all clips in the catalogue against the patient's neck diameter and "
        "aspect ratio (loaded from session morphometry). Returns up to 8 ranked "
        "recommendations.\n\n"
        "Scoring weights: coverage ratio 45%, shape fit 40%, closing force 15%."
    ),
)
async def get_clip_recommendations(session_id: str) -> list[ClipRecommendation]:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    neck_mm      = _load_float(session_id, "morpho.neck_mm", 0.0)
    aspect_ratio = _load_float(session_id, "morpho.ar",       0.0)

    # Require at least a minimal neck measurement for meaningful recommendations
    if neck_mm <= 0:
        return []

    recs = recommend_clips(neck_mm=neck_mm, aspect_ratio=aspect_ratio, n=8)
    return [ClipRecommendation(**r) for r in recommendations_to_api(recs)]


@router.post(
    "/clips/plan",
    response_model=ClipPlanResult,
    summary="Compute clip placement plan",
    description=(
        "Accepts clip placements and optional surgical trajectory, then computes "
        "neck coverage and collision detection via VTK mesh operations. "
        "Returns the combined clips mesh URL for 3D display.\n\n"
        "**Note:** Full VTK-based collision detection is implemented in Session E."
    ),
)
async def plan_clips(req: ClipPlanRequest) -> ClipPlanResult:
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    # TODO (Session E): run VTK mesh intersection for neck coverage & collision detection
    n_clips = len(req.placements)
    # Estimate: each clip covers ~30% of a typical neck + small overlap
    raw_coverage = min(100.0, n_clips * 30.0)
    collision    = False

    return ClipPlanResult(
        clips_mesh_url=f"/static/sample-meshes/clips_placed.vtp",
        trajectory_mesh_url=(
            "/static/sample-meshes/trajectory.vtp"
            if req.trajectory_entry and req.trajectory_target else None
        ),
        neck_coverage_pct=raw_coverage,
        collision_detected=collision,
        warning=(
            "Cobertura estimada: añadir más clips para oclusión completa"
            if raw_coverage < 95.0 and n_clips > 0 else None
        ),
    )
