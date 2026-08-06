"""Vessel centerline extraction router (medial-axis between two points)."""
from __future__ import annotations

import asyncio
import logging
import time

import numpy as np
from fastapi import APIRouter, HTTPException

from models.centerline import (
    CenterlineRequest, CenterlineResult, CrossSectionRequest, CrossSectionResult,
    ClStentRequest, ClStentResult,
)
from services.centerline import extract_centerline
from services.cross_section import compute_cross_sections
from services.stent_deployment import deploy_stent_on_centerline
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


def _run_cross_section(vessel_path, points_path, n_samples):
    vessel = read_vtp(vessel_path)
    data = np.load(points_path)
    return compute_cross_sections(data["points"], vessel, n_samples)


@router.post(
    "/cross-section/{session_id}",
    response_model=CrossSectionResult,
    summary="Analyse vessel cross-sections along the centreline",
    description=(
        "Cuts the vessel with planes perpendicular to the extracted centreline "
        "and measures the cross-sectional area (shoelace) at each, yielding a "
        "diameter profile and a stenosis estimate. Requires that the centreline "
        "was extracted first (POST /api/centerline/{session_id})."
    ),
)
async def compute_cross_section(session_id: str, req: CrossSectionRequest) -> CrossSectionResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    meshes_dir = session_subdir(session_id, "meshes")
    vessel_path = meshes_dir / "vessel_tree.vtp"
    points_path = meshes_dir / "centerline_points.npz"
    if not vessel_path.exists():
        raise HTTPException(status_code=409, detail="No hay malla vascular. Ejecuta la segmentación primero.")
    if not points_path.exists():
        raise HTTPException(status_code=409, detail="Extrae la línea central primero.")

    try:
        result = await asyncio.to_thread(
            _run_cross_section, vessel_path, points_path, req.n_samples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cross-section analysis failed")
        raise HTTPException(status_code=500, detail=f"Error en sección transversal: {exc}")

    pct = (1.0 - result.stenosis_ratio) * 100.0
    if pct < 20:
        label = "Sin estenosis"
    elif pct < 50:
        label = "Leve"
    else:
        label = "Significativa"
    warning = None
    if pct >= 50:
        warning = f"Estenosis significativa (~{pct:.0f}%) en el punto más estrecho."

    return CrossSectionResult(
        arc_positions_mm=[round(float(a), 2) for a in result.arc_positions_mm],
        diameters_mm=[round(float(d), 3) for d in result.diameters_mm],
        mean_diameter_mm=round(result.mean_diameter_mm, 2),
        median_diameter_mm=round(result.median_diameter_mm, 2),
        min_diameter_mm=round(result.min_diameter_mm, 2),
        max_diameter_mm=round(result.max_diameter_mm, 2),
        mean_area_mm2=round(result.mean_area_mm2, 2),
        stenosis_ratio=round(result.stenosis_ratio, 3),
        stenosis_pct=round(pct, 1),
        stenosis_label=label,
        warning=warning,
    )


def _run_cl_stent(points_path, req: ClStentRequest, out_path):
    data = np.load(points_path)
    result = deploy_stent_on_centerline(
        data["points"], data["radii"],
        stent_diameter_mm=req.stent_diameter_mm,
        start_arc_mm=req.start_arc_mm,
        end_arc_mm=req.end_arc_mm,
        braid=req.braid,
        braid_count=req.braid_count,
    )
    write_vtp(result.stent_poly_data, out_path)
    return result


@router.post(
    "/cl-stent/{session_id}",
    response_model=ClStentResult,
    summary="Deploy a stent along the vessel centreline",
    description=(
        "Sweeps a stent tube along the previously-extracted centreline between two "
        "arc-length positions (parallel-transport frames + optional helical braids), "
        "following the true vessel curvature — unlike the straight neck stent. "
        "Requires that the centreline was extracted first "
        "(POST /api/centerline/{session_id})."
    ),
)
async def deploy_cl_stent(session_id: str, req: ClStentRequest) -> ClStentResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    meshes_dir = session_subdir(session_id, "meshes")
    points_path = meshes_dir / "centerline_points.npz"
    if not points_path.exists():
        raise HTTPException(status_code=409, detail="Extrae la línea central primero.")

    out_path = meshes_dir / "cl_stent.vtp"
    try:
        result = await asyncio.to_thread(_run_cl_stent, points_path, req, out_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Centreline stent deployment failed")
        raise HTTPException(status_code=500, detail=f"Error desplegando el stent: {exc}")

    cov = result.coverage_ratio
    warning = None
    if cov < 0.9:
        warning = f"Stent infradimensionado (cobertura {cov:.2f}) — considera un diámetro mayor."
    elif cov > 1.15:
        warning = f"Stent sobredimensionado (cobertura {cov:.2f}) — riesgo de sobreexpansión."

    url = f"{mesh_url(session_id, 'cl_stent.vtp')}?v={int(time.time() * 1000)}"
    return ClStentResult(
        stent_mesh_url=url,
        length_mm=round(result.length_mm, 1),
        nominal_diameter_mm=round(result.nominal_diameter_mm, 2),
        mean_vessel_diameter_mm=round(result.mean_vessel_diameter_mm, 2),
        coverage_ratio=round(result.coverage_ratio, 2),
        total_arc_mm=round(result.total_arc_mm, 1),
        warning=warning,
    )
