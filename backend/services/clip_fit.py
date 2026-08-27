"""Second-stage clip check: place the candidate on the real neck and measure it.

`clip_selection` judges a clip by arithmetic on the morphometry — blade against
neck, force against neck, shape against region. That is fast enough to run over
the whole catalogue, but it never looks at the patient's actual vessel. Two
clips with identical blade length occupy very different space if one is a
bayonet, and only geometry can tell whether the far end of the blade runs into
the branch next door.

So the top few analytic candidates come here and get built at their real
dimensions (`devices.make_clip_shaped`), posed on the measured neck plane, and
measured.

What "collision" means here
---------------------------
A clip placed across the neck necessarily intersects the vessel surface — the
neck IS vessel. Testing the clip against the whole tree therefore reports a
collision for every clip, which is worse than useless: it looks like a safety
check and answers nothing.

The question worth asking is whether the clip hits something *beyond* the
target. So the vessel is first cut with a sphere around the neck, removing the
sac and the immediate neck region, and the collision test runs against what
remains. A hit then means the blade reaches into a neighbouring structure,
which is a genuine reason to prefer another clip.

The blade is still an approximation of a machined clip (no fillets, no real
spring), so a contact count is evidence, not a verdict.
"""
from __future__ import annotations

import logging

import vtk

from services.clip_selection import (
    ClipCandidate,
    ClipCase,
    Criterion,
    GeometryCheck,
    recompute_score,
)
from services.devices import (
    apply_transform,
    check_collision,
    clip_neck_coverage,
    make_clip_shaped,
    plane_span,
    pose_transform,
)

logger = logging.getLogger(__name__)

# Rotations tried around the neck normal. A clip that fouls a branch at one roll
# angle is often clean at another, and the surgeon can rotate the applier — so
# reporting the worst pose would reject clips that are perfectly usable.
_ROTATIONS_DEG: tuple[float, ...] = (0.0, 30.0, 60.0, 90.0, 120.0, 150.0)

# How much of the vessel around the neck is excluded from the collision test,
# as a multiple of the neck diameter. Large enough to drop the sac and the neck
# itself; small enough that a true neighbour stays in.
_EXCLUSION_RATIO: float = 1.2
_EXCLUSION_MIN_MM: float = 3.0


def vessel_beyond_neck(
    vessel: vtk.vtkPolyData,
    neck_origin: tuple[float, float, float],
    neck_mm: float,
) -> vtk.vtkPolyData:
    """The vessel tree with the sac and neck region cut away.

    What is left is everything a clip blade has no business touching.
    """
    radius = max(_EXCLUSION_MIN_MM, float(neck_mm) * _EXCLUSION_RATIO)
    sphere = vtk.vtkSphere()
    sphere.SetCenter(float(neck_origin[0]), float(neck_origin[1]), float(neck_origin[2]))
    sphere.SetRadius(radius)
    cutter = vtk.vtkClipPolyData()
    cutter.SetInputData(vessel)
    cutter.SetClipFunction(sphere)
    cutter.InsideOutOff()          # keep what is OUTSIDE the sphere
    cutter.Update()
    return cutter.GetOutput()


def build_candidate_mesh(cand: ClipCandidate) -> vtk.vtkPolyData:
    """The candidate clip at its catalogue dimensions, in the local frame."""
    spec = cand.clip
    return make_clip_shaped(
        blade_length_mm=spec.blade_length_mm,
        blade_width_mm=spec.blade_width_mm,
        blade_height_mm=spec.blade_height_mm,
        shape=spec.shape.name,
        angle_deg=90.0 if spec.shape.name == "ANGLED" else (45.0 if spec.shape.name == "ANGLED_45" else 0.0),
        fenestration_mm=spec.fenestration_mm,
    )


