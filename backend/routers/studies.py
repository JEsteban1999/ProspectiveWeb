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
from services.db_models import ImagingStudy, PlanningSession, Patient, Study, User
from services.sessions import create_session, has_saved_session, session_subdir
from services.storage import get_storage
from services.study_archive import archive_session_dicom, restore_study_to_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/studies", tags=["studies"])


def _to_card(img: ImagingStudy, latest: PlanningSession | None) -> StudyCard:
    """One imaging study as a gallery card, carrying its case + patient context."""
    case: Study | None = img.case
    p: Patient | None = img.patient or (case.patient if case else None)
    return StudyCard(
        id=img.id,
        case_id=img.case_id,
        patient_id=img.patient_id,
        patient_name=(p.full_name if p else ""),
        hospital_id=(p.hospital_id if p else ""),
        description=img.description or (case.dx_principal if case else "") or "Estudio",
        modality=img.modality or "",
        acquired_at=img.acquired_at or (case.acquired_at if case else "") or "",
        dx_principal=(case.dx_principal if case else "") or "",
        created_at=img.created_at,
        archived=img.archived,
        has_thumbnail=bool(img.thumb_key),
        n_files=img.n_files or 0,
        n_slices=img.n_slices or 0,
        size_mb=img.size_mb or 0.0,
        session_count=len(img.sessions or []),
        last_step=(latest.current_step if latest else None),
        max_diameter_mm=(latest.max_diameter_mm if latest else None),
        rupture_risk_label=(latest.rupture_risk_label if latest else None),
        # Only offer resuming when the snapshot is really there: sessions saved
        # before durable saving existed, or purged since, would 409 on restore.
        resumable_session_id=(
            latest.session_id
            if latest is not None and has_saved_session(latest.session_id)
            else None
        ),
    )


@router.get(
    "",
    response_model=list[StudyCard],
    summary="List studies for the gallery",
    description=(
        "Every study with its patient identity, archive state and pipeline "
        "progress. `q` filters in the database by surname, given name, national "
        "ID (historia clínica), series description or the case diagnosis; "
        "`patient_id` restricts the list to one patient."
    ),
)
async def list_studies(
    db: Annotated[Session, Depends(get_db)],
    q: str = Query("", description="Filtro por nombre de paciente o cédula/HC"),
    patient_id: int | None = Query(None, description="Solo los estudios de este paciente"),
    case_id: int | None = Query(None, description="Solo los estudios de este caso clínico"),
    limit: int = Query(200, ge=1, le=1000),
) -> list[StudyCard]:
    query = db.query(ImagingStudy)
    if patient_id is not None:
        query = query.filter(ImagingStudy.patient_id == patient_id)
    if case_id is not None:
        query = query.filter(ImagingStudy.case_id == case_id)

    # `q` has to narrow the query BEFORE the limit. Filtering afterwards searched
    # only the newest `limit` rows, so on a real archive a patient from last year
    # simply came back empty — with nothing to say why.
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        query = (
            query.outerjoin(Patient, ImagingStudy.patient_id == Patient.id)
                 .outerjoin(Study, ImagingStudy.case_id == Study.id)
                 .filter(
                     Patient.surname.ilike(like)
                     | Patient.given_name.ilike(like)
                     | Patient.hospital_id.ilike(like)
                     | ImagingStudy.description.ilike(like)
                     | Study.dx_principal.ilike(like)
                 )
        )

    images = query.order_by(ImagingStudy.created_at.desc()).limit(limit).all()

    cards: list[StudyCard] = []
    for img in images:
        latest = None
        if img.sessions:
            latest = max(img.sessions, key=lambda x: x.updated_at or x.created_at)
        cards.append(_to_card(img, latest))
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
    img = db.query(ImagingStudy).filter_by(id=study_id).first()
    if img is None:
        raise HTTPException(status_code=404, detail=f"Estudio {study_id} no encontrado")
    if not img.thumb_key:
        raise HTTPException(status_code=404, detail="Este estudio no tiene vista previa")
    try:
        data = get_storage().get_bytes(img.thumb_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"Vista previa no disponible: {exc}")
    # Private: it is patient imaging, so never let a shared cache keep it.
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.post(
    "/cases/{case_id}/archive",
    response_model=StudyCard,
    summary="Archive a session's DICOM as a new imaging study of a case",
    description=(
        "Copies the DICOM of `session_id` into durable storage as a NEW imaging "
        "study of this clinical case and renders its preview, so it survives the "
        "session TTL and appears in the gallery. A case can hold several imaging "
        "studies (CT + angiography + follow-up), so archiving never overwrites a "
        "previous one."
    ),
)
async def archive_study(
    case_id: int,
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User | None, Depends(get_current_user)] = None,
) -> StudyCard:
    case = db.query(Study).filter_by(id=case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail=f"Caso {case_id} no encontrado")

    from services.sessions import read_state
    modality = read_state(session_id, "dicom.modality", "") or ""
    try:
        n_slices = int(float(read_state(session_id, "dicom.n_slices", "0") or 0))
    except ValueError:
        n_slices = 0

    # Create the row first: the archive lives under the imaging study's own id,
    # so several acquisitions of one case never share a storage prefix.
    img = ImagingStudy(
        case_id=case.id,
        patient_id=case.patient_id,
        description=read_state(session_id, "dicom.series_description", "") or (modality and f"Estudio {modality}") or "Estudio",
        modality=modality,
        acquired_at=case.acquired_at or "",
        n_slices=n_slices,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    try:
        info = archive_session_dicom(session_id, img.id)
    except ValueError as exc:
        db.delete(img); db.commit()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.delete(img); db.commit()
        logger.exception("Archive failed")
        raise HTTPException(status_code=500, detail=f"No se pudo archivar el estudio: {exc}")

    img.storage_prefix = info["storage_prefix"]
    img.thumb_key      = info["thumb_key"]
    img.n_files        = info["n_files"]
    img.size_mb        = info["size_mb"]
    if not case.modality:
        case.modality = modality
    case.dicom_path = info["storage_prefix"]      # legacy pointer, keeps old code happy

    # Link the session that produced it, so the gallery shows real progress.
    ps = db.query(PlanningSession).filter_by(session_id=session_id).first()
    if ps is not None:
        ps.imaging_study_id = img.id
        ps.study_id = case.id
        ps.patient_id = case.patient_id

    db.commit()
    db.refresh(img)

    latest = max(img.sessions, key=lambda x: x.updated_at or x.created_at) if img.sessions else None
    return _to_card(img, latest)


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
    img = db.query(ImagingStudy).filter_by(id=study_id).first()
    if img is None:
        raise HTTPException(status_code=404, detail=f"Estudio {study_id} no encontrado")
    if not img.storage_prefix:
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
