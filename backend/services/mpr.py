"""MPR slice service — serve axial/coronal/sagittal DICOM slices as PNG.

The DICOM volume is loaded once per session (via dicom_loader) and cached on
disk as a .npy memmap so slice requests are cheap. Windowing (WC/WW) is applied
per request, mirroring the desktop SliceWidget (_apply_window / _get_slice).
"""
from __future__ import annotations

import io
import json
import logging
from functools import lru_cache
from pathlib import Path

import numpy as np

from services.dicom_loader import load_series
from services.sessions import read_state, session_dir, session_subdir

logger = logging.getLogger(__name__)

Plane = str  # "axial" | "coronal" | "sagital"
_PLANES = ("axial", "coronal", "sagital")


def _cache_paths(session_id: str) -> tuple[Path, Path]:
    """Return (volume.npy, volume_meta.json) paths for a session."""
    d = session_subdir(session_id, "meshes")  # reuse an existing sub-dir
    return d / "_volume.npy", d / "_volume_meta.json"


def ensure_volume_cached(session_id: str) -> dict:
    """Load the primary DICOM series volume (if not already cached) and return meta.

    Meta = {shape:[z,y,x], spacing:[sz,sy,sx], wc, ww, modality}.
    The volume is saved as float32 .npy for fast per-slice memmap access.
    """
    npy_path, meta_path = _cache_paths(session_id)
    if npy_path.exists() and meta_path.exists():
        return json.loads(meta_path.read_text())

    series_id = read_state(session_id, "dicom.series_id") or ""
    dicom_dir = session_dir(session_id) / "dicom"
    logger.info("MPR: loading volume for session %s (series %s)", session_id, series_id)
    dcm = load_series(series_id, dicom_dir)

    vol = np.ascontiguousarray(dcm.volume, dtype=np.float32)
    np.save(npy_path, vol)

    meta = {
        "shape": [int(x) for x in vol.shape],
        "spacing": [float(s) for s in dcm.spacing],
        "wc": float(dcm.window_center),
        "ww": float(dcm.window_width if dcm.window_width > 1 else 400.0),
        "modality": dcm.modality,
    }
    meta_path.write_text(json.dumps(meta))
    logger.info("MPR: cached volume %s shape=%s", session_id, meta["shape"])
    return meta


@lru_cache(maxsize=4)
def _load_memmap(npy_path_str: str, mtime: float) -> np.ndarray:
    """Memmap the cached volume. mtime keys the cache so re-uploads invalidate it."""
    return np.load(npy_path_str, mmap_mode="r")


def _get_volume(session_id: str) -> np.ndarray:
    npy_path, _ = _cache_paths(session_id)
    if not npy_path.exists():
        ensure_volume_cached(session_id)
    return _load_memmap(str(npy_path), npy_path.stat().st_mtime)


def slice_count(session_id: str, plane: Plane) -> int:
    meta = ensure_volume_cached(session_id)
    z, y, x = meta["shape"]
    return {"axial": z, "coronal": y, "sagital": x}[plane]


def _extract_slice(vol: np.ndarray, plane: Plane, index: int) -> np.ndarray:
    """Return the 2-D slice for a plane, oriented for display (row=top)."""
    z, y, x = vol.shape
    if plane == "axial":
        i = int(np.clip(index, 0, z - 1))
        return np.asarray(vol[i, :, :])
    if plane == "coronal":
        i = int(np.clip(index, 0, y - 1))
        # flip Z so superior is up
        return np.asarray(vol[::-1, i, :])
    i = int(np.clip(index, 0, x - 1))
    return np.asarray(vol[::-1, :, i])


def _apply_window(slc: np.ndarray, wc: float, ww: float) -> np.ndarray:
    """Window/level → uint8, same formula as the desktop SliceWidget."""
    ww = max(1.0, ww)
    lo = wc - ww / 2.0
    hi = wc + ww / 2.0
    return ((np.clip(slc, lo, hi) - lo) / (hi - lo) * 255.0).astype(np.uint8)


def render_slice_png(
    session_id: str,
    plane: Plane,
    index: int,
    wc: float | None = None,
    ww: float | None = None,
) -> bytes:
    """Return a PNG (grayscale) of the requested slice with windowing applied."""
    from PIL import Image

    if plane not in _PLANES:
        raise ValueError(f"plane must be one of {_PLANES}, got {plane!r}")

    meta = ensure_volume_cached(session_id)
    vol = _get_volume(session_id)

    if wc is None:
        wc = meta["wc"]
    if ww is None:
        ww = meta["ww"]

    slc = _extract_slice(vol, plane, index)
    img8 = _apply_window(slc, wc, ww)

    buf = io.BytesIO()
    Image.fromarray(img8, mode="L").save(buf, format="PNG")
    return buf.getvalue()
