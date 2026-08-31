"""Surgical clip library and planning router."""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from models import ClipLibraryItem, ClipPlanRequest, ClipPlanResult, ClipRecommendation
from models.detection import Position3D
from models.clips import (
    ClipAnimationResult,
    ClipCandidateOut,
    ClipCaseOut,
    ClipCriterion,
    ClipFitCheck,
    ClipSelectionResult,
    CustomJawOut,
    ManufactureSpecOut,
)
from services.clips   import catalogue_to_api, recommend_clips, recommendations_to_api
from services.clip_selection import (
    ClipCandidate,
    ClipCase,
    ClipSelection,
    ManufactureSpec,
    derive_manufacture_spec,
    select_clips,
)
from services.sessions import (
    export_url, mesh_url, read_state, session_exists, session_subdir, write_state,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["clips"])

def _clip_geometry_for(clip_id: str, meshes_dir):
    """The real geometry for this clip id, in the clip's own local frame.

    Three sources, most specific first: a mesh imported into this session, a
    NAVARRO™ design (built at its jaw length, drawn or stretched), and — for the
    built-in catalogue, which has no meshes — a shape-aware synthetic clip at the
    catalogue's dimensions. Shared by placement and by the animation, so what is
    shown moving is the same solid that was placed.
    """
    from services import devices
    from services.segmentation import read_vtp

    index = _catalogue_index()
    if clip_id.startswith("custom:"):
        idx = clip_id.split(":", 1)[1]
        path = meshes_dir / f"custom_clip_{idx}.vtp"
        if path.exists():
            return read_vtp(path)
        logger.warning("Custom clip %s not found; falling back to synthetic", clip_id)

    if clip_id.startswith("navarro:"):
        try:
            from services.navarro import mesh_for_id
            return mesh_for_id(clip_id)
        except Exception as exc:  # noqa: BLE001 — never fail a plan on geometry
            logger.warning("NAVARRO geometry unavailable for %s: %s", clip_id, exc)

    spec = index.get(clip_id)
    if spec is None:
        logger.warning("Unknown clip id %s; placing a default 9 mm clip", clip_id)
        return devices.make_clip(9.0)
    return devices.make_clip_shaped(
        blade_length_mm=spec.blade_length_mm,
        blade_width_mm=spec.blade_width_mm,
        blade_height_mm=spec.blade_height_mm,
        shape=spec.shape.name,
        angle_deg=spec.bend_angle_deg or (
            90.0 if spec.shape.name == "ANGLED" else 45.0 if spec.shape.name == "ANGLED_45" else 0.0
        ),
        fenestration_mm=spec.fenestration_mm,
    )


def _catalogue_index() -> dict[str, "object"]:
    """id → ClipSpec across every source the selector can recommend from.

    Built per call, not frozen at import: the library and the NAVARRO™ family are
    read from disk and can grow while the server runs. Freezing this was a real
    defect — a NAVARRO clip could be recommended and then, when placed, silently
    fall back to a generic 9 mm box, so the plan and the report described a clip
    nobody had chosen.
    """
    from services.clip_library import catalogue_with_library

    return {spec.identifier: spec for spec in catalogue_with_library()}

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
    index = _catalogue_index()

    def _clip_local(clip_id: str):
        return _clip_geometry_for(clip_id, meshes_dir)

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
                     else (index[pl.clip_id].name if pl.clip_id in index else pl.clip_id)),
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


# ── Criteria-based clip selection ─────────────────────────────────────────── #
# The endpoint above answers "rank the catalogue". This one answers the question
# a surgeon actually has: does anything I own fit this aneurysm, and if not,
# what do I have to have made?


def _case_record(session_id: str, case_id: int | None) -> tuple[str, str, str]:
    """Region, laterality and aneurysm type for this session's clinical case.

    A live session that has never been saved has no DB row, so the case is
    looked up by the id the workspace already holds. Failing to find it is not
    an error: the selection then judges on geometry alone and says so in its
    caveats, which beats guessing a location.
    """
    from services.database import SessionLocal
    from services.db_models import PlanningSession, Study

    db = SessionLocal()
    try:
        study = None
        if case_id:
            study = db.get(Study, int(case_id))
        if study is None:
            ps = (db.query(PlanningSession)
                    .filter(PlanningSession.session_id == session_id)
                    .order_by(PlanningSession.id.desc())
                    .first())
            if ps is not None and ps.study_id:
                study = db.get(Study, ps.study_id)
        if study is None:
            return "", "", ""
        return (study.region_anatomica or "", study.lateralidad or "",
                study.tipo_aneurisma or "")
    except Exception as exc:  # noqa: BLE001 — the selection must survive a DB hiccup
        logger.warning("Case lookup failed for session %s: %s", session_id, exc)
        return "", "", ""
    finally:
        db.close()


