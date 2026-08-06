"""3D-print preparation router (Feature 7): prepare the vessel mesh and export
a print-ready STL, with printer-bed fit checks."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from models.print_prep import PrintBed, PrintPrepRequest, PrintPrepResult
from services.mesh_prep import PRINT_BED_PRESETS, prepare_mesh_for_print
from services.segmentation import read_vtp
from services.sessions import session_exists, session_subdir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["print-prep"])


@router.get(
    "/print-prep/beds",
    response_model=list[PrintBed],
    summary="List 3D-printer bed presets",
)
async def list_beds() -> list[PrintBed]:
    return [PrintBed(name=n, x_mm=b[0], y_mm=b[1], z_mm=b[2]) for n, b in PRINT_BED_PRESETS.items()]


def _run_prep(vessel_path: Path, out_path: Path, req: PrintPrepRequest) -> PrintPrepResult:
    mesh = read_vtp(vessel_path)
    if mesh is None or mesh.GetNumberOfPoints() == 0:
        raise ValueError("La malla vascular está vacía.")
    result = prepare_mesh_for_print(
        mesh,
        target_size_mm=req.target_size_mm,
        smooth_iterations=req.smooth_iterations,
        smooth_relaxation=req.smooth_relaxation,
        fill_holes=req.fill_holes,
        hole_size=req.hole_size,
        subdivide=req.subdivide,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.export_stl(out_path)
    fits = result.fits_in_bed((req.bed_x_mm, req.bed_y_mm, req.bed_z_mm))
    return PrintPrepResult(
        stl_url="",  # filled by the caller (needs the session id)
        scale_factor=result.scale_factor,
        dimensions_mm=list(result.dimensions_mm),
        volume_cm3=result.volume_cm3,
        surface_area_cm2=result.surface_area_cm2,
        is_watertight=result.is_watertight,
        open_edge_count=result.open_edge_count,
        fits_in_bed=fits,
        warnings=list(result.warnings),
    )


@router.post(
    "/print-prep/{session_id}",
    response_model=PrintPrepResult,
    summary="Prepare the vessel mesh for 3D printing",
    description=(
        "Fill holes → smooth → optional subdivision → scale to a target size, then "
        "report physical dimensions, solid volume, watertightness (open-edge count) "
        "and whether it fits the requested printer bed. Writes a print-ready STL. "
        "Requires that segmentation produced `vessel_tree.vtp`."
    ),
)
async def print_prep(session_id: str, req: PrintPrepRequest) -> PrintPrepResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    vessel_path = session_subdir(session_id, "meshes") / "vessel_tree.vtp"
    if not vessel_path.exists():
        raise HTTPException(status_code=409, detail="No hay malla vascular. Ejecuta la segmentación primero.")

    out_path = session_subdir(session_id, "exports") / f"{session_id}_print.stl"
    try:
        result = await asyncio.to_thread(_run_prep, vessel_path, out_path, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Print-prep failed")
        raise HTTPException(status_code=500, detail=f"Error en la preparación de impresión: {exc}")

    result.stl_url = f"/data/sessions/{session_id}/exports/{session_id}_print.stl"
    return result
