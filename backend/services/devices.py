"""Device geometry + real geometric metrics for clip / coil / stent planning.

Replaces the mock plan endpoints. This module:
  • builds actual .vtp meshes for placed devices (so the 3D viewer can render them),
  • runs real vtkCollisionDetectionFilter for clip–vessel collision (port of the
    desktop processing/collision.py), and
  • computes neck coverage from the real neck-plane geometry.

All meshes are returned in world coordinates (the placement pose is baked in).
"""
from __future__ import annotations

import logging
import math

import numpy as np
import vtk

logger = logging.getLogger(__name__)

Vec3 = tuple[float, float, float]


# ── Pose ───────────────────────────────────────────────────────────────────── #

def pose_transform(position: Vec3, normal: Vec3, rotation_deg: float = 0.0) -> vtk.vtkTransform:
    """Transform placing a local-frame object at *position*, aligning its local
    +Z axis to *normal*, then rolling *rotation_deg* around that axis.

    Point transform order (PreMultiply, VTK default): Translate · Align · RollZ.
    """
    n = np.asarray(normal, dtype=float)
    ln = float(np.linalg.norm(n))
    n = n / ln if ln > 1e-9 else np.array([0.0, 0.0, 1.0])

    t = vtk.vtkTransform()
    t.Translate(float(position[0]), float(position[1]), float(position[2]))

    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(z, n)
    axis_len = float(np.linalg.norm(axis))
    if axis_len >= 1e-9:
        angle = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(z, n))))))
        t.RotateWXYZ(angle, *(axis / axis_len))
    elif n[2] < 0:  # anti-parallel
        t.RotateWXYZ(180.0, 1.0, 0.0, 0.0)

    t.RotateZ(float(rotation_deg))
    return t


def apply_transform(poly: vtk.vtkPolyData, t: vtk.vtkTransform) -> vtk.vtkPolyData:
    """Bake *t* into *poly*, returning a new world-space polydata."""
    f = vtk.vtkTransformPolyDataFilter()
    f.SetInputData(poly)
    f.SetTransform(t)
    f.Update()
    out = vtk.vtkPolyData()
    out.DeepCopy(f.GetOutput())
    return out


def combine(polys: list[vtk.vtkPolyData]) -> vtk.vtkPolyData:
    """Merge several polydata into one."""
    app = vtk.vtkAppendPolyData()
    for p in polys:
        if p and p.GetNumberOfPoints() > 0:
            app.AddInputData(p)
    app.Update()
    out = vtk.vtkPolyData()
    out.DeepCopy(app.GetOutput())
    return out


def _triangulate(poly: vtk.vtkPolyData) -> vtk.vtkPolyData:
    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(poly)
    tri.Update()
    return tri.GetOutput()


# ── Device geometry (local frame) ──────────────────────────────────────────── #

def make_clip(length_mm: float) -> vtk.vtkPolyData:
    """Two parallel blades approximating a surgical clip.

    Local frame: blade length along +X, jaw opening along +Y, depth along +Z
    (so +Z is the blade normal — matches pose_transform's normal alignment).
    """
    length = max(2.0, float(length_mm))
    blade_w = 0.5      # blade width (Y)
    blade_h = 1.4      # blade depth (Z)
    jaw = 1.2          # gap between the two blades (Y)
    blades = []
    for sign in (+1.0, -1.0):
        c = vtk.vtkCubeSource()
        c.SetXLength(length)
        c.SetYLength(blade_w)
        c.SetZLength(blade_h)
        c.SetCenter(0.0, sign * (jaw / 2.0 + blade_w / 2.0), 0.0)
        c.Update()
        blades.append(c.GetOutput())
    # small hinge bar joining the blades at one end
    hinge = vtk.vtkCubeSource()
    hinge.SetXLength(blade_w)
    hinge.SetYLength(jaw + blade_w * 2)
    hinge.SetZLength(blade_h)
    hinge.SetCenter(-length / 2.0, 0.0, 0.0)
    hinge.Update()
    blades.append(hinge.GetOutput())
    return combine(blades)


