"""Coil embolization router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from models import CoilLibraryItem, CoilPlanRequest, CoilPlanResult
from services.coils    import catalogue_to_api, coils_for_aneurysm, estimate_coil_count, COIL_CATALOGUE
from services.sessions import read_state, session_exists

router = APIRouter(prefix="/api", tags=["coils"])


def _load_float(session_id: str, key: str, default: float) -> float:
    try:
        raw = read_state(session_id, key, "")
        return float(raw) if raw else default
    except (ValueError, Exception):
        return default


@router.get(
    "/coils",
    response_model=list[CoilLibraryItem],
    summary="Get coil device library",
    description=(
        "Returns the full endovascular coil library (40+ models: Stryker Target 360°, "
        "Penumbra Ruby, MicroVention HydroCoil, Medtronic Axium). Each entry includes "
        "diameter, length, coil type (framing/filling/finishing) and required microwire."
    ),
)
async def get_coil_library() -> list[CoilLibraryItem]:
    return [CoilLibraryItem(**item) for item in catalogue_to_api()]


@router.post(
    "/coils/plan",
    response_model=CoilPlanResult,
    summary="Compute coil embolization plan",
    description=(
        "Accepts a list of coil placements and estimates the resulting packing density "
        "based on coil wire volumes and the aneurysm sac volume (from session morphometry). "
        "Returns packing density and estimated angiographic occlusion grade.\n\n"
        "Target: ≥ 20% packing density for durable occlusion (Sluzewski AJNR 2004)."
    ),
)
async def plan_coils(req: CoilPlanRequest) -> CoilPlanResult:
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    # Load aneurysm volume from session morphometry (written after morpho computation)
    aneurysm_vol = _load_float(req.session_id, "morpho.volume_mm3", 0.0)

    if aneurysm_vol > 0 and req.placements:
        # Compute actual packing density from coil wire volumes
        # Match placed coil IDs back to catalogue entries for wire_volume_mm3
        from services.coils import _slug
        id_to_spec = {_slug(c.name): c for c in COIL_CATALOGUE}

        total_wire_vol = 0.0
        for placement in req.placements:
            spec = id_to_spec.get(placement.coil_id)
            if spec:
                total_wire_vol += spec.wire_volume_mm3

        packing = total_wire_vol / aneurysm_vol if aneurysm_vol > 0 else 0.0
        packing = min(packing, 0.55)   # physical upper limit ~55% (platinum packing)
    else:
        # Fallback when morpho is not yet available: estimate 8% per coil
        n        = max(len(req.placements), 0)
        packing  = min(0.08 * n, 0.45)

    # Occlusion estimate: packing → Raymond grade proxy
    # 0.25+ packing ≈ 95%+ occlusion (Raymond I, complete)
    occlusion_pct = min(float(packing) * 380.0, 100.0)

    return CoilPlanResult(
        coils_mesh_url="/static/sample-meshes/coils_placed.vtp",
        total_packing_density=round(packing, 3),
        estimated_occlusion_pct=round(occlusion_pct, 1),
        warning=(
            f"Densidad de empaquetamiento {packing*100:.0f}% < 20% — añadir más coils "
            "para lograr oclusión durable (objetivo ≥ 25%)"
            if packing < 0.20 and len(req.placements) > 0 else None
        ),
    )
