"""Upload router — receives DICOM files, creates a session, extracts series metadata."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.formparsers import MultiPartException

from models import SeriesInfo, SpacingXYZ, UploadResult
from services.sessions     import create_session, session_exists, session_subdir, write_state
from services.dicom_loader import scan_series

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])

# Maximum allowed upload size per file (MB) — prevents OOM on tiny servers
_MAX_FILE_MB = 500
_MAX_FILE_BYTES = _MAX_FILE_MB * 1_000_000

# A single fine-slice CTA can exceed Starlette's default 1000-file limit, and a
# multi-series study more so. Raise the cap to a value that covers any realistic
# study while still bounding the request. Each file is spooled to disk, so this
# does not grow in-memory usage linearly with file count.
_MAX_FILES = 20_000


@router.post(
    "/upload",
    response_model=UploadResult,
    summary="Upload DICOM files",
    description=(
        "Accepts one or more DICOM files (multipart/form-data). "
        "Creates a new processing session, saves files to disk, and returns "
        "session_id and the metadata of every DICOM series detected.\n\n"
        "Send as `Content-Type: multipart/form-data` with field name `files`."
    ),
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            }
                        },
                        "required": ["files"],
                    }
                }
            }
        }
    },
)
async def upload_dicom(request: Request) -> UploadResult:
    # Parse the multipart form ourselves so we can raise the max-files cap above
    # Starlette's 1000 default (FastAPI's File(...) injection would parse with the
    # default *before* this function runs, rejecting large studies).
    try:
        form = await request.form(max_files=_MAX_FILES, max_fields=_MAX_FILES)
    except MultiPartException as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    files = [v for v in form.getlist("files") if isinstance(v, StarletteUploadFile)]
    if not files:
        raise HTTPException(status_code=422, detail="No files provided")

    # ── 1. Create isolated session directory ──────────────────────────────── #
    session_id = create_session()
    dicom_dir  = session_subdir(session_id, "dicom")

    logger.info("Upload started — session=%s  files=%d", session_id, len(files))

    # ── 2. Save uploaded bytes to disk ────────────────────────────────────── #
    saved: list[Path] = []
    for uf in files:
        # Use the original filename; sanitise it to avoid path traversal
        safe_name = Path(uf.filename or "unnamed.dcm").name
        dest = dicom_dir / safe_name

        # If two files share a name, append a counter
        idx = 0
        while dest.exists():
            idx += 1
            dest = dicom_dir / f"{dest.stem}_{idx}{dest.suffix}"

        try:
            content = await uf.read()
            if len(content) > _MAX_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{uf.filename}' exceeds {_MAX_FILE_MB} MB limit",
                )
            dest.write_bytes(content)
            saved.append(dest)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to save %s: %s", uf.filename, exc)
            raise HTTPException(
                status_code=500,
                detail=f"Could not save file '{uf.filename}': {exc}",
            ) from exc

    logger.info("Saved %d files to %s", len(saved), dicom_dir)

    # ── 3. Scan for DICOM series ──────────────────────────────────────────── #
    try:
        raw_series = scan_series(dicom_dir)
    except Exception as exc:
        logger.error("Series scan failed: %s", exc)
        raw_series = []

    if not raw_series:
        # No DICOM data found — still return the session so the user knows something happened
        logger.warning("No DICOM series detected in uploaded files")
        return UploadResult(
            session_id=session_id,
            series=[],
            total_files=len(saved),
        )

    # ── 4. Build SeriesInfo objects ───────────────────────────────────────── #
    series_list = _build_series_list(session_id, raw_series)

    # ── 5. Write primary series metadata to session state ─────────────────── #
    primary = series_list[0]
    _activate_series(session_id, primary)

    logger.info(
        "Upload complete — session %s: %d files, %d series, primary=%s (%d slices)",
        session_id, len(saved), len(series_list), primary.description, primary.slices,
    )
    return UploadResult(
        session_id=session_id,
        series=series_list,
        total_files=len(saved),
    )


def _build_series_list(session_id: str, raw_series: list[dict]) -> list[SeriesInfo]:
    """Map raw scan dicts → SeriesInfo, ranked best-3D-volume first."""
    series_list: list[SeriesInfo] = []
    for raw in raw_series:
        uid   = raw.get("series_uid", "unknown")
        sx    = float(raw.get("spacing_x", 1.0))
        sy    = float(raw.get("spacing_y", 1.0))
        sz    = float(raw.get("spacing_z", 1.0))
        nsl   = int(raw.get("n_slices", raw.get("n_files", 1)))
        wc    = float(raw.get("window_center", 40.0))
        ww    = float(raw.get("window_width", 400.0))
        mod   = str(raw.get("modality", "CT")).upper()
        desc  = str(raw.get("series_description", "")).strip() or f"Serie {uid[:8]}"

        in_plane  = min(sx, sy)
        is_proj   = nsl < 10 or (sz > 4.0 * in_plane and in_plane > 0)
        proj_warn = None
        if is_proj:
            proj_warn = (
                f"Serie 2D o cuasi-2D ({nsl} cortes)." if nsl < 10 else
                f"Espaciado Z ({sz:.2f} mm) >> en plano ({in_plane:.2f} mm) — probable proyección 2D."
            )

        # Estimate volume RAM in MB (float32 = 4 bytes/voxel)
        size_mb = round(nsl * 512 * 512 * 4 / 1e6, 1)   # conservative 512² estimate

        info = SeriesInfo(
            session_id=        session_id,
            series_id=         uid,
            description=       desc,
            modality=          mod,
            slices=            nsl,
            spacing=           SpacingXYZ(x=sx, y=sy, z=sz),
            window_center=     wc,
            window_width=      ww,
            is_projection=     is_proj,
            projection_warning=proj_warn,
            size_mb=           size_mb,
        )
        series_list.append(info)

    # Rank the series so the ACTIVE one is the best candidate for 3-D work: a
    # real volume first (never a localiser/projection), then the one with most
    # slices. A study can carry a dozen series (localisers, 2-D cines, several
    # 3-D acquisitions) and the scan order is arbitrary, so taking series[0]
    # blindly could hand the pipeline a 2-slice scout.
    series_list.sort(key=lambda s: (s.is_projection, -s.slices))
    return series_list


def _activate_series(session_id: str, s: SeriesInfo) -> None:
    """Make `s` the session's active series (downstream routers read this state)."""
    write_state(session_id, "dicom.series_id",     s.series_id)
    # Persisted so a resumed session can rebuild the series card verbatim.
    write_state(session_id, "dicom.description",   s.description)
    write_state(session_id, "dicom.modality",      s.modality)
    write_state(session_id, "dicom.window_center", str(s.window_center))
    write_state(session_id, "dicom.window_width",  str(s.window_width))
    write_state(session_id, "dicom.spacing_x",     str(s.spacing.x))
    write_state(session_id, "dicom.spacing_y",     str(s.spacing.y))
    write_state(session_id, "dicom.spacing_z",     str(s.spacing.z))
    write_state(session_id, "dicom.n_slices",      str(s.slices))
    write_state(session_id, "dicom.is_projection", "1" if s.is_projection else "0")


