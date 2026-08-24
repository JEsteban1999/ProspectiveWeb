"""Detection and morphometry router — wires real AneurysmDetector + MorphometricAnalyzer."""
from __future__ import annotations

import asyncio
import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from fastapi import APIRouter, HTTPException

from models import (
    AneurysmCandidate as PydAneurysmCandidate,
    AneurysmDetectionResult,
    DetectionDiagnostics,
    MorphometryResult,
    NeckPlaneRequest,
    Position3D,
)
from services.sessions import (
    read_state, session_exists, session_subdir, write_state, mesh_url,
)
from services.aneurysm_detector import AneurysmDetector, AneurysmCandidate as DetCandidate
from services.morphometrics import MorphometricAnalyzer
from services.sac_isolation import isolate_closed_sac, isolate_sac_volumetric
from services.perforator_risk import neck_origin_from_morpho
from services.segmentation import read_vtp, write_vtp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["detection"])

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="det-worker")

# Modalities that produce noisy 3DRA meshes needing the XA preset
_XA_MODALITIES = {"XA", "RF", "DX", "CR", "DR"}


def _clamp01(v: float) -> float:
    """Clamp a shape index to the [0, 1] the API contract (and the PDF) assume."""
    return min(1.0, max(0.0, v))


def _detector_for_modality(modality: str) -> AneurysmDetector:
    """Build the detector with the desktop app's modality preset.

    Mirrors aneurysm_panel._apply_preset_xa / _apply_preset_cta: XA/3DRA meshes
    are much noisier than CTA, so they need heavier Laplacian pre-smoothing and
    lower curvature percentiles or the hard gates reject every real dome.
    """
    if modality.upper() in _XA_MODALITIES:
        return AneurysmDetector(
            gauss_percentile          = 60.0,
            mean_curv_gate_percentile = 40.0,
            min_radius_mm             = 1.5,
            max_radius_mm             = 20.0,
            min_points                = 4,
            min_positive_gauss_frac   = 0.55,
            min_sphericity            = 0.25,
            pre_smooth_iterations     = 25,
        )
    return AneurysmDetector(
        gauss_percentile          = 85.0,
        mean_curv_gate_percentile = 75.0,
        min_radius_mm             = 1.0,
        max_radius_mm             = 20.0,
        min_points                = 8,
        min_positive_gauss_frac   = 0.60,
        min_sphericity            = 0.35,
        pre_smooth_iterations     = 10,
    )


# ── POST /detect/{session_id} ──────────────────────────────────────────────── #

