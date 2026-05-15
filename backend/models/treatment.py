"""Treatment decision models — CLIP vs ENDOVASCULAR recommendation.

Matches prospective/processing/treatment_decision.py.
Step 5 — Planificación › Decisión terapéutica.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Aneurysm locations (from treatment_decision.py LOCATIONS list)
AneurysmLocation = Literal[
    "Desconocida / No especificada",
    "ACM — Arteria Cerebral Media",
    "ACA / ACoA — Arteria Comunicante Anterior",
    "ACI proximal (segm. cavernoso / clinoideo)",
    "ACI distal (PCOM / oftálmica)",
    "ACoP — Arteria Comunicante Posterior",
    "Basilar (punta, tronco o AICA)",
    "PICA / Vertebral",
    "Otra localización",
]

RecommendationKey = Literal["clip", "endo", "mdt", "surveillance"]
Confidence = Literal["Alta", "Moderada", "Baja"]


class DecisionFactor(BaseModel):
    """One contributing factor in the CLIP vs ENDO scoring."""

    name: str = Field(..., description="Short display name of the factor")
    detail: str = Field(..., description="One-line clinical rationale")
    direction: Literal["clip", "endo", "neutral"] = Field(
        ..., description="Which direction this factor pushes the recommendation"
    )
    points: int = Field(..., ge=0, description="Weight / magnitude of this factor")


class TreatmentDecisionRequest(BaseModel):
    """Clinical context inputs needed to compute the CLIP vs ENDO recommendation."""

    session_id: str

    # Clinical inputs (optional — default to unknown/false when not provided)
    location: AneurysmLocation = Field(
        "Desconocida / No especificada",
        description="Anatomical location of the aneurysm",
    )
    is_ruptured: bool = Field(
        False, description="True if the aneurysm is acutely ruptured (SAH)"
    )
    patient_age: int | None = Field(
        None, ge=0, le=120,
        description="Patient age in years — older patients may favour endovascular",
    )
    has_comorbidities: bool = Field(
        False, description="True if significant surgical comorbidities are present"
    )


class TreatmentDecisionResult(BaseModel):
    """Full output of the CLIP vs ENDO decision engine."""

    # ── Scores ────────────────────────────────────────────────────────────── #
    clip_pct: int = Field(..., ge=0, le=100, description="Clip score as percentage (0–100)")
    endo_pct: int = Field(..., ge=0, le=100, description="Endo score as percentage (0–100)")
    balance: int = Field(
        ..., description="clip_score − endo_score (positive → clip preferred)"
    )

    # ── Recommendation ────────────────────────────────────────────────────── #
    recommendation: str = Field(..., description="Human-readable recommendation string")
    recommendation_key: RecommendationKey = Field(
        ..., description="Machine-readable recommendation key"
    )
    confidence: Confidence = Field(..., description="Confidence level of the recommendation")
    icon: str = Field(..., description="Single emoji for the recommendation badge")

    # ── Factors breakdown ─────────────────────────────────────────────────── #
    factors: list[DecisionFactor] = Field(
        ..., description="All factors that contributed to the score, for display"
    )
    clip_factors: list[str] = Field(
        ..., description="Names of factors favouring clip"
    )
    endo_factors: list[str] = Field(
        ..., description="Names of factors favouring endovascular"
    )
