"""Surgical clip library and planning router."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from models import ClipLibraryItem, ClipPlanRequest, ClipPlanResult, ClipRecommendation
from services.clips   import catalogue_to_api, recommend_clips, recommendations_to_api
from services.sessions import read_state, session_exists, session_subdir, mesh_url, write_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["clips"])

# clip_id → blade length (mm) / display name, built once from the catalogue
_CLIP_LENGTH = {item["id"]: item["length_mm"] for item in catalogue_to_api()}
_CLIP_NAME = {item["id"]: item["name"] for item in catalogue_to_api()}

# Custom clip uploads: cap size and remember display names per session.
_MAX_CLIP_BYTES = 8 * 1024 * 1024
_CUSTOM_REGISTRY_KEY = "clips.custom_registry"


class CustomClipInfo(BaseModel):
    clip_id: str
    name: str


def _load_float(session_id: str, key: str, default: float) -> float:
    try:
        raw = read_state(session_id, key, "")
        return float(raw) if raw else default
    except (ValueError, Exception):
        return default


def _custom_registry(session_id: str) -> dict:
    raw = read_state(session_id, _CUSTOM_REGISTRY_KEY, "")
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


def _custom_index(clip_id: str) -> int | None:
    """Numeric suffix of a `custom:N` clip id, or None when it is not one."""
    if not clip_id.startswith("custom:"):
        return None
    try:
        return int(clip_id.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


def _next_custom_index(registry: dict) -> int:
    """One past the highest index ever used.

    Deriving it from `len(registry)` was fine while entries could only be added;
    now that one can be deleted, reusing an index would silently point a new
    import at the surviving `.vtp` of a clip the user thought they removed.
    """
    used = [i for i in (_custom_index(k) for k in registry) if i is not None]
    return max(used) + 1 if used else 0


def _custom_clip_name(session_id: str, clip_id: str) -> str:
    return _custom_registry(session_id).get(clip_id, "Clip personalizado")


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

    # Without a usable neck (no morphometry yet, or an open detector cap where
    # the neck can't be measured) we used to return NOTHING — which left the
    # clip dropdown empty and the clinician unable to place any clip at all,
    # while the coil catalogue stayed fully available. Fall back to a typical
    # neck instead, so the catalogue is offered as a GENERAL (non case-specific)
    # ranking that the clinician can override, keeping the workflow unblocked.
    eff_neck = neck_mm if neck_mm >= 1.0 else 4.0
    eff_ar   = aspect_ratio if aspect_ratio > 0 else 1.4

    recs = recommend_clips(neck_mm=eff_neck, aspect_ratio=eff_ar, n=8)
    return [ClipRecommendation(**r) for r in recommendations_to_api(recs)]


@router.post(
    "/clips/custom/{session_id}",
    response_model=CustomClipInfo,
    summary="Upload a custom clip mesh (STL/OBJ)",
    description=(
        "Imports a user-supplied clip geometry (STL or OBJ), centres it at the "
        "origin and stores it for placement. Returns a `custom:*` clip_id usable "
        "in the clip plan alongside catalogue clips."
    ),
)
async def upload_custom_clip(
    session_id: str,
    file: UploadFile = File(...),
) -> CustomClipInfo:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    name = file.filename or "clip"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("stl", "obj"):
        raise HTTPException(status_code=422, detail="Formato no soportado. Usa STL u OBJ.")
    raw = await file.read()
    if len(raw) > _MAX_CLIP_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el límite de 8 MB.")

    meshes_dir = session_subdir(session_id, "meshes")
    custom_dir = meshes_dir / "custom_clips"
    custom_dir.mkdir(parents=True, exist_ok=True)

    registry = _custom_registry(session_id)
    idx = _next_custom_index(registry)
    clip_id = f"custom:{idx}"

    import tempfile
    from pathlib import Path as _Path
    import vtk
    from services.segmentation import write_vtp

    tmp = custom_dir / f"_upload_{idx}.{ext}"
    tmp.write_bytes(raw)
    try:
        reader = vtk.vtkSTLReader() if ext == "stl" else vtk.vtkOBJReader()
        reader.SetFileName(str(tmp))
        reader.Update()
        poly = reader.GetOutput()
        if poly is None or poly.GetNumberOfPoints() == 0:
            raise ValueError("La malla del clip está vacía o no se pudo leer.")
        # Centre at the origin so pose_transform places it at the neck.
        b = [0.0] * 6
        poly.GetBounds(b)
        cx, cy, cz = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2
        tf = vtk.vtkTransform()
        tf.Translate(-cx, -cy, -cz)
        f = vtk.vtkTransformPolyDataFilter()
        f.SetInputData(poly)
        f.SetTransform(tf)
        f.Update()
        write_vtp(f.GetOutput(), meshes_dir / f"custom_clip_{idx}.vtp")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"No se pudo importar el clip: {exc}")
    finally:
        try:
            _Path(tmp).unlink()
        except OSError:
            pass

    registry[clip_id] = name
    write_state(session_id, _CUSTOM_REGISTRY_KEY, json.dumps(registry))
    logger.info("Custom clip imported — session=%s id=%s name=%s", session_id, clip_id, name)
    return CustomClipInfo(clip_id=clip_id, name=name)


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
    def _clip_local(clip_id: str):
        """Local clip geometry — a stored custom mesh or a synthetic catalogue clip."""
        if clip_id.startswith("custom:"):
            idx = clip_id.split(":", 1)[1]
            path = meshes_dir / f"custom_clip_{idx}.vtp"
            if path.exists():
                return read_vtp(path)
            logger.warning("Custom clip %s not found; falling back to synthetic", clip_id)
        return devices.make_clip(_CLIP_LENGTH.get(clip_id, 9.0))

    clip_polys = []
    for pl in req.placements:
        local = _clip_local(pl.clip_id)
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
            "name": (_custom_clip_name(req.session_id, pl.clip_id)
                     if pl.clip_id.startswith("custom:")
                     else _CLIP_NAME.get(pl.clip_id, pl.clip_id)),
            "position": [pl.position.x, pl.position.y, pl.position.z],
            "orientation": [0.0, 0.0, float(pl.rotation_deg)],
            "is_custom": pl.clip_id.startswith("custom:"),
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


# ── Custom clip library: list / remove ────────────────────────────────────── #

@router.get(
    "/clips/custom/{session_id}",
    response_model=list[CustomClipInfo],
    summary="Custom clips imported in this session",
    description=(
        "The imported clips survive in the session directory, but the browser "
        "forgets them on resume, so the dropdown lost geometry that was still on "
        "disk. This restores the list."
    ),
)
async def list_custom_clips(session_id: str) -> list[CustomClipInfo]:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    registry = _custom_registry(session_id)
    return [
        CustomClipInfo(clip_id=cid, name=name)
        for cid, name in sorted(registry.items(), key=lambda kv: _custom_index(kv[0]) or 0)
    ]


@router.delete(
    "/clips/custom/{session_id}/{clip_index}",
    response_model=list[CustomClipInfo],
    summary="Remove an imported custom clip",
    description=(
        "Deletes the imported geometry and its catalogue entry. Without it a "
        "mis-imported file stayed in the dropdown for the rest of the session. "
        "Returns the remaining custom clips.\n\n"
        "Clips already placed in the plan are untouched — clear those from the "
        "devices step."
    ),
)
async def delete_custom_clip(session_id: str, clip_index: int) -> list[CustomClipInfo]:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    clip_id = f"custom:{clip_index}"
    registry = _custom_registry(session_id)
    if clip_id not in registry:
        raise HTTPException(status_code=404, detail=f"No hay un clip personalizado '{clip_id}'.")

    del registry[clip_id]
    write_state(session_id, _CUSTOM_REGISTRY_KEY, json.dumps(registry))

    path = session_subdir(session_id, "meshes") / f"custom_clip_{clip_index}.vtp"
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:  # noqa: BLE001 — the catalogue entry is already gone
            logger.warning("Could not delete %s for %s: %s", path.name, session_id, exc)

    logger.info("Custom clip removed — session=%s id=%s", session_id, clip_id)
    return [
        CustomClipInfo(clip_id=cid, name=name)
        for cid, name in sorted(registry.items(), key=lambda kv: _custom_index(kv[0]) or 0)
    ]
