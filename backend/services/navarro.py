"""The NAVARRO™ clip family — the institution's own made-to-order designs.

These are not catalogue clips anyone stocks: they are parametric designs meant to
be manufactured for the case at hand. That changes two things about how the rest
of the system must treat them, and both are encoded here rather than left to the
caller to remember.

What the files are
------------------
`NAVARRO™ - Variantes/` holds each variant twice, and only one export is usable:

- **`.obj` — unusable.** Written in CENTIMETRES (measured ratio 9.996–10.008
  against the STL across all 41 pairs) and, worse, exported without welding
  vertices: the 7 mm clip reads as 14 334 loose triangles with 43 002 boundary
  edges. It is a triangle soup, not a solid, so it cannot be collision-tested.
- **`.stl` — the real thing.** Already in MILLIMETRES, watertight, one piece
  (0 boundary edges, 107.1 mm³ at 7 mm to 186.1 mm³ at 22 mm). No rescaling.

Geometry, measured rather than assumed
--------------------------------------
Every variant shares one body (the spring and the applier grip):

    body envelope   X[-1.80, 1.80]  Y[-4.81, 4.81]  Z[-11.80, 2.50]

and the jaw grows along the axis (sin θ, 0, cos θ), where θ is the angle in the
file name. `total length = jaw + 14.30 mm` holds exactly across the straight
sizes. Where the jaw *starts* along that axis is not a single constant — 2.50 mm
at 0° and 90°, up to 3.95 mm at 15°, because the knee occupies room — so it is
read off each mesh (`jaw_root_offset`) rather than assumed.

The name states the JAW, not the clip: "7mm" is 7 mm of useful grip, on a clip
21.30 mm long overall. That distinction is the whole reason this module exists —
measuring the bounding box and calling it the blade would record 21.30 mm for a
clip that grips 7 mm, and the selector would reject the very clip that fits.

Why resizing the jaw is legitimate
----------------------------------
The jaw tapers (≈4.3 mm at the root to ≈1.7 mm at the tip). Sampling the taper
at ten stations along each size and normalising by jaw length, the profiles agree
to within ~0.05 mm across the 10/13/16/19/22 mm sizes — the designs are the same
shape stretched, not six separately drawn parts. So scaling the jaw region along
its own axis reproduces the family's own design language instead of inventing a
shape. `resize_jaw` does exactly that, and nothing else: the body, the spring and
every cross-section perpendicular to the jaw axis are untouched, which is what
keeps whatever closing force the spring ends up having.

A stretched mesh is a faithful preview for display and collision testing. It is
NOT the manufacturing master — that comes from the parametric CAD, and
`resize_jaw` says so in what it returns.
"""
from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Default location of the design library, beside the backend.
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "NAVARRO™ - Variantes"


def library_root() -> Path:
    """Where the designs live. Read per call, not frozen at import.

    Two reasons: a test can point at an empty directory to exercise "no family
    installed" whatever this machine happens to have, and moving the folder does
    not need a server restart.
    """
    return Path(os.environ.get("NAVARRO_ROOT", "") or DEFAULT_ROOT)

MANUFACTURER = "NAVARRO™ (UNINAVARRA)"

# ── Measured constants ─────────────────────────────────────────────────────── #

#: Length of the fixed body (spring + grip), constant across all 42 variants.
BODY_LENGTH_MM: float = 14.30
#: Where the jaw leaves the body on a straight clip, measured along its axis.
#: The bent variants sit further out (2.50 mm at 0° and 90°, up to 3.95 mm at
#: 15°, because the knee takes up room), and the offset is constant per angle but
#: not across angles — so `jaw_root_offset` derives it from the mesh instead of
#: assuming this value. Kept as the documented straight-clip figure.
JAW_ROOT_Z_MM: float = 2.50
#: Body envelope, used to tell jaw points from body points.
BODY_X = (-1.80, 1.80)
BODY_Z_MIN = -11.80

#: Jaw lengths that exist as drawn CAD. Anything else is a stretch of these.
STOCK_JAW_MM: tuple[int, ...] = (7, 10, 13, 16, 19, 22)

# ── Closing force ──────────────────────────────────────────────────────────── #
# Not characterised yet: the manufacturer has given a design band, not a value.
# It travels as a band on purpose — collapsing it to a midpoint would let the
# selector report a precision the part does not have. The spring is identical
# across all 42 variants, so when the real figure arrives it is ONE number for
# the whole family, set here.
CLOSING_FORCE_MIN_G: float = 120.0
CLOSING_FORCE_MAX_G: float = 200.0
FORCE_IS_PROVISIONAL: bool = True