@router.post(
    "/detect/{session_id}",
    response_model=AneurysmDetectionResult,
    summary="Detect aneurysm candidates in the segmented mesh",
    description=(
        "Runs the v6 aneurysm detector on the stored vessel-tree mesh.\n\n"
        "**Algorithm:** Gaussian curvature thresholding → connected-component "
        "analysis → 3 hard shape gates (positive_gauss_frac, compactness, "
        "sphericity) → composite score.\n\n"
        "Each candidate is written as an isolated `.vtp` mesh and its URL is "
        "returned so vtk.js can render individual domes.\n\n"
        "**Prerequisite:** `POST /segment` must be called first."
    ),
)
async def detect_aneurysm(session_id: str) -> AneurysmDetectionResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    meshes_dir = session_subdir(session_id, "meshes")
    vtp_path   = meshes_dir / "vessel_tree.vtp"

    if not vtp_path.exists():
        raise HTTPException(
            status_code=422,
            detail="No segmented mesh found. Run POST /segment first.",
        )

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            partial(
                _run_detection_sync,
                session_id=session_id,
                vtp_path=vtp_path,
                meshes_dir=meshes_dir,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Detection failed for session %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Detection error: {exc}") from exc

    return result


def _run_detection_sync(
    session_id: str,
    vtp_path:   Path,
    meshes_dir: Path,
) -> AneurysmDetectionResult:
    """Load VTP → run AneurysmDetector → write candidate VTPs → update state."""
    poly = read_vtp(vtp_path)

    if poly.GetNumberOfPoints() == 0:
        raise ValueError("Segmented mesh has no geometry. Re-run segmentation.")

    modality   = read_state(session_id, "dicom.modality") or "CT"
    detector   = _detector_for_modality(modality)
    logger.info("Detection preset for modality %s", modality)
    det_result = detector.detect(poly)

    pyd_candidates: list[PydAneurysmCandidate] = []

    for cand in det_result.candidates:
        cand_name = f"aneurysm_cand_{cand.index:03d}.vtp"
        cand_path = meshes_dir / cand_name
        write_vtp(cand.poly_data, cand_path)
        url = mesh_url(session_id, cand_name)

        # Persist candidate metadata to session state
        prefix = f"detect.cand_{cand.index:03d}"
        write_state(session_id, f"{prefix}.vtp_name",    cand_name)
        write_state(session_id, f"{prefix}.url",         url)
        write_state(session_id, f"{prefix}.centroid_x",  str(cand.centroid[0]))
        write_state(session_id, f"{prefix}.centroid_y",  str(cand.centroid[1]))
        write_state(session_id, f"{prefix}.centroid_z",  str(cand.centroid[2]))
        write_state(session_id, f"{prefix}.diameter_mm", str(cand.diameter_mm))
        write_state(session_id, f"{prefix}.score",       str(cand.score))

        pyd_candidates.append(
            PydAneurysmCandidate(
                id=f"cand-{cand.index:03d}",
                center_mm=Position3D(
                    x=cand.centroid[0],
                    y=cand.centroid[1],
                    z=cand.centroid[2],
                ),
                max_diameter_mm=cand.diameter_mm,
                confidence=round(cand.score, 4),
                dome_mesh_url=url,
                selected=(cand.index == 1),  # top-scored candidate pre-selected
            )
        )

    # Persist summary for downstream morphometry / perforators
    write_state(session_id, "detect.n_candidates", str(len(pyd_candidates)))
    if pyd_candidates:
        write_state(session_id, "detect.best_vtp_name", f"aneurysm_cand_001.vtp")
    else:
        # No aneurysm found — clear any stale state from a previous run
        write_state(session_id, "detect.best_vtp_name", "")

    logger.info(
        "Detection complete — session=%s  candidates=%d",
        session_id, len(pyd_candidates),
    )

    return AneurysmDetectionResult(
        found=len(pyd_candidates) > 0,
        candidates=pyd_candidates,
        # Carried out so an empty result can explain itself. On a complete mesh
        # the size gate rejects the vast majority: high-curvature patches merge
        # across several vessels and their equivalent radius exceeds the bound.
        diagnostics=DetectionDiagnostics(
            regions_analyzed        = det_result.n_regions_total,
            rejected_too_few_points = det_result.n_failed_points,
            rejected_size           = det_result.n_failed_size,
            rejected_mean_curvature = det_result.n_failed_mean_curv,
            rejected_positive_gauss = det_result.n_failed_pgf,
            rejected_compactness    = det_result.n_failed_compact,
            rejected_sphericity     = det_result.n_failed_sphericity,
            merged                  = det_result.n_merged,
            removed_components      = det_result.n_removed_components,
            min_radius_mm           = detector.min_radius_mm,
            max_radius_mm           = detector.max_radius_mm,
        ),
    )


# ── GET /morphometry/{session_id} ─────────────────────────────────────────── #

@router.get(
    "/morphometry/{session_id}",
    response_model=MorphometryResult,
    summary="Compute aneurysm morphometry",
    description=(
        "Runs the full morphometric analysis on the best-scoring candidate "
        "mesh from the most recent detection run.\n\n"
        "Returns all clinical indices:\n"
        "- **DNR** (Dome-to-Neck Ratio) — risk ↑ if > 2.0\n"
        "- **AR** (Aspect Ratio) — risk ↑ if > 1.6\n"
        "- **BF** (Bottleneck Factor) — wide neck if > 1.5\n"
        "- **UI** (Undulation Index) — irregular dome if > 0.15\n"
        "- **EI** (Ellipticity Index) — non-spherical if > 0.35\n"
        "- **NSI** (Non-Sphericity Index)\n\n"
        "Neck origin is saved to session state for the perforators endpoint.\n\n"
        "**Prerequisite:** `POST /detect/{session_id}` must be called first."
    ),
)
async def get_morphometry(session_id: str) -> MorphometryResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    best_vtp_name = read_state(session_id, "detect.best_vtp_name", "")
    if not best_vtp_name:
        raise HTTPException(
            status_code=422,
            detail=(
                "No aneurysm candidate available. "
                "Run POST /detect/{session_id} first."
            ),
        )

    meshes_dir = session_subdir(session_id, "meshes")
    vtp_path   = meshes_dir / best_vtp_name

    if not vtp_path.exists():
        raise HTTPException(
            status_code=422,
            detail=f"Candidate mesh '{best_vtp_name}' not found on disk. Re-run detection.",
        )

    # A neck plane the user defined earlier is sticky: re-measuring the session
    # (e.g. after «Reanudar», which replays this endpoint) must reproduce the
    # manual closed-sac result, not fall back to the unreliable automatic one.
    saved_plane = _read_saved_neck_plane(session_id)

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            partial(
                _run_morphometry_sync,
                session_id=session_id,
                vtp_path=vtp_path,
                neck_plane=saved_plane,
            ),
        )
    except ValueError as exc:
        if saved_plane is None:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # The stored plane no longer isolates a sac (mesh re-segmented, say).
        # Keep it on record — the user may just need to re-mark — but answer
        # with the automatic analysis instead of failing the whole step.
        logger.warning("Stored neck plane no longer valid for %s (%s) — using auto",
                       session_id, exc)
        result = await loop.run_in_executor(
            _executor,
            partial(_run_morphometry_sync, session_id=session_id, vtp_path=vtp_path),
        )
    except Exception as exc:
        logger.error("Morphometry failed for session %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Morphometry error: {exc}") from exc

    return result


