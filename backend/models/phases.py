"""PHASES score models — 5-year rupture risk of an unruptured aneurysm.

Greving et al., Lancet Neurology 2014. Ported from the desktop phases_panel.py.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Population = Literal["other", "japan", "finland"]
Site = Literal["ica", "mca", "aca_pcom_posterior"]


class PhasesRequest(BaseModel):
    """Clinical inputs for the PHASES score. Size auto-fills from morphometry."""

    session_id: str | None = Field(
        None,
        description=(
            "Planning session to record the score in. When given, the result and "
            "the inputs it was computed from are persisted so the score reaches "
            "the PDF report and the DICOM SR. Omit for a throw-away calculation."
        ),
    )
    population: Population = Field("other", description="Patient population")
    hypertension: bool = Field(False, description="History of hypertension")
    age_years: int = Field(60, ge=0, le=120, description="Patient age in years")
    size_mm: float = Field(..., ge=0.0, description="Aneurysm max diameter (mm)")
    earlier_sah: bool = Field(False, description="Earlier subarachnoid haemorrhage from another aneurysm")
    site: Site = Field("ica", description="Aneurysm location category")


class PhasesResult(BaseModel):
    """PHASES total score, per-factor breakdown, and 5-year rupture risk."""

    population_pts: int
    hypertension_pts: int
    age_pts: int
    size_pts: int
    sah_pts: int
    site_pts: int
    total_score: int = Field(..., ge=0, le=22, description="Sum of all PHASES factors")
    risk_5yr_pct: float = Field(..., description="Estimated 5-year rupture risk (%)")
    risk_band: Literal["low", "moderate", "high"] = Field(
        ..., description="high ≥ 7% · moderate ≥ 2% · low < 2%"
    )