def verify_candidate(
    cand: ClipCandidate,
    case: ClipCase,
    vessel: vtk.vtkPolyData,
    neck_origin: tuple[float, float, float],
    neck_normal: tuple[float, float, float],
    obstacles: vtk.vtkPolyData | None = None,
) -> GeometryCheck:
    """Pose the clip on the neck plane and measure fit, over several rolls.

    `obstacles` is the vessel minus the neck region; pass it in when checking
    several candidates so the cut runs once instead of once per clip.
    """
    if obstacles is None:
        obstacles = vessel_beyond_neck(vessel, neck_origin, case.neck_mm)

    local = build_candidate_mesh(cand)
    best: GeometryCheck | None = None
    clean = 0

    for roll in _ROTATIONS_DEG:
        t = pose_transform(neck_origin, neck_normal, roll)
        world = apply_transform(local, t)
        try:
            hit, contacts = check_collision(obstacles, world)
        except Exception as exc:  # noqa: BLE001 — a degenerate mesh must not sink the run
            logger.warning("Collision test failed for %s: %s", cand.clip.name, exc)
            hit, contacts = False, 0
        if not hit:
            clean += 1
        span = plane_span(world, neck_origin, neck_normal)
        coverage = clip_neck_coverage(world, neck_origin, neck_normal, case.neck_mm)

        check = GeometryCheck(
            collision=bool(hit),
            n_contacts=int(contacts),
            span_mm=round(float(span), 2),
            neck_coverage_pct=round(float(coverage), 1),
            note=f"roll {roll:.0f}°",
        )
        # Fewest contacts wins; ties go to the pose that covers more neck.
        if best is None or (check.n_contacts, -check.neck_coverage_pct) < (best.n_contacts, -best.neck_coverage_pct):
            best = check

    assert best is not None
    best.clean_rolls = clean
    best.n_rolls = len(_ROTATIONS_DEG)

    cover = (f"cubre el cuello por completo" if best.neck_coverage_pct >= 99.0
             else f"cubre el {best.neck_coverage_pct:.0f}% del cuello")
    if clean == 0:
        best.note = (
            f"Toca estructuras vecinas en las {best.n_rolls} orientaciones probadas "
            f"({best.n_contacts} triángulos en la mejor); {cover}"
        )
    elif best.tight:
        best.note = (
            f"Solo libra los vasos vecinos en {clean} de {best.n_rolls} orientaciones: "
            f"exige una aplicación precisa; {cover}"
        )
    elif clean < best.n_rolls:
        best.note = (
            f"Libra los vasos vecinos en {clean} de {best.n_rolls} orientaciones; {cover}"
        )
    else:
        best.note = f"Libra los vasos vecinos en toda orientación; {cover}"
    return best


def verify_all(
    candidates: list[ClipCandidate],
    case: ClipCase,
    vessel: vtk.vtkPolyData,
    neck_origin: tuple[float, float, float],
    neck_normal: tuple[float, float, float],
    limit: int = 5,
) -> None:
    """Verify the top `limit` candidates in place, filling in `cand.verified`.

    Deliberately capped: each candidate costs several collision tests, and the
    analytic ranking is good enough that verifying the tail buys nothing.
    """
    if vessel is None or vessel.GetNumberOfPoints() == 0 or case.neck_mm <= 0:
        return
    obstacles = vessel_beyond_neck(vessel, neck_origin, case.neck_mm)
    if obstacles is None or obstacles.GetNumberOfPoints() == 0:
        # Nothing outside the neck region — a cropped mesh holding only the sac.
        # Say so rather than reporting a clean bill of health that was not earned.
        for cand in candidates[:limit]:
            cand.verified = GeometryCheck(
                collision=False, n_contacts=0, span_mm=0.0, neck_coverage_pct=0.0,
                clean_rolls=0, n_rolls=0,
                note="La malla no contiene estructuras fuera del cuello: no se pudo "
                     "comprobar colisión con vasos vecinos",
            )
            cand.criteria.append(_geometry_criterion(cand.verified))
            recompute_score(cand)
        return
    for cand in candidates[:limit]:
        try:
            check = verify_candidate(
                cand, case, vessel, neck_origin, neck_normal, obstacles=obstacles
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Verification failed for %s: %s", cand.clip.name, exc)
            continue
        cand.verified = check
        cand.criteria.append(_geometry_criterion(check))
        recompute_score(cand)


def _geometry_criterion(check: GeometryCheck) -> Criterion:
    """Fold the measured fit back into the candidate's criteria.

    This is the only criterion that looked at the patient rather than at a
    table, so it carries the heaviest weight — and a clip that fouls a
    neighbouring vessel at every approach angle is rejected outright, whatever
    its blade length says.
    """
    if check.n_rolls == 0:
        return Criterion("geometry", "Ajuste real", "warn",
                         "No se pudo comprobar sobre la malla del paciente", 0.5, weight=1.0)
    if check.clean_rolls == 0:
        return Criterion("geometry", "Ajuste real", "fail", check.note, 0.0, weight=2.5)
    if check.tight:
        return Criterion("geometry", "Ajuste real", "warn", check.note, 0.45, weight=2.5)
    if check.clean_rolls < check.n_rolls:
        return Criterion("geometry", "Ajuste real", "warn", check.note, 0.75, weight=2.5)
    return Criterion("geometry", "Ajuste real", "ok", check.note, 1.0, weight=2.5)