def _read_saved_neck_plane(session_id: str) -> NeckPlaneRequest | None:
    """Rebuild the user's neck plane from session state, or None if never set.

    Written by `_run_morphometry_sync` on every manual (Tier-2) run and copied
    verbatim into session snapshots, so it survives save → restore.
    """
    def _f(key: str) -> float | None:
        raw = read_state(session_id, key, "")
        try:
            return float(raw) if raw != "" else None
        except ValueError:
            return None

    ox, oy, oz = _f("morpho.plane_origin_x"), _f("morpho.plane_origin_y"), _f("morpho.plane_origin_z")
    nx, ny, nz = _f("morpho.plane_normal_x"), _f("morpho.plane_normal_y"), _f("morpho.plane_normal_z")
    if None in (ox, oy, oz, nx, ny, nz):
        return None
    if nx == 0.0 and ny == 0.0 and nz == 0.0:
        return None

    sx, sy, sz = _f("morpho.plane_seed_x"), _f("morpho.plane_seed_y"), _f("morpho.plane_seed_z")
    seed = None if None in (sx, sy, sz) else Position3D(x=sx, y=sy, z=sz)

    return NeckPlaneRequest(
        origin=Position3D(x=ox, y=oy, z=oz),
        normal=[nx, ny, nz],
        dome_seed=seed,
    )


