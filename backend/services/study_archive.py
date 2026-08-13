"""Archive an uploaded study into durable storage + build its preview thumbnail.

The pipeline works on `data/sessions/<uuid>`, which the TTL sweep deletes. This
module copies a session's DICOM into the durable store (local or S3) under the
study's prefix, and renders ONE small PNG (mid axial slice) so the gallery can
show a preview without ever touching the DICOM.
"""
from __future__ import annotations

import io
import logging

import numpy as np

from services.sessions import session_subdir
from services.storage import dicom_key, get_storage, study_prefix, thumb_key

logger = logging.getLogger(__name__)

_THUMB_MAX_PX = 320


def build_thumbnail_png(session_id: str) -> bytes | None:
    """Render the mid axial slice of the session volume as a small PNG.

    Delegates the windowing to `render_slice_png` — the very function the MPR
    viewer uses — so the preview looks exactly like the study does in the app.
    (Re-implementing the normalisation here produced near-black previews on
    3D-RA, whose wide display window leaves soft tissue at the bottom of the
    range.) Uses the cached volume, so no DICOM re-read. Returns None when there
    is no usable volume, e.g. a 2-D projection-only study.
    """
    try:
        from PIL import Image
        from services.mpr import ensure_volume_cached, _get_volume, render_slice_png

        ensure_volume_cached(session_id)
        vol = np.asarray(_get_volume(session_id))
        if vol.ndim != 3 or min(vol.shape) < 1:
            return None

        png = render_slice_png(session_id, "axial", vol.shape[0] // 2)
        img = Image.open(io.BytesIO(png))
        img.thumbnail((_THUMB_MAX_PX, _THUMB_MAX_PX))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 — a missing preview must not fail the archive
        logger.warning("Thumbnail generation failed for session %s: %s", session_id, exc)
        return None


def archive_session_dicom(session_id: str, study_id: int) -> dict:
    """Copy the session's DICOM into durable storage and store a thumbnail.

    Returns {"storage_prefix", "thumb_key", "n_files", "size_mb"} for the Study row.
    """
    storage = get_storage()
    prefix = study_prefix(study_id)
    dicom_dir = session_subdir(session_id, "dicom")

    files = sorted(p for p in dicom_dir.rglob("*") if p.is_file())
    if not files:
        raise ValueError("La sesión no tiene archivos DICOM que archivar.")

    # Re-archiving replaces the previous copy so a study never mixes two uploads.
    storage.delete_prefix(prefix)
    for f in files:
        storage.put_file(dicom_key(study_id, f.name), f)

    tkey = ""
    png = build_thumbnail_png(session_id)
    if png:
        tkey = thumb_key(study_id)
        storage.put_bytes(tkey, png)

    size_mb = round(storage.size_bytes(prefix) / 1e6, 1)
    logger.info(
        "Archived study %s from session %s: %d files, %.1f MB, thumb=%s",
        study_id, session_id, len(files), size_mb, bool(png),
    )
    return {
        "storage_prefix": prefix,
        "thumb_key": tkey,
        "n_files": len(files),
        "size_mb": size_mb,
    }


def restore_study_to_session(study_id: int, session_id: str) -> int:
    """Copy an archived study's DICOM back into a live session. Returns file count."""
    storage = get_storage()
    dest = session_subdir(session_id, "dicom")
    n = storage.download_prefix(f"{study_prefix(study_id)}/dicom", dest)
    if n == 0:
        raise FileNotFoundError(f"El estudio {study_id} no tiene DICOM archivado.")
    logger.info("Restored %d DICOM files of study %s into session %s", n, study_id, session_id)
    return n
