"""Clip application as motion: approach the neck, open, close on it.

A placed clip is shown as a finished fact — geometry already sitting on the
neck. Rehearsing the manoeuvre needs the three moments that matter: coming down
the approach corridor with the jaw open, arriving astride the neck, and closing.
This module produces the pieces a viewer needs to play that.

What is derived and what is assumed
-----------------------------------
**Derived from the mesh**, so it holds for any clip and cannot drift from a
constant written here:

- the jaw-opening axis — the one axis with a clean empty corridor down the
  middle of the blades;
- the hinge — the coordinate along the clip where that corridor starts, i.e.
  where the two blades stop being two things;
- which way the jaw points from the hinge.

Measured this way the NAVARRO™ hinge lands at the same place in all six sizes,
which is what a real family does.

**Assumed**, because a closed STL records no mechanism: how far the jaw opens.
The figures below are taken from how commercial clips behave and are gathered in
one place precisely so they can be replaced with the real ones when the
manufacturer gives them — nothing else needs to change.

What this is not
----------------
A visualisation of the intended placement, not a simulation. No tissue yields,
no applier is modelled, and nothing here says whether the corridor can actually
be reached with human hands. It shows, in motion, the placement the rest of the
pipeline computed.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# ── Opening mechanics: ASSUMED, pending the real figures ──────────────────── #
# Commercial aneurysm clips open their tips to roughly one blade length — a 7 mm
# clip admits about 7 mm between the tips — and the applier limits the travel
# rather than the spring. Both are expressed relative to the blade so they scale
# with the size, and both are capped so a long blade does not open absurdly.
#: Tip separation at full open, as a multiple of blade length.
OPEN_TIP_RATIO: float = 1.0
#: Hard ceiling on how far each blade swings, whatever the ratio asks for.
MAX_BLADE_SWING_DEG: float = 30.0
#: True while these are inferred rather than supplied by the manufacturer, so
#: the UI can say so instead of implying the motion is specified.
MECHANICS_ARE_ASSUMED: bool = True

# ── Approach ──────────────────────────────────────────────────────────────── #
#: How far back the clip starts, as a multiple of its own length.
APPROACH_STANDOFF_RATIO: float = 2.2
APPROACH_STANDOFF_MIN_MM: float = 18.0

_GAP_TOL_MM: float = 0.12
_MIN_SIDE_POINTS: int = 8


def _points(poly):
    import numpy as np

    return np.array([poly.GetPoint(i) for i in range(poly.GetNumberOfPoints())])


def jaw_geometry(poly) -> dict:
    """Where the blades part, along which axis, and which way the jaw points.

    Read off the mesh rather than declared, because the two clip families do not
    share a layout: the synthetic catalogue clips hinge at one end of the blade
    and the NAVARRO™ exports hinge near the middle of the part. Both, however,
    have exactly one axis with an empty corridor between the blades, and the
    corridor starts at the hinge.
    """
    import numpy as np

    P = _points(poly)
    if len(P) < 20:
        raise ValueError("La malla del clip es demasiado pequeña para analizarla.")

    # The long axis first: the clip's own length is simply its largest extent.
    spans = [float(P[:, a].max() - P[:, a].min()) for a in range(3)]
    long_axis = int(np.argmax(spans))

    # The jaw corridor exists only along the BLADES, never through the body where
    # the two halves are one piece. Looking for it across the whole clip made the
    # 7 mm NAVARRO pick the wrong axis — its spring has points on the mid-plane —
    # so the search runs on the distal fifth at each end, and the end that has a
    # corridor is by definition the jaw.
    lo_all, hi_all = P[:, long_axis].min(), P[:, long_axis].max()
    reach = (hi_all - lo_all) * 0.2
    ends = {+1: P[P[:, long_axis] >= hi_all - reach],
            -1: P[P[:, long_axis] <= lo_all + reach]}

    open_axis, jaw_end = None, None
    for direction, band in ends.items():
        if len(band) < _MIN_SIDE_POINTS * 2:
            continue
        for axis in range(3):
            if axis == long_axis:
                continue
            mid = int((np.abs(band[:, axis]) <= _GAP_TOL_MM).sum())
            pos = int((band[:, axis] > _GAP_TOL_MM).sum())
            neg = int((band[:, axis] < -_GAP_TOL_MM).sum())
            if mid == 0 and pos > _MIN_SIDE_POINTS and neg > _MIN_SIDE_POINTS:
                open_axis, jaw_end = axis, direction
                break
        if open_axis is not None:
            break
    if open_axis is None:
        # Blades that touch when closed leave no corridor; take the axis whose
        # mid-plane is emptiest, which is the same axis in practice.
        counts = [int((np.abs(P[:, a]) <= _GAP_TOL_MM).sum()) if a != long_axis else 10**9
                  for a in range(3)]
        open_axis = int(np.argmin(counts))
        jaw_end = +1 if (hi_all - np.median(P[:, long_axis])) > (np.median(P[:, long_axis]) - lo_all) else -1

    lo, hi = float(lo_all), float(hi_all)
    step = max(0.25, (hi - lo) / 60.0)
    # Walk inwards from the tip; the hinge is where the corridor first closes.
    direction = -jaw_end
    start = hi if jaw_end > 0 else lo
    hinge_pos = None
    for k in range(1, 61):
        a = start + direction * step * k
        b = a + direction * step
        band = P[(P[:, long_axis] >= min(a, b)) & (P[:, long_axis] < max(a, b))]
        if len(band) < _MIN_SIDE_POINTS:
            continue
        if int((np.abs(band[:, open_axis]) <= _GAP_TOL_MM).sum()) > 0:
            hinge_pos = float(a)
            break
    if hinge_pos is None:
        hinge_pos = float(lo if jaw_end > 0 else hi)
    jaw_dir = int(jaw_end)

    tip = hi if jaw_dir > 0 else lo
    return {
        "open_axis": int(open_axis),
        "long_axis": int(long_axis),
        "hinge": float(hinge_pos),
        "jaw_direction": int(jaw_dir),
        "tip": float(tip),
        "lever_mm": abs(float(tip) - float(hinge_pos)),
    }


def blade_swing_deg(geom: dict, blade_mm: float) -> float:
    """How far each blade turns to reach the assumed opening, in degrees.

    Half the tip separation over the lever arm from the hinge. Capped, so a long
    blade opens like a clip rather than like a pair of scissors.
    """
    lever = max(0.5, geom["lever_mm"])
    half_gap = max(0.0, blade_mm * OPEN_TIP_RATIO) / 2.0
    return min(MAX_BLADE_SWING_DEG, math.degrees(math.atan2(half_gap, lever)))


def split_blades(poly):
    """Separate a closed clip into (body, blade_positive, blade_negative).

    The cut runs along the jaw corridor, so each blade comes away whole. Each
    half is left open at the cut face — invisible from outside, and harmless
    because this geometry is for display: the collision test keeps using the
    closed solid.
    """
    import vtk

    geom = jaw_geometry(poly)
    axis, long_axis = geom["open_axis"], geom["long_axis"]
    hinge, jaw_dir = geom["hinge"], geom["jaw_direction"]

    def _clip(normal, origin, inside_out):
        plane = vtk.vtkPlane()
        plane.SetOrigin(*origin)
        plane.SetNormal(*normal)
        c = vtk.vtkClipPolyData()
        c.SetInputData(poly)
        c.SetClipFunction(plane)
        c.SetInsideOut(inside_out)
        c.Update()
        return c.GetOutput()

    long_n = [0.0, 0.0, 0.0]
    long_n[long_axis] = float(jaw_dir)
    at_hinge = [0.0, 0.0, 0.0]
    at_hinge[long_axis] = hinge

    # Everything behind the hinge is the body and never moves.
    body = _clip(long_n, at_hinge, 1)

    open_n = [0.0, 0.0, 0.0]
    open_n[axis] = 1.0

    def _blade(inside_out):
        half = _clip(open_n, [0.0, 0.0, 0.0], inside_out)
        c = vtk.vtkClipPolyData()
        plane = vtk.vtkPlane()
        plane.SetOrigin(*at_hinge)
        plane.SetNormal(*long_n)
        c.SetInputData(half)
        c.SetClipFunction(plane)
        c.SetInsideOut(0)          # keep the jaw side of the hinge
        c.Update()
        return c.GetOutput()

    return body, _blade(0), _blade(1), geom


def default_approach(
    neck_origin: tuple[float, float, float],
    neck_normal: tuple[float, float, float],
    clip_length_mm: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Where the clip comes from when no approach corridor has been marked.

    Along the neck normal, from the side away from the dome. The normal already
    points at the dome, so backing off against it is the one direction that is
    certain to be free of the aneurysm — the surgeon's own corridor may differ,
    which is exactly why marking Entrada/Diana overrides this.
    """
    import numpy as np

    n = np.asarray(neck_normal, dtype=float)
    ln = float(np.linalg.norm(n))
    n = n / ln if ln > 1e-9 else np.array([0.0, 0.0, 1.0])
    standoff = max(APPROACH_STANDOFF_MIN_MM, clip_length_mm * APPROACH_STANDOFF_RATIO)
    o = np.asarray(neck_origin, dtype=float)
    entry = o - n * standoff
    return (float(entry[0]), float(entry[1]), float(entry[2])), (
        float(o[0]), float(o[1]), float(o[2]))
