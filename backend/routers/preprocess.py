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

from models.preprocess import PreprocessRequest, PreprocessResult
from services.sessions import session_exists

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["preprocess"])


def _run(session_id: str, req: PreprocessRequest) -> PreprocessResult:
    import gc
    import os
    from services.mpr import _cache_paths, ensure_volume_cached, _get_volume

    from services.preprocess import preprocess_volume

    if not (req.clip_hu or req.resample_isotropic or req.smooth):
        raise ValueError("Selecciona al menos una operación de preprocesamiento.")

    meta = ensure_volume_cached(session_id)
    # Copy the volume into RAM so we can release the memmap that keeps the .npy
    # file open (Windows forbids overwriting a memory-mapped file).
    volume = np.array(_get_volume(session_id), dtype=np.float32)
    spacing = tuple(float(s) for s in meta["spacing"])  # (sz, sy, sx)

    new_vol, new_spacing = preprocess_volume(
        volume, spacing,
        clip_hu=req.clip_hu,
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
    if req.clip_hu:
        ops.append("recorte HU")
    if req.resample_isotropic:
        ops.append(f"remuestreo isotrópico {req.target_spacing_mm} mm")
    if req.smooth:
        ops.append(f"suavizado σ={req.smooth_sigma}")
    return PreprocessResult(
        shape_before=[int(x) for x in volume.shape],
        shape_after=[int(x) for x in new_vol.shape],
        spacing_before=[round(float(s), 3) for s in spacing],
        spacing_after=[round(float(s), 3) for s in new_spacing],
        note=f"Aplicado: {', '.join(ops)}. Vuelve a segmentar para usar el volumen preprocesado.",
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
