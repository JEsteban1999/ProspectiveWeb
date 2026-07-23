"""Upload router — receives DICOM files, creates a session, extracts series metadata."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.formparsers import MultiPartException

from models import SeriesInfo, SpacingXYZ, UploadResult
from services.sessions     import create_session, session_subdir, write_state
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

    # ── 5. Write primary series metadata to session state ─────────────────── #
    # Use the first (or only) series as the "active" series.
    # Downstream routers read these keys from session state.
    primary = series_list[0]
    write_state(session_id, "dicom.series_id",     primary.series_id)
    write_state(session_id, "dicom.modality",      primary.modality)
    write_state(session_id, "dicom.window_center", str(primary.window_center))
    write_state(session_id, "dicom.window_width",  str(primary.window_width))
    write_state(session_id, "dicom.spacing_x",     str(primary.spacing.x))
    write_state(session_id, "dicom.spacing_y",     str(primary.spacing.y))
    write_state(session_id, "dicom.spacing_z",     str(primary.spacing.z))
    write_state(session_id, "dicom.n_slices",      str(primary.slices))
    write_state(session_id, "dicom.is_projection", "1" if primary.is_projection else "0")

    logger.info(
        "Upload complete — session=%s  series=%d  primary=%s (%s)  %d slices",
        session_id, len(series_list), primary.series_id[:12], primary.modality, primary.slices,
    )

    return UploadResult(
        session_id=session_id,
        series=series_list,
        total_files=len(saved),
    )
