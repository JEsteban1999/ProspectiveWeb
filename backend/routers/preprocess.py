"""Optional DICOM volume preprocessing router (Feature 10).

Applies HU clipping / isotropic resampling / Gaussian smoothing to the session's
cached volume and rewrites the MPR cache, so subsequent MPR views and
segmentation use the preprocessed volume. Downstream results must be re-run.
"""
from __future__ import annotations

import asyncio
import json
import logging

import numpy as np
from fastapi import APIRouter, HTTPException

from models.preprocess import PreprocessRequest, PreprocessResult, PreprocessStatus
from services.sessions import read_state, session_exists, write_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["preprocess"])

#: Set once the cached volume has been rewritten; cleared by the revert below.
_OPS_KEY = "preprocess.ops"


def _run(session_id: str, req: PreprocessRequest) -> PreprocessResult:
    import gc
    import os
    from services.mpr import _cache_paths, ensure_volume_cached, _get_volume

    from services.preprocess import preprocess_volume

    if not (req.clip_hu or req.resample_isotropic or req.smooth):
        raise ValueError("Selecciona al menos una operación de preprocesamiento.")

    from services.preprocess import is_hounsfield

    meta = ensure_volume_cached(session_id)
    # Copy the volume into RAM so we can release the memmap that keeps the .npy
    # file open (Windows forbids overwriting a memory-mapped file).
    volume = np.array(_get_volume(session_id), dtype=np.float32)
    spacing = tuple(float(s) for s in meta["spacing"])  # (sz, sy, sx)

    # The HU clamp is a Hounsfield operation: applying it to a 3DRA/XA volume
    # silently flattens everything above 3000, which on those studies is where
    # the contrast column lives. Skip it rather than damage the volume.
    modality = str(meta.get("modality", "") or "")
    clip_hu = req.clip_hu and is_hounsfield(modality)
    clip_skipped = req.clip_hu and not clip_hu
    if clip_skipped and not (req.resample_isotropic or req.smooth):
        raise ValueError(
            f"El recorte de HU no aplica a un volumen {modality or 'no-TAC'}: sus "
            "intensidades no son unidades Hounsfield. Selecciona otra operación."
        )

    new_vol, new_spacing = preprocess_volume(
        volume, spacing,
        clip_hu=clip_hu,
        resample_isotropic=req.resample_isotropic,
        target_spacing_mm=req.target_spacing_mm,
        smooth=req.smooth,
        smooth_sigma=req.smooth_sigma,
    )

    npy_path, meta_path = _cache_paths(session_id)

    # Drop every cached reference to the old memmap, then GC so Windows releases
    # the file handle before we replace it.
    try:
        from services.mpr import _load_memmap, _downsampled_volume
        _load_memmap.cache_clear()
        _downsampled_volume.cache_clear()
    except Exception:  # noqa: BLE001
        pass
    gc.collect()

    # Write to a sibling .npy then atomically replace (avoids partial writes).
    tmp_path = npy_path.with_name("_volume_new.npy")
    np.save(tmp_path, np.ascontiguousarray(new_vol, dtype=np.float32))
    os.replace(tmp_path, npy_path)

    new_meta = dict(meta)
    new_meta["shape"] = [int(x) for x in new_vol.shape]
    new_meta["spacing"] = [float(s) for s in new_spacing]
    meta_path.write_text(json.dumps(new_meta))

    ops = []
    if clip_hu:
        ops.append("recorte HU")
    if req.resample_isotropic:
        ops.append(f"remuestreo isotrópico {req.target_spacing_mm} mm")
    if req.smooth:
        ops.append(f"suavizado σ={req.smooth_sigma}")
    write_state(session_id, _OPS_KEY, ", ".join(ops))
    note = f"Aplicado: {', '.join(ops)}. Vuelve a segmentar para usar el volumen preprocesado."
    if clip_skipped:
        note = (
            f"Recorte de HU omitido: un volumen {modality or 'no-TAC'} no está en "
            f"unidades Hounsfield. {note}"
        )
    return PreprocessResult(
        shape_before=[int(x) for x in volume.shape],
        shape_after=[int(x) for x in new_vol.shape],
        spacing_before=[round(float(s), 3) for s in spacing],
        spacing_after=[round(float(s), 3) for s in new_spacing],
        note=note,
    )