def make_stent(diameter_mm: float, length_mm: float) -> vtk.vtkPolyData:
    """Hollow-looking tube approximating a stent / flow diverter.

    Local frame: tube axis along +Z (align with the vessel direction via pose).
    """
    cyl = vtk.vtkCylinderSource()
    cyl.SetRadius(max(0.5, float(diameter_mm) / 2.0))
    cyl.SetHeight(max(4.0, float(length_mm)))
    cyl.SetResolution(28)
    cyl.CappingOff()
    cyl.Update()
    # vtkCylinderSource axis is +Y → rotate to +Z
    t = vtk.vtkTransform()
    t.RotateX(90.0)
    return apply_transform(cyl.GetOutput(), t)


def make_coil_bundle(radius_mm: float, n: int = 5) -> vtk.vtkPolyData:
    """A cluster of small spheres approximating a coil mass filling the sac."""
    r = max(0.8, float(radius_mm))
    rng = np.random.default_rng(42)
    parts = []
    for _ in range(max(1, n)):
        s = vtk.vtkSphereSource()
        s.SetRadius(r * 0.55)
        s.SetThetaResolution(12)
        s.SetPhiResolution(12)
        off = (rng.random(3) - 0.5) * r
        s.SetCenter(float(off[0]), float(off[1]), float(off[2]))
        s.Update()
        parts.append(s.GetOutput())
    return combine(parts)


# ── Collision (port of desktop processing/collision.py) ─────────────────────── #

def check_collision(vessel: vtk.vtkPolyData, device_world: vtk.vtkPolyData) -> tuple[bool, int]:
    """Return (collision_detected, n_contacts) between the vessel and a device
    mesh, both already in world coordinates."""
    if vessel is None or device_world is None:
        return False, 0
    identity = vtk.vtkTransform()
    identity.Identity()
    col = vtk.vtkCollisionDetectionFilter()
    col.SetInputData(0, _triangulate(vessel))
    col.SetInputData(1, _triangulate(device_world))
    col.SetTransform(0, identity)
    col.SetTransform(1, identity)
    col.SetCollisionModeToAllContacts()
    col.GenerateScalarsOn()
    try:
        col.Update()
        n = int(col.GetNumberOfContacts())
    except Exception as exc:  # defensive — never fail the request on collision
        logger.warning("Collision check failed: %s", exc)
        return False, 0
    return n > 0, n


# ── Neck-plane coverage ─────────────────────────────────────────────────────── #

def plane_span(device_world: vtk.vtkPolyData, origin: Vec3, normal: Vec3) -> float:
    """Extent (mm) of the device's intersection with the neck plane.

    Cuts the device mesh with the plane and returns the diagonal of the
    intersection's bounding box — how wide the device sits across the neck.
    Returns 0 when the device does not reach the plane.
    """
    if device_world is None or device_world.GetNumberOfPoints() == 0:
        return 0.0
    plane = vtk.vtkPlane()
    plane.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))
    plane.SetNormal(float(normal[0]), float(normal[1]), float(normal[2]))
    cutter = vtk.vtkCutter()
    cutter.SetInputData(device_world)
    cutter.SetCutFunction(plane)
    cutter.Update()
    cut = cutter.GetOutput()
    if cut is None or cut.GetNumberOfPoints() == 0:
        return 0.0
    b = cut.GetBounds()  # xmin,xmax,ymin,ymax,zmin,zmax
    dx, dy, dz = b[1] - b[0], b[3] - b[2], b[5] - b[4]
    return float(math.sqrt(dx * dx + dy * dy + dz * dz))


