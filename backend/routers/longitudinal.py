"""Longitudinal follow-up router — real DB query (Session D)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models import LongitudinalDelta, LongitudinalEntry, LongitudinalResult
from services.database import get_db
from services.db_models import PlanningSession
from services.sessions import session_exists, read_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["longitudinal"])


# ── Helpers ────────────────────────────────────────────────────────────────── #

def _read_float(session_id: str, key: str, default: float = 0.0) -> float:
    raw = read_state(session_id, key, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _ps_to_entry(ps: PlanningSession, label: str | None = None,
                 when: "date | None" = None, n_sessions: int = 1) -> LongitudinalEntry:
    return LongitudinalEntry(
        session_date        = when or (ps.created_at.date() if ps.created_at else date.today()),
        session_label       = label or ps.label or ps.session_id[:12],
        imaging_study_id    = ps.imaging_study_id,
        case_id             = ps.study_id,
        n_sessions          = n_sessions,
        max_diameter_mm     = ps.max_diameter_mm or 0.0,
        neck_mm             = ps.neck_mm         or 0.0,
        volume_mm3          = ps.volume_mm3       or 0.0,
        ar                  = ps.ar               or 0.0,
        dnr                 = ps.dnr              or 0.0,
        rupture_risk_label  = ps.rupture_risk_label or "Bajo",
    )


def _compute_deltas(current: LongitudinalEntry, previous: LongitudinalEntry) -> list[LongitudinalDelta]:
    """Return growth deltas between two consecutive sessions."""
    metrics = [
        # (field, label, concern threshold for is_concerning)
        ("max_diameter_mm", "Diametro maximo", 1.0),   # > 1 mm growth → concerning
        ("volume_mm3",      "Volumen",         20.0),  # > 20% relative change → concerning
        ("ar",              "Aspect Ratio",    0.15),  # absolute delta > 0.15 → concerning
    ]
    deltas: list[LongitudinalDelta] = []
    for field, label, threshold in metrics:
        v_cur  = getattr(current,  field, 0.0) or 0.0
        v_prev = getattr(previous, field, 0.0) or 0.0
        delta  = v_cur - v_prev
        pct    = (delta / v_prev * 100.0) if v_prev > 0 else 0.0

        if field == "volume_mm3":
            is_concerning = abs(pct) > threshold
        else:
            is_concerning = abs(delta) > threshold

        if delta > 0.005:
            trend = "↑ crecimiento"
        elif delta < -0.005:
            trend = "↓ reduccion"
        else:
            trend = "→ estable"

        deltas.append(
            LongitudinalDelta(
                metric         = field,
                label          = label,
                value_current  = round(v_cur,  3),
                value_previous = round(v_prev, 3),
                delta          = round(delta,  3),
                delta_pct      = round(pct,    1),
                trend          = trend,
                is_concerning  = is_concerning,
            )
        )
    return deltas


def _growth_message(deltas: list[LongitudinalDelta]) -> str | None:
    concerning = [d for d in deltas if d.is_concerning]
    if not concerning:
        return None
    labels = ", ".join(d.label for d in concerning)
    return f"Crecimiento significativo en: {labels}. Considerar revision clinica."


# ── GET /longitudinal/{session_id} ────────────────────────────────────────── #

@router.get(
    "/longitudinal/{session_id}",
    response_model=LongitudinalResult,
    summary="Get longitudinal follow-up data for this session's patient",
    description=(
        "Returns all historical planning sessions for the patient linked to this session, "
        "ordered by date, plus computed deltas against the previous session.\n\n"
        "**Prerequisite:** the session must have been saved via "
        "`POST /api/sessions/save` with a `patient_id` to enable longitudinal comparison. "
        "Without a saved record, returns only the current session's morphometry snapshot."
    ),
)
async def get_longitudinal(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> LongitudinalResult:
    # ── 1. Find DB record for this session ─────────────────────────────── #
    ps_current = db.query(PlanningSession).filter_by(session_id=session_id).first()

    # ── 2. No saved record → return single-entry snapshot from session state ─ #
    if ps_current is None or ps_current.patient_id is None:
        # Attempt to build an entry from live session state
        if session_exists(session_id):
            max_d   = _read_float(session_id, "morpho.max_diameter_mm")
            neck    = _read_float(session_id, "morpho.neck_mm")
            vol     = _read_float(session_id, "morpho.volume_mm3")
            ar_val  = _read_float(session_id, "morpho.ar")
            dnr_val = _read_float(session_id, "morpho.dnr")
            risk    = read_state(session_id, "morpho.rupture_risk", "") or "Bajo"

            current_entry = LongitudinalEntry(
                session_date       = date.today(),
                session_label      = "Sesion actual",
                max_diameter_mm    = max_d,
                neck_mm            = neck,
                volume_mm3         = vol,
                ar                 = ar_val,
                dnr                = dnr_val,
                rupture_risk_label = risk,
            )
            return LongitudinalResult(
                patient_id    = None,
                entries       = [current_entry],
                deltas        = [],
                growth_alert  = False,
                growth_alert_message = (
                    "Guarde la sesion con POST /api/sessions/save y asociela a un "
                    "paciente para habilitar comparacion longitudinal."
                ),
            )

        # Fallback: completely empty
        return LongitudinalResult(
            patient_id=None, entries=[], deltas=[],
            growth_alert=False, growth_alert_message=None,
        )

    # ── 3. One point per ACQUISITION, not per session ─────────────────────── #
    #
    # Re-running the pipeline on the same images is not a new time point: two
    # runs of the same study differ by a millimetre of segmentation noise, and
    # plotting both reads as growth when nothing grew. So sessions are grouped by
    # the imaging study they analysed and only the most recent of each is kept.
    #
    # Restricted to the current clinical case when there is one — comparing a
    # control against the baseline of the SAME aneurysm is the clinical question;
    # a different case in the same patient is a different lesion.
    query = db.query(PlanningSession).filter(
        PlanningSession.patient_id == ps_current.patient_id
    )
    case_id = ps_current.study_id
    if case_id is not None:
        query = query.filter(PlanningSession.study_id == case_id)
    all_sessions = query.order_by(PlanningSession.created_at.asc()).all()

    from services.db_models import ImagingStudy

    def _acquired_on(img_id: int | None) -> "date | None":
        if img_id is None:
            return None
        img = db.get(ImagingStudy, img_id)
        if img is None or not img.acquired_at:
            return None
        try:
            return date.fromisoformat(str(img.acquired_at)[:10])
        except ValueError:
            return None

    # Group by acquisition; sessions predating the imaging-study model have no
    # id and each stands on its own so their history is not silently merged.
    groups: dict[object, list[PlanningSession]] = {}
    for ps in all_sessions:
        key = ps.imaging_study_id if ps.imaging_study_id is not None else f"session:{ps.session_id}"
        groups.setdefault(key, []).append(ps)

    points: list[tuple[date, LongitudinalEntry]] = []
    for key, sessions in groups.items():
        # Prefer a run that actually has morphometry, then the most recent.
        measured = [p for p in sessions if p.max_diameter_mm is not None] or sessions
        latest = max(measured, key=lambda p: p.updated_at or p.created_at)
        img_id = latest.imaging_study_id
        when = _acquired_on(img_id) or (
            latest.created_at.date() if latest.created_at else date.today()
        )
        is_this = any(p.session_id == session_id for p in sessions)
        label = "Estudio actual" if is_this else (latest.label or f"Estudio {when.isoformat()}")
        points.append((when, _ps_to_entry(latest, label=label, when=when,
                                          n_sessions=len(sessions))))

    points.sort(key=lambda t: t[0])
    entries: list[LongitudinalEntry] = [e for _w, e in points]

    # ── 4. Compute deltas between last two entries ────────────────────────── #
    deltas: list[LongitudinalDelta] = []
    if len(entries) >= 2:
        deltas = _compute_deltas(entries[-1], entries[-2])

    growth_alert = any(d.is_concerning for d in deltas)
    growth_alert_message = _growth_message(deltas) if growth_alert else None

    logger.info(
        "Longitudinal — session=%s  patient=%s  case=%s  acquisitions=%d (from %d sessions)",
        session_id, ps_current.patient_id, case_id, len(entries), len(all_sessions),
    )

    return LongitudinalResult(
        patient_id           = ps_current.patient_id,
        case_id              = case_id,
        entries              = entries,
        deltas               = deltas,
        growth_alert         = growth_alert,
        growth_alert_message = growth_alert_message,
    )