@dataclass(frozen=True)
class NavarroVariant:
    """One drawn design: a series, a bend angle and a jaw length."""
    series: str            # "T1" | "T3"
    angle_deg: float       # 0 for T1; 15/30/45/60/75/90 for T3
    jaw_mm: int
    path: Path

    @property
    def name(self) -> str:
        shape = "Recto" if self.angle_deg == 0 else f"Angulado {self.angle_deg:.0f}°"
        return f"NAVARRO™ {self.series} {shape} {self.jaw_mm} mm"

    @property
    def total_length_mm(self) -> float:
        return self.jaw_mm + BODY_LENGTH_MM

    @property
    def jaw_axis(self) -> tuple[float, float, float]:
        """Unit vector the jaw runs along, in the file's own frame."""
        t = math.radians(self.angle_deg)
        return (math.sin(t), 0.0, math.cos(t))


_NAME_RE = re.compile(r"(T\d)\s*—\s*(Straight|Angled)(?:\s*(\d+)°)?\s*\((\d+)\s*mm\)", re.I)


def _parse(path: Path) -> NavarroVariant | None:
    m = _NAME_RE.search(path.name)
    if not m:
        return None
    series, kind, angle, jaw = m.groups()
    return NavarroVariant(
        series=series.upper(),
        angle_deg=float(angle) if angle else 0.0,
        jaw_mm=int(jaw),
        path=path,
    )


def list_variants(root: Path | None = None) -> list[NavarroVariant]:
    """Every drawn design, from the STL exports only (see the module docstring)."""
    base = Path(root) if root is not None else library_root()
    if not base.is_dir():
        return []
    out: list[NavarroVariant] = []
    seen: set[tuple[str, float, int]] = set()
    for p in sorted(base.rglob("*.stl")):
        v = _parse(p)
        if v is None:
            logger.warning("NAVARRO: unrecognised file name, skipped: %s", p.name)
            continue
        key = (v.series, v.angle_deg, v.jaw_mm)
        if key in seen:            # the same design is exported under two folders
            continue
        seen.add(key)
        out.append(v)
    return sorted(out, key=lambda v: (v.series, v.angle_deg, v.jaw_mm))


def available_angles(root: Path | None = None) -> list[float]:
    return sorted({v.angle_deg for v in list_variants(root)})


def nearest_variant(angle_deg: float, jaw_mm: float,
                    root: Path | None = None) -> NavarroVariant | None:
    """The drawn design closest to a requested angle and jaw length.

    Angle wins over jaw length: the bend is a different part, whereas the jaw is
    the dimension the family is designed to vary.
    """
    variants = list_variants(root)
    if not variants:
        return None
    return min(variants, key=lambda v: (abs(v.angle_deg - angle_deg), abs(v.jaw_mm - jaw_mm)))


# ── Geometry ───────────────────────────────────────────────────────────────── #

def load_mesh(variant: NavarroVariant):
    """Read one design's STL. Raises if the file is gone or unreadable."""
    import vtk

    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(variant.path))
    reader.Update()
    poly = reader.GetOutput()
    if poly is None or poly.GetNumberOfPoints() == 0:
        raise ValueError(f"No se pudo leer la geometría de {variant.path.name}")
    return poly


def jaw_root_offset(poly, jaw_mm: float, angle_deg: float) -> float:
    """Distance along the jaw axis from the origin to where the jaw begins.

    Derived, not assumed: the tip sits at `offset + jaw`, so the offset is the
    farthest projection minus the jaw the design is named for. Measured this way
    it comes out constant for a given bend (identical at 7 mm and 22 mm) and
    different between bends — 2.50 mm straight, 3.95 mm at 15° — which is the
    knee taking up room. Reading it off the mesh means a redrawn CAD cannot
    silently invalidate a constant sitting in this file.
    """
    t = math.radians(angle_deg)
    ax = (math.sin(t), 0.0, math.cos(t))
    pts = poly.GetPoints()
    best = -1e30
    for i in range(pts.GetNumberOfPoints()):
        x, _y, z = pts.GetPoint(i)
        proj = x * ax[0] + z * ax[2]
        if proj > best:
            best = proj
    return best - float(jaw_mm)


