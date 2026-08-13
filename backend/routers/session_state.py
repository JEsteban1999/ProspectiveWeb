"""Session save / restore router — real SQLite persistence (Session D)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import (
    SessionSaveRequest, SessionSaveResult, SessionRestoreResult, SessionListItem,
    SeriesInfo, SpacingXYZ,
)
from services.database import get_db
from services.auth_service import get_current_user
from services.db_models import PlanningSession, Patient, User
from services.sessions import (
    session_exists, session_subdir, read_state, write_state, create_session,
    snapshot_session, rehydrate_session, has_saved_session, mesh_url as mesh_url_for,
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


def _restored_series(session_id: str) -> "SeriesInfo | None":
    """Rebuild the series card from the rehydrated volume cache.

    Restoring copies `_volume.npy` + its meta, so everything the upload step
    displays is already on disk — it just was never sent back, which made a
    resumed session look like nothing had been loaded.
    """
    from services.mpr import _cache_paths

    _npy, meta_path = _cache_paths(session_id)
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
        sz, sy, sx = meta["spacing"]
        z, y, x = meta["shape"]
        return SeriesInfo(
            size_mb=round(z * y * x * 4 / (1024 * 1024), 1),   # float32 volume
            session_id=session_id,
            series_id=read_state(session_id, "dicom.series_id", "") or "",
            description=read_state(session_id, "dicom.description", "") or "Serie restaurada",
            modality=meta.get("modality") or read_state(session_id, "dicom.modality", "") or "",
            slices=int(meta["shape"][0]),
            spacing=SpacingXYZ(x=float(sx), y=float(sy), z=float(sz)),
            window_center=float(meta.get("wc", 0.0)),
            window_width=float(meta.get("ww", 0.0)),
            is_projection=read_state(session_id, "dicom.is_projection", "0") == "1",
        )
    except (KeyError, ValueError, TypeError):
        logger.warning("No se pudo reconstruir la serie de la sesión %s", session_id)
        return None


def _case_label(case) -> str:
    """Short label for a clinical case — diagnosis first, as the UI shows it."""
    if case is None:
        return ""
    return (case.dx_principal or case.description or f"Caso {case.id}").strip()


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
    # Snapshot the whole session dir (volume + meshes + state) into the durable
    # store so it survives the TTL purge and can be rehydrated on resume.
    try:
        file_size = snapshot_session(req.session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Session snapshot failed")
        raise HTTPException(status_code=500, detail=f"No se pudo guardar la sesión: {exc}")
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
    ps.imaging_study_id     = (req.imaging_study_id if req.imaging_study_id is not None
                               else ps.imaging_study_id)
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
    if not has_saved_session(session_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "La sesión existe en la base de datos pero sus archivos ya no están "
                "disponibles (guardada antes de habilitar el guardado duradero, o "
                "purgada). Vuelve a generar y guardar el estudio."
            ),
        )

    # Rehydrate: copy the durable snapshot into a brand-new live session dir.
    try:
        new_sid = rehydrate_session(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Session rehydration failed")
        raise HTTPException(status_code=500, detail=f"No se pudo restaurar la sesión: {exc}")

    # Inspect the rehydrated dir to build a payload the frontend can hydrate from.
    meshes = session_subdir(new_sid, "meshes")
    vessel = meshes / "vessel_tree.vtp"
    has_seg = vessel.exists()
    has_det = (meshes / "aneurysm_cand_001.vtp").exists()
    has_morpho = ps.max_diameter_mm is not None
    has_plan   = ps.current_step >= 4

    def _int_state(key: str) -> int:
        raw = read_state(new_sid, key, "")
        try:
            return int(float(raw)) if raw else 0
        except ValueError:
            return 0

    mesh_url = f"{mesh_url_for(new_sid, 'vessel_tree.vtp')}?v={int(datetime.now().timestamp() * 1000)}" if has_seg else ""

    logger.info(
        "Session restored — original=%s  new=%s  step=%d  has_seg=%s",
        session_id, new_sid, ps.current_step, has_seg,
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
        mesh_url=mesh_url,
        n_vertices=_int_state("seg.n_vertices"),
        n_faces=_int_state("seg.n_faces"),
        modality=read_state(new_sid, "dicom.modality", "") or "",
        patient_id=ps.patient_id,
        study_id=ps.study_id,
        # Carry the case and the acquisition through the resume, otherwise the
        # rehydrated session forgets what it was planning and the next "Guardar
        # progreso" would have to ask for the case again.
        study_label=_case_label(ps.study),
        imaging_study_id=ps.imaging_study_id,
        series=_restored_series(new_sid),
    )
