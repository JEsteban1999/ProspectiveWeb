"""Segmentation router — auto-thresholds and full VTK marching-cubes pipeline."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from fastapi import APIRouter, HTTPException

from models import AutoThresholdResult, SegmentRequest, SegmentResult
from services.sessions     import read_state, session_exists, session_subdir, write_state, mesh_url
from services.thresholds   import compute_auto_thresholds, strategy_hint
from services.dicom_loader import load_series
from services.segmentation import (
    SegmentationPipeline, write_vtp,
    voxel_fraction as seg_voxel_fraction,
    level_to_smooth_iters, level_to_cleanup_verts,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["segmentation"])

# Thread-pool for CPU-bound DICOM + VTK work (keeps the event loop free)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="seg-worker")


# ── Helpers ────────────────────────────────────────────────────────────────── #

def _load_float(session_id: str, key: str, default: float) -> float:
    try:
        raw = read_state(session_id, key, "")
        return float(raw) if raw else default
    except (ValueError, Exception):
        return default


# ── GET /thresholds/{session_id} ───────────────────────────────────────────── #

@router.get(
    "/thresholds/{session_id}",
    response_model=AutoThresholdResult,
    summary="Get auto-computed thresholds",
    description=(
        "Returns the automatically computed lower/upper HU thresholds for the "
        "DICOM series loaded in this session, along with the strategy key and a "
        "Spanish clinical hint string.\n\n"
        "This endpoint uses WindowCenter/WindowWidth from the DICOM header to give "
        "an instant response. The **POST /segment** endpoint uses the actual voxel "
        "distribution for the final segmentation.\n\n"
        "Strategies: `ct_stats`, `ct_wc_ww`, `xa_band_pass`, `xa_wc_ww`, "
        "`dsa`, `mr_percentile`, `wc_ww`."
    ),
)
async def get_thresholds(session_id: str) -> AutoThresholdResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Read DICOM metadata persisted by upload router
    modality      = read_state(session_id, "dicom.modality",       "CT")
    window_center = _load_float(session_id, "dicom.window_center", 400.0)
    window_width  = _load_float(session_id, "dicom.window_width",  1500.0)

    # Fast path: WC/WW-only thresholds (no volume load).
    # When volume IS available after segmentation, the voxel_fraction key is updated.
    lower, upper, strategy = compute_auto_thresholds(
        volume=None,
        modality=modality,
        window_center=window_center,
        window_width=window_width,
    )

    is_dsa = strategy == "dsa"
    hint   = strategy_hint(strategy, lower, upper, is_dsa)

    # Best-effort: if a previous segmentation stored the voxel fraction, use it
    vf_str = read_state(session_id, "seg.voxel_fraction", "")
    vf     = float(vf_str) if vf_str else None

    return AutoThresholdResult(
        lower=lower,
        upper=upper,
        strategy=strategy,
        is_dsa=is_dsa,
        hint=hint,
        voxel_fraction=vf,
    )


# ── POST /segment ──────────────────────────────────────────────────────────── #

@router.post(
    "/segment",
    response_model=SegmentResult,
    summary="Run segmentation pipeline",
    description=(
        "Loads the DICOM volume from disk, applies the requested lower/upper thresholds, "
        "and runs the full VTK Marching-Cubes pipeline (smoothing + decimation + normals). "
        "Returns the mesh URL (.vtp) ready for vtk.js rendering.\n\n"
        "**Processing time:** 5–60 s depending on volume size and smoothing level. "
        "Use the WebSocket `/ws/progress/{session_id}` endpoint to stream progress updates."
    ),
)
async def segment(req: SegmentRequest) -> SegmentResult:
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    dicom_dir  = session_subdir(req.session_id, "dicom")
    meshes_dir = session_subdir(req.session_id, "meshes")

    if not any(dicom_dir.iterdir()):
        raise HTTPException(
            status_code=422,
            detail="No DICOM files found in session. Did you upload files first?",
        )

    # Map API levels (0–10) to pipeline parameters
    smooth_iters  = level_to_smooth_iters(req.smoothing)
    cleanup_verts = level_to_cleanup_verts(req.cleanup)

    # Run heavy CPU work off the event loop
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            partial(
                _run_segmentation_sync,
                session_id=   req.session_id,
                series_id=    req.series_id,
                dicom_dir=    dicom_dir,
                meshes_dir=   meshes_dir,
                lower=        req.lower,
                upper=        req.upper,
                smooth_iters= smooth_iters,
                cleanup_verts=cleanup_verts,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Segmentation failed for session %s: %s", req.session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Segmentation error: {exc}") from exc

    return result


# ── Synchronous worker (runs in thread-pool) ───────────────────────────────── #

def _run_segmentation_sync(
    session_id:    str,
    series_id:     str,
    dicom_dir:     Path,
    meshes_dir:    Path,
    lower:         float,
    upper:         float,
    smooth_iters:  int,
    cleanup_verts: int,
) -> SegmentResult:
    """Load DICOM → run VTK pipeline → write .vtp → update session state.

    Runs in a thread-pool worker to avoid blocking the asyncio event loop.
    """
    # ── Load DICOM volume ──────────────────────────────────────────────────── #
    logger.info(
        "Loading DICOM series '%s' for session '%s' ...", series_id, session_id
    )
    dcm = load_series(series_id, dicom_dir)

    # Re-compute thresholds with the real volume (upgrades WC/WW estimate to p90/p99)
    # then override with what the user explicitly requested via req.lower/upper
    # (the user already saw the auto-thresholds and may have adjusted sliders)
    modality = dcm.modality
    _, _, strategy = compute_auto_thresholds(
        volume=dcm.volume,
        modality=modality,
        window_center=dcm.window_center,
        window_width=dcm.window_width,
    )
    is_dsa = strategy == "dsa"

    # Compute what fraction of voxels falls in the user-requested threshold band
    vf = seg_voxel_fraction(dcm.volume, lower, upper)

    # ── Build pipeline parameters ─────────────────────────────────────────── #
    pipeline = SegmentationPipeline(
        threshold_hu=        lower,
        threshold_max_hu=    upper if upper > lower else 0.0,
        smooth_iterations=   smooth_iters,
        smooth_pass_band=    0.06,
        target_reduction=    0.70,
        gaussian_sigma=      0.5,
        min_component_verts= cleanup_verts,
        morpho_closing_mm=   0.5,   # small closing to fill micro-gaps
        keep_top_n=          0,     # use min_component_verts, not top-N
    )

    # ── Run marching cubes ────────────────────────────────────────────────── #
    logger.info(
        "Running marching cubes: lower=%.0f upper=%.0f smooth=%d cleanup=%d shape=%s",
        lower, upper, smooth_iters, cleanup_verts, dcm.volume.shape,
    )
    seg_result = pipeline.run(dcm.volume, dcm.spacing)

    # ── Write VTP mesh ────────────────────────────────────────────────────── #
    vtp_name = "vessel_tree.vtp"
    vtp_path = meshes_dir / vtp_name
    write_vtp(seg_result.poly_data, vtp_path)

    url = mesh_url(session_id, vtp_name)

    # ── Persist metadata to session state ─────────────────────────────────── #
    write_state(session_id, "seg.mesh_url",       url)
    write_state(session_id, "seg.n_vertices",     str(seg_result.n_vertices))
    write_state(session_id, "seg.n_faces",        str(seg_result.n_triangles))
    write_state(session_id, "seg.voxel_fraction", f"{vf:.6f}")
    write_state(session_id, "seg.threshold_lower",str(lower))
    write_state(session_id, "seg.threshold_upper",str(upper))
    write_state(session_id, "seg.strategy",       strategy)
    # Volume geometry — needed by Session C (morphometry + aneurysm detection)
    write_state(session_id, "dicom.volume_z",     str(dcm.volume.shape[0]))
    write_state(session_id, "dicom.volume_y",     str(dcm.volume.shape[1]))
    write_state(session_id, "dicom.volume_x",     str(dcm.volume.shape[2]))
    write_state(session_id, "dicom.spacing_z",    str(dcm.spacing[0]))
    write_state(session_id, "dicom.spacing_y",    str(dcm.spacing[1]))
    write_state(session_id, "dicom.spacing_x",    str(dcm.spacing[2]))

    logger.info(
        "Segmentation complete — session=%s  verts=%d  tris=%d  vf=%.3f  url=%s",
        session_id, seg_result.n_vertices, seg_result.n_triangles, vf, url,
    )

    return SegmentResult(
        mesh_url=       url,
        voxel_fraction= vf,
        strategy=       strategy,
        is_dsa=         is_dsa,
        vertices=       seg_result.n_vertices,
        faces=          seg_result.n_triangles,
    )
