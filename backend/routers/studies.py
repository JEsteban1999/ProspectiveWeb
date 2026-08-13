"""Study gallery — browse archived studies, preview them, reopen them.

Complements the patient-centric endpoints in `routers/patients.py` with a
cross-patient view: every study, filterable by patient name or national ID,
each with a preview thumbnail.

PRIVACY: thumbnails and DICOM are served ONLY through these authenticated
endpoints. They are never placed under `data/`, which is public StaticFiles.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from models.dicom import UploadResult
from models.patient import StudyCard
from services.auth_service import get_current_user
from services.database import get_db
from services.db_models import PlanningSession, Patient, Study, User
from services.sessions import create_session, session_subdir
from services.storage import get_storage
from services.study_archive import archive_session_dicom, restore_study_to_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/studies", tags=["studies"])


def _to_card(s: Study, p: Patient | None, latest: PlanningSession | None) -> StudyCard:
    return StudyCard(
        id=s.id,
        patient_id=s.patient_id,
        patient_name=(p.full_name if p else ""),
        hospital_id=(p.hospital_id if p else ""),
        description=s.description or s.dx_principal or "Estudio",
        modality=s.modality or "",
        acquired_at=s.acquired_at or "",
        dx_principal=s.dx_principal or "",
        created_at=s.created_at,
        archived=bool(s.storage_prefix),
        has_thumbnail=bool(s.thumb_key),
        n_files=s.n_files or 0,
        n_slices=s.n_slices or 0,
        size_mb=s.size_mb or 0.0,
        session_count=len(s.sessions or []),
        last_step=(latest.current_step if latest else None),
        max_diameter_mm=(latest.max_diameter_mm if latest else None),
        rupture_risk_label=(latest.rupture_risk_label if latest else None),
    )


@router.get(
    "",
    response_model=list[StudyCard],
    summary="List studies for the gallery",
    description=(
        "Every study with its patient identity, archive state and pipeline "
        "progress. `q` filters by patient name or national ID (historia "
        "clínica); `patient_id` restricts the list to one patient."
    ),
)
async def list_studies(
    db: Annotated[Session, Depends(get_db)],
    q: str = Query("", description="Filtro por nombre de paciente o cédula/HC"),
    patient_id: int | None = Query(None, description="Solo los estudios de este paciente"),
    limit: int = Query(200, ge=1, le=1000),
) -> list[StudyCard]:
    query = db.query(Study)
    if patient_id is not None:
        query = query.filter(Study.patient_id == patient_id)
    studies = query.order_by(Study.created_at.desc()).limit(limit).all()

    needle = q.strip().lower()
    cards: list[StudyCard] = []
    for s in studies:
        p = s.patient
        if needle:
            hay = f"{p.full_name if p else ''} {p.hospital_id if p else ''}".lower()
            if needle not in hay:
                continue
        latest = None
        if s.sessions:
            latest = max(s.sessions, key=lambda x: x.updated_at or x.created_at)
        cards.append(_to_card(s, p, latest))
    return cards


@router.get(
    "/{study_id}/thumbnail",
    summary="Preview image of a study",
    description="Small PNG (mid axial slice) rendered when the study was archived.",
    responses={200: {"content": {"image/png": {}}}},
)
async def get_thumbnail(
    study_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User | None, Depends(get_current_user)] = None,
) -> Response:
    s = db.query(Study).filter_by(id=study_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail=f"Estudio {study_id} no encontrado")
    if not s.thumb_key:
        raise HTTPException(status_code=404, detail="Este estudio no tiene vista previa")
    try:
        data = get_storage().get_bytes(s.thumb_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Vista previa no disponible: {exc}")
    # Private: it is patient imaging, so never let a shared cache keep it.
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.post(
    "/{study_id}/archive",
    response_model=StudyCard,
    summary="Archive a session's DICOM into durable storage",
    description=(
        "Copies the DICOM of `session_id` into the durable store under this "
        "study and renders its preview thumbnail, so the study survives the "
        "session TTL and shows up in the gallery."
    ),
)
async def archive_study(
    study_id: int,
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User | None, Depends(get_current_user)] = None,
) -> StudyCard:
    s = db.query(Study).filter_by(id=study_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail=f"Estudio {study_id} no encontrado")

    try:
        info = archive_session_dicom(session_id, study_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Archive failed")
        raise HTTPException(status_code=500, detail=f"No se pudo archivar el estudio: {exc}")

    from services.sessions import read_state
    s.storage_prefix = info["storage_prefix"]
    s.thumb_key      = info["thumb_key"]
    s.n_files        = info["n_files"]
    s.size_mb        = info["size_mb"]
    s.dicom_path     = info["storage_prefix"]     # legacy field now points at the archive
    if not s.modality:
        s.modality = read_state(session_id, "dicom.modality", "") or ""
    try:
        s.n_slices = int(float(read_state(session_id, "dicom.n_slices", "0") or 0))
    except ValueError:
        s.n_slices = 0
    db.commit()
    db.refresh(s)

    latest = max(s.sessions, key=lambda x: x.updated_at or x.created_at) if s.sessions else None
    return _to_card(s, s.patient, latest)


@router.post(
    "/{study_id}/open",
    response_model=UploadResult,
    summary="Open an archived study in a fresh session",
    description=(
        "Materialises the archived DICOM into a new working session, scans its "
        "series and activates the best 3-D volume — exactly as a fresh upload "
        "would — so the pipeline can start straight away. Returns the same shape "
        "as `POST /api/upload`."
    ),
)
async def open_study(
    study_id: int,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User | None, Depends(get_current_user)] = None,
) -> UploadResult:
    s = db.query(Study).filter_by(id=study_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail=f"Estudio {study_id} no encontrado")
    if not s.storage_prefix:
        raise HTTPException(
            status_code=409,
            detail="Este estudio no tiene DICOM archivado. Cárgalo y pulsa «Guardar estudio».",
        )

    sid = create_session()
    try:
        n = restore_study_to_session(study_id, sid)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OSError as exc:
        logger.exception("Open study failed (filesystem)")
        raise HTTPException(status_code=507, detail=f"No se pudo abrir el estudio: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Open study failed")
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el estudio: {exc}")

    # Scan + activate a series, exactly like an upload: without this the session
    # has no `dicom.series_id`, so the volume loader would lump every file into
    # one bogus series and the panel would show no study at all.
    from routers.upload import _activate_series, _build_series_list
    from services.dicom_loader import scan_series

    try:
        raw = scan_series(session_subdir(sid, "dicom"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Series scan failed on open")
        raise HTTPException(status_code=500, detail=f"No se pudieron leer las series: {exc}")

    series_list = _build_series_list(sid, raw)
    if not series_list:
        raise HTTPException(status_code=422, detail="El estudio archivado no contiene series DICOM legibles.")
    _activate_series(sid, series_list[0])

    logger.info("Opened study %s into session %s: %d files, %d series", study_id, sid, n, len(series_list))
    return UploadResult(session_id=sid, series=series_list, total_files=n)
