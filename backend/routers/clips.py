"""Surgical clip library and planning router."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models import ClipLibraryItem, ClipPlanRequest, ClipPlanResult, ClipRecommendation
from services.clips   import catalogue_to_api, recommend_clips, recommendations_to_api
from services.sessions import read_state, session_exists, session_subdir, mesh_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["clips"])

# clip_id → blade length (mm) / display name, built once from the catalogue
_CLIP_LENGTH = {item["id"]: item["length_mm"] for item in catalogue_to_api()}
_CLIP_NAME = {item["id"]: item["name"] for item in catalogue_to_api()}


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

    # No morphometry at all → no recommendations (UI prompts to run it first).
    if neck_mm <= 0:
        return []

    # When neck detection was degenerate (< 1 mm, e.g. on a coarse mesh), fall
    # back to a typical neck so the workflow stays usable instead of returning
    # nothing. The recommendations are then general rather than case-specific.
    eff_neck = neck_mm if neck_mm >= 1.0 else 4.0
    eff_ar   = aspect_ratio if aspect_ratio > 0 else 1.4

    recs = recommend_clips(neck_mm=eff_neck, aspect_ratio=eff_ar, n=8)
    return [ClipRecommendation(**r) for r in recommendations_to_api(recs)]


@router.post(
    "/clips/plan",
    response_model=ClipPlanResult,
    summary="Compute clip placement plan",
    description=(
        "Builds a real 3D mesh of each placed clip, checks collision against the "
        "segmented vessel with vtkCollisionDetectionFilter, and estimates neck "
        "coverage from the intersection of the clips with the neck plane. "
        "Returns the combined clip mesh URL (.vtp) for the 3D viewer."
    ),
)
async def plan_clips(req: ClipPlanRequest) -> ClipPlanResult:
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    import time
    from services import devices
    from services.segmentation import read_vtp, write_vtp

    # No placements → nothing to build; report an empty plan.
    if not req.placements:
        return ClipPlanResult(
            clips_mesh_url="",
            trajectory_mesh_url=None,
            neck_coverage_pct=0.0,
            collision_detected=False,
            warning=None,
        )

    meshes_dir = session_subdir(req.session_id, "meshes")
    vessel_path = meshes_dir / "vessel_tree.vtp"

    # ── Build a real mesh for every placed clip at its pose ─────────────── #
    clip_polys = []
    for pl in req.placements:
        length = _CLIP_LENGTH.get(pl.clip_id, 9.0)
        local = devices.make_clip(length)
        t = devices.pose_transform(
            (pl.position.x, pl.position.y, pl.position.z),
            tuple(pl.normal) if pl.normal else (0.0, 0.0, 1.0),
            pl.rotation_deg,
        )
        clip_polys.append(devices.apply_transform(local, t))

    clips_world = devices.combine(clip_polys)

    # ── Real collision against the vessel mesh ───────────────────────────── #
    collision, n_contacts = False, 0
    if vessel_path.exists():
        try:
            vessel = read_vtp(vessel_path)
            collision, n_contacts = devices.check_collision(vessel, clips_world)
        except Exception as exc:
            logger.warning("Clip collision check skipped: %s", exc)

    # ── Real neck coverage from the neck plane ───────────────────────────── #
    neck_mm = _load_float(req.session_id, "morpho.neck_mm", 0.0)
    neck_origin = (
        _load_float(req.session_id, "morpho.neck_origin_x", 0.0),
        _load_float(req.session_id, "morpho.neck_origin_y", 0.0),
        _load_float(req.session_id, "morpho.neck_origin_z", 0.0),
    )
    neck_axis = (
        _load_float(req.session_id, "morpho.axis_x", 0.0),
        _load_float(req.session_id, "morpho.axis_y", 0.0),
        _load_float(req.session_id, "morpho.axis_z", 1.0),
    )
    coverage = devices.clip_neck_coverage(clips_world, neck_origin, neck_axis, neck_mm)

    # ── Trajectory cylinder (entry → target) ─────────────────────────────── #
    trajectory_url = None
    if req.trajectory_entry and req.trajectory_target:
        try:
            line = _trajectory_mesh(req.trajectory_entry, req.trajectory_target)
            traj_name = "trajectory.vtp"
            write_vtp(line, meshes_dir / traj_name)
            trajectory_url = mesh_url(req.session_id, traj_name)
        except Exception as exc:
            logger.warning("Trajectory mesh skipped: %s", exc)

    # ── Persist the combined clip mesh (real URL, cache-busted) ──────────── #
    clips_name = "clips_placed.vtp"
    write_vtp(clips_world, meshes_dir / clips_name)
    clips_url = f"{mesh_url(req.session_id, clips_name)}?v={int(time.time() * 1000)}"

    # ── Persist placed clips for the report / session restore ────────────── #
    from services.device_state import save_clips
    save_clips(req.session_id, [
        {
            "index": i,
            "name": _CLIP_NAME.get(pl.clip_id, pl.clip_id),
            "position": [pl.position.x, pl.position.y, pl.position.z],
            "orientation": [0.0, 0.0, float(pl.rotation_deg)],
            "is_custom": False,
        }
        for i, pl in enumerate(req.placements)
    ])

    warning = None
    if collision:
        warning = f"Colisión detectada entre clip y vaso ({n_contacts} contactos) — reposicionar."
    elif neck_mm <= 0.1:
        warning = "Ejecuta la morfometría para calcular la cobertura del cuello."
    elif coverage < 95.0:
        warning = "Cobertura parcial del cuello — considerar reposicionar o añadir un clip."

    return ClipPlanResult(
        clips_mesh_url=clips_url,
        trajectory_mesh_url=trajectory_url,
        neck_coverage_pct=round(coverage, 1),
        collision_detected=collision,
        warning=warning,
    )


def _trajectory_mesh(entry, target):
    """A thin cylinder from the entry point to the target (surgical approach)."""
    import vtk
    line = vtk.vtkLineSource()
    line.SetPoint1(entry.x, entry.y, entry.z)
    line.SetPoint2(target.x, target.y, target.z)
    line.Update()
    tube = vtk.vtkTubeFilter()
    tube.SetInputData(line.GetOutput())
    tube.SetRadius(0.4)
    tube.SetNumberOfSides(12)
    tube.Update()
    out = vtk.vtkPolyData()
    out.DeepCopy(tube.GetOutput())
    return out