@router.post(
    "/preprocess/{session_id}",
    response_model=PreprocessResult,
    summary="Preprocess the session volume (clip / isotropic resample / smooth)",
    description=(
        "Applies optional HU clipping, isotropic resampling and Gaussian smoothing "
        "to the cached volume and rewrites the MPR cache. The segmentation and any "
        "downstream analysis must be re-run afterwards. Requires an uploaded volume."
    ),
)
async def preprocess(session_id: str, req: PreprocessRequest) -> PreprocessResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    try:
        return await asyncio.to_thread(_run, session_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=409, detail="No hay volumen en la sesión. Sube un DICOM primero.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Preprocess failed")
        raise HTTPException(status_code=500, detail=f"Error en el preprocesamiento: {exc}")


# ── Reverting the preprocessing ───────────────────────────────────────────── #

def _revert(session_id: str) -> PreprocessResult:
    """Drop the rewritten volume cache; the DICOM in the session rebuilds it.

    Preprocessing overwrites the cached volume in place, which made a bad
    isotropic resample permanent for the rest of the session. The original DICOM
    never leaves the session directory, so deleting the two cache files and
    letting `ensure_volume_cached` run again is a complete undo — no re-upload.
    """
    import gc
    from services.mpr import _cache_paths, ensure_volume_cached

    import os

    npy_path, meta_path = _cache_paths(session_id)
    if not npy_path.exists():
        raise FileNotFoundError("No hay volumen cacheado en la sesión.")

    before = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    # Release the memmap first — Windows refuses to move a mapped file.
    try:
        from services.mpr import _load_memmap, _downsampled_volume
        _load_memmap.cache_clear()
        _downsampled_volume.cache_clear()
    except Exception:  # noqa: BLE001
        pass
    gc.collect()

    # Move the cache aside rather than deleting it. If the DICOM turns out to be
    # unreadable, deleting first would leave the session with NO volume at all —
    # strictly worse than the preprocessed one the user wanted to undo.
    bak_npy = npy_path.with_name("_volume_prev.npy")
    bak_meta = meta_path.with_name("_volume_meta_prev.json")
    os.replace(npy_path, bak_npy)
    if meta_path.exists():
        os.replace(meta_path, bak_meta)

    try:
        after = ensure_volume_cached(session_id)   # re-derives from the original DICOM
    except Exception as exc:  # noqa: BLE001
        os.replace(bak_npy, npy_path)
        if bak_meta.exists():
            os.replace(bak_meta, meta_path)
        raise RuntimeError(
            "No se pudo reconstruir el volumen desde el DICOM de la sesión "
            f"({exc}). Se conserva el volumen preprocesado."
        ) from exc

    bak_npy.unlink(missing_ok=True)
    bak_meta.unlink(missing_ok=True)
    write_state(session_id, _OPS_KEY, "")

    return PreprocessResult(
        shape_before=[int(x) for x in before.get("shape", after["shape"])],
        shape_after=[int(x) for x in after["shape"]],
        spacing_before=[round(float(s), 3) for s in before.get("spacing", after["spacing"])],
        spacing_after=[round(float(s), 3) for s in after["spacing"]],
        note="Volumen restaurado desde el DICOM original. Vuelve a segmentar.",
    )


@router.get(
    "/preprocess/{session_id}",
    response_model=PreprocessStatus,
    summary="Whether this session's volume has been preprocessed",
    description=(
        "Lets the panel offer «Revertir» after a session is resumed, when the "
        "browser has no memory of the operations that were applied."
    ),
)
async def preprocess_status(session_id: str) -> PreprocessStatus:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    ops = read_state(session_id, _OPS_KEY, "") or ""
    return PreprocessStatus(applied=bool(ops), ops=ops)


@router.delete(
    "/preprocess/{session_id}",
    response_model=PreprocessResult,
    summary="Revert the volume to the original DICOM",
    description=(
        "Discards the preprocessed volume and rebuilds it from the DICOM still "
        "stored in the session — a complete undo of HU clipping, resampling and "
        "smoothing, with no re-upload. The segmentation and everything downstream "
        "must be re-run, since they were derived from the altered volume."
    ),
)
async def revert_preprocess(session_id: str) -> PreprocessResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    try:
        return await asyncio.to_thread(_revert, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        # The volume the user has is intact; say so instead of a bare 500.
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Preprocess revert failed")
        raise HTTPException(status_code=500, detail=f"No se pudo restaurar el volumen: {exc}")
