"""Vessel centerline extraction router (medial-axis between two points)."""
from __future__ import annotations

import asyncio
import logging
import time

import numpy as np
from fastapi import APIRouter, HTTPException

from models.centerline import CenterlineRequest, CenterlineResult
from services.centerline import extract_centerline
from services.segmentation import read_vtp, write_vtp
from services.sessions import mesh_url, session_exists, session_subdir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["centerline"])


def _run_extraction(vessel_path, source, target, voxel_size, out_path, points_path):
    """Synchronous heavy work — run in a worker thread."""
    vessel = read_vtp(vessel_path)
    result = extract_centerline(vessel, source, target, voxel_size_mm=voxel_size)
    write_vtp(result.poly_data, out_path)
    # Persist geometry so cross-section analysis can reuse it without recomputing.
    np.savez(
        points_path,
        points=result.points.astype(np.float32),
        radii=result.radii.astype(np.float32),
    )
    return result


@router.post(
    "/centerline/{session_id}",
    response_model=CenterlineResult,
    summary="Extract the vessel centreline between two points",
    description=(
        "Computes the medial-axis centreline of the segmented vessel between a "
        "source and a target point (voxelisation + EDT + Dijkstra on the "
        "distance-weighted grid). Returns a tube mesh of varying radius plus "
        "clinical metrics: arc length, tortuosity and vessel diameter statistics."
    ),
)
async def compute_centerline(session_id: str, req: CenterlineRequest) -> CenterlineResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    meshes_dir = session_subdir(session_id, "meshes")
    vessel_path = meshes_dir / "vessel_tree.vtp"
    if not vessel_path.exists():
        raise HTTPException(
            status_code=409,
            detail="No hay malla vascular. Ejecuta la segmentación primero.",
        )

    source = (req.source.x, req.source.y, req.source.z)
    target = (req.target.x, req.target.y, req.target.z)
    out_path    = meshes_dir / "centerline.vtp"
    points_path = meshes_dir / "centerline_points.npz"

    try:
        result = await asyncio.to_thread(
            _run_extraction, vessel_path, source, target,
            req.voxel_size_mm, out_path, points_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Centerline extraction failed")
        raise HTTPException(status_code=500, detail=f"Error en línea central: {exc}")

    url = f"{mesh_url(session_id, 'centerline.vtp')}?v={int(time.time() * 1000)}"

    tort = result.tortuosity
    warning = None
    if tort >= 1.25:
        warning = f"Tortuosidad alta ({tort:.2f}) — acceso endovascular potencialmente difícil."

    return CenterlineResult(
        centerline_mesh_url=url,
        n_points=int(len(result.points)),
        arc_length_mm=round(result.arc_length_mm, 1),
        chord_length_mm=round(result.chord_length_mm, 1),
        tortuosity=round(result.tortuosity, 3),
        tortuosity_index_pct=round(result.tortuosity_index * 100.0, 1),
        mean_diameter_mm=round(result.mean_radius_mm * 2.0, 2),
        min_diameter_mm=round(result.min_radius_mm * 2.0, 2),
        max_diameter_mm=round(result.max_radius_mm * 2.0, 2),
        warning=warning,
    )