def resize_jaw(poly, from_jaw_mm: float, to_jaw_mm: float, angle_deg: float):
    """Stretch ONLY the jaw, along its own axis, leaving the body untouched.

    A point's offset along the jaw axis from the root plane is scaled by
    `to/from`; everything at or behind the root, and every dimension across the
    axis, is left exactly as drawn. That preserves the spring — and so whatever
    closing force it has — which a uniform scale would not: scaling the whole
    clip by 1.5 also makes the spring 1.5x, and its force is no longer the
    family's.

    Returns a new polydata. The caller is responsible for telling the user this
    is a preview, not the manufacturing master.
    """
    import vtk

    if from_jaw_mm <= 0 or to_jaw_mm <= 0:
        raise ValueError("Las longitudes de mordaza deben ser positivas.")
    k = float(to_jaw_mm) / float(from_jaw_mm)
    out = vtk.vtkPolyData()
    out.DeepCopy(poly)
    if abs(k - 1.0) < 1e-9:
        return out

    t = math.radians(angle_deg)
    ax = (math.sin(t), 0.0, math.cos(t))
    # Where the jaw starts, read off this very mesh (see jaw_root_offset).
    d0 = jaw_root_offset(poly, from_jaw_mm, angle_deg)

    points = out.GetPoints()
    for i in range(points.GetNumberOfPoints()):
        x, y, z = points.GetPoint(i)
        s = x * ax[0] + z * ax[2] - d0
        if s <= 0.0:
            continue                       # body side of the root plane: untouched
        grow = s * (k - 1.0)
        points.SetPoint(i, x + ax[0] * grow, y, z + ax[2] * grow)
    points.Modified()
    out.Modified()
    return out


def build_jaw(angle_deg: float, jaw_mm: float, root: Path | None = None):
    """Geometry for any jaw length, drawn or stretched.

    Returns `(polydata, source_variant, exact)`. `exact` is True when a design
    with that jaw length exists as drawn CAD and nothing was stretched.
    """
    src = nearest_variant(angle_deg, jaw_mm, root)
    if src is None:
        raise FileNotFoundError(
            "La biblioteca NAVARRO™ no está disponible en este servidor "
            f"({library_root()})."
        )
    mesh = load_mesh(src)
    exact = abs(src.jaw_mm - jaw_mm) < 1e-6 and abs(src.angle_deg - angle_deg) < 1e-6
    if exact:
        return mesh, src, True
    return resize_jaw(mesh, src.jaw_mm, jaw_mm, src.angle_deg), src, False


# ── Feeding the selector ───────────────────────────────────────────────────── #

def _shape_for(angle_deg: float):
    """Map a bend angle onto the selector's shape vocabulary.

    The family bends in 15° steps but the selector knows three straight-ish
    classes, so each angle lands on the nearest one. The real angle travels
    separately in the spec, and it is the real angle that gets manufactured.
    """
    from services.clips import ClipShape

    if angle_deg <= 7.5:
        return ClipShape.STRAIGHT
    if angle_deg <= 52.5:
        return ClipShape.ANGLED_45
    return ClipShape.ANGLED


def to_spec(variant: NavarroVariant, jaw_mm: float | None = None):
    """A `ClipSpec` the selector can score.

    `blade_length_mm` is the JAW — the useful grip that has to span the neck —
    never the overall length. Width and height come from the drawn cross-section
    at the jaw root; the spring length is the measured body.
    """
    from services.clips import ClipSpec

    jaw = float(jaw_mm if jaw_mm is not None else variant.jaw_mm)
    custom = jaw_mm is not None and abs(jaw - variant.jaw_mm) > 1e-6
    shape = _shape_for(variant.angle_deg)
    label = (f"NAVARRO™ {variant.series} "
             f"{'Recto' if variant.angle_deg == 0 else f'Angulado {variant.angle_deg:.0f}°'} "
             f"{jaw:.1f} mm" + (" (a medida)" if custom else ""))
    return ClipSpec(
        name=label,
        shape=shape,
        blade_length_mm=jaw,
        # Measured across the jaw at its root: 2.37 mm thick, 4.4 mm deep.
        blade_width_mm=2.37,
        blade_height_mm=4.40,
        spring_length_mm=BODY_LENGTH_MM,
        closing_force_g=CLOSING_FORCE_MIN_G,
        manufacturer=MANUFACTURER,
        fenestration_mm=0.0,
        closing_force_max_g=CLOSING_FORCE_MAX_G,
        force_provisional=FORCE_IS_PROVISIONAL,
        availability="made_to_order",
        bend_angle_deg=variant.angle_deg,
    )


def family_specs(root: Path | None = None) -> list:
    """Every drawn NAVARRO™ design as a `ClipSpec`, for the selector."""
    return [to_spec(v) for v in list_variants(root)]