@router.post(
    "/morphometry/{session_id}/neck-plane",
    response_model=MorphometryResult,
    summary="Morphometry from a user-defined neck plane (closed-sac)",
    description=(
        "Semi-automatic Tier-2 morphometry. The user supplies a **neck plane** "
        "(a point on the neck and a normal pointing toward the dome). The "
        "backend clips the vessel tree at the plane, keeps the dome-side "
        "connected component, caps it into a **closed watertight sac**, and "
        "measures the neck directly from the clip contour.\n\n"
        "Use this when the automatic analysis returns `reliable=false` (the "
        "detector isolated an open surface cap, on which volume/neck degenerate)."
    ),
)
async def morphometry_neck_plane(
    session_id: str,
    request:    NeckPlaneRequest,
) -> MorphometryResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    meshes_dir  = session_subdir(session_id, "meshes")
    vessel_path = meshes_dir / "vessel_tree.vtp"
    if not vessel_path.exists():
        raise HTTPException(
            status_code=422,
            detail="vessel_tree.vtp no encontrado. Ejecute la segmentación primero.",
        )

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            partial(
                _run_morphometry_sync,
                session_id=session_id,
                vtp_path=vessel_path,      # parent dir holds vessel_tree.vtp + sac output
                neck_plane=request,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Neck-plane morphometry failed for %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Morphometry error: {exc}") from exc

    return result


def _run_morphometry_sync(
    session_id: str,
    vtp_path:   Path,
    neck_plane: NeckPlaneRequest | None = None,
) -> MorphometryResult:
    """Load candidate VTP → run MorphometricAnalyzer → persist state → return result.

    When *neck_plane* is given (semi-automatic Tier 2), the vessel tree is
    clipped at the user's neck plane into a closed watertight sac, the neck is
    measured from the clip contour, and morphometry runs on that sac — yielding
    valid volume/DNR/AR/BF instead of the degenerate numbers an open detector
    cap produces.
    """
    analyzer    = MorphometricAnalyzer()
    neck_source = "auto"
    plane_arg   = None

    if neck_plane is not None:
        # ── Semi-automatic closed-sac isolation ───────────────────────────── #
        origin = (neck_plane.origin.x, neck_plane.origin.y, neck_plane.origin.z)
        nrm    = np.asarray(neck_plane.normal, dtype=float)
        nrm    = nrm / (np.linalg.norm(nrm) or 1.0)
        normal = tuple(float(v) for v in nrm)
        if neck_plane.dome_seed is not None:
            seed = (neck_plane.dome_seed.x, neck_plane.dome_seed.y, neck_plane.dome_seed.z)
        else:
            seed = tuple(origin[i] + 3.0 * normal[i] for i in range(3))

        # The two user clicks (neck point + dome apex) size the sac: their
        # distance is roughly the dome height, so bound the isolation to a
        # sphere of that radius around the apex — keeping parent vessels that
        # cross the neck plane out of the sac.
        apex_dist  = float(np.linalg.norm(np.asarray(seed) - np.asarray(origin)))
        bound_r    = apex_dist * 1.25 + 1.5
        crop_half  = max(12.0, apex_dist * 1.35 + 6.0)

        sac_mesh: "vtk.vtkPolyData | None" = None
        neck_diam = 0.0
        # Primary: build a WATERTIGHT sac in the volume domain from the cached
        # full-res volume (robust — marching cubes on a bounded mask is always
        # closed, unlike surface clip + fill-holes on the downsampled tree).
        try:
            from services.mpr import ensure_volume_cached, _get_volume
            meta   = ensure_volume_cached(session_id)
            volume = _get_volume(session_id)
            lower  = float(read_state(session_id, "seg.threshold_lower", "") or 0.0)
            upper  = float(read_state(session_id, "seg.threshold_upper", "") or 0.0)
            if lower or upper:
                sac_mesh, neck_diam = isolate_sac_volumetric(
                    volume, meta["spacing"], origin, normal, seed,
                    lower, upper, bound_r, half_extent_mm=crop_half,
                )
                logger.info("Volumetric sac isolation: %d pts, neck %.2f mm",
                            sac_mesh.GetNumberOfPoints(), neck_diam)
        except Exception as exc:
            logger.warning("Volumetric isolation failed, will try surface clip: %s", exc)
            sac_mesh = None

        # Fallback: surface clip + cap on the (coarse) vessel tree.
        if sac_mesh is None or sac_mesh.GetNumberOfPoints() < 50:
            vessel_path = vtp_path.parent / "vessel_tree.vtp"
            if not vessel_path.exists():
                raise ValueError(
                    "vessel_tree.vtp no disponible — se requiere para aislar el saco."
                )
            sac = isolate_closed_sac(read_vtp(vessel_path), origin, normal,
                                     dome_seed=seed, max_radius=bound_r)
            sac_mesh, neck_diam = sac.poly_data, sac.neck_diameter_mm

        # Validate: a valid sac needs a real neck and body.  A tiny result means
        # the apex was placed off the dome — ask the user to re-mark it.
        if sac_mesh.GetNumberOfPoints() < 50 or neck_diam < 1.0:
            raise ValueError(
                "No se aísla un saco válido con este plano. Verifica que el punto "
                "de cuello esté sobre el cuello y el ápice sobre la cúpula del domo."
            )
        # Persist the closed sac so the UI can display it.
        write_vtp(sac_mesh, vtp_path.parent / "aneurysm_sac.vtp")
        poly        = sac_mesh
        plane_arg   = (origin, normal, neck_diam)
        neck_source = "manual"

        # Persist the plane ITSELF (not just the numbers it produced) so the
        # measurement is reproducible: GET /morphometry replays it, which is
        # what makes a restored session come back with the manual sac instead
        # of the unreliable automatic cap.
        write_state(session_id, "morpho.plane_origin_x", str(origin[0]))
        write_state(session_id, "morpho.plane_origin_y", str(origin[1]))
        write_state(session_id, "morpho.plane_origin_z", str(origin[2]))
        write_state(session_id, "morpho.plane_normal_x", str(normal[0]))
        write_state(session_id, "morpho.plane_normal_y", str(normal[1]))
        write_state(session_id, "morpho.plane_normal_z", str(normal[2]))
        write_state(session_id, "morpho.plane_seed_x",   str(seed[0]))
        write_state(session_id, "morpho.plane_seed_y",   str(seed[1]))
        write_state(session_id, "morpho.plane_seed_z",   str(seed[2]))
    else:
        poly = read_vtp(vtp_path)

    mr = analyzer.analyze(poly, neck_plane=plane_arg)

    # ── Size Ratio: estimate the parent-artery diameter from the full vessel ─ #
    # SR = max_aneurysm_diameter / parent_artery_diameter (Dhar 2008). Requires
    # the whole vascular tree (the candidate mesh alone is not enough).
    vessel_path = vtp_path.parent / "vessel_tree.vtp"
    if vessel_path.exists():
        try:
            from services.parent_artery import estimate_parent_artery_diameter
            vessel = read_vtp(vessel_path)
            parent_dia = estimate_parent_artery_diameter(
                vessel, mr.centroid, mr.principal_axis,
                mr.neck_diameter_mm, mr.neck_plane_pos,
            )
            if parent_dia > 0.1:
                mr.size_ratio = mr.max_diameter_mm / parent_dia
                write_state(session_id, "morpho.parent_artery_mm", str(round(parent_dia, 3)))
                logger.info("SR = %.2f (parent Ø %.2f mm)", mr.size_ratio, parent_dia)
        except Exception as exc:
            logger.warning("Parent-artery / SR estimation skipped: %s", exc)

    # ── Neck origin (for perforator router) ───────────────────────────── #
    neck_origin = neck_origin_from_morpho(mr, poly)
    write_state(session_id, "morpho.neck_origin_x",  str(neck_origin[0]))
    write_state(session_id, "morpho.neck_origin_y",  str(neck_origin[1]))
    write_state(session_id, "morpho.neck_origin_z",  str(neck_origin[2]))

    # Principal (neck→dome) axis — used as the neck-plane normal by the device
    # planning endpoints (clip coverage, stent orientation).
    axis = mr.principal_axis or (0.0, 0.0, 1.0)
    write_state(session_id, "morpho.axis_x", str(axis[0]))
    write_state(session_id, "morpho.axis_y", str(axis[1]))
    write_state(session_id, "morpho.axis_z", str(axis[2]))

    # ── Persist key morphometry ───────────────────────────────────────── #
    # Consumed by the longitudinal comparison, the treatment engine and the
    # report/DICOM-SR builders — every field those read must be written here,
    # or it silently renders as 0 in the PDF.
    write_state(session_id, "morpho.max_diameter_mm",  str(mr.max_diameter_mm))
    write_state(session_id, "morpho.neck_mm",          str(mr.neck_diameter_mm))
    write_state(session_id, "morpho.dome_height_mm",   str(mr.dome_height_mm))
    write_state(session_id, "morpho.volume_mm3",       str(mr.volume_mm3))
    write_state(session_id, "morpho.surface_area_mm2", str(mr.surface_area_mm2))
    write_state(session_id, "morpho.ar",               str(mr.aspect_ratio))
    write_state(session_id, "morpho.dnr",              str(mr.dome_to_neck_ratio))
    write_state(session_id, "morpho.bf",               str(mr.bottleneck_factor))
    write_state(session_id, "morpho.ui",               str(mr.undulation_index))
    # Clamped like the API response: an open mesh can yield sphericity > 1, and
    # the report prints this against a "1.0 = esfera perfecta" reference.
    write_state(session_id, "morpho.compactness",      str(_clamp01(mr.compactness)))
    write_state(session_id, "morpho.rupture_risk",     mr.rupture_risk_label)
    write_state(session_id, "morpho.neck_source",      neck_source)

    # ── Reliability guard (Tier 1) ────────────────────────────────────── #
    # analyze() nulls volume/neck metrics when the mesh is an open patch or the
    # sac is not physically plausible; surface that reason first so the UI can
    # flag the whole analysis, not just the neck.
    warning = None
    if not mr.reliable and mr.reliability_note:
        warning = mr.reliability_note

    # ── Neck validity check ───────────────────────────────────────────── #
    neck_valid = mr.neck_diameter_mm >= 1.0
    if not neck_valid and warning is None:
        warning = (
            "Cuello no detectado (diámetro < 1 mm). "
            "DNR, AR y BF son poco fiables. Ajuste manualmente si es posible."
        )

    # ── Clamp shape indices to physical range ─────────────────────────── #
    # Candidate domes are open surface patches, not closed volumes;
    # vtkMassProperties on an open mesh can yield sphericity > 1 or EI < 0.
    # The desktop dataclass shows these raw values; our API contract enforces
    # [0, 1], so clamp (see _clamp01) and flag the mesh as unreliable instead
    # of erroring.
    indices_out_of_range = (
        not (0.0 <= mr.compactness <= 1.0)
        or not (0.0 <= mr.ellipticity_index <= 1.0)
        or not (0.0 <= mr.undulation_index <= 1.0)
    )
    if indices_out_of_range:
        note = (
            "Índices de forma fuera de rango físico (malla de domo abierta) — "
            "compacidad/EI/UI acotados a [0, 1]; interpretar con cautela."
        )
        warning = f"{warning} {note}" if warning else note

    # ── Map desktop dataclass → Pydantic model ────────────────────────── #
    return MorphometryResult(
        volume_mm3        = round(mr.volume_mm3,        2),
        surface_area_mm2  = round(mr.surface_area_mm2,  2),
        eq_sphere_diam_mm = round(mr.eq_sphere_diam_mm, 3),
        max_diameter_mm   = round(mr.max_diameter_mm,   3),
        bbox_w_mm         = round(mr.bbox_w_mm,         3),
        bbox_h_mm         = round(mr.bbox_h_mm,         3),
        neck_mm           = round(mr.neck_diameter_mm,  3),
        dome_height_mm    = round(mr.dome_height_mm,    3),
        dnr               = round(mr.dome_to_neck_ratio, 3),
        ar                = round(mr.aspect_ratio,       3),
        bf                = round(mr.bottleneck_factor,  3),
        compactness       = round(_clamp01(mr.compactness),        4),
        ui                = round(_clamp01(mr.undulation_index),   4),
        ei                = round(_clamp01(mr.ellipticity_index),  4),
        nsi               = round(_clamp01(mr.non_sphericity_idx), 4),
        sr                = round(max(0.0, mr.size_ratio),         3),
        rupture_risk_label= mr.rupture_risk_label,
        reliable          = mr.reliable,
        neck_source       = neck_source,
        neck_valid        = neck_valid,
        warning           = warning,
        centroid          = Position3D(
            x=mr.centroid[0], y=mr.centroid[1], z=mr.centroid[2]
        ),
        principal_axis    = list(mr.principal_axis),
        neck_origin       = Position3D(
            x=neck_origin[0], y=neck_origin[1], z=neck_origin[2]
        ),
    )