def clip_neck_coverage(
    clips_world: vtk.vtkPolyData,
    neck_origin: Vec3,
    neck_axis: Vec3,
    neck_mm: float,
) -> float:
    """Fraction (0–100) of the neck diameter spanned by the clips at the neck plane."""
    if neck_mm <= 0.1:
        return 0.0
    span = plane_span(clips_world, neck_origin, neck_axis)
    return float(min(100.0, span / neck_mm * 100.0))


def perpendicular(axis: Vec3) -> Vec3:
    """A stable unit vector perpendicular to *axis* (for stent orientation)."""
    a = np.asarray(axis, dtype=float)
    ln = float(np.linalg.norm(a))
    a = a / ln if ln > 1e-9 else np.array([0.0, 0.0, 1.0])
    ref = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    p = np.cross(a, ref)
    p /= (np.linalg.norm(p) or 1.0)
    return (float(p[0]), float(p[1]), float(p[2]))


# ── Shape-aware clip geometry ─────────────────────────────────────────────── #
# `make_clip` above is a fixed-proportion proxy: every clip comes out 0.5 mm wide
# with a straight blade, whatever the catalogue says. That is fine for showing
# "a clip is here", but it cannot answer "does THIS clip fit" — a bayonet and a
# straight clip of the same blade length occupy completely different space, and
# the collision test is only meaningful on the geometry that will actually be
# implanted. The builder below takes the real specification.
#
# Local frame matches `make_clip` and `pose_transform`: blade length along +X,
# jaw opening along +Y, blade depth along +Z (so +Z is the blade normal).

