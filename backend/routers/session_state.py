"""Session save / restore router — real SQLite persistence (Session D)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import SessionSaveRequest, SessionSaveResult, SessionRestoreResult, SessionListItem
from services.database import get_db
from services.auth_service import get_current_user
from services.db_models import PlanningSession, Patient, User
from services.sessions import (
    session_exists, session_subdir, read_state, write_state, create_session,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ── Helpers ────────────────────────────────────────────────────────────────── #

def _session_dir_size_kb(session_id: str) -> float:
    """Return total size of the session directory in KB (best-effort)."""
    try:
        base = session_subdir(session_id, "").parent
        total = sum(f.stat().st_size for f in base.rglob("*") if f.is_file())
        return round(total / 1024, 1)
    except Exception:
        return 0.0


def _read_float(session_id: str, key: str) -> float | None:
    raw = read_state(session_id, key, "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _read_morpho(session_id: str) -> dict:
    """Read morphometry values from session state for snapshotting."""
    return {
        "max_diameter_mm":    _read_float(session_id, "morpho.max_diameter_mm"),
        "neck_mm":            _read_float(session_id, "morpho.neck_mm"),
        "dome_height_mm":     _read_float(session_id, "morpho.dome_height_mm"),
        "volume_mm3":         _read_float(session_id, "morpho.volume_mm3"),
        "ar":                 _read_float(session_id, "morpho.ar"),
        "dnr":                _read_float(session_id, "morpho.dnr"),
        "bf":                 _read_float(session_id, "morpho.bf"),
        "ui":                 _read_float(session_id, "morpho.ui"),
        "rupture_risk_label": read_state(session_id, "morpho.rupture_risk", "") or None,
        "seg_n_vertices":     None,
        "seg_n_faces":        None,
        "dicom_modality":     read_state(session_id, "dicom.modality", "") or None,
    }


def _restore_state(session_id: str, ps: PlanningSession) -> None:
    """Write DB-stored morphometry back into the (new) session state."""
    fields = {
        "morpho.max_diameter_mm": ps.max_diameter_mm,
        "morpho.neck_mm":         ps.neck_mm,
        "morpho.dome_height_mm":  ps.dome_height_mm,
        "morpho.volume_mm3":      ps.volume_mm3,
        "morpho.ar":              ps.ar,
        "morpho.dnr":             ps.dnr,
        "morpho.bf":              ps.bf,
        "morpho.ui":              ps.ui,
        "morpho.rupture_risk":    ps.rupture_risk_label,
        "dicom.modality":         ps.dicom_modality,
    }
    for key, val in fields.items():
        if val is not None:
            write_state(session_id, key, str(val))


# ── POST /sessions/save ────────────────────────────────────────────────────── #

@router.post(
    "/save",
    response_model=SessionSaveResult,
    summary="Save current session state to database",
    description=(
        "Persists the session's morphometry snapshot and metadata to the database. "
        "Subsequent calls update the same record (upsert on session_id). "
        "Optionally links the session to a patient and/or study record."
    ),
)
async def save_session(
    req:          SessionSaveRequest,
    db:           Annotated[Session,    Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> SessionSaveResult:
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    morpho      = _read_morpho(req.session_id)
    file_size   = _session_dir_size_kb(req.session_id)
    now         = datetime.now(timezone.utc)

    # Upsert: update existing record or create new one
    ps = db.query(PlanningSession).filter_by(session_id=req.session_id).first()
    if ps is None:
        ps = PlanningSession(session_id=req.session_id, created_at=now)
        db.add(ps)

    ps.label                = req.label or ps.label
    ps.current_step         = req.current_step
    ps.study_id             = req.study_id   if req.study_id   is not None else ps.study_id
    ps.patient_id           = req.patient_id if req.patient_id is not None else ps.patient_id
    ps.max_diameter_mm      = morpho["max_diameter_mm"]
    ps.neck_mm              = morpho["neck_mm"]
    ps.dome_height_mm       = morpho["dome_height_mm"]
    ps.volume_mm3           = morpho["volume_mm3"]
    ps.ar                   = morpho["ar"]
    ps.dnr                  = morpho["dnr"]
    ps.bf                   = morpho["bf"]
    ps.ui                   = morpho["ui"]
    ps.rupture_risk_label   = morpho["rupture_risk_label"]
    ps.dicom_modality       = morpho["dicom_modality"]
    ps.file_size_kb         = file_size
    ps.updated_at           = now

    db.commit()
    db.refresh(ps)

    logger.info(
        "Session saved — id=%s  label=%r  step=%d  patient_id=%s",
        req.session_id, ps.label, ps.current_step, ps.patient_id,
    )

    download_url = f"/data/sessions/{req.session_id}"
    return SessionSaveResult(
        file_path=str(session_subdir(req.session_id, "").parent),
        download_url=download_url,
        saved_at=now,
    )


# ── GET /sessions ──────────────────────────────────────────────────────────── #

@router.get(
    "",
    response_model=list[SessionListItem],
    summary="List all saved sessions",
    description="Returns all planning sessions from the database, newest first.",
)
async def list_sessions(
    db: Annotated[Session, Depends(get_db)],
) -> list[SessionListItem]:
    records = (
        db.query(PlanningSession)
        .order_by(PlanningSession.updated_at.desc())
        .all()
    )

    items: list[SessionListItem] = []
    for ps in records:
        patient_name = ""
        if ps.patient is not None:
            patient_name = ps.patient.full_name

        items.append(
            SessionListItem(
                id=ps.id,
                session_id=ps.session_id,
                label=ps.label or ps.session_id[:12],
                current_step=ps.current_step,
                patient_name=patient_name,
                created_at=ps.created_at,
                updated_at=ps.updated_at,
                file_size_kb=ps.file_size_kb,
            )
        )
    return items


# ── POST /sessions/{session_id}/restore ───────────────────────────────────── #

@router.post(
    "/{session_id}/restore",
    response_model=SessionRestoreResult,
    summary="Restore a saved session",
    description=(
        "Creates a fresh temporary session and re-populates its state from the "
        "database record identified by `session_id`. "
        "Returns the new session_id to use for subsequent API calls."
    ),
)
async def restore_session(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> SessionRestoreResult:
    ps = db.query(PlanningSession).filter_by(session_id=session_id).first()
    if ps is None:
        raise HTTPException(
            status_code=404,
            detail=f"No saved session found with id '{session_id}'",
        )

    # Create a brand-new temp session dir
    new_sid = create_session()
    _restore_state(new_sid, ps)

    # Detect what data is available (check if files still exist on disk)
    try:
        old_meshes = session_subdir(session_id, "meshes")
        has_seg  = (old_meshes / "vessel_tree.vtp").exists()
        has_det  = (old_meshes / "aneurysm_cand_001.vtp").exists()
    except Exception:
        has_seg = has_det = False

    has_morpho = ps.max_diameter_mm is not None
    has_plan   = ps.current_step >= 4

    logger.info(
        "Session restored — original=%s  new=%s  step=%d",
        session_id, new_sid, ps.current_step,
    )

    return SessionRestoreResult(
        session_id=new_sid,
        current_step=ps.current_step,
        label=ps.label or "",
        has_segmentation=has_seg,
        has_detection=has_det,
        has_morphometry=has_morpho,
        has_plan=has_plan,
        restored_at=datetime.now(timezone.utc),
    )