def _build_case(session_id: str, case_id: int | None) -> ClipCase:
    """Assemble everything that changes which clip fits, from what was measured."""
    region, laterality, aneurysm_type = _case_record(session_id, case_id)
    neck_source = read_state(session_id, "morpho.neck_source", "auto") or "auto"
    return ClipCase(
        neck_mm          = _load_float(session_id, "morpho.neck_mm", 0.0),
        dome_height_mm   = _load_float(session_id, "morpho.dome_height_mm", 0.0),
        max_diameter_mm  = _load_float(session_id, "morpho.max_diameter_mm", 0.0),
        ar               = _load_float(session_id, "morpho.ar", 0.0),
        dnr              = _load_float(session_id, "morpho.dnr", 0.0),
        bf               = _load_float(session_id, "morpho.bf", 0.0),
        parent_artery_mm = _load_float(session_id, "morpho.parent_artery_mm", 0.0),
        neck_source      = neck_source,
        neck_tilt_deg    = _load_float(session_id, "morpho.neck_tilt_deg", 0.0),
        # An automatic neck on a detector cap is exactly the case where the
        # numbers look fine and mean nothing, so trust only a marked plane.
        neck_reliable    = True,
        region           = region,
        laterality       = laterality,
        aneurysm_type    = aneurysm_type,
    )


def _neck_plane(session_id: str) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """The marked neck plane, or None when the neck was never placed by hand."""
    keys = ("morpho.plane_origin_x", "morpho.plane_origin_y", "morpho.plane_origin_z",
            "morpho.plane_normal_x", "morpho.plane_normal_y", "morpho.plane_normal_z")
    vals = [read_state(session_id, k, "") for k in keys]
    if not all(vals):
        return None
    try:
        o = tuple(float(v) for v in vals[:3])
        n = tuple(float(v) for v in vals[3:])
    except ValueError:
        return None
    if not any(abs(c) > 1e-9 for c in n):
        return None
    return o, n  # type: ignore[return-value]


def _criteria_out(cand: ClipCandidate) -> list[ClipCriterion]:
    return [ClipCriterion(key=c.key, label=c.label, verdict=c.verdict, detail=c.detail)
            for c in cand.criteria]


def _candidate_out(cand: ClipCandidate) -> ClipCandidateOut:
    v = cand.verified
    f_lo, f_hi = cand.clip.force_band
    return ClipCandidateOut(
        clip_id          = cand.clip.identifier,
        clip_name        = cand.clip.name,
        manufacturer     = cand.clip.manufacturer,
        shape            = cand.clip.shape.value,
        blade_length_mm  = cand.clip.blade_length_mm,
        closing_force_g  = cand.clip.closing_force_g,
        score            = cand.score,
        verdict          = cand.verdict,
        headline         = cand.headline,
        coverage_ratio   = cand.coverage_ratio,
        safety_margin_mm = cand.safety_margin_mm,
        availability     = getattr(cand.clip, "availability", "stock"),
        bend_angle_deg   = getattr(cand.clip, "bend_angle_deg", 0.0),
        closing_force_min_g = f_lo,
        closing_force_max_g = f_hi,
        force_provisional   = getattr(cand.clip, "force_provisional", False),
        criteria         = _criteria_out(cand),
        fit              = None if v is None else ClipFitCheck(
            collision=v.collision, n_contacts=v.n_contacts, span_mm=v.span_mm,
            neck_coverage_pct=v.neck_coverage_pct, clean_rolls=v.clean_rolls,
            n_rolls=v.n_rolls, note=v.note,
        ),
    )


def _spec_out(spec: ManufactureSpec, stl_url: str | None = None) -> ManufactureSpecOut:
    return ManufactureSpecOut(
        blade_length_mm  = spec.blade_length_mm,
        blade_width_mm   = spec.blade_width_mm,
        blade_height_mm  = spec.blade_height_mm,
        spring_length_mm = spec.spring_length_mm,
        shape            = spec.shape.value,
        angle_deg        = spec.angle_deg,
        closing_force_g  = spec.closing_force_g,
        fenestration_mm  = spec.fenestration_mm,
        neck_mm          = spec.neck_mm,
        label            = spec.label,
        reasons          = spec.reasons,
        confidence_notes = spec.confidence_notes,
        stl_url          = stl_url,
    )


