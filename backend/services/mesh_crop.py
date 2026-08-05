"""Mesh region-of-interest (ROI) cropping — port of the desktop
prospective/processing/mesh_crop.py (A-02-05b).

Two non-destructive operations; neither modifies the input mesh:

  clip_box(poly, xmin, xmax, ymin, ymax, zmin, zmax)
      Keep geometry inside an axis-aligned bounding box (six chained plane clips).

  clip_sphere(poly, center, radius)
      Keep geometry inside a sphere (single vtkClipPolyData + vtkSphere).

Both use InsideOutOn so that f(p) < 0 (inside the box/sphere) is retained. Pass
invert=True at the router level to keep the OUTSIDE instead (remove a bad blob).
"""
from __future__ import annotations

import logging

import vtk

logger = logging.getLogger(__name__)


def clip_box(
    poly: vtk.vtkPolyData,
    xmin: float, xmax: float,
    ymin: float, ymax: float,
    zmin: float, zmax: float,
    invert: bool = False,
) -> vtk.vtkPolyData:
    """Return the portion of *poly* inside (invert=False) or outside the box."""
    if poly.GetNumberOfPoints() == 0:
        return poly

    # Six planes: (normal, origin). InsideOutOn keeps f(p) = N·(p-O) < 0.
    _planes = [
        ((-1,  0,  0), (xmin,  0,    0   )),  # keep x >= xmin
        (( 1,  0,  0), (xmax,  0,    0   )),  # keep x <= xmax
        (( 0, -1,  0), (0,     ymin,  0  )),  # keep y >= ymin
        (( 0,  1,  0), (0,     ymax,  0  )),  # keep y <= ymax
        (( 0,  0, -1), (0,     0,    zmin)),  # keep z >= zmin
        (( 0,  0,  1), (0,     0,    zmax)),  # keep z <= zmax
    ]

    if invert:
        # Keep OUTSIDE the box: the outside is the union of the six half-spaces
        # outside each face, which a chained AND of clips cannot express. Use a
        # single vtkBox implicit function with InsideOutOff instead.
        box = vtk.vtkBox()
        box.SetBounds(xmin, xmax, ymin, ymax, zmin, zmax)
        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(poly)
        clipper.SetClipFunction(box)
        clipper.InsideOutOff()  # vtkBox f<0 inside; default keeps f>0 → outside
        clipper.Update()
        clean = vtk.vtkCleanPolyData()
        clean.SetInputConnection(clipper.GetOutputPort())
        clean.Update()
        result = clean.GetOutput()
        logger.info(
            "clip_box(invert): %d → %d vertices", poly.GetNumberOfPoints(),
            result.GetNumberOfPoints(),
        )
        return result

    data: vtk.vtkPolyData = poly
    for normal, origin in _planes:
        if data.GetNumberOfPoints() == 0:
            logger.debug("clip_box: mesh became empty after a plane clip — stopping early")
            break
        plane = vtk.vtkPlane()
        plane.SetNormal(*normal)
        plane.SetOrigin(*origin)

        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(data)
        clipper.SetClipFunction(plane)
        clipper.InsideOutOn()   # keep where f(p) < 0 (inside the half-space)
        clipper.Update()
        data = clipper.GetOutput()

    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(data)
    clean.Update()
    result = clean.GetOutput()

    logger.info(
        "clip_box: %d → %d vertices  (bounds [%.1f,%.1f] [%.1f,%.1f] [%.1f,%.1f])",
        poly.GetNumberOfPoints(), result.GetNumberOfPoints(),
        xmin, xmax, ymin, ymax, zmin, zmax,
    )
    return result


def clip_sphere(
    poly: vtk.vtkPolyData,
    center: tuple[float, float, float],
    radius: float,
    invert: bool = False,
) -> vtk.vtkPolyData:
    """Return the portion of *poly* inside (invert=False) or outside the sphere."""
    if poly.GetNumberOfPoints() == 0:
        return poly
    if radius <= 0:
        logger.warning("clip_sphere: radius <= 0, returning empty mesh")
        return vtk.vtkPolyData()

    sphere = vtk.vtkSphere()
    sphere.SetCenter(*center)
    sphere.SetRadius(radius)

    clipper = vtk.vtkClipPolyData()
    clipper.SetInputData(poly)
    clipper.SetClipFunction(sphere)
    if invert:
        clipper.InsideOutOff()  # keep f>0 → outside the sphere
    else:
        clipper.InsideOutOn()   # vtkSphere f(p)=|p-c|²-r²; f<0 inside → kept
    clipper.Update()

    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(clipper.GetOutputPort())
    clean.Update()
    result = clean.GetOutput()

    logger.info(
        "clip_sphere%s: %d → %d vertices  (center=(%.1f,%.1f,%.1f)  r=%.1f mm)",
        "(invert)" if invert else "",
        poly.GetNumberOfPoints(), result.GetNumberOfPoints(),
        center[0], center[1], center[2], radius,
    )
    return result
