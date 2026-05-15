"""Mesh export utilities — STL via VTK writers (backend, no Qt).

Adapted from prospective/io/mesh_exporter.py — import path only.
"""
from __future__ import annotations

import logging
from pathlib import Path

try:
    import vtkmodules.all as vtk
except ImportError:
    import vtk  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


def export_stl(poly_data, path: str | Path, binary: bool = True) -> Path:
    """Write *poly_data* to *path* as an STL file.  Returns the resolved Path."""
    p = Path(path).with_suffix(".stl")
    p.parent.mkdir(parents=True, exist_ok=True)

    writer = vtk.vtkSTLWriter()
    writer.SetInputData(poly_data)
    writer.SetFileName(str(p))
    if binary:
        writer.SetFileTypeToBinary()
    else:
        writer.SetFileTypeToASCII()
    writer.Write()

    n      = poly_data.GetNumberOfPolys()
    size_kb = p.stat().st_size / 1024
    logger.info("Exported STL: %s  (%d triangles, %.1f KB)", p, n, size_kb)
    return p


def merge_poly_datas(parts: list) -> "vtk.vtkPolyData":
    """Combine multiple vtkPolyData objects into one with vtkAppendPolyData."""
    append = vtk.vtkAppendPolyData()
    for pd in parts:
        if pd is not None and pd.GetNumberOfPoints() > 0:
            append.AddInputData(pd)
    append.Update()
    return append.GetOutput()


def apply_scale(poly_data, scale: float) -> "vtk.vtkPolyData":
    """Return a new vtkPolyData uniformly scaled by *scale*."""
    if abs(scale - 1.0) < 1e-9:
        return poly_data
    transform = vtk.vtkTransform()
    transform.Scale(scale, scale, scale)
    xf = vtk.vtkTransformPolyDataFilter()
    xf.SetInputData(poly_data)
    xf.SetTransform(transform)
    xf.Update()
    return xf.GetOutput()
