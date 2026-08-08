"""Vascular segmentation pipeline + mesh I/O.

Adapted from prospective/processing/segmentation.py — pure Python + VTK + NumPy.
Zero Qt dependencies.

Pipeline
--------
numpy volume (z, y, x)
    │
    ▼  Gaussian pre-smooth   (optional, scipy or SimpleITK)
    │
    ▼  Binary mask            (threshold band-pass or single-sided)
    │
    ▼  Morphological closing  (optional, fills micro-gaps)
    │
    ▼  Connected-component filter (keep largest N components)
    │
    ▼  vtkMarchingCubes       (iso-surface at 0.5 on binary mask)
    │
    ▼  vtkWindowedSincPolyDataFilter  (mesh smoothing)
    │
    ▼  vtkQuadricDecimation   (polygon count reduction)
    │
    ▼  vtkPolyDataNormals     (smooth normals for shading)
    │
    vtkPolyData  →  .vtp (vtk.js) / .stl (3D printing)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import vtk

try:
    from vtkmodules.util import numpy_support as ns
except ImportError:
    from vtk.util import numpy_support as ns  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ── Result dataclass ───────────────────────────────────────────────────────── #

@dataclass
class SegmentationResult:
    poly_data:           vtk.vtkPolyData
    n_vertices:          int
    n_triangles:         int
    threshold_hu:        float
    reduction_pct:       float         # actual decimation achieved
    n_fragments_removed: int = 0
    is_preview:          bool = False


# ── Main pipeline ──────────────────────────────────────────────────────────── #

class SegmentationPipeline:
    """Extract an iso-surface from a CT/XA volume using VTK Marching Cubes.

    Parameters
    ----------
    threshold_hu      : lower iso-surface value in HU (or raw units for XA)
    threshold_max_hu  : upper bound (0 = disabled, single-sided threshold)
    smooth_iterations : WindowedSinc iterations (0 = skip)
    smooth_pass_band  : pass-band [0–2], lower = smoother (default 0.06)
    target_reduction  : fraction of triangles to remove (default 0.70)
    gaussian_sigma    : pre-smoothing std-dev in voxels (0 = skip, default 0.5)
    min_component_verts : discard fragments < this many vertices (0 = keep all)
    vessel_lower_hu   : secondary lower threshold for thin-vessel recovery (0 = off)
    vessel_dilation_mm: dilation radius around primary mask for thin-vessel recovery
    morpho_closing_mm : morphological closing radius in mm (0 = off)
    keep_top_n        : keep only N largest components (0 = use min_component_verts)
    """

    def __init__(
        self,
        threshold_hu:        float = 150.0,
        threshold_max_hu:    float = 0.0,
        smooth_iterations:   int   = 20,
        smooth_pass_band:    float = 0.06,
        target_reduction:    float = 0.70,
        gaussian_sigma:      float = 0.5,
        min_component_verts: int   = 100,
        vessel_lower_hu:     float = 0.0,
        vessel_dilation_mm:  float = 3.0,
        morpho_closing_mm:   float = 0.0,
        keep_top_n:          int   = 0,
    ) -> None:
        self.threshold_hu        = threshold_hu
        self.threshold_max_hu    = threshold_max_hu
        self.smooth_iterations   = smooth_iterations
        self.smooth_pass_band    = smooth_pass_band
        self.target_reduction    = target_reduction
        self.gaussian_sigma      = gaussian_sigma
        self.min_component_verts = min_component_verts
        self.vessel_lower_hu     = vessel_lower_hu
        self.vessel_dilation_mm  = vessel_dilation_mm
        self.morpho_closing_mm   = morpho_closing_mm
        self.keep_top_n          = keep_top_n

    # ── Public API ─────────────────────────────────────────────────────────── #

    def run(
        self,
        volume:  np.ndarray,
        spacing: tuple[float, float, float],
    ) -> SegmentationResult:
        """Execute full pipeline on *volume* (z,y,x float32).

        Parameters
        ----------
        volume  : float32 array (z, y, x) in HU
        spacing : (sz, sy, sx) in mm

        Returns
        -------
        SegmentationResult with vtkPolyData and mesh statistics
        """
        use_dual = (
            self.vessel_lower_hu > 0
            and self.vessel_lower_hu < self.threshold_hu
        )
        use_max = self.threshold_max_hu > self.threshold_hu

        logger.info(
            "Segmentation started — threshold=%.0f HU  max=%.0f HU  "
            "dual=%s  closing=%.1f mm  top_n=%d  shape=%s",
            self.threshold_hu,
            self.threshold_max_hu if use_max else float("inf"),
            use_dual, self.morpho_closing_mm, self.keep_top_n, volume.shape,
        )

        # 1. Gaussian pre-smooth
        vol_f = volume.astype(np.float32)
        if self.gaussian_sigma > 0.0:
            vol_f = self._numpy_gaussian(vol_f, self.gaussian_sigma)

        # 2. Binary mask
        if use_dual:
            mask = self._dual_threshold_mask(
                vol_f, spacing, self.threshold_hu,
                self.vessel_lower_hu, self.vessel_dilation_mm,
            )
            if use_max:
                mask = mask * (vol_f <= self.threshold_max_hu).astype(np.float32)
        elif use_max:
            mask = ((vol_f >= self.threshold_hu) & (vol_f <= self.threshold_max_hu)).astype(np.float32)
        else:
            mask = (vol_f >= self.threshold_hu).astype(np.float32)

        # 3. Morphological closing
        if self.morpho_closing_mm > 0.0:
            mask = self._morpho_closing(mask, spacing, self.morpho_closing_mm)

        # 4. Connected-component filtering in mask space
        n_fragments_removed = 0
        if self.keep_top_n > 0 or self.min_component_verts > 0:
            mask, n_fragments_removed = self._filter_mask_components(
                mask, self.min_component_verts, self.keep_top_n,
            )

        # 5. Marching Cubes on binary mask at iso=0.5
        mc_input = self._to_vtk_image(mask, spacing)
        mc = vtk.vtkMarchingCubes()
        mc.SetInputData(mc_input)
        mc.SetValue(0, 0.5)
        mc.ComputeNormalsOff()
        mc.ComputeGradientsOff()
        mc.Update()

        n_raw = mc.GetOutput().GetNumberOfPolys()
        logger.info("Marching Cubes: %d triangles", n_raw)

        if n_raw == 0:
            n_sel = int(mask.sum())
            vmax  = float(vol_f.max())
            if n_sel == 0:
                raise ValueError(
                    f"Ningún vóxel supera el umbral inferior de {self.threshold_hu:.0f} HU "
                    f"(intensidad máxima del volumen = {vmax:.0f}). Baja el umbral inferior."
                )
            raise ValueError(
                f"El umbral de {self.threshold_hu:.0f} HU selecciona {n_sel} vóxeles, pero no "
                "forman una superficie (volumen demasiado fino o todo fragmentos pequeños). "
                "Prueba la serie principal del estudio o reduce la limpieza de fragmentos."
            )

        # 6. Smoothing
        if self.smooth_iterations > 0:
            smoother = vtk.vtkWindowedSincPolyDataFilter()
            smoother.SetInputConnection(mc.GetOutputPort())
            smoother.SetNumberOfIterations(self.smooth_iterations)
            smoother.SetPassBand(self.smooth_pass_band)
            smoother.BoundarySmoothingOff()
            smoother.FeatureEdgeSmoothingOff()
            smoother.NonManifoldSmoothingOn()
            smoother.NormalizeCoordinatesOn()
            smoother.Update()
            prev_port = smoother.GetOutputPort()
        else:
            prev_port = mc.GetOutputPort()

        # 7. Decimation
        if self.target_reduction > 0:
            decimate = vtk.vtkQuadricDecimation()
            decimate.SetInputConnection(prev_port)
            decimate.SetTargetReduction(self.target_reduction)
            decimate.Update()
            prev_port = decimate.GetOutputPort()

        # 8. Normals for smooth shading
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(prev_port)
        normals.ComputePointNormalsOn()
        normals.ComputeCellNormalsOff()
        normals.SplittingOff()
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.Update()

        poly = normals.GetOutput()
        n_verts = poly.GetNumberOfPoints()
        n_tris  = poly.GetNumberOfPolys()
        actual_reduction = 1.0 - n_tris / max(n_raw, 1)

        logger.info(
            "Segmentation done — %d verts, %d tris (%.0f%% reduction) "
            "%d fragments removed",
            n_verts, n_tris, actual_reduction * 100, n_fragments_removed,
        )

        return SegmentationResult(
            poly_data=poly,
            n_vertices=n_verts,
            n_triangles=n_tris,
            threshold_hu=self.threshold_hu,
            reduction_pct=actual_reduction * 100,
            n_fragments_removed=n_fragments_removed,
        )

    def run_fast_preview(
        self,
        volume:     np.ndarray,
        spacing:    tuple[float, float, float],
        downsample: int = 2,
    ) -> SegmentationResult:
        """Rapid preview: downsampled volume, no smoothing/decimation.

        ~8× faster than run() with downsample=2. Used for interactive
        threshold parameter tuning in the frontend.
        """
        s     = max(1, int(downsample))
        vol_d = volume[::s, ::s, ::s]
        sp_d  = tuple(sp * s for sp in spacing)

        _use_max = self.threshold_max_hu > self.threshold_hu
        if _use_max:
            mask = (
                (vol_d >= self.threshold_hu) & (vol_d <= self.threshold_max_hu)
            ).astype(np.float32)
        else:
            mask = (vol_d >= self.threshold_hu).astype(np.float32)

        kn = self.keep_top_n if self.keep_top_n > 0 else 20
        mask, _ = self._filter_mask_components(mask, 0, kn)

        img = self._to_vtk_image(mask, sp_d)
        mc  = vtk.vtkMarchingCubes()
        mc.SetInputData(img)
        mc.SetValue(0, 0.5)
        mc.ComputeNormalsOff()
        mc.ComputeGradientsOff()
        mc.Update()

        n_raw = mc.GetOutput().GetNumberOfPolys()
        if n_raw == 0:
            raise ValueError(
                f"No iso-surface at {self.threshold_hu:.0f} HU in preview. "
                "Try lowering the threshold."
            )

        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputConnection(mc.GetOutputPort())
        smoother.SetNumberOfIterations(5)
        smoother.SetPassBand(0.10)
        smoother.NormalizeCoordinatesOn()
        smoother.Update()

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(smoother.GetOutputPort())
        normals.ComputePointNormalsOn()
        normals.ComputeCellNormalsOff()
        normals.SplittingOff()
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.Update()

        poly = normals.GetOutput()
        return SegmentationResult(
            poly_data=poly,
            n_vertices=poly.GetNumberOfPoints(),
            n_triangles=poly.GetNumberOfPolys(),
            threshold_hu=self.threshold_hu,
            reduction_pct=0.0,
            n_fragments_removed=0,
            is_preview=True,
        )

    # ── Static helpers ─────────────────────────────────────────────────────── #

    @staticmethod
    def _morpho_closing(
        mask:       np.ndarray,
        spacing:    tuple[float, float, float],
        closing_mm: float,
    ) -> np.ndarray:
        min_sp = min(float(spacing[0]), float(spacing[1]), float(spacing[2]))
        radius = max(1, round(closing_mm / min_sp))
        try:
            import SimpleITK as sitk
            sz, sy, sx = spacing
            sitk_mask = sitk.GetImageFromArray(mask.astype(np.uint8))
            sitk_mask.SetSpacing((float(sx), float(sy), float(sz)))
            closed = sitk.BinaryMorphologicalClosing(sitk_mask, [radius, radius, radius])
            return sitk.GetArrayFromImage(closed).astype(np.float32)
        except Exception:
            pass
        try:
            from scipy.ndimage import binary_closing, generate_binary_structure
            struct = generate_binary_structure(3, 1)
            closed = binary_closing(mask.astype(bool), structure=struct, iterations=radius)
            return closed.astype(np.float32)
        except Exception as exc:
            logger.warning("Morphological closing skipped: %s", exc)
            return mask.astype(np.float32)

    @staticmethod
    def _filter_mask_components(
        mask:        np.ndarray,
        min_voxels:  int,
        keep_top_n:  int,
    ) -> tuple[np.ndarray, int]:
        try:
            from scipy.ndimage import label as scipy_label
        except ImportError:
            logger.warning("scipy not available — component filtering skipped")
            return mask.astype(np.float32), 0

        labeled, n_labels = scipy_label(mask.astype(bool))
        if n_labels <= 1:
            return mask.astype(np.float32), 0

        sizes = np.bincount(labeled.ravel())
        component_list = [(int(sizes[i + 1]), i + 1) for i in range(n_labels)]

        if keep_top_n > 0:
            component_list.sort(key=lambda x: x[0], reverse=True)
            keep_set = {idx for _, idx in component_list[:keep_top_n]}
        else:
            keep_set = {idx for sz, idx in component_list if sz >= min_voxels}
            if not keep_set:
                keep_set = {max(component_list, key=lambda x: x[0])[1]}

        n_removed = n_labels - len(keep_set)
        if n_removed == 0:
            return mask.astype(np.float32), 0

        result = np.isin(labeled, list(keep_set)).astype(np.float32)
        logger.info(
            "Component filter: kept %d/%d components (%s)",
            len(keep_set), n_labels,
            f"top-{keep_top_n}" if keep_top_n > 0 else f"≥{min_voxels} voxels",
        )
        return result, n_removed

    @staticmethod
    def _dual_threshold_mask(
        volume:        np.ndarray,
        spacing:       tuple[float, float, float],
        main_hu:       float,
        vessel_hu:     float,
        dilation_mm:   float,
    ) -> np.ndarray:
        try:
            import SimpleITK as sitk
        except ImportError:
            logger.warning("SimpleITK not found — dual threshold skipped")
            return (volume >= main_hu).astype(np.float32)

        main_mask   = (volume >= main_hu).astype(np.uint8)
        vessel_mask = (volume >= vessel_hu).astype(np.uint8)

        sz, sy, sx = spacing
        sitk_main  = sitk.GetImageFromArray(main_mask)
        sitk_main.SetSpacing((float(sx), float(sy), float(sz)))

        radius  = max(1, round(dilation_mm / min(float(sz), float(sy), float(sx))))
        dilated = sitk.BinaryDilate(sitk_main, [radius, radius, radius])
        dil_np  = sitk.GetArrayFromImage(dilated).astype(bool)

        combined = main_mask.astype(bool) | (vessel_mask.astype(bool) & dil_np)
        return combined.astype(np.float32)

    @staticmethod
    def _numpy_gaussian(volume: np.ndarray, sigma: float) -> np.ndarray:
        try:
            from scipy.ndimage import gaussian_filter
            return gaussian_filter(volume.astype(np.float32), sigma=sigma)
        except ImportError:
            pass
        try:
            import SimpleITK as sitk
            img     = sitk.GetImageFromArray(volume.astype(np.float32))
            blurred = sitk.SmoothingRecursiveGaussian(img, sigma)
            return sitk.GetArrayFromImage(blurred)
        except Exception:
            pass
        logger.warning("No Gaussian library — skipping pre-smooth")
        return volume.astype(np.float32)

    @staticmethod
    def _to_vtk_image(
        volume:  np.ndarray,
        spacing: tuple[float, float, float],
    ) -> vtk.vtkImageData:
        z, y, x = volume.shape
        sz, sy, sx = spacing

        img = vtk.vtkImageData()
        img.SetDimensions(x, y, z)
        img.SetSpacing(sx, sy, sz)
        img.SetOrigin(0.0, 0.0, 0.0)

        flat = np.ascontiguousarray(volume, dtype=np.float32).ravel()
        arr  = ns.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_FLOAT)
        arr.SetName("HU")
        img.GetPointData().SetScalars(arr)
        return img


# ── Smoothing / cleanup level → pipeline parameter maps ───────────────────── #
# smoothing level 0–10 → smooth_iterations
_SMOOTH_ITER = [0, 5, 10, 20, 25, 30, 35, 40, 45, 50, 60]
# cleanup level 0–10 → min_component_verts (or keep_top_n if 0)
_CLEANUP_VERTS = [0, 20, 50, 100, 200, 500, 800, 1200, 1500, 2000, 3000]

# Cleanup level 0–10 → (keep_top_n, min_voxels, morpho_closing_mm), ported from
# the desktop segmentation panel (_LIMPIEZA_MAP). From level 5 up it switches to
# TOPOLOGICAL isolation — keep only the N largest connected components — which
# removes large tissue/noise blobs a size-only filter cannot. Level 10 keeps just
# the 3 biggest structures (the clean vascular tree in a subtracted volume).
_CLEANUP_MAP: list[tuple[int, int, float]] = [
    (0,    0,  0.0),  # 0 — Ninguna
    (0,   30,  0.0),  # 1
    (0,  100,  0.0),  # 2
    (0,  200,  0.0),  # 3
    (0,  500,  0.5),  # 4
    (20,   0,  0.5),  # 5 — Media (switches to top-N)
    (15,   0,  0.5),  # 6
    (10,   0,  0.5),  # 7
    (7,    0,  1.0),  # 8
    (5,    0,  1.0),  # 9
    (3,    0,  1.0),  # 10 — Máxima: solo los 3 componentes más grandes
]


def level_to_smooth_iters(level: int) -> int:
    return _SMOOTH_ITER[max(0, min(10, level))]


def level_to_cleanup_verts(level: int) -> int:
    return _CLEANUP_VERTS[max(0, min(10, level))]


def level_to_cleanup(level: int) -> tuple[int, int, float]:
    """Cleanup level 0–10 → (keep_top_n, min_voxels, morpho_closing_mm)."""
    return _CLEANUP_MAP[max(0, min(10, level))]


# ── Mesh I/O ───────────────────────────────────────────────────────────────── #

def write_vtp(poly_data: vtk.vtkPolyData, path: str | Path) -> None:
    """Write *poly_data* to an XML VTP file (vtk.js compatible, binary mode)."""
    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(poly_data)
    writer.SetDataModeToBinary()   # smaller than ASCII
    writer.Write()
    logger.info("Wrote VTP: %s (%d verts, %d tris)",
                path, poly_data.GetNumberOfPoints(), poly_data.GetNumberOfPolys())


def write_stl(poly_data: vtk.vtkPolyData, path: str | Path) -> None:
    """Write *poly_data* to a binary STL file (3D printing)."""
    writer = vtk.vtkSTLWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(poly_data)
    writer.SetFileTypeToBinary()
    writer.Write()
    logger.info("Wrote STL: %s", path)


def read_vtp(path: str | Path) -> vtk.vtkPolyData:
    """Read a .vtp (VTK XML PolyData) file and return the vtkPolyData.

    Used by detection, morphometry and perforator routers to reload
    meshes that were written during segmentation or detection.
    """
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    poly = reader.GetOutput()
    logger.info(
        "Read VTP: %s (%d verts, %d tris)",
        path, poly.GetNumberOfPoints(), poly.GetNumberOfPolys(),
    )
    return poly


def voxel_fraction(
    volume: np.ndarray,
    lower:  float,
    upper:  float,
) -> float:
    """Return the fraction of voxels in [lower, upper] (0–1)."""
    flat = volume.ravel().astype("float32")
    return float(np.mean((flat >= lower) & (flat <= upper)))
