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


@lru_cache(maxsize=4)
def _downsampled_volume(npy_path_str: str, mtime: float, max_dim: int) -> tuple:
    """Cache a strided-down float32 copy of the volume + the stride used."""
    vol = np.load(npy_path_str, mmap_mode="r")
    z, y, x = vol.shape
    stride = max(1, int(np.ceil(max(z, y, x) / float(max_dim))))
    sub = np.ascontiguousarray(vol[::stride, ::stride, ::stride], dtype=np.float32)
    return sub, stride


def _get_downsampled(session_id: str, max_dim: int = 256) -> tuple:
    npy_path, _ = _cache_paths(session_id)
    if not npy_path.exists():
        ensure_volume_cached(session_id)
    return _downsampled_volume(str(npy_path), npy_path.stat().st_mtime, max_dim)


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


def get_volume_raw_uint8(session_id: str, max_dim: int = 192) -> tuple[bytes, list[int], list[float]]:
    """Return the volume as raw uint8 bytes for client-side volume rendering.

    Downsampled by an integer stride so the largest axis is <= max_dim, and
    rescaled over a robust [p1, p99] intensity window to 0-255. Returns
    (bytes, dims[z,y,x], spacing[sz,sy,sx]).
    """
    meta = ensure_volume_cached(session_id)
    vol = _get_volume(session_id)
    z, y, x = vol.shape

    stride = max(1, int(np.ceil(max(z, y, x) / float(max_dim))))
    sub = np.ascontiguousarray(vol[::stride, ::stride, ::stride], dtype=np.float32)

    lo, hi = np.percentile(sub, [1.0, 99.0])
    if hi - lo < 1e-3:
        lo, hi = float(sub.min()), float(sub.max()) or 1.0
    u8 = np.clip((sub - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)

    sp = meta["spacing"]  # [sz, sy, sx]
    dims = [int(d) for d in u8.shape]
    spacing = [float(sp[i]) * stride for i in range(3)]
    return u8.tobytes(order="C"), dims, spacing


def render_oblique_png(
    session_id: str,
    tilt_deg: float,
    pos: float,
    axis: str = "x",
    wc: float | None = None,
    ww: float | None = None,
) -> bytes:
    """Resample an oblique plane through the volume centre and return a PNG.

    The plane starts axial and is tilted by *tilt_deg* around the x-axis
    (axis='x') or y-axis (axis='y'); *pos* in [0,1] scans it along its normal.
    """
    from PIL import Image
    from scipy.ndimage import map_coordinates

    meta = ensure_volume_cached(session_id)
    # Oblique resampling is interactive → sample from a downsampled copy for speed.
    vol, _stride = _get_downsampled(session_id, max_dim=256)
    z, y, x = vol.shape
    if wc is None:
        wc = meta["wc"]
    if ww is None:
        ww = meta["ww"]

    z0, y0, x0 = z / 2.0, y / 2.0, x / 2.0
    th = np.deg2rad(tilt_deg)
    ct, st = np.cos(th), np.sin(th)
    offset = (pos - 0.5) * z  # scan along the normal over ~volume depth

    if axis == "y":
        # Tilt the axial plane toward x: rows=y, cols=x tilted into z.
        H, W = y, x
        ii, jj = np.mgrid[0:H, 0:W].astype(np.float32)
        di, dj = ii - H / 2.0, jj - W / 2.0
        zc = z0 + dj * st - offset * ct
        yc = y0 + di
        xc = x0 + dj * ct + offset * st
    else:
        # Tilt the axial plane toward y (default): rows=y tilted into z, cols=x.
        H, W = y, x
        ii, jj = np.mgrid[0:H, 0:W].astype(np.float32)
        di, dj = ii - H / 2.0, jj - W / 2.0
        zc = z0 + di * st - offset * ct
        yc = y0 + di * ct + offset * st
        xc = x0 + dj

    coords = np.stack([zc.ravel(), yc.ravel(), xc.ravel()])
    sampled = map_coordinates(vol, coords, order=1, mode="constant", cval=float(vol.min()))
    slc = sampled.reshape(H, W)[::-1, :]  # flip so superior is up

    img8 = _apply_window(slc, wc, ww)
    buf = io.BytesIO()
    Image.fromarray(img8, mode="L").save(buf, format="PNG")
    return buf.getvalue()


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