def _run_selection(session_id: str, case_id: int | None, verify: bool) -> ClipSelection:
    """Analytic pass over the catalogue, then geometry on the survivors."""
    case = _build_case(session_id, case_id)
    selection = select_clips(case)
    if not verify or not selection.recommended:
        return selection

    plane = _neck_plane(session_id)
    if plane is None:
        return selection
    mesh_path = session_subdir(session_id, "meshes") / "vessel_tree.vtp"
    if not mesh_path.exists():
        return selection
    try:
        from services.clip_fit import verify_all
        from services.segmentation import read_vtp
        vessel = read_vtp(mesh_path)
        verify_all(selection.recommended, case, vessel, plane[0], plane[1])
        # Geometry can demote a candidate below the bar entirely, so the split
        # between recommended and rejected has to be redrawn — not just re-sorted.
        from services.clip_selection import repartition_after_verification
        repartition_after_verification(selection)
    except Exception as exc:  # noqa: BLE001 — verification is a bonus, not a gate
        logger.warning("Clip geometry verification failed — session=%s: %s", session_id, exc)
    return selection


@router.get(
    "/clips/selection/{session_id}",
    response_model=ClipSelectionResult,
    summary="Which clip fits this aneurysm, and why — or what to have made",
    description=(
        "Judges every clip in the catalogue against this session's morphometry and "
        "the clinical case, criterion by criterion (blade vs neck, closing force, "
        "shape vs location, fenestration calibre), then poses the best candidates on "
        "the measured neck plane and checks them against the patient's own mesh.\n\n"
        "Never returns an empty list: when nothing in the inventory fits, `outcome` "
        "is `manufacture` and `manufacture` carries the specification to send out — "
        "dimensions, shape, closing force and window calibre.\n\n"
        "Geometric verification needs a hand-marked neck plane and a segmented mesh; "
        "without them the analytic criteria still apply and `fit` stays null."
    ),
)
async def clip_selection(
    session_id: str,
    case_id: int | None = Query(None, description="Clinical case, when the session is not yet saved"),
    verify: bool = Query(True, description="Run the geometric check on the top candidates"),
) -> ClipSelectionResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    selection = _run_selection(session_id, case_id, verify)
    c = selection.case
    return ClipSelectionResult(
        outcome     = selection.outcome,
        summary     = selection.summary,
        case        = ClipCaseOut(
            neck_mm=c.neck_mm, dome_height_mm=c.dome_height_mm,
            max_diameter_mm=c.max_diameter_mm, ar=c.ar, dnr=c.dnr,
            parent_artery_mm=c.parent_artery_mm, neck_source=c.neck_source,
            neck_tilt_deg=c.neck_tilt_deg, region=c.region,
            laterality=c.laterality, aneurysm_type=c.aneurysm_type,
        ),
        recommended = [_candidate_out(x) for x in selection.recommended],
        rejected    = [_candidate_out(x) for x in selection.rejected],
        manufacture = None if selection.manufacture is None else _spec_out(selection.manufacture),
        custom_jaw  = None if selection.custom_jaw is None else CustomJawOut(
            series=selection.custom_jaw.series,
            angle_deg=selection.custom_jaw.angle_deg,
            jaw_mm=selection.custom_jaw.jaw_mm,
            nearest_drawn_mm=selection.custom_jaw.nearest_drawn_mm,
            label=selection.custom_jaw.label,
            reason=selection.custom_jaw.reason,
        ),
        caveats     = selection.caveats,
    )


