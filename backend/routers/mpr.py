"""MPR router — serve DICOM slices (axial/coronal/sagital) as PNG for the viewer."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from services.mpr import (
    ensure_volume_cached, render_slice_png, render_oblique_png, get_volume_raw_uint8,
)
from services.sessions import session_exists

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mpr"])

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mpr-worker")
_PLANES = {"axial", "coronal", "sagital"}


@router.get(
    "/volume/{session_id}/meta",
    summary="Get DICOM volume metadata for MPR",
    description=(
        "Loads (and caches) the primary DICOM series volume and returns its shape, "
        "spacing and default window/level so the frontend can set up the MPR sliders. "
        "First call triggers the volume load; subsequent calls are instant."
    ),
)
async def volume_meta(session_id: str) -> dict:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    loop = asyncio.get_event_loop()
    try:
        meta = await loop.run_in_executor(_executor, partial(ensure_volume_cached, session_id))
    except Exception as exc:
        logger.error("Volume meta failed for %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"No se pudo cargar el volumen: {exc}") from exc
    return meta


@router.get(
    "/volume/{session_id}/raw",
    summary="Get the downsampled volume as raw uint8 for 3D volume rendering",
    description=(
        "Returns the DICOM volume as raw uint8 bytes (C-order, z·y·x), downsampled "
        "so the largest axis is ≤ 192 and rescaled over a robust intensity window. "
        "Dimensions and spacing are returned in the X-Dims / X-Spacing headers. "
        "Consumed by the client-side vtk.js volume renderer."
    ),
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_volume_raw(session_id: str) -> Response:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    loop = asyncio.get_event_loop()
    try:
        data, dims, spacing = await loop.run_in_executor(
            _executor, partial(get_volume_raw_uint8, session_id)
        )
    except Exception as exc:
        logger.error("Volume raw failed for %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"No se pudo cargar el volumen: {exc}") from exc
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "X-Dims": ",".join(str(d) for d in dims),
            "X-Spacing": ",".join(f"{s:.5f}" for s in spacing),
            "Access-Control-Expose-Headers": "X-Dims, X-Spacing",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get(
    "/slice-oblique/{session_id}",
    summary="Get an oblique (tilted) MPR slice as PNG",
    description=(
        "Resamples an oblique plane through the volume centre, tilted by `tilt` "
        "degrees around the x- or y-axis, scanned along its normal by `pos` (0–1)."
    ),
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_oblique_slice(
    session_id: str,
    tilt: float = Query(0.0, ge=-80.0, le=80.0, description="Tilt angle in degrees"),
    pos: float = Query(0.5, ge=0.0, le=1.0, description="Position along the normal (0–1)"),
    axis: str = Query("x", description="Tilt axis: 'x' or 'y'"),
    wc: float | None = Query(None),
    ww: float | None = Query(None),
) -> Response:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    loop = asyncio.get_event_loop()
    try:
        png = await loop.run_in_executor(
            _executor, partial(render_oblique_png, session_id, tilt, pos, axis, wc, ww)
        )
    except Exception as exc:
        logger.error("Oblique slice failed %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"No se pudo generar el corte oblicuo: {exc}") from exc
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=600"})


@router.get(
    "/slice/{session_id}/{plane}/{index}",
    summary="Get a single MPR slice as PNG",
    description=(
        "Returns a grayscale PNG of the requested plane and slice index, with the "
        "given window center/width applied. Planes: axial · coronal · sagital."
    ),
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_slice(
    session_id: str,
    plane: str,
    index: int,
    wc: float | None = Query(None, description="Window center (defaults to volume WC)"),
    ww: float | None = Query(None, description="Window width (defaults to volume WW)"),
) -> Response:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if plane not in _PLANES:
        raise HTTPException(status_code=422, detail=f"plane debe ser uno de {sorted(_PLANES)}")

    loop = asyncio.get_event_loop()
    try:
        png = await loop.run_in_executor(
            _executor,
            partial(render_slice_png, session_id, plane, index, wc, ww),
        )
    except Exception as exc:
        logger.error("Slice render failed %s/%s/%s: %s", session_id, plane, index, exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"No se pudo generar el corte: {exc}") from exc

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
