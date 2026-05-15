"""Treatment decision router — CLIP vs ENDOVASCULAR."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import json

from models import TreatmentDecisionRequest, TreatmentDecisionResult, DecisionFactor
from services.treatment import compute_decision
from services.sessions  import read_state, write_state, session_exists

router = APIRouter(prefix="/api", tags=["treatment"])


def _load_float(session_id: str, key: str, default: float) -> float:
    """Read a float from session state; fall back to default on any error."""
    try:
        raw = read_state(session_id, key, "")
        return float(raw) if raw else default
    except (ValueError, Exception):
        return default


@router.post(
    "/treatment-decision",
    response_model=TreatmentDecisionResult,
    summary="Compute CLIP vs ENDOVASCULAR recommendation",
    description=(
        "Runs the 8-factor evidence-based decision engine using aneurysm morphometry "
        "(stored in the session after Step 3 — Detección/Morfometría) and optional "
        "clinical inputs (location, rupture status). "
        "Returns a scored recommendation with full factor breakdown.\n\n"
        "**References:** ISAT 2002, BRAT 2013, AHA/ASA Guidelines 2015."
    ),
)
async def compute_treatment_decision(
    req: TreatmentDecisionRequest,
) -> TreatmentDecisionResult:
    # Validate session (soft check — morpho may not be available yet in early development)
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    # Load morphometric values persisted by the morphometry step (Session C).
    # Keys are written by routers/detect.py after compute_morphometrics().
    # Values default to 0.0 when morphometry has not been run yet; compute_decision()
    # treats 0.0 inputs as "not available" and skips the corresponding factors.
    neck_mm           = _load_float(req.session_id, "morpho.neck_mm",          0.0)
    aspect_ratio      = _load_float(req.session_id, "morpho.ar",               0.0)
    dnr               = _load_float(req.session_id, "morpho.dnr",              0.0)
    max_diameter_mm   = _load_float(req.session_id, "morpho.max_diameter_mm",  0.0)
    bottleneck_factor = _load_float(req.session_id, "morpho.bf",               0.0)
    undulation_index  = _load_float(req.session_id, "morpho.ui",               0.0)

    result = compute_decision(
        neck_mm=neck_mm,
        aspect_ratio=aspect_ratio,
        dnr=dnr,
        max_diameter_mm=max_diameter_mm,
        bottleneck_factor=bottleneck_factor,
        undulation_index=undulation_index,
        location=req.location,
        ruptured=req.is_ruptured,
    )

    # Persist treatment result to session state for report generation (Session E).
    write_state(req.session_id, "treatment.recommendation",     result["recommendation"])
    write_state(req.session_id, "treatment.recommendation_key", result["recommendation_key"])
    write_state(req.session_id, "treatment.confidence",         result["confidence"])
    write_state(req.session_id, "treatment.clip_pct",           str(result["clip_pct"]))
    write_state(req.session_id, "treatment.endo_pct",           str(result["endo_pct"]))
    # Serialise factors list as JSON for report builder
    factors_for_json = [
        {"name": f["name"], "direction": f["direction"], "points": f["points"]}
        for f in result.get("factors", [])
    ]
    write_state(req.session_id, "treatment.factors_json", json.dumps(factors_for_json))

    return TreatmentDecisionResult(**result)
