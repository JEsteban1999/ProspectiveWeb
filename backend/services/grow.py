"""Grow-from-seeds segmentation — port of the desktop
prospective/processing/segmentation.py::GrowSegmentationPipeline (S-3).

Region growing with SimpleITK ConnectedThreshold from user seed voxels, then
Marching Cubes → smoothing → decimation → normals. Reuses the mask post-filters
of the web SegmentationPipeline so behaviour matches the threshold pipeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import vtk

try:
    from vtkmodules.util import numpy_support as ns
except ImportError:  # pragma: no cover
    from vtk.util import numpy_support as ns  # type: ignore[no-redef]

from services.segmentation import SegmentationPipeline

logger = logging.getLogger(__name__)


@dataclass
class GrowResult:
    poly_data:           vtk.vtkPolyData
    n_vertices:          int
    n_triangles:         int
    lower_hu:            float
    upper_hu:            float
    seeds:               list[tuple[int, int, int]] = field(default_factory=list)
    n_voxels:            int = 0
    n_fragments_removed: int = 0


def grow_from_seeds(
    volume:  np.ndarray,
    spacing: tuple[float, float, float],
    seeds:   list[tuple[int, int, int]],
    lower_hu:          float = 80.0,
    upper_hu:          float = 600.0,
    smooth_iterations: int   = 15,
    smooth_pass_band:  float = 0.10,
    target_reduction:  float = 0.70,
    keep_top_n:        int   = 1,
    morpho_closing_mm: float = 0.5,
) -> GrowResult:
    """Region-grow from seed voxels and build a surface mesh.

    Parameters
    ----------
    volume:   (Z, Y, X) HU array.
    spacing:  (sz, sy, sx) in mm.
    seeds:    list of (z, y, x) voxel indices (at least one).
    """
    try:
        import SimpleITK as sitk
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "SimpleITK is required for grow-from-seeds segmentation."
        ) from exc

    if not seeds:
        raise ValueError("Se requiere al menos una semilla.")

    nz, ny, nx = volume.shape
    # Clamp seeds into bounds and drop any that fall outside the volume.
    clamped: list[tuple[int, int, int]] = []
    for z, y, x in seeds:
        z = int(min(max(z, 0), nz - 1))
        y = int(min(max(y, 0), ny - 1))
        x = int(min(max(x, 0), nx - 1))
        clamped.append((z, y, x))
    seeds = clamped

    logger.info(
        "Grow-from-seeds: lower=%.0f upper=%.0f seeds=%s shape=%s",
        lower_hu, upper_hu, seeds, volume.shape,
    )

    sz, sy, sx = spacing

    # ── 1. numpy → SimpleITK ───────────────────────────────────────────────── #
    vol_f32 = np.ascontiguousarray(volume, dtype=np.float32)
    sitk_img = sitk.GetImageFromArray(vol_f32)          # (Z,Y,X) → ITK (X,Y,Z)
    sitk_img.SetSpacing((float(sx), float(sy), float(sz)))

    # ── 2. ConnectedThreshold (ITK seed order is x,y,z) ────────────────────── #
    sitk_seeds = [(int(x), int(y), int(z)) for z, y, x in seeds]
    seg = sitk.ConnectedThreshold(
        sitk_img,
        seedList=sitk_seeds,
        lower=float(lower_hu),
        upper=float(upper_hu),
        replaceValue=1,
    )
    mask = sitk.GetArrayFromImage(seg).astype(np.uint8)
    n_voxels = int(mask.sum())
    logger.info("ConnectedThreshold: %d voxels", n_voxels)

    if n_voxels == 0:
        raise ValueError(
            f"No se encontraron vóxeles en el rango [{lower_hu:.0f}, {upper_hu:.0f}] "
            "conectados a la(s) semilla(s). Ajusta el rango HU o recoloca la semilla "
            "sobre el vaso."
        )

    # ── 2b. Optional morphological closing (fills thin-vessel gaps) ────────── #
    mask_f = mask.astype(np.float32)
    if morpho_closing_mm > 0.0:
        mask_f = SegmentationPipeline._morpho_closing(mask_f, spacing, morpho_closing_mm)

    # ── 2c. Optional component filter (drop satellite leaks) ───────────────── #
    n_fragments_removed = 0
    if keep_top_n > 0:
        mask_f, n_fragments_removed = SegmentationPipeline._filter_mask_components(
            mask_f, 0, keep_top_n
        )
    n_voxels = int(mask_f.sum())

    # ── 3. binary mask → vtkImageData ──────────────────────────────────────── #
    img = vtk.vtkImageData()
    img.SetDimensions(nx, ny, nz)
    img.SetSpacing(float(sx), float(sy), float(sz))
    img.SetOrigin(0.0, 0.0, 0.0)
    flat = np.ascontiguousarray(mask_f, dtype=np.float32).ravel(order="C")
    arr = ns.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_FLOAT)
    arr.SetName("mask")
    img.GetPointData().SetScalars(arr)

    # ── 4. Marching Cubes ──────────────────────────────────────────────────── #
    mc = vtk.vtkMarchingCubes()
    mc.SetInputData(img)
    mc.SetValue(0, 0.5)
    mc.ComputeNormalsOff()
    mc.ComputeGradientsOff()
    mc.Update()
    if mc.GetOutput().GetNumberOfPolys() == 0:
        raise ValueError(
            "Marching Cubes no produjo triángulos: la región es demasiado pequeña "
            "o son vóxeles aislados."
        )

    prev_port = mc.GetOutputPort()

    # ── 5. Smoothing ───────────────────────────────────────────────────────── #
    if smooth_iterations > 0:
        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputConnection(prev_port)
        smoother.SetNumberOfIterations(smooth_iterations)
        smoother.SetPassBand(smooth_pass_band)
        smoother.BoundarySmoothingOff()
        smoother.FeatureEdgeSmoothingOff()
        smoother.NonManifoldSmoothingOn()
        smoother.NormalizeCoordinatesOn()
        smoother.Update()
        prev_port = smoother.GetOutputPort()

    # ── 6. Decimation ──────────────────────────────────────────────────────── #
    if target_reduction > 0:
        decimate = vtk.vtkQuadricDecimation()
        decimate.SetInputConnection(prev_port)
        decimate.SetTargetReduction(target_reduction)
        decimate.Update()
        prev_port = decimate.GetOutputPort()

    # ── 7. Normals ─────────────────────────────────────────────────────────── #
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
    n_tris = poly.GetNumberOfPolys()

    logger.info(
        "Grow-from-seeds done — %d verts, %d tris, %d voxels, %d fragments removed",
        n_verts, n_tris, n_voxels, n_fragments_removed,
    )

    return GrowResult(
        poly_data=poly,
        n_vertices=n_verts,
        n_triangles=n_tris,
        lower_hu=lower_hu,
        upper_hu=upper_hu,
        seeds=list(seeds),
        n_voxels=n_voxels,
        n_fragments_removed=n_fragments_removed,
    )