@router.post(
    "/clips/manufacture/{session_id}",
    response_model=ManufactureSpecOut,
    summary="Generate the STL of the clip this case would need",
    description=(
        "Builds the specified clip as a solid and writes it to the session's exports "
        "as a binary STL, ready to send to a workshop or a printer.\n\n"
        "The geometry is an approximation of a machined clip: correct blade length, "
        "width, height, shape class and window calibre, but no fillets and no real "
        "spring. It is a specification to manufacture FROM, not a finished part."
    ),
)
async def clip_manufacture_spec(
    session_id: str,
    case_id: int | None = Query(None, description="Clinical case, when the session is not yet saved"),
) -> ManufactureSpecOut:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    case = _build_case(session_id, case_id)
    if case.neck_mm <= 0:
        raise HTTPException(
            status_code=409,
            detail="No hay un cuello medido: marca el plano del cuello en Morfometría "
                   "antes de especificar un clip a medida.",
        )
    selection = select_clips(case)
    spec = selection.manufacture or derive_manufacture_spec(case, [])

    try:
        from services.devices import make_clip_shaped, write_stl
        poly = make_clip_shaped(
            blade_length_mm = spec.blade_length_mm,
            blade_width_mm  = spec.blade_width_mm,
            blade_height_mm = spec.blade_height_mm,
            shape           = spec.shape.name,
            angle_deg       = spec.angle_deg,
            fenestration_mm = spec.fenestration_mm,
        )
        exports = session_subdir(session_id, "exports")
        name = "clip_a_medida.stl"
        write_stl(poly, exports / name)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Custom clip STL generation failed")
        raise HTTPException(status_code=500, detail=f"No se pudo generar el STL del clip: {exc}")

    # Cache-busted: the filename is fixed per session, so a second spec would
    # otherwise be served from the browser's copy of the first.
    stamp = int(time.time() * 1000)
    logger.info("Custom clip spec generated — session=%s %s", session_id, spec.label)
    return _spec_out(spec, stl_url=f"{export_url(session_id, name)}?v={stamp}")


# ── NAVARRO™: build a clip at any jaw length ──────────────────────────────── #

@router.post(
    "/clips/navarro/{session_id}",
    response_model=CustomJawOut,
    summary="Build a NAVARRO™ clip at a given bend angle and jaw length",
    description=(
        "The NAVARRO clips are manufactured per case, so the jaw is not restricted "
        "to the six drawn sizes. This builds the geometry for any jaw length: a "
        "drawn size is returned as designed, anything else is produced by "
        "stretching the jaw of the nearest design ALONG ITS OWN AXIS. "
        "Only the jaw moves. The body and spring are left exactly as drawn, "
        "because a uniform scale would resize the spring too and its closing force "
        "would no longer be the family's. The taper profile is the same shape "
        "across every drawn size (measured to ~0.05 mm), so stretching the jaw "
        "reproduces the family's own design language rather than inventing one. "
        "The result is a faithful preview for display and collision testing - NOT "
        "the manufacturing master, which comes from the parametric CAD."
    ),
)
async def build_navarro_clip(
    session_id: str,
    jaw_mm: float = Query(..., gt=0.5, le=40.0, description="Useful grip length (mm)"),
    angle_deg: float = Query(0.0, ge=0.0, le=90.0, description="Bend angle (0 = straight)"),
) -> CustomJawOut:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    try:
        from services.navarro import build_jaw
        from services.devices import write_stl
        from services.segmentation import write_vtp
        mesh, src, exact = build_jaw(angle_deg, jaw_mm)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("NAVARRO build failed")
        raise HTTPException(status_code=422, detail=f"No se pudo generar el clip: {exc}")

    meshes  = session_subdir(session_id, "meshes")
    exports = session_subdir(session_id, "exports")
    stem = f"navarro_{src.series.lower()}_{angle_deg:.0f}deg_{jaw_mm:.1f}mm".replace(".", "_")
    try:
        write_vtp(mesh, meshes / f"{stem}.vtp")
        write_stl(mesh, exports / f"{stem}.stl")
    except Exception as exc:  # noqa: BLE001
        logger.exception("NAVARRO export failed")
        raise HTTPException(status_code=500, detail=f"No se pudo guardar el clip: {exc}")

    stamp = int(time.time() * 1000)
    shape = "Recto" if src.angle_deg == 0 else f"Angulado {src.angle_deg:.0f}°"
    reason = (
        f"Talla dibujada de {src.jaw_mm} mm, tal cual."
        if exact else
        f"Mordaza estirada desde la talla dibujada de {src.jaw_mm} mm. "
        f"Vista previa para visualizar y comprobar colisiones; la pieza real sale "
        f"del CAD paramétrico."
    )
    logger.info("NAVARRO clip built — session=%s %s jaw=%.1f exact=%s",
                session_id, src.name, jaw_mm, exact)
    return CustomJawOut(
        series=src.series,
        angle_deg=float(src.angle_deg),
        jaw_mm=float(jaw_mm),
        nearest_drawn_mm=float(src.jaw_mm),
        label=f"NAVARRO™ {src.series} {shape}, mordaza {jaw_mm:.1f} mm",
        reason=reason,
        mesh_url=f"{mesh_url(session_id, stem + '.vtp')}?v={stamp}",
        stl_url=f"{export_url(session_id, stem + '.stl')}?v={stamp}",
    )


