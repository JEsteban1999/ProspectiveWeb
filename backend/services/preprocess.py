"""DICOM volume preprocessing — port of the desktop
prospective/dicom/preprocessor.py.

Optional pipeline applied to a session's cached HU volume:
  1. HU clipping   — clamp extreme outliers to [-1000, 3000]
  2. Isotropic resampling — resample to cubic voxels (target mm)
  3. Gaussian smoothing   — mild noise reduction

Plus a standalone bone-subtraction utility for cleaner CTA volume rendering.
Works on the (Z, Y, X) HU arrays the MPR service caches.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

HU_MIN = -1000.0
HU_MAX = 3000.0


def preprocess_volume(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    clip_hu: bool = True,
    resample_isotropic: bool = False,
    target_spacing_mm: float = 0.5,
    smooth: bool = False,
    smooth_sigma: float = 0.5,
) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Return (new_volume, new_spacing) after the requested preprocessing.

    volume:  (Z, Y, X) HU array.  spacing: (sz, sy, sx) in mm.
    """
    import SimpleITK as sitk

    vol = np.ascontiguousarray(volume, dtype=np.float32)
    sz, sy, sx = (float(s) for s in spacing)
    img = sitk.GetImageFromArray(vol)          # (Z,Y,X) → ITK (X,Y,Z)
    img.SetSpacing((sx, sy, sz))

    if clip_hu:
        img = sitk.Clamp(img, sitk.sitkFloat32, HU_MIN, HU_MAX)

    if resample_isotropic:
        img = _resample(img, float(target_spacing_mm))

    if smooth and smooth_sigma > 0:
        img = sitk.SmoothingRecursiveGaussian(img, float(smooth_sigma))

    out = sitk.GetArrayFromImage(img).astype(np.float32)   # (Z,Y,X)
    osx, osy, osz = img.GetSpacing()
    logger.info(
        "Preprocess: %s @ %s → %s @ (%.3f,%.3f,%.3f) (clip=%s iso=%s smooth=%s)",
        volume.shape, spacing, out.shape, osz, osy, osx,
        clip_hu, resample_isotropic, smooth,
    )
    return out, (float(osz), float(osy), float(osx))


def _resample(image, target_mm: float):
    import SimpleITK as sitk

    original_spacing = image.GetSpacing()
    original_size = image.GetSize()
    new_spacing = (target_mm, target_mm, target_mm)
    new_size = [int(round(osz * ospc / target_mm)) for osz, ospc in zip(original_size, original_spacing)]

    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing(new_spacing)
    resampler.SetSize(new_size)
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetTransform(sitk.Transform())
    resampler.SetDefaultPixelValue(-1000.0)
    resampler.SetInterpolator(sitk.sitkLinear)
    return resampler.Execute(image)


def subtract_bone(volume: np.ndarray, bone_threshold_hu: float = 300.0) -> np.ndarray:
    """Return a copy of *volume* with bone voxels (> threshold HU) set to air (-1000)."""
    result = volume.copy()
    result[result > bone_threshold_hu] = -1000.0
    return result
