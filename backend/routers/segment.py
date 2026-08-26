"""Segmentation router — auto-thresholds and full VTK marching-cubes pipeline."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from models import AutoThresholdResult, SegmentRequest, SegmentResult
from models.segmentation import SuggestedBand, PreviewRequest, PreviewResult
from services              import mesh_backup
from services.sessions     import read_state, session_exists, session_subdir, write_state, mesh_url
from services.thresholds   import compute_auto_thresholds, strategy_hint
from services.dicom_loader import load_series
from services.segmentation import (
    SegmentationPipeline, write_vtp,
    voxel_fraction as seg_voxel_fraction,
    level_to_smooth_iters, level_to_cleanup_mm3,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["segmentation"])

# Thread-pool for CPU-bound DICOM + VTK work (keeps the event loop free)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="seg-worker")

# Cap the largest volume axis fed to Marching Cubes. Larger volumes are
# integer-downsampled so segmentation stays responsive (a 384³ 3DRA drops from
# ~5 min / 2.7M verts to ~30 s / 460k verts). The MPR viewer keeps the full-res
# volume — only the mesh is coarsened, mirroring the desktop's preview downsample.
_SEG_MAX_AXIS = 256

# Ceiling for full_resolution. Marching cubes holds several float32 copies of the
# volume at once, so a 1030×512×512 CT (270 M voxels, ~1.1 GB per copy) would take
# the process down. The angiographic studies this option exists for are 50–60 M.
_FULL_RES_MAX_VOXELS = 120_000_000

# Voxels sampled when deriving auto-thresholds. Percentiles are stable well
# below this, and it keeps a 1 GB CT from being read whole just to get p90/p99.
_THRESHOLD_SAMPLE = 8_000_000


def _threshold_volume(session_id: str) -> "np.ndarray | None":
    """Subsampled copy of the session volume for threshold statistics.

    Reads the .npy the MPR service caches on upload (memmap → only the sampled
    voxels are actually read). Returns None if no volume is available yet, in
    which case the caller falls back to WC/WW.
    """
    try:
        from services.mpr import _cache_paths, ensure_volume_cached, _get_volume

        npy_path, _ = _cache_paths(session_id)
        if not npy_path.exists():
            ensure_volume_cached(session_id)  # idempotent; MPR needs it anyway
        vol = _get_volume(session_id)
        flat = vol.ravel()
        if flat.size > _THRESHOLD_SAMPLE:
            stride = int(np.ceil(flat.size / _THRESHOLD_SAMPLE))
            return np.asarray(flat[::stride], dtype=np.float32)
        return np.asarray(flat, dtype=np.float32)
    except Exception as exc:  # noqa: BLE001 — thresholds must never 500
        logger.warning("Threshold volume unavailable for %s (%s); using WC/WW", session_id, exc)
        return None


def _maybe_downsample(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    max_axis: int = _SEG_MAX_AXIS,
) -> tuple[np.ndarray, tuple[float, float, float], int]:
    """Integer-downsample the volume if its largest axis exceeds *max_axis*.

    Returns (volume, spacing, factor). factor == 1 means no change.
    """
    factor = max(1, math.ceil(max(volume.shape) / max_axis))
    if factor <= 1:
        return volume, spacing, 1
    ds = np.ascontiguousarray(volume[::factor, ::factor, ::factor])
    sp = (spacing[0] * factor, spacing[1] * factor, spacing[2] * factor)
    logger.info(
        "Downsampling volume %s -> %s (factor %d) for segmentation",
        volume.shape, ds.shape, factor,
    )
    return ds, sp, factor


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
        "Thresholds are derived from the **actual voxel distribution** (which is "
        "what detects DSA subtraction, display-preset windows, etc.). The volume "
        "is read from the MPR cache and subsampled, so the call stays fast; if no "
        "volume is available yet it falls back to WindowCenter/WindowWidth.\n\n"
        "Strategies: `ct_stats`, `ct_wc_ww`, `xa_band_pass`, `xa_wc_ww`, "
        "`xa_window_mismatch`, `xa_raw16`, `dsa`, `mr_percentile`, `wc_ww`."
    ),
)
async def get_thresholds(session_id: str) -> AutoThresholdResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Read DICOM metadata persisted by upload router
    modality      = read_state(session_id, "dicom.modality",       "CT")
    window_center = _load_float(session_id, "dicom.window_center", 400.0)
    window_width  = _load_float(session_id, "dicom.window_width",  1500.0)

    # Thresholds MUST see the voxel distribution: the WC/WW header is often a
    # display preset (e.g. a DSA reading 0/1000, or a 3DRA reading 0/200) and
    # deriving the band from it alone segments background instead of vessels.
    loop = asyncio.get_event_loop()
    volume = await loop.run_in_executor(_executor, partial(_threshold_volume, session_id))

    lower, upper, strategy = compute_auto_thresholds(
        volume=volume,
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
    smooth_iters = level_to_smooth_iters(req.smoothing)
    min_mm3, top_n, closing_mm = level_to_cleanup_mm3(req.cleanup)

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
                min_mm3=      min_mm3,
                top_n=        top_n,
                closing_mm=   closing_mm,
                full_resolution= req.full_resolution,
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


# ── GET /segment/suggested-band/{session_id} ───────────────────────────────── #

@router.get(
    "/segment/suggested-band/{session_id}",
    response_model=SuggestedBand,
    summary="Adaptive starting band from the volume histogram",
    description=(
        "Starting band + a robust value range for the sliders, derived from THIS "
        "volume's own intensity distribution via the SAME modality-aware logic the "
        "segmentation uses (compute_auto_thresholds). One source of truth: the live "
        "preview reflects the real result, and non-subtracted 3DRA/CTA start on the "
        "bright vasculature (~1%) instead of a generic p94 that grabbed ~6% of tissue."
    ),
)
async def suggested_band(session_id: str) -> SuggestedBand:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    loop = asyncio.get_event_loop()
    sample = await loop.run_in_executor(_executor, partial(_threshold_volume, session_id))
    if sample is None or sample.size == 0:
        # No volume cached yet → sensible CT-HU fallback.
        return SuggestedBand(lower=150.0, upper=500.0, vmin=-500.0, vmax=1500.0)
    s = np.asarray(sample, dtype=np.float32)
    vmin = float(np.percentile(s, 0.5))
    vmax = float(np.percentile(s, 99.9))
    # Start the sliders (and the live preview) at the SAME modality-aware band
    # the segmentation actually uses — one source of truth, no drift. A flat p94
    # ignored the modality and, on non-subtracted 3DRA/CTA, captured ~6% of
    # voxels (a solid tissue+skull blob) before the user even placed a seed.
    modality      = read_state(session_id, "dicom.modality", "CT")
    window_center = _load_float(session_id, "dicom.window_center", 400.0)
    window_width  = _load_float(session_id, "dicom.window_width", 1500.0)
    try:
        lower, upper, _strategy = compute_auto_thresholds(
            volume=s, modality=modality,
            window_center=window_center, window_width=window_width,
        )
    except Exception as exc:  # noqa: BLE001 — the slider band must never 500
        logger.warning("Auto-band failed for %s (%s); using p94 fallback", session_id, exc)
        lower, upper = float(np.percentile(s, 94.0)), vmax
    # Let the slider's top reach the computed band's upper: on subtracted DSA the
    # band's upper (≈ the bright vessel max) sits ABOVE p99.9, and clamping it down
    # to p99.9 would silently narrow the band, dropping the dense vessel cores.
    vmax = max(vmax, upper)
    # Bound to the robust slider range so the handles can always reach the band.
    lower = float(np.clip(lower, vmin, vmax))
    upper = float(np.clip(upper, lower, vmax))
    if upper <= lower:
        upper = lower + max(1.0, (vmax - vmin) * 0.05)
    return SuggestedBand(
        lower=round(lower, 1), upper=round(upper, 1),
        vmin=round(vmin, 1), vmax=round(vmax, 1),
    )


# ── POST /segment/preview/{session_id} ─────────────────────────────────────── #

@router.post(
    "/segment/preview/{session_id}",
    response_model=PreviewResult,
    summary="Fast coarse-mesh preview for interactive threshold tuning",
    description=(
        "Runs a downsampled marching-cubes pass (no full smoothing/decimation) with "
        "top-N component isolation, so the clinician sees the 3D vascular tree form "
        "in near-real-time as they move the sliders — like the desktop app."
    ),
)
async def segment_preview(session_id: str, req: PreviewRequest) -> PreviewResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    meshes_dir = session_subdir(session_id, "meshes")
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            _executor, partial(_run_preview_sync, session_id, meshes_dir, req)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=409, detail="No hay volumen en la sesión. Sube un DICOM primero.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Segment preview failed")
        raise HTTPException(status_code=500, detail=f"Error en la vista previa: {exc}")
    return result


def _run_preview_sync(session_id: str, meshes_dir: Path, req: PreviewRequest) -> PreviewResult:
    """Coarse preview mesh from the cached full-res volume (downsampled)."""
    from services.mpr import _get_volume, ensure_volume_cached

    meta = ensure_volume_cached(session_id)
    volume = np.asarray(_get_volume(session_id))
    spacing = tuple(float(s) for s in meta["spacing"])  # (sz, sy, sx)

    # The preview must filter exactly like the real run, or the mesh the user
    # tunes the sliders against is not the mesh they get.
    min_mm3, top_n, _closing = level_to_cleanup_mm3(req.cleanup)
    pipeline = SegmentationPipeline(
        threshold_hu=req.lower,
        threshold_max_hu=req.upper if req.upper > req.lower else 0.0,
        min_component_mm3=min_mm3,
        keep_top_n=top_n,
        min_component_verts=0,
    )
    seg = pipeline.run_fast_preview(volume, spacing, downsample=req.downsample)

    vtp_path = meshes_dir / "preview_mesh.vtp"
    write_vtp(seg.poly_data, vtp_path)
    vf = seg_voxel_fraction(volume, req.lower, req.upper)
    url = f"{mesh_url(session_id, 'preview_mesh.vtp')}?v={int(time.time() * 1000)}"
    return PreviewResult(mesh_url=url, vertices=seg.n_vertices, voxel_fraction=round(float(vf), 6))


# ── Synchronous worker (runs in thread-pool) ───────────────────────────────── #

def _run_segmentation_sync(
    session_id:    str,
    series_id:     str,
    dicom_dir:     Path,
    meshes_dir:    Path,
    lower:         float,
    upper:         float,
    smooth_iters:  int,
    min_mm3:       float,
    top_n:         int,
    closing_mm:    float,
    full_resolution: bool = False,
) -> SegmentResult:
    """Load DICOM → run VTK pipeline → write .vtp → update session state.

    Runs in a thread-pool worker to avoid blocking the asyncio event loop.
    """
    # ── Load DICOM volume ──────────────────────────────────────────────────── #
    logger.info(
        "Loading DICOM series '%s' for session '%s' ...", series_id, session_id
    )
    dcm = load_series(series_id, dicom_dir)

    # ── Guard: reject non-volumetric series with an actionable message ─────── #
    # Localizers, scouts and 2D projections have one (or two) slices; marching
    # cubes yields an empty surface and the old "lower the threshold" hint was
    # misleading — the real problem is that there is no 3D volume to segment.
    if dcm.volume.ndim != 3 or min(dcm.volume.shape) < 3:
        raise ValueError(
            f"La serie tiene forma {tuple(dcm.volume.shape)}: es un localizador o "
            "proyección 2D, no un volumen 3D, y no puede segmentarse en una malla "
            "vascular. Selecciona la serie principal del estudio (la de mayor número "
            "de cortes)."
        )

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
    # Cleanup discards connected components below a physical volume. See
    # _CLEANUP_MM3 for why this replaced "keep the N largest".
    pipeline = SegmentationPipeline(
        threshold_hu=        lower,
        threshold_max_hu=    upper if upper > lower else 0.0,
        smooth_iterations=   smooth_iters,
        smooth_pass_band=    0.06,
        target_reduction=    0.70,
        gaussian_sigma=      0.5,
        morpho_closing_mm=   closing_mm,
        min_component_mm3=   min_mm3,
        keep_top_n=          top_n,
        # One of min_component_mm3 / keep_top_n is active per level; the pipeline
        # default of 100 vertices must not filter on top of them (nor at level 0).
        min_component_verts= 0,
    )

    # ── Downsample very large volumes so segmentation stays responsive ────── #
    # full_resolution keeps every voxel: thin vessels stay above threshold and
    # the tree comes out in far fewer pieces, at the cost of minutes.
    if full_resolution:
        n_voxels = int(np.prod(dcm.volume.shape))
        if n_voxels > _FULL_RES_MAX_VOXELS:
            raise ValueError(
                f"Este volumen tiene {n_voxels / 1e6:.0f} millones de vóxeles; a "
                f"resolución completa la segmentación agotaría la memoria del "
                f"servidor (el límite son {_FULL_RES_MAX_VOXELS / 1e6:.0f} millones). "
                f"Segmenta sin esa opción, o recorta el volumen antes."
            )
        seg_volume = np.ascontiguousarray(dcm.volume, dtype=np.float32)
        seg_spacing, ds_factor = tuple(dcm.spacing), 1
    else:
        seg_volume, seg_spacing, ds_factor = _maybe_downsample(dcm.volume, dcm.spacing)

    # ── Run marching cubes ────────────────────────────────────────────────── #
    logger.info(
        "Running marching cubes: lower=%.0f upper=%.0f smooth=%d min_mm3=%.1f top_n=%d shape=%s (ds=%d)",
        lower, upper, smooth_iters, min_mm3, top_n, seg_volume.shape, ds_factor,
    )
    seg_result = pipeline.run(seg_volume, seg_spacing)

    # ── Write VTP mesh ────────────────────────────────────────────────────── #
    vtp_name = "vessel_tree.vtp"
    vtp_path = meshes_dir / vtp_name
    # Re-segmenting used to wipe the history, so twenty minutes of cropping and
    # growing vanished the moment someone tried another threshold band. It is an
    # edit like any other: snapshot first, and it can be undone.
    mesh_backup.snapshot(session_id, "segment")
    write_vtp(seg_result.poly_data, vtp_path)

    url = mesh_url(session_id, vtp_name)
    # The .vtp filename is reused on every re-segmentation, so append a
    # generation token to the URL returned to the client — otherwise the
    # browser/vtk.js serves the previous mesh from cache (304 Not Modified).
    url_versioned = f"{url}?v={int(time.time() * 1000)}"

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
        mesh_url=       url_versioned,
        voxel_fraction= vf,
        strategy=       strategy,
        is_dsa=         is_dsa,
        vertices=       seg_result.n_vertices,
        faces=          seg_result.n_triangles,
        downsample_factor=   ds_factor,
        kept_fraction=       seg_result.kept_fraction,
        fragments_removed=   seg_result.n_fragments_removed,
        largest_removed_mm3= round(seg_result.largest_removed_mm3, 1),
    )
