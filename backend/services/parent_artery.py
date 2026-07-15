"""Parent artery diameter estimation → Size Ratio (SR).

Ported from the desktop prospective/processing/parent_artery.py. Estimates the
parent-artery diameter at the aneurysm neck by cutting the *full vessel* mesh
with several planes just below the neck and taking the median equivalent-circle
diameter of the largest contour. SR = max_aneurysm_diameter / parent_diameter
(Dhar 2008, ISUIA) — the most strongly validated morphometric rupture predictor.
"""
from __future__ import annotations

import logging
import math

import numpy as np
import vtk

try:
    from vtkmodules.util.numpy_support import vtk_to_numpy
except ImportError:  # pragma: no cover
    from vtk.util.numpy_support import vtk_to_numpy  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_N_SAMPLES = 8
_OFFSET_START = 1.0   # begin 1 × neck_radius below the neck
_OFFSET_END = 3.5     # end   3.5 × neck_radius below the neck


def estimate_parent_artery_diameter(
    vessel_poly: vtk.vtkPolyData,
    centroid,
    principal_axis,
    neck_mm: float,
    neck_plane_pos: float,
) -> float:
    """Estimate the parent-artery outer diameter (mm) near the neck, or 0.0."""
    if vessel_poly is None or vessel_poly.GetNumberOfPoints() == 0:
        return 0.0

    c = np.asarray(centroid, dtype=float)
    axis = np.asarray(principal_axis, dtype=float)
    n = float(np.linalg.norm(axis))
    if n < 1e-9:
        return 0.0
    axis /= n

    pts = vtk_to_numpy(vessel_poly.GetPoints().GetData()).astype(float)
    proj = (pts - c) @ axis
    p_min, p_max = float(proj.min()), float(proj.max())
    extent = p_max - p_min
    if extent <= 1e-6:
        return 0.0

    neck_abs = p_min + float(neck_plane_pos) * extent
    neck_r = max(float(neck_mm) / 2.0, 1.0)

    # Parent artery lies below the neck (toward p_min).
    sample_start = neck_abs - _OFFSET_START * neck_r
    sample_end = neck_abs - _OFFSET_END * neck_r
    if sample_end > sample_start:
        sample_start, sample_end = sample_end, sample_start
    sample_start = max(sample_start, p_min + 0.5)
    sample_end = min(sample_end, p_max - 0.5)
    if sample_start <= sample_end:
        sample_start = p_min + extent * 0.05
        sample_end = neck_abs - neck_r * 0.5

    positions = np.linspace(sample_end, sample_start, _N_SAMPLES)
    diameters: list[float] = []
    for pos in positions:
        origin = c + pos * axis
        d = _cut_largest_component_diameter(vessel_poly, origin, axis)
        if d > 0:
            diameters.append(d)

    if not diameters:
        return 0.0
    result = float(np.median(diameters))
    logger.info("parent_artery: Ø = %.2f mm (from %d samples)", result, len(diameters))
    return result


def _cut_largest_component_diameter(poly_data, origin, normal) -> float:
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

    conn = vtk.vtkConnectivityFilter()
    conn.SetInputData(cut)
    conn.SetExtractionModeToLargestRegion()
    conn.Update()
    largest = conn.GetOutput()
    if largest.GetNumberOfPoints() < 3:
        return 0.0

    stripper = vtk.vtkStripper()
    stripper.SetInputData(largest)
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
        m = id_list.GetNumberOfIds()
        if m > len(best):
            best = [id_list.GetId(i) for i in range(m)]
    if len(best) < 3:
        return 0.0

    area = _shoelace(all_pts[best], np.asarray(origin, float), np.asarray(normal, float))
    if area <= 0:
        return 0.0
    return 2.0 * math.sqrt(area / math.pi)


def _shoelace(pts: np.ndarray, origin: np.ndarray, normal: np.ndarray) -> float:
    n = normal / (np.linalg.norm(normal) + 1e-12)
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.8 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, helper); u /= np.linalg.norm(u)
    v = np.cross(n, u)
    rel = pts.astype(float) - origin.astype(float)
    x = rel @ u
    y = rel @ v
    cx, cy = x.mean(), y.mean()
    order = np.argsort(np.arctan2(y - cy, x - cx))
    x, y = x[order], y[order]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
