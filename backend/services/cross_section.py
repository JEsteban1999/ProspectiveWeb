"""Cross-section analysis along a vessel centreline — port of the desktop
processing/cross_section.py (Feature 2).

For each sample along the centreline: cut the vessel with a plane perpendicular
to the local tangent, order the contour (vtkStripper), and measure the enclosed
area with the shoelace formula. Equivalent-circle diameter = 2·√(A/π).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

logger = logging.getLogger(__name__)


@dataclass
class CrossSectionResult:
    arc_positions_mm: np.ndarray
    areas_mm2:        np.ndarray
    diameters_mm:     np.ndarray

    min_area_mm2:  float = 0.0
    max_area_mm2:  float = 0.0
    mean_area_mm2: float = 0.0
    median_area_mm2: float = 0.0

    min_diameter_mm:    float = 0.0
    max_diameter_mm:    float = 0.0
    mean_diameter_mm:   float = 0.0
    median_diameter_mm: float = 0.0

    stenosis_ratio: float = 1.0   # min_area / median_area (1.0 = uniform)


def compute_cross_sections(
    points: np.ndarray,
    poly_data: vtk.vtkPolyData,
    n_samples: int = 40,
    progress_cb=None,
) -> CrossSectionResult:
    """Measure vessel cross-sectional area at *n_samples* positions along the
    centreline defined by *points* (N, 3)."""
    _progress = progress_cb or (lambda _: None)

    pts = np.asarray(points, dtype=np.float64)
    N = len(pts)
    if N < 2:
        raise ValueError("La línea central debe tener al menos 2 puntos.")

    # Tangents (forward differences; last = penultimate)
    tangents = np.zeros_like(pts)
    tangents[:-1] = pts[1:] - pts[:-1]
    tangents[-1] = tangents[-2]
    norms = np.linalg.norm(tangents, axis=1, keepdims=True)
    norms = np.where(norms < 1e-9, 1.0, norms)
    tangents /= norms

    # Arc-length positions
    seg_lens = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    total_len = seg_lens[-1]
    if total_len < 1e-3:
        raise ValueError("La línea central es demasiado corta para el análisis.")

    # Uniform sample positions, skipping the noisy 5 % at each boundary
    margin = 0.05 * total_len
    sample_arcs = np.linspace(margin, total_len - margin, n_samples)
    sample_indices = np.interp(sample_arcs, seg_lens, np.arange(N)).astype(int)
    sample_indices = np.clip(sample_indices, 0, N - 1)

    areas = np.zeros(n_samples, dtype=np.float64)
    for k, idx in enumerate(sample_indices):
        _progress(k / n_samples)
        areas[k] = _cut_area(poly_data, pts[idx], tangents[idx])
    _progress(1.0)

    valid = areas > 0.0
    if not valid.any():
        raise ValueError(
            "No se pudo calcular ninguna sección transversal. Verifique que la "
            "malla sea cerrada y la línea central esté dentro del vaso."
        )

    arc_pos = sample_arcs[valid]
    areas_v = areas[valid]
    diams = 2.0 * np.sqrt(areas_v / np.pi)

    # IQR outlier filter (removes bifurcation / aneurysm artefacts)
    if len(areas_v) >= 8:
        q1, q3 = np.percentile(areas_v, [25, 75])
        iqr = q3 - q1
        inliers = (areas_v >= q1 - 3.0 * iqr) & (areas_v <= q3 + 3.0 * iqr)
        if inliers.sum() >= 4:
            arc_pos = arc_pos[inliers]
            areas_v = areas_v[inliers]
            diams = diams[inliers]

    min_a = float(areas_v.min())
    max_a = float(areas_v.max())
    mean_a = float(areas_v.mean())
    median_a = float(np.median(areas_v))
    stenosis = min_a / median_a if median_a > 1e-9 else 1.0

    return CrossSectionResult(
        arc_positions_mm   = arc_pos,
        areas_mm2          = areas_v,
        diameters_mm       = diams,
        min_area_mm2       = min_a,
        max_area_mm2       = max_a,
        mean_area_mm2      = mean_a,
        median_area_mm2    = median_a,
        median_diameter_mm = 2.0 * float(np.sqrt(median_a / np.pi)),
        min_diameter_mm    = float(diams.min()),
        max_diameter_mm    = float(diams.max()),
        mean_diameter_mm   = float(diams.mean()),
        stenosis_ratio     = stenosis,
    )


def _cut_area(poly_data: vtk.vtkPolyData, origin: np.ndarray, normal: np.ndarray) -> float:
    """Slice the mesh with a plane and return the enclosed 2-D area (mm²)."""
    plane = vtk.vtkPlane()
    plane.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))
    plane.SetNormal(float(normal[0]), float(normal[1]), float(normal[2]))

    cutter = vtk.vtkCutter()
    cutter.SetCutFunction(plane)
    cutter.SetInputData(poly_data)
    cutter.Update()

    cut = cutter.GetOutput()
    if cut.GetNumberOfPoints() < 3:
        return 0.0

    stripper = vtk.vtkStripper()
    stripper.SetInputData(cut)
    stripper.JoinContiguousSegmentsOn()
    stripper.Update()
    stripped = stripper.GetOutput()
    if stripped.GetNumberOfPoints() < 3:
        return 0.0

    all_pts = vtk_to_numpy(stripped.GetPoints().GetData())
    lines = stripped.GetLines()
    if lines is None or lines.GetNumberOfCells() == 0:
        return 0.0

    best: list[int] = []
    lines.InitTraversal()
    id_list = vtk.vtkIdList()
    while lines.GetNextCell(id_list):
        n = id_list.GetNumberOfIds()
        if n > len(best):
            best = [id_list.GetId(i) for i in range(n)]
    if len(best) < 3:
        return 0.0

    return _shoelace_area(all_pts[best], origin, normal)


def _shoelace_area(pts: np.ndarray, origin: np.ndarray, normal: np.ndarray) -> float:
    """2-D area of a planar polygon projected onto the cutting plane."""
    if len(pts) < 3:
        return 0.0
    n = normal.astype(float)
    n_norm = np.linalg.norm(n)
    if n_norm < 1e-9:
        return 0.0
    n = n / n_norm

    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.8 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, helper)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)

    rel = pts.astype(float) - origin.astype(float)
    x = rel @ u
    y = rel @ v

    cx, cy = x.mean(), y.mean()
    angles = np.arctan2(y - cy, x - cx)
    order = np.argsort(angles)
    x, y = x[order], y[order]

    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return float(area)