# ── Clip application as motion ────────────────────────────────────────────── #

@router.post(
    "/clips/animation/{session_id}",
    response_model=ClipAnimationResult,
    summary="The pieces needed to show a clip being applied",
    description=(
        "Splits the chosen clip into the body and its two blades, and returns the "
        "hinge, the swing and the approach run, so the viewer can play the "
        "manoeuvre: down the corridor with the jaw open, astride the neck, then "
        "closed.\n\n"
        "The hinge and the opening axis are DERIVED from the mesh, so they hold "
        "for any clip. How far the jaw opens is ASSUMED from how commercial clips "
        "behave, because a closed STL records no mechanism; `mechanics_assumed` "
        "says so and the figures live in one place to be replaced.\n\n"
        "For rehearsal, not simulation: no tissue yields, no applier is modelled, "
        "and nothing here says the corridor can be reached with human hands."
    ),
)
async def clip_animation(
    session_id: str,
    req: ClipPlanRequest,
) -> ClipAnimationResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if not req.placements:
        raise HTTPException(status_code=422, detail="Indica el clip que se va a colocar.")

    pl = req.placements[0]
    meshes_dir = session_subdir(session_id, "meshes")
    index = _catalogue_index()
    spec = index.get(pl.clip_id)

    try:
        from services.clip_animation import (
            MECHANICS_ARE_ASSUMED, blade_swing_deg, default_approach, jaw_geometry,
            split_blades,
        )
        from services.segmentation import write_vtp

        local = _clip_geometry_for(pl.clip_id, meshes_dir)
        body, blade_a, blade_b, geom = split_blades(local)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Clip animation build failed")
        raise HTTPException(status_code=422, detail=f"No se pudo preparar la animación: {exc}")

    stamp = int(time.time() * 1000)
    names = {}
    for tag, poly in (("body", body), ("blade_a", blade_a), ("blade_b", blade_b)):
        fn = f"anim_{tag}.vtp"
        write_vtp(poly, meshes_dir / fn)
        names[tag] = f"{mesh_url(session_id, fn)}?v={stamp}"

    blade_mm = spec.blade_length_mm if spec is not None else geom["lever_mm"]
    swing = blade_swing_deg(geom, blade_mm)

    hinge = [0.0, 0.0, 0.0]
    hinge[geom["long_axis"]] = geom["hinge"]
    # The blades turn about the axis perpendicular to both the clip's length and
    # its opening direction.
    third = ({0, 1, 2} - {geom["long_axis"], geom["open_axis"]}).pop()
    axis = [0.0, 0.0, 0.0]
    axis[third] = 1.0

    normal = tuple(pl.normal) if pl.normal else (0.0, 0.0, 1.0)
    marked = req.trajectory_entry is not None and req.trajectory_target is not None
    if marked:
        entry = (req.trajectory_entry.x, req.trajectory_entry.y, req.trajectory_entry.z)
        target = (req.trajectory_target.x, req.trajectory_target.y, req.trajectory_target.z)
    else:
        entry, target = default_approach(
            (pl.position.x, pl.position.y, pl.position.z), normal,
            float(blade_mm) + 14.0,
        )

    logger.info("Clip animation — session=%s clip=%s swing=%.1f marked_path=%s",
                session_id, pl.clip_id, swing, marked)
    return ClipAnimationResult(
        body_url=names["body"], blade_a_url=names["blade_a"], blade_b_url=names["blade_b"],
        hinge=Position3D(x=hinge[0], y=hinge[1], z=hinge[2]),
        hinge_axis=axis,
        swing_deg=round(swing, 2),
        mechanics_assumed=MECHANICS_ARE_ASSUMED,
        approach_entry=Position3D(x=entry[0], y=entry[1], z=entry[2]),
        approach_target=Position3D(x=target[0], y=target[1], z=target[2]),
        approach_is_default=not marked,
        position=pl.position,
        normal=list(normal),
        rotation_deg=pl.rotation_deg,
        clip_name=spec.name if spec is not None else pl.clip_id,
    )
