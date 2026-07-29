"""Tier 1 (reliability guard) + Tier 2 (semi-automatic closed-sac) morphometry.

Uses synthetic VTK meshes so it runs without the DICOM corpus:
  • an open spherical cap  → must be flagged unreliable (volume/neck nulled)
  • a sphere-on-cylinder vessel tree clipped at a neck plane → closed sac with a
    valid neck (Tier 2), analysis reliable.
"""
from __future__ import annotations

import vtk

from services.morphometrics import MorphometricAnalyzer
from services.sac_isolation import isolate_closed_sac, measure_neck


def _sphere(radius: float, center=(0.0, 0.0, 0.0), res: int = 40) -> vtk.vtkPolyData:
    s = vtk.vtkSphereSource()
    s.SetRadius(radius)
    s.SetCenter(*center)
    s.SetThetaResolution(res)
    s.SetPhiResolution(res)
    s.Update()
    return s.GetOutput()


def _open_cap() -> vtk.vtkPolyData:
    """A hemisphere — clipping a closed sphere leaves an open boundary."""
    plane = vtk.vtkPlane()
    plane.SetOrigin(0.0, 0.0, 0.0)
    plane.SetNormal(0.0, 0.0, 1.0)
    clip = vtk.vtkClipPolyData()
    clip.SetInputData(_sphere(3.0))
    clip.SetClipFunction(plane)
    clip.Update()
    return clip.GetOutput()


def _vessel_tree() -> vtk.vtkPolyData:
    """Aneurysm sac (sphere) on a parent artery (cylinder along +Y).

    Built as an implicit union sampled by marching cubes so the result is a
    *single connected manifold* — like real segmentation output — rather than
    two interpenetrating but topologically separate primitive surfaces.
    """
    sphere = vtk.vtkSphere()
    sphere.SetRadius(3.0)
    sphere.SetCenter(0.0, 7.0, 0.0)
    cyl = vtk.vtkCylinder()           # infinite cylinder; bounded by sample region
    cyl.SetRadius(1.5)
    cyl.SetCenter(0.0, 0.0, 0.0)
    cyl.SetAxis(0.0, 1.0, 0.0)
    union = vtk.vtkImplicitBoolean()
    union.SetOperationTypeToUnion()
    union.AddFunction(sphere)
    union.AddFunction(cyl)

    sample = vtk.vtkSampleFunction()
    sample.SetImplicitFunction(union)
    sample.SetModelBounds(-4.0, 4.0, -7.0, 11.0, -4.0, 4.0)
    sample.SetSampleDimensions(48, 96, 48)
    sample.ComputeNormalsOff()

    contour = vtk.vtkContourFilter()
    contour.SetInputConnection(sample.GetOutputPort())
    contour.SetValue(0, 0.0)          # inside = implicit fn < 0
    contour.Update()
    return contour.GetOutput()


# ── Tier 1 ──────────────────────────────────────────────────────────────── #

def test_open_cap_flagged_unreliable():
    mr = MorphometricAnalyzer().analyze(_open_cap())
    assert mr.reliable is False
    assert mr.watertight is False
    assert mr.neck_diameter_mm == 0.0     # neck nulled, not a garbage grazing value
    assert mr.volume_mm3 == 0.0           # open-mesh volume nulled
    assert mr.dome_to_neck_ratio == 0.0
    assert "cuello" in mr.reliability_note or "abierta" in mr.reliability_note


def test_closed_sphere_volume_survives_even_if_auto_neck_degenerates():
    """A watertight sphere keeps a plausible volume; only the neck may be nulled."""
    mr = MorphometricAnalyzer().analyze(_sphere(3.0))
    assert mr.watertight is True
    # Volume of a Ø6 sphere ≈ 113 mm³ — must be plausible, never nulled here.
    assert 80.0 < mr.volume_mm3 < 140.0


# ── Tier 2 ──────────────────────────────────────────────────────────────── #

def test_neck_plane_isolates_closed_sac_with_valid_neck():
    vessel = _vessel_tree()
    origin = (0.0, 3.0, 0.0)     # neck plane in the parent-artery region
    normal = (0.0, 1.0, 0.0)     # toward the dome (sphere at +Y)

    sac = isolate_closed_sac(vessel, origin, normal, dome_seed=(0.0, 7.0, 0.0))
    assert sac.n_boundary_edges == 0            # watertight sac
    assert 2.0 < sac.neck_diameter_mm < 4.0     # ≈ cylinder Ø 3 mm

    mr = MorphometricAnalyzer().analyze(
        sac.poly_data,
        neck_plane=(sac.neck_origin, sac.neck_normal, sac.neck_diameter_mm),
    )
    assert mr.reliable is True
    assert mr.volume_mm3 > 0.0
    assert mr.max_diameter_mm > 5.0             # ≈ sphere Ø 6 mm
    assert 2.0 < mr.neck_diameter_mm < 4.0
    assert mr.dome_height_mm > 3.0
    assert mr.dome_to_neck_ratio > 1.0


def test_measure_neck_matches_cylinder_diameter():
    vessel = _vessel_tree()
    diam, area = measure_neck(
        vessel, (0.0, 3.0, 0.0), (0.0, 1.0, 0.0), (0.0, 7.0, 0.0)
    )
    assert 2.0 < diam < 4.0    # parent-artery Ø ≈ 3 mm
    assert area > 0.0
