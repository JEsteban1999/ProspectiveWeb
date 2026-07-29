"""Semi-automatic aneurysm-sac isolation (Tier 2).

The aneurysm detector returns an *open* curvature patch (a cap), on which
volume/neck morphometry degenerates (see services/morphometrics.py Tier-1
guard).  Fully-automatic sac isolation is unreliable because the aneurysm is a
small bulge embedded in a dense, connected vessel tree with no clean waist to
clip at.

This module implements the robust, clinically-standard alternative: the user
supplies a **neck plane** (an origin point and a normal pointing toward the
dome).  We then

  1. measure the neck diameter directly from the plane∩tree contour (exact —
     no blind search),
  2. clip the vessel tree at the plane, keep the dome-side connected component,
  3. cap the clip opening → a closed, watertight sac suitable for morphometry.

The resulting sac passes the Tier-1 reliability guard, so the existing
MorphometricAnalyzer produces valid volume / DNR / AR / BF / SR.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import vtk

try:
    from vtkmodules.util import numpy_support as ns
except ImportError:  # pragma: no cover
    from vtk.util import numpy_support as ns  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


@dataclass
class ClosedSac:
    """Result of semi-automatic sac isolation."""

    poly_data: vtk.vtkPolyData    # closed, watertight sac mesh
    neck_diameter_mm: float       # equivalent-circle Ø of the neck contour
    neck_area_mm2: float          # enclosed area of the neck contour
    neck_origin: tuple[float, float, float]
    neck_normal: tuple[float, float, float]
    n_boundary_edges: int         # 0 → watertight


def _largest_or_nearest_loop(
    cut: vtk.vtkPolyData,
    seed: np.ndarray,
) -> vtk.vtkPolyData:
    """Connected loop of *cut* closest to *seed* (the dome side)."""
    cc = vtk.vtkConnectivityFilter()
    cc.SetInputData(cut)
    cc.SetExtractionModeToClosestPointRegion()
    cc.SetClosestPoint(*[float(x) for x in seed])
    cc.Update()
    return cc.GetOutput()


def _contour_area(loop: vtk.vtkPolyData) -> float:
    """Enclosed planar area (mm²) of a closed contour loop."""
    if loop is None or loop.GetNumberOfPoints() < 3:
        return 0.0
    strip = vtk.vtkStripper()
    strip.SetInputData(loop)
    strip.Update()
    tri = vtk.vtkContourTriangulator()
    tri.SetInputData(strip.GetOutput())
    tri.Update()
    mp = vtk.vtkMassProperties()
    mp.SetInputData(tri.GetOutput())
    mp.Update()
    return float(mp.GetSurfaceArea())


def measure_neck(
    vessel_poly: vtk.vtkPolyData,
    origin: np.ndarray,
    normal: np.ndarray,
    dome_seed: np.ndarray,
) -> tuple[float, float]:
    """Neck (Ø_mm, area_mm²) from the vessel∩plane contour nearest the dome.

    Equivalent-circle diameter Ø = 2·√(A/π).  Returns (0, 0) if the plane does
    not cut the mesh near the dome.
    """
    plane = vtk.vtkPlane()
    plane.SetOrigin(*[float(x) for x in origin])
    plane.SetNormal(*[float(x) for x in normal])

    cutter = vtk.vtkCutter()
    cutter.SetInputData(vessel_poly)
    cutter.SetCutFunction(plane)
    cutter.Update()
    cut = cutter.GetOutput()
    if cut.GetNumberOfPoints() < 3:
        return 0.0, 0.0

    loop = _largest_or_nearest_loop(cut, dome_seed)
    area = _contour_area(loop)
    diam = 2.0 * math.sqrt(area / math.pi) if area > 0 else 0.0
    return diam, area


def isolate_closed_sac(
    vessel_poly: vtk.vtkPolyData,
    neck_origin,
    neck_normal,
    dome_seed=None,
) -> ClosedSac:
    """Clip the vessel tree at the neck plane and return a closed sac.

    Parameters
    ----------
    vessel_poly:
        The full vascular tree mesh.
    neck_origin:
        A point on the neck plane (world mm).
    neck_normal:
        Plane normal pointing toward the dome (world).  The dome side (where
        the mesh is kept) is the ``+normal`` half-space.
    dome_seed:
        Optional point inside the dome used to pick the connected component and
        the neck contour loop.  Defaults to ``neck_origin + 3·normal``.
    """
    origin = np.asarray(neck_origin, dtype=np.float64)
    normal = np.asarray(neck_normal, dtype=np.float64)
    normal = normal / (np.linalg.norm(normal) or 1.0)
    seed = (np.asarray(dome_seed, dtype=np.float64)
            if dome_seed is not None else origin + 3.0 * normal)

    # 1) Neck diameter from the clip contour (exact, no blind search).
    neck_diam, neck_area = measure_neck(vessel_poly, origin, normal, seed)

    # 2) Clip: keep the dome-side half-space (implicit fn > 0 = +normal side).
    plane = vtk.vtkPlane()
    plane.SetOrigin(*[float(x) for x in origin])
    plane.SetNormal(*[float(x) for x in normal])
    clip = vtk.vtkClipPolyData()
    clip.SetInputData(vessel_poly)
    clip.SetClipFunction(plane)
    clip.SetValue(0.0)
    clip.InsideOutOff()          # keep f(x) > 0  (the +normal / dome side)
    clip.Update()

    # 3) Keep the connected component that contains the dome.
    comp = _largest_or_nearest_loop(clip.GetOutput(), seed)

    surf = vtk.vtkGeometryFilter()
    surf.SetInputData(comp)
    surf.Update()

    # 4) Cap the clip opening → closed sac.  A plane clip leaves a single clean
    #    loop, so vtkFillHolesFilter closes it (unlike the ragged detector cap).
    fill = vtk.vtkFillHolesFilter()
    fill.SetInputData(surf.GetOutput())
    fill.SetHoleSize(1.0e6)
    fill.Update()

    # 5) Consistent outward normals (vtkMassProperties needs them for volume).
    nrm = vtk.vtkPolyDataNormals()
    nrm.SetInputData(fill.GetOutput())
    nrm.ConsistencyOn()
    nrm.SplittingOff()
    nrm.AutoOrientNormalsOn()
    nrm.Update()
    sac = nrm.GetOutput()

    n_boundary = _boundary_edge_count(sac)
    if n_boundary:
        logger.warning("Isolated sac not watertight — %d boundary edges", n_boundary)

    return ClosedSac(
        poly_data=sac,
        neck_diameter_mm=neck_diam,
        neck_area_mm2=neck_area,
        neck_origin=tuple(float(x) for x in origin),
        neck_normal=tuple(float(x) for x in normal),
        n_boundary_edges=n_boundary,
    )


def _boundary_edge_count(poly_data: vtk.vtkPolyData) -> int:
    fe = vtk.vtkFeatureEdges()
    fe.SetInputData(poly_data)
    fe.BoundaryEdgesOn()
    fe.FeatureEdgesOff()
    fe.NonManifoldEdgesOff()
    fe.ManifoldEdgesOff()
    fe.Update()
    return int(fe.GetOutput().GetNumberOfCells())
