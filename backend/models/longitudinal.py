"""Longitudinal follow-up models.

Matches prospective/processing/longitudinal.py and
prospective/ui/widgets/longitudinal_panel.py.
Step 4 — Morfometría › Seguimiento longitudinal.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class LongitudinalEntry(BaseModel):
    """Morphometry snapshot from one historical session."""

    session_date: date = Field(..., description="Acquisition date, or the session date if unknown")
    session_label: str = Field("", description="User label for this session")
    imaging_study_id: int | None = Field(
        None, description="Acquisition this point measures (one point per acquisition)"
    )
    case_id: int | None = Field(None, description="Clinical case the acquisition belongs to")
    n_sessions: int = Field(
        1, description="Saved sessions on this acquisition; only the latest is plotted"
    )

    # Key metrics stored per session (subset of MorphometryResult)
    max_diameter_mm: float
    neck_mm: float
    volume_mm3: float
    ar: float
    dnr: float
    rupture_risk_label: str


class LongitudinalDelta(BaseModel):
    """Change in a metric between two sessions."""

    metric: str = Field(..., description="Metric name (e.g. 'max_diameter_mm')")
    label: str = Field(..., description="Human-readable metric label")
    value_current: float
    value_previous: float
    delta: float = Field(..., description="Absolute change (current − previous)")
    delta_pct: float = Field(..., description="Relative change in percent")
    trend: str = Field(..., description="'↑ crecimiento' | '↓ reducción' | '→ estable'")
    is_concerning: bool = Field(
        False, description="True when growth exceeds clinical concern threshold"
    )


class LongitudinalResult(BaseModel):
    """Longitudinal comparison between the current session and historical ones."""

    patient_id: int | None = None
    case_id: int | None = Field(
        None, description="Set when the series was restricted to one clinical case"
    )
    entries: list[LongitudinalEntry] = Field(
        ...,
        description=(
            "One point per imaging study, ordered by acquisition date. Re-running "
            "the pipeline on the same images is not a new time point — it would "
            "read as growth when nothing changed — so repeated sessions on one "
            "acquisition collapse to the most recent."
        ),
    )
    deltas: list[LongitudinalDelta] = Field(
        ...,
        description=(
            "Changes between the current and most recent previous session. "
            "Empty when no previous session exists."
        ),
    )
    growth_alert: bool = Field(
        False,
        description=(
            "True when diameter growth > 1 mm/year or volume growth > 20% — "
            "triggers a clinical alert banner in the UI."
        ),
    )
    growth_alert_message: str | None = Field(
        None, description="Human-readable growth alert message"
    )
