"""PHASES score router — 5-year rupture risk of an unruptured aneurysm."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from models.phases import PhasesRequest, PhasesResult
from services.phases import compute_phases
from services.sessions import session_exists, write_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["phases"])


@router.post(
    "/phases",
    response_model=PhasesResult,
    summary="Compute the PHASES score",
    description=(
        "Computes the PHASES 5-year rupture-risk score for an unruptured aneurysm "
        "(Greving et al., Lancet Neurology 2014) from six factors: Population, "
        "Hypertension, Age, Size, Earlier SAH and Site. The Size factor is usually "
        "filled from the morphometric analysis.\n\n"
        "Pass `session_id` to record the score in the planning session — that is "
        "what makes it appear in the PDF report and the DICOM SR."
    ),
)
async def phases(req: PhasesRequest) -> PhasesResult:
    result = compute_phases(req)

    if req.session_id:
        if not session_exists(req.session_id):
            raise HTTPException(
                status_code=404, detail=f"Session '{req.session_id}' not found"
            )
        # Store the inputs alongside the score: the size auto-fills from the
        # morphometry, so a later re-measurement would otherwise leave a number
        # in the report that nothing on file explains.
        write_state(req.session_id, "phases.json", json.dumps({
            "total_score":  result.total_score,
            "risk_5yr_pct": result.risk_5yr_pct,
            "risk_band":    result.risk_band,
            "points": {
                "population":   result.population_pts,
                "hypertension": result.hypertension_pts,
                "age":          result.age_pts,
                "size":         result.size_pts,
                "sah":          result.sah_pts,
                "site":         result.site_pts,
            },
            "inputs": {
                "population":   req.population,
                "hypertension": req.hypertension,
                "age_years":    req.age_years,
                "size_mm":      req.size_mm,
                "earlier_sah":  req.earlier_sah,
                "site":         req.site,
            },
        }))
        logger.info("PHASES recorded for %s — score=%d (%.1f%%)",
                    req.session_id, result.total_score, result.risk_5yr_pct)

    return result
