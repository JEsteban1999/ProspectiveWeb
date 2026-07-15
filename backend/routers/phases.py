"""PHASES score router — 5-year rupture risk of an unruptured aneurysm."""
from __future__ import annotations

from fastapi import APIRouter

from models.phases import PhasesRequest, PhasesResult
from services.phases import compute_phases

router = APIRouter(prefix="/api", tags=["phases"])


@router.post(
    "/phases",
    response_model=PhasesResult,
    summary="Compute the PHASES score",
    description=(
        "Computes the PHASES 5-year rupture-risk score for an unruptured aneurysm "
        "(Greving et al., Lancet Neurology 2014) from six factors: Population, "
        "Hypertension, Age, Size, Earlier SAH and Site. The Size factor is usually "
        "filled from the morphometric analysis."
    ),
)
async def phases(req: PhasesRequest) -> PhasesResult:
    return compute_phases(req)
