"""Detection and morphometry router — wires real AneurysmDetector + MorphometricAnalyzer."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from fastapi import APIRouter, HTTPException

from models import (
    AneurysmCandidate as PydAneurysmCandidate,
    AneurysmDetectionResult,
    MorphometryResult,
    Position3D,
)
from services.sessions import (
    read_state, session_exists, session_subdir, write_state, mesh_url,
)
from services.aneurysm_detector import AneurysmDetector, AneurysmCandidate as DetCandidate
from services.morphometrics import MorphometricAnalyzer
from services.perforator_risk import neck_origin_from_morpho
from services.segmentation import read_vtp, write_vtp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["detection"])

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="det-worker")

# Modalities that produce noisy 3DRA meshes needing the XA preset
_XA_MODALITIES = {"XA", "RF", "DX", "CR", "DR"}


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

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            partial(
                _run_morphometry_sync,
                session_id=session_id,
                vtp_path=vtp_path,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Morphometry failed for session %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Morphometry error: {exc}") from exc

    return result


def _run_morphometry_sync(
    session_id: str,
    vtp_path:   Path,
) -> MorphometryResult:
    """Load candidate VTP → run MorphometricAnalyzer → persist state → return result."""
    poly     = read_vtp(vtp_path)
    analyzer = MorphometricAnalyzer()
    mr       = analyzer.analyze(poly)

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

    # ── Persist key morphometry for longitudinal comparison ───────────── #
    write_state(session_id, "morpho.max_diameter_mm", str(mr.max_diameter_mm))
    write_state(session_id, "morpho.neck_mm",         str(mr.neck_diameter_mm))
    write_state(session_id, "morpho.dome_height_mm",  str(mr.dome_height_mm))
    write_state(session_id, "morpho.volume_mm3",      str(mr.volume_mm3))
    write_state(session_id, "morpho.ar",              str(mr.aspect_ratio))
    write_state(session_id, "morpho.dnr",             str(mr.dome_to_neck_ratio))
    write_state(session_id, "morpho.bf",              str(mr.bottleneck_factor))
    write_state(session_id, "morpho.ui",              str(mr.undulation_index))
    write_state(session_id, "morpho.rupture_risk",    mr.rupture_risk_label)

    # ── Neck validity check ───────────────────────────────────────────── #
    neck_valid = mr.neck_diameter_mm >= 1.0
    warning    = None
    if not neck_valid:
        warning = (
            "Cuello no detectado (diámetro < 1 mm). "
            "DNR, AR y BF son poco fiables. Ajuste manualmente si es posible."
        )

    # ── Clamp shape indices to physical range ─────────────────────────── #
    # Candidate domes are open surface patches, not closed volumes;
    # vtkMassProperties on an open mesh can yield sphericity > 1 or EI < 0.
    # The desktop dataclass shows these raw values; our API contract enforces
    # [0, 1], so clamp and flag the mesh as unreliable instead of erroring.
    def _clamp01(v: float) -> float:
        return min(1.0, max(0.0, v))

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
        neck_valid        = neck_valid,
        warning           = warning,
        centroid          = Position3D(
            x=mr.centroid[0], y=mr.centroid[1], z=mr.centroid[2]
        ),
        principal_axis    = list(mr.principal_axis),
    )
