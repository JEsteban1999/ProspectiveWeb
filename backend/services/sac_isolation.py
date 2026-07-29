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
    max_radius: float | None = None,
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
    max_radius:
        Optional spatial bound (mm) around *dome_seed*.  Clipping the neck plane
        alone keeps every branch distal to it — including parent vessels that
        run past the neck — which inflates the sac.  When the user marks the
        dome apex, the neck→apex distance sizes the sac: only mesh within this
        radius of the apex is kept, so the isolated sac stays the aneurysm.
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
    dome_side = clip.GetOutput()

    # 2b) Optional spatial bound: keep only what is near the dome apex, so a
    #     parent vessel crossing the neck plane is not swept into the sac.
    if max_radius is not None and max_radius > 0.0:
        sphere = vtk.vtkSphere()
        sphere.SetCenter(*[float(x) for x in seed])
        sphere.SetRadius(float(max_radius))
        sclip = vtk.vtkClipPolyData()
        sclip.SetInputData(dome_side)
        sclip.SetClipFunction(sphere)
        sclip.InsideOutOn()      # keep interior of the sphere
        sclip.Update()
        dome_side = sclip.GetOutput()

    # 3) Keep the connected component that contains the dome.
    comp = _largest_or_nearest_loop(dome_side, seed)

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


def resegment_local_mesh(
    volume,
    spacing,
    center_world,
    lower: float,
    upper: float,
    half_extent_mm: float = 18.0,
) -> vtk.vtkPolyData:
    """Re-segment a *dense, full-resolution* mesh of a small box around the dome.

    The production pipeline downsamples the volume for speed, giving a coarse
    tree on which clip+cap cannot form a watertight sac.  Here we crop the
    cached full-res volume to a box around *center_world* and run marching cubes
    at full resolution (no decimation) so the local sac is finely resolved.  The
    mesh is translated back into patient/world coordinates so a neck plane placed
    on the coarse mesh still applies.

    Parameters
    ----------
    volume:        full-res volume, shape (z, y, x).
    spacing:       (sz, sy, sx) in mm.
    center_world:  (x, y, z) in mm — box centre (typically the dome seed).
    lower, upper:  HU threshold band used for segmentation.
    half_extent_mm: half box size per axis (box is 2·half wide).
    """
    import numpy as np
    from services.segmentation import SegmentationPipeline

    sz, sy, sx = float(spacing[0]), float(spacing[1]), float(spacing[2])
    zdim, ydim, xdim = volume.shape
    cx, cy, cz = (float(center_world[0]), float(center_world[1]), float(center_world[2]))

    hx = int(math.ceil(half_extent_mm / sx))
    hy = int(math.ceil(half_extent_mm / sy))
    hz = int(math.ceil(half_extent_mm / sz))
    x0 = max(0, int(round(cx / sx)) - hx); x1 = min(xdim, int(round(cx / sx)) + hx + 1)
    y0 = max(0, int(round(cy / sy)) - hy); y1 = min(ydim, int(round(cy / sy)) + hy + 1)
    z0 = max(0, int(round(cz / sz)) - hz); z1 = min(zdim, int(round(cz / sz)) + hz + 1)
    if x1 - x0 < 2 or y1 - y0 < 2 or z1 - z0 < 2:
        return vtk.vtkPolyData()

    sub = np.ascontiguousarray(volume[z0:z1, y0:y1, x0:x1])
    seg = SegmentationPipeline(
        threshold_hu=float(lower),
        threshold_max_hu=float(upper) if upper > lower else 0.0,
        smooth_iterations=3,
        smooth_pass_band=0.06,
        target_reduction=0.0,      # NO decimation → dense local mesh
        gaussian_sigma=0.5,
        min_component_verts=20,
        morpho_closing_mm=0.5,
        keep_top_n=0,
    ).run(sub, (sz, sy, sx))

    tf = vtk.vtkTransform()
    tf.Translate(x0 * sx, y0 * sy, z0 * sz)   # crop origin → world
    tpf = vtk.vtkTransformPolyDataFilter()
    tpf.SetInputData(seg.poly_data)
    tpf.SetTransform(tf)
    tpf.Update()
    return tpf.GetOutput()


