"""Clearing placed devices (clips / coils / stents).

The planners write both a mesh the 3D viewer draws and a session-state record
the PDF report and the DICOM SR read back. Until this router existed there was
no way to take a device off again: trying a second clip left the first one in
the report, and switching from a clip to a stent produced a plan describing
both. Removing a device therefore has to delete the mesh AND the state record —
either one left behind is a plan that disagrees with itself.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query

from models.plan import DeviceClearResult
from services.device_state import DEVICE_KINDS, clear_device, read_clips, read_coils, read_stent
from services.sessions import mesh_url, session_exists, session_subdir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["devices"])


def _placed(session_id: str) -> list[str]:
    """Which device kinds currently hold a plan for this session."""
    out: list[str] = []
    if read_clips(session_id):
        out.append("clips")
    if read_coils(session_id):
        out.append("coils")
    if read_stent(session_id):
        out.append("stent")
    return out


def _mesh_urls(session_id: str, kinds: list[str]) -> dict[str, str]:
    """Cache-busted URL of each still-placed family's mesh, when the file exists."""
    meshes_dir = session_subdir(session_id, "meshes")
    stamp = int(time.time() * 1000)
    urls: dict[str, str] = {}
    for kind in kinds:
        for name in DEVICE_KINDS[kind][1]:
            if (meshes_dir / name).exists():
                urls[kind] = f"{mesh_url(session_id, name)}?v={stamp}"
                break
    return urls


@router.get(
    "/devices/{session_id}",
    response_model=DeviceClearResult,
    summary="Which devices are currently placed",
    description=(
        "Lists the device kinds with a saved plan in this session. The devices "
        "panel uses it to enable its «Limpiar» actions after a session is resumed, "
        "when the browser has no memory of what was placed."
    ),
)
async def list_placed_devices(session_id: str) -> DeviceClearResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    remaining = _placed(session_id)
    return DeviceClearResult(
        cleared=[], remaining=remaining, meshes_removed=0,
        mesh_urls=_mesh_urls(session_id, remaining),
    )


@router.delete(
    "/devices/{session_id}",
    response_model=DeviceClearResult,
    summary="Remove placed devices from the plan",
    description=(
        "Deletes the placed device meshes and the state records that feed the PDF "
        "report and the DICOM SR, so another device can be planned on a clean "
        "scene. `kind` clears one family (`clips`, `coils` or `stent` — the latter "
        "covers both the straight catalogue stent and the centreline-guided one); "
        "omit it to clear every device.\n\n"
        "Idempotent: clearing a device that was never placed succeeds and reports "
        "nothing removed."
    ),
)
async def clear_devices_endpoint(
    session_id: str,
    kind: str | None = Query(
        None,
        description="Device family to clear: 'clips', 'coils' or 'stent'. Omit for all.",
    ),
) -> DeviceClearResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if kind is not None and kind not in DEVICE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo de dispositivo desconocido: '{kind}'. Usa {sorted(DEVICE_KINDS)}.",
        )

    kinds = [kind] if kind else list(DEVICE_KINDS)
    meshes_dir = session_subdir(session_id, "meshes")
    removed = 0

    for k in kinds:
        clear_device(session_id, k)
        for name in DEVICE_KINDS[k][1]:
            path = meshes_dir / name
            if path.exists():
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:  # noqa: BLE001 — state is already cleared
                    logger.warning("Could not delete %s for %s: %s", name, session_id, exc)

    logger.info("Cleared devices %s for session=%s (%d mesh file(s))", kinds, session_id, removed)
    remaining = _placed(session_id)
    return DeviceClearResult(
        cleared=kinds, remaining=remaining, meshes_removed=removed,
        mesh_urls=_mesh_urls(session_id, remaining),
    )
