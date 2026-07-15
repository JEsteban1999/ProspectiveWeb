"""DICOM loading service — SimpleITK + pydicom, zero Qt dependencies.

Adapted from prospective/dicom/loader.py + series.py.
All logic preserved: multi-file series, Enhanced multi-frame fallback,
2D-projection detection, spacing extraction from SharedFunctionalGroupsSequence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Modalities treated as projections (2D angiography)
_XA_MODALITIES = {"XA", "RF", "DX", "CR", "DR"}


# ── Result dataclass ───────────────────────────────────────────────────────── #

@dataclass
class DicomLoadResult:
    """Everything produced by loading one DICOM series."""
    volume:             np.ndarray                  # (z, y, x) float32 HU
    spacing:            tuple[float, float, float]  # (sz, sy, sx) mm
    origin:             tuple[float, float, float]
    modality:           str
    series_uid:         str
    series_description: str
    patient_name:       str
    patient_id:         str
    study_date:         str
    window_center:      float
    window_width:       float
    n_slices:           int
    is_projection:      bool
    projection_warning: str | None

    @property
    def size_mb(self) -> float:
        """Estimated RAM footprint of the volume array (MB)."""
        return float(self.volume.nbytes) / 1e6


# ── Public API ─────────────────────────────────────────────────────────────── #

def scan_series(dicom_dir: Path) -> list[dict]:
    """Scan *dicom_dir* and return lightweight metadata for every series found.

    No volume is loaded — only DICOM headers are read.

    Returns
    -------
    list of dicts with keys:
        series_uid, n_files, description, modality, n_slices,
        spacing_x, spacing_y, spacing_z, window_center, window_width
    """
    import SimpleITK as sitk

    reader = sitk.ImageSeriesReader()
    series_ids = reader.GetGDCMSeriesIDs(str(dicom_dir))

    results: list[dict] = []
    for sid in series_ids:
        file_names = reader.GetGDCMSeriesFileNames(str(dicom_dir), sid)
        if not file_names:
            continue
        try:
            meta = _extract_metadata(Path(file_names[0]), len(file_names))
            results.append({"series_uid": sid, "n_files": len(file_names), **meta})
        except Exception as exc:
            logger.warning("Metadata read failed for series %s: %s", sid, exc)

    # Fallback: no GDCM series IDs but .dcm files exist
    if not results:
        dcm_files = sorted(dicom_dir.glob("*.dcm"))
        if dcm_files:
            try:
                meta = _extract_metadata(dcm_files[0], len(dcm_files))
                results.append({"series_uid": "unknown", "n_files": len(dcm_files), **meta})
            except Exception as exc:
                logger.warning("Fallback metadata read failed: %s", exc)

    # Sort: real 3D volumes first (more slices = more useful for planning)
    results.sort(key=lambda r: int(r.get("n_slices", 0)), reverse=True)
    return results


def load_series(series_uid: str, dicom_dir: Path) -> DicomLoadResult:
    """Load a DICOM series by Series Instance UID from *dicom_dir*.

    Uses SimpleITK ImageSeriesReader for robust multi-file sorting.
    Falls back to scanning all .dcm files if the UID cannot be resolved.

    Parameters
    ----------
    series_uid : DICOM Series Instance UID (from scan_series output)
    dicom_dir  : path to the session's dicom/ sub-directory

    Returns
    -------
    DicomLoadResult with the volume array and all metadata
    """
    import SimpleITK as sitk

    reader = sitk.ImageSeriesReader()
    file_names: list[str] = []

    # Primary: resolve by exact UID
    if series_uid and series_uid != "unknown":
        file_names = list(reader.GetGDCMSeriesFileNames(str(dicom_dir), series_uid))

    # Fallback 1: first series found in directory
    if not file_names:
        all_ids = reader.GetGDCMSeriesIDs(str(dicom_dir))
        if all_ids:
            file_names = list(reader.GetGDCMSeriesFileNames(str(dicom_dir), all_ids[0]))
            logger.info("Falling back to first series found: %s", all_ids[0])

    # Fallback 2: all .dcm files in directory
    if not file_names:
        file_names = sorted(str(p) for p in dicom_dir.glob("*.dcm"))
        logger.info("Falling back to all .dcm files (%d)", len(file_names))

    if not file_names:
        raise FileNotFoundError(
            f"No DICOM files found for series '{series_uid}' in {dicom_dir}"
        )

    # Single file → read directly with sitk.ReadImage so multi-frame files
    # (Enhanced XA / Enhanced CT-MR) load every frame as a 3-D volume.
    # ImageSeriesReader treats one file as one slice and would drop the frames.
    # Mirrors DICOMLoader._read_single_file in the desktop app.
    if len(file_names) == 1:
        logger.info("Single-file load (multi-frame aware): %s", file_names[0])
        image = sitk.ReadImage(file_names[0])
        return _image_to_result(image, Path(file_names[0]), series_uid)

    reader.SetFileNames(file_names)
    reader.MetaDataDictionaryArrayUpdateOn()
    reader.LoadPrivateTagsOn()
    image = reader.Execute()

    return _image_to_result(image, Path(file_names[0]), series_uid)


# ── Internal helpers ───────────────────────────────────────────────────────── #

def _image_to_result(
    image:      "sitk.Image",
    ref_file:   Path,
    series_uid: str,
) -> DicomLoadResult:
    """Convert a loaded SimpleITK image to DicomLoadResult."""
    import SimpleITK as sitk

    array = sitk.GetArrayFromImage(image).astype(np.float32)

    # Normalise dimensionality to 3-D (z, y, x)
    while array.ndim > 3 and array.shape[0] == 1:
        array = array[0]
    if array.ndim > 3:
        logger.warning("Volume has %d dims — taking first 3-D sub-volume", array.ndim)
        array = array[0]
    if array.ndim == 2:
        array = array[np.newaxis, ...]   # 2-D → 1 × y × x

    # Spacing: SimpleITK gives (sx, sy, sz) in mm
    raw_sp = image.GetSpacing()
    sx = float(raw_sp[0]) if len(raw_sp) > 0 else 1.0
    sy = float(raw_sp[1]) if len(raw_sp) > 1 else 1.0
    sz = float(raw_sp[2]) if len(raw_sp) > 2 else 1.0

    raw_or = image.GetOrigin()
    origin = (
        float(raw_or[0]) if len(raw_or) > 0 else 0.0,
        float(raw_or[1]) if len(raw_or) > 1 else 0.0,
        float(raw_or[2]) if len(raw_or) > 2 else 0.0,
    )

    meta = _extract_metadata(ref_file, array.shape[0])

    # Override pixel spacing from SimpleITK (more reliable after multi-file sort)
    meta["spacing_x"] = sx
    meta["spacing_y"] = sy
    meta["spacing_z"] = sz

    # Projection detection (matches desktop: slices < 10 OR sz > 4 × in-plane)
    n_slices  = array.shape[0]
    in_plane  = min(sx, sy)
    is_proj   = n_slices < 10 or (sz > 4.0 * in_plane and in_plane > 0)
    proj_warn = None
    if is_proj:
        if n_slices < 10:
            proj_warn = (
                f"Serie 2D o cuasi-2D ({n_slices} cortes). "
                "La segmentación 3D no es significativa."
            )
        else:
            proj_warn = (
                f"Espaciado Z ({sz:.2f} mm) >> espaciado en plano ({in_plane:.2f} mm). "
                "Probable proyección 2D — la segmentación 3D dará resultados incorrectos."
            )

    logger.info(
        "Loaded series %s: shape=%s spacing=(%.3f,%.3f,%.3f) modality=%s proj=%s",
        series_uid, array.shape, sz, sy, sx, meta["modality"], is_proj,
    )

    return DicomLoadResult(
        volume=array,
        spacing=(sz, sy, sx),   # (z, y, x) matches volume axes
        origin=origin,
        modality=meta["modality"],
        series_uid=series_uid,
        series_description=meta["series_description"],
        patient_name=meta["patient_name"],
        patient_id=meta["patient_id"],
        study_date=meta["study_date"],
        window_center=meta["window_center"],
        window_width=meta["window_width"],
        n_slices=n_slices,
        is_projection=is_proj,
        projection_warning=proj_warn,
    )


def _extract_metadata(dcm_path: Path, n_slices: int) -> dict:
    """Read DICOM tags from *dcm_path* using pydicom.

    Handles both classic DICOM (top-level spacing tags) and Enhanced multi-frame
    formats (spacing inside SharedFunctionalGroupsSequence).
    """
    import pydicom

    _defaults = dict(
        patient_name="",
        patient_id="",
        study_date="",
        study_description="",
        series_description="",
        modality="CT",
        spacing_x=1.0,
        spacing_y=1.0,
        spacing_z=1.0,
        window_center=40.0,
        window_width=400.0,
        n_slices=n_slices,
    )

    try:
        ds = pydicom.dcmread(str(dcm_path), stop_before_pixels=True)
    except Exception as exc:
        logger.warning("pydicom read failed %s: %s", dcm_path, exc)
        return _defaults

    def _str(tag: str, default: str = "") -> str:
        try:
            v = getattr(ds, tag, None)
            return str(v).strip() if v is not None else default
        except Exception:
            return default

    def _float(tag: str, default: float = 0.0) -> float:
        try:
            v = getattr(ds, tag, None)
            if v is None:
                return default
            if hasattr(v, "__iter__") and not isinstance(v, str):
                return float(v[0])
            return float(v)
        except Exception:
            return default

    # ── Pixel spacing & slice thickness ───────────────────────────────────── #
    raw_ps = getattr(ds, "PixelSpacing", None)
    raw_st = getattr(ds, "SliceThickness", None)

    sy, sx = 1.0, 1.0
    sz     = 1.0

    if raw_ps is not None:
        try:
            sy, sx = float(raw_ps[0]), float(raw_ps[1])
        except Exception:
            pass

    if raw_st is not None:
        try:
            sz = float(raw_st)
        except Exception:
            pass

    # Enhanced multi-frame fallback (Enhanced XA, Enhanced CT/MR)
    if raw_ps is None or raw_st is None:
        try:
            pms = ds.SharedFunctionalGroupsSequence[0].PixelMeasuresSequence[0]
            if raw_ps is None:
                ps2 = getattr(pms, "PixelSpacing", None)
                if ps2 is not None:
                    sy, sx = float(ps2[0]), float(ps2[1])
            if raw_st is None:
                st2 = getattr(pms, "SliceThickness", None)
                if st2 is not None:
                    sz = float(st2)
        except Exception:
            pass

    # Multi-frame files (Enhanced XA/CT/MR): one .dcm holds the whole volume.
    # The real slice count is NumberOfFrames, not the file count — the desktop
    # app gets this for free by loading pixels (volume.shape[0]); here we only
    # read headers, so honour the tag explicitly.
    try:
        n_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    except Exception:
        n_frames = 1
    if n_frames > 1:
        n_slices = max(n_slices, n_frames) if n_slices > 1 else n_frames

    return dict(
        patient_name=       _str("PatientName"),
        patient_id=         _str("PatientID"),
        study_date=         _str("StudyDate"),
        study_description=  _str("StudyDescription"),
        series_description= _str("SeriesDescription"),
        modality=           _str("Modality", "CT"),
        spacing_x=          sx,
        spacing_y=          sy,
        spacing_z=          sz,
        window_center=      _float("WindowCenter", 40.0),
        window_width=       _float("WindowWidth", 400.0),
        n_slices=           n_slices,
    )