def isolate_sac_volumetric(
    volume,
    spacing,
    neck_origin,
    neck_normal,
    apex,
    lower: float,
    upper: float,
    max_radius: float,
    half_extent_mm: float = 16.0,
) -> tuple[vtk.vtkPolyData, float]:
    """Isolate a *watertight* aneurysm sac in the VOLUME domain (robust).

    Surface clip + vtkFillHolesFilter is fragile: it leaves un-closeable boundary
    loops on arbitrary clip geometry, so the sac is often not watertight.  Here we
    instead build a binary mask of the sac directly from the full-res volume —

        (HU in [lower, upper])  ∧  (dome side of the neck plane)  ∧
        (within max_radius of the apex)

    keep the connected component containing the apex, and run marching cubes on
    that bounded mask.  Marching cubes on a bounded interior region always yields
    a **closed** surface, so the sac is watertight by construction; the flat neck
    cap forms automatically where the mask meets the neck-plane half-space.

    Returns ``(sac_mesh_world, neck_diameter_mm)``.
    """
    import numpy as np
    from scipy import ndimage
    from services.segmentation import SegmentationPipeline

    sz, sy, sx = float(spacing[0]), float(spacing[1]), float(spacing[2])
    zdim, ydim, xdim = volume.shape
    o = np.asarray(neck_origin, dtype=np.float64)
    n = np.asarray(neck_normal, dtype=np.float64); n = n / (np.linalg.norm(n) or 1.0)
    a = np.asarray(apex, dtype=np.float64)

    hx = int(math.ceil(half_extent_mm / sx))
    hy = int(math.ceil(half_extent_mm / sy))
    hz = int(math.ceil(half_extent_mm / sz))
    x0 = max(0, int(round(a[0] / sx)) - hx); x1 = min(xdim, int(round(a[0] / sx)) + hx + 1)
    y0 = max(0, int(round(a[1] / sy)) - hy); y1 = min(ydim, int(round(a[1] / sy)) + hy + 1)
    z0 = max(0, int(round(a[2] / sz)) - hz); z1 = min(zdim, int(round(a[2] / sz)) + hz + 1)
    if x1 - x0 < 2 or y1 - y0 < 2 or z1 - z0 < 2:
        return vtk.vtkPolyData(), 0.0

    sub = np.ascontiguousarray(volume[z0:z1, y0:y1, x0:x1]).astype(np.float32)

    # World coordinates of the sub-volume voxels (broadcast grids).
    zc = (np.arange(z0, z1) * sz)[:, None, None]
    yc = (np.arange(y0, y1) * sy)[None, :, None]
    xc = (np.arange(x0, x1) * sx)[None, None, :]
    dot   = (xc - o[0]) * n[0] + (yc - o[1]) * n[1] + (zc - o[2]) * n[2]   # >0 = dome side
    dist2 = (xc - a[0]) ** 2 + (yc - a[1]) ** 2 + (zc - a[2]) ** 2

    thr = sub >= lower
    if upper > lower:
        thr &= sub <= upper
    mask = thr & (dot > 0.0) & (dist2 <= max_radius * max_radius)
    if not mask.any():
        return vtk.vtkPolyData(), 0.0

    # Keep the connected component containing (or nearest to) the apex.
    lab, _ = ndimage.label(mask)
    aiz = int(round(a[2] / sz)) - z0
    aiy = int(round(a[1] / sy)) - y0
    aix = int(round(a[0] / sx)) - x0
    comp_id = 0
    if 0 <= aiz < lab.shape[0] and 0 <= aiy < lab.shape[1] and 0 <= aix < lab.shape[2]:
        comp_id = int(lab[aiz, aiy, aix])
    if comp_id == 0:                       # apex not on the mask → take nearest voxel
        idx = np.argwhere(mask)
        d2 = ((idx - np.array([aiz, aiy, aix])) ** 2).sum(1)
        comp_id = int(lab[tuple(idx[d2.argmin()])])
    comp = lab == comp_id

    # Marching cubes on the isolated component: pass HU inside, a sentinel below
    # the threshold outside, so the pipeline surfaces only the component.
    hu = np.where(comp, np.maximum(sub, np.float32(lower)),
                  np.float32(lower - 1000.0)).astype(np.float32)
    seg = SegmentationPipeline(
        threshold_hu=float(lower),
        threshold_max_hu=float(upper) if upper > lower else 0.0,
        smooth_iterations=5,
        smooth_pass_band=0.06,
        target_reduction=0.0,
        gaussian_sigma=0.5,
        min_component_verts=0,
        morpho_closing_mm=0.0,
        keep_top_n=0,
    ).run(hu, (sz, sy, sx))

    tf = vtk.vtkTransform()
    tf.Translate(x0 * sx, y0 * sy, z0 * sz)
    tpf = vtk.vtkTransformPolyDataFilter()
    tpf.SetInputData(seg.poly_data)
    tpf.SetTransform(tf)
    tpf.Update()
    mesh = tpf.GetOutput()

    # Neck diameter: cross-section just inside the dome (the flat cap sits on the
    # plane; sample 0.6 mm in so the contour is the true neck ostium).
    neck_diam, _ = measure_neck(mesh, (o + n * 0.6), n, a)
    return mesh, neck_diam


def _boundary_edge_count(poly_data: vtk.vtkPolyData) -> int:
    fe = vtk.vtkFeatureEdges()
    fe.SetInputData(poly_data)
    fe.BoundaryEdgesOn()
    fe.FeatureEdgesOff()
    fe.NonManifoldEdgesOff()
    fe.ManifoldEdgesOff()
    fe.Update()
    return int(fe.GetOutput().GetNumberOfCells())