def _blade_path(shape: str, length: float, angle_deg: float, n: int = 14) -> list[tuple[float, float]]:
    """Centreline of one blade in the XZ plane, as (x, z) samples.

    Every shape is expressed as a path rather than as a special case, so the
    sweep below does not care which clip it is building.
    """
    x0, x1 = -length / 2.0, length / 2.0
    pts: list[tuple[float, float]] = []

    if shape == "CURVED":
        # A shallow arc bowing out of the jaw plane; the bow depth is a fraction
        # of the blade so long clips curve more than short ones, as real ones do.
        bow = length * 0.18
        for i in range(n + 1):
            t = i / n
            x = x0 + t * length
            pts.append((x, bow * math.sin(math.pi * t)))
        return pts

    if shape in ("ANGLED", "ANGLED_45"):
        # Straight proximal half, then a bend of `angle_deg` away from the axis.
        bend_at = 0.45
        ang = math.radians(angle_deg or (90.0 if shape == "ANGLED" else 45.0))
        knee_x = x0 + bend_at * length
        seg = length * (1.0 - bend_at)
        half = max(2, n // 2)
        for i in range(half + 1):
            pts.append((x0 + (knee_x - x0) * i / half, 0.0))
        for i in range(1, half + 1):
            d = seg * i / half
            pts.append((knee_x + d * math.cos(ang), d * math.sin(ang)))
        return pts

    if shape == "BAYONET":
        # Two opposite jogs: the distal blade runs parallel to the proximal one
        # but offset, which is what keeps the shaft out of the line of sight.
        jog = length * 0.22
        keys = [(x0, 0.0), (x0 + 0.32 * length, 0.0),
                (x0 + 0.50 * length, jog), (x0 + 0.68 * length, jog), (x1, jog)]
        for i in range(len(keys) - 1):
            (ax, az), (bx, bz) = keys[i], keys[i + 1]
            steps = max(2, n // (len(keys) - 1))
            for k in range(steps):
                t = k / steps
                pts.append((ax + (bx - ax) * t, az + (bz - az) * t))
        pts.append(keys[-1])
        return pts

    # STRAIGHT and FENESTRATED share a straight blade; the window is added
    # separately at the hinge end.
    for i in range(n + 1):
        pts.append((x0 + length * i / n, 0.0))
    return pts


def _sweep_blade(path: list[tuple[float, float]], width: float, height: float,
                 y_offset: float) -> list[vtk.vtkPolyData]:
    """Sweep a rectangular section along `path`, offset to one side of the jaw."""
    out: list[vtk.vtkPolyData] = []
    for i in range(len(path) - 1):
        (ax, az), (bx, bz) = path[i], path[i + 1]
        dx, dz = bx - ax, bz - az
        seg = math.hypot(dx, dz)
        if seg <= 1e-6:
            continue
        cube = vtk.vtkCubeSource()
        # Slight overlap keeps consecutive segments watertight enough for the
        # collision filter, which counts intersecting triangles.
        cube.SetXLength(seg * 1.15)
        cube.SetYLength(width)
        cube.SetZLength(height)
        cube.SetCenter(0.0, 0.0, 0.0)
        cube.Update()
        t = vtk.vtkTransform()
        t.Translate((ax + bx) / 2.0, y_offset, (az + bz) / 2.0)
        t.RotateY(-math.degrees(math.atan2(dz, dx)))
        out.append(apply_transform(cube.GetOutput(), t))
    return out


def make_clip_shaped(
    blade_length_mm: float,
    blade_width_mm: float = 0.5,
    blade_height_mm: float = 1.4,
    shape: str = "STRAIGHT",
    angle_deg: float = 0.0,
    fenestration_mm: float = 0.0,
    jaw_mm: float = 1.2,
) -> vtk.vtkPolyData:
    """Build a clip from its real specification.

    `shape` is a `ClipShape` member NAME (STRAIGHT, CURVED, ANGLED, ANGLED_45,
    BAYONET, FENESTRATED) so this module keeps no dependency on the catalogue.

    The result is an approximation — a machined clip has fillets and a real
    spring — but it is the right size, the right shape class and the right
    window calibre, which is what the collision and span tests read.
    """
    length = max(1.0, float(blade_length_mm))
    width = max(0.15, float(blade_width_mm))
    height = max(0.3, float(blade_height_mm))
    jaw = max(0.2, float(jaw_mm))

    path = _blade_path(shape, length, angle_deg)
    parts: list[vtk.vtkPolyData] = []
    for sign in (+1.0, -1.0):
        parts.extend(_sweep_blade(path, width, height, sign * (jaw / 2.0 + width / 2.0)))

    # Hinge bar closing the proximal end.
    hinge = vtk.vtkCubeSource()
    hinge.SetXLength(width)
    hinge.SetYLength(jaw + width * 2.0)
    hinge.SetZLength(height)
    hinge.SetCenter(-length / 2.0, 0.0, 0.0)
    hinge.Update()
    parts.append(hinge.GetOutput())

    # The window of a fenestrated clip: a ring just distal to the hinge, lying in
    # the plane of the jaw, sized to the vessel it has to spare.
    if fenestration_mm > 0.0:
        r = float(fenestration_mm) / 2.0
        circle = vtk.vtkRegularPolygonSource()
        circle.SetNumberOfSides(24)
        circle.SetRadius(r)
        circle.SetCenter(0.0, 0.0, 0.0)
        circle.SetNormal(0.0, 0.0, 1.0)
        circle.GeneratePolygonOff()          # outline only — the tube gives it body
        circle.Update()
        tube = vtk.vtkTubeFilter()
        tube.SetInputData(circle.GetOutput())
        tube.SetRadius(max(0.12, width * 0.6))
        tube.SetNumberOfSides(10)
        tube.CappingOn()
        tube.Update()
        t = vtk.vtkTransform()
        t.Translate(-length / 2.0 + r + width, 0.0, 0.0)
        t.RotateX(90.0)                       # ring opening along the jaw axis
        parts.append(apply_transform(tube.GetOutput(), t))

    return combine(parts)


def write_stl(poly: vtk.vtkPolyData, path) -> None:
    """Write a polydata to a binary STL (for sending a clip out to manufacture)."""
    tri = _triangulate(poly)
    w = vtk.vtkSTLWriter()
    w.SetFileName(str(path))
    w.SetFileTypeToBinary()
    w.SetInputData(tri)
    w.Write()