@router.post(
    "/upload/{session_id}/series/{series_id}",
    response_model=SeriesInfo,
    summary="Switch the session's active DICOM series",
    description=(
        "A study often carries several series (localisers, 2-D cines and more "
        "than one 3-D acquisition). Upload activates the best 3-D volume, but the "
        "clinician may want a different acquisition. This re-points the session at "
        "`series_id` and drops the cached volume so MPR/segmentation reload it.\n\n"
        "Everything derived from the previous series (mesh, detection, morphometry) "
        "becomes stale — the client must reset those steps."
    ),
)
async def set_active_series(session_id: str, series_id: str) -> SeriesInfo:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    dicom_dir = session_subdir(session_id, "dicom")
    try:
        raw_series = scan_series(dicom_dir)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"No se pudieron leer las series: {exc}")

    series_list = _build_series_list(session_id, raw_series)
    chosen = next((s for s in series_list if s.series_id == series_id), None)
    if chosen is None:
        raise HTTPException(
            status_code=404,
            detail=f"La serie '{series_id}' no existe en esta sesión.",
        )

    _activate_series(session_id, chosen)

    # Drop the cached volume (it belongs to the previous series). The memmap
    # keeps the file open on Windows, so clear the caches and collect first.
    import gc
    from services.mpr import _cache_paths, _load_memmap, _downsampled_volume
    _load_memmap.cache_clear()
    _downsampled_volume.cache_clear()
    gc.collect()
    npy_path, meta_path = _cache_paths(session_id)
    for p in (npy_path, meta_path):
        try:
            if p.exists():
                p.unlink()
        except OSError as exc:
            logger.warning("Could not drop cached volume %s: %s", p, exc)

    logger.info(
        "Active series switched — session=%s  series=%s (%s)  %d slices",
        session_id, chosen.series_id[:12], chosen.modality, chosen.slices,
    )
    return chosen
