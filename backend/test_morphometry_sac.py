"""Tier 1 (reliability guard) + Tier 2 (semi-automatic closed-sac) morphometry.

Uses synthetic VTK meshes so it runs without the DICOM corpus:
  • an open spherical cap  → must be flagged unreliable (volume/neck nulled)
  • a sphere-on-cylinder vessel tree clipped at a neck plane → closed sac with a
    valid neck (Tier 2), analysis reliable.
"""
from __future__ import annotations

import numpy as np
import pytest
import vtk

from services.morphometrics import MorphometricAnalyzer
from services.sac_isolation import (
    isolate_closed_sac,
    isolate_sac_volumetric,
    measure_neck,
)


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


# ── Tier 2 volumetric (robust, production path) ─────────────────────────── #

def _sac_volume() -> np.ndarray:
    """Synthetic volume: sac (sphere) on a parent artery (cylinder along +Z).

    HU 1000 inside, 0 outside.  World coord = index (spacing 1 mm).
    """
    vol = np.zeros((60, 60, 60), dtype=np.float32)
    zz, yy, xx = np.mgrid[0:60, 0:60, 0:60]
    sphere = (xx - 30) ** 2 + (yy - 30) ** 2 + (zz - 40) ** 2 <= 16   # r = 4, centre z=40
    cyl = ((xx - 30) ** 2 + (yy - 30) ** 2 <= 4) & (zz <= 40)         # r = 2, parent
    vol[sphere | cyl] = 1000.0
    return vol


def test_volumetric_isolation_is_watertight_with_valid_neck():
    vol = _sac_volume()
    mesh, neck = isolate_sac_volumetric(
        vol, spacing=(1.0, 1.0, 1.0),
        neck_origin=(30.0, 30.0, 35.0),   # in the parent, below the sphere
        neck_normal=(0.0, 0.0, 1.0),      # toward the dome (+Z)
        apex=(30.0, 30.0, 43.0),          # inside the sphere near its top
        lower=500.0, upper=2000.0,
        max_radius=9.0, half_extent_mm=14.0,
    )
    assert mesh.GetNumberOfPoints() > 50

    fe = vtk.vtkFeatureEdges()
    fe.SetInputData(mesh)
    fe.BoundaryEdgesOn(); fe.FeatureEdgesOff(); fe.NonManifoldEdgesOff(); fe.ManifoldEdgesOff()
    fe.Update()
    assert fe.GetOutput().GetNumberOfCells() == 0     # watertight by construction
    assert 2.0 < neck < 6.0                            # ≈ parent Ø 4 mm

    mr = MorphometricAnalyzer().analyze(
        mesh, neck_plane=((30.0, 30.0, 35.0), (0.0, 0.0, 1.0), neck)
    )
    assert mr.reliable is True
    assert mr.volume_mm3 > 0.0
    assert mr.max_diameter_mm > 6.0                    # ≈ sphere Ø 8 mm


# ── Tier 2 persistence: the manual plane must survive re-measure + restore ── #

def _session_with_synthetic_tree():
    """A live session holding the sphere-on-cylinder tree + a candidate cap."""
    from fastapi.testclient import TestClient
    from main import app
    from services.sessions import create_session, session_subdir, write_state
    from services.segmentation import write_vtp

    sid = create_session()
    meshes = session_subdir(sid, "meshes")
    write_vtp(_vessel_tree(), meshes / "vessel_tree.vtp")
    write_vtp(_open_cap(), meshes / "cand_001.vtp")     # detector output: open cap
    write_state(sid, "detect.best_vtp_name", "cand_001.vtp")
    return TestClient(app, raise_server_exceptions=True), sid


_NECK_PLANE_BODY = {
    "origin":    {"x": 0.0, "y": 3.0, "z": 0.0},
    "normal":    [0.0, 1.0, 0.0],
    "dome_seed": {"x": 0.0, "y": 7.0, "z": 0.0},
}


def test_manual_neck_plane_is_persisted_and_replayed_by_get_morphometry():
    """GET /morphometry must not silently downgrade a manual measurement.

    Regression: the automatic analysis of the detector cap is unreliable
    (neck 0), so re-running it — which is exactly what «Reanudar» does —
    used to wipe the clinician's closed-sac measurement.
    """
    from services.sessions import read_state

    client, sid = _session_with_synthetic_tree()

    auto = client.get(f"/api/morphometry/{sid}").json()
    assert auto["neck_source"] == "auto"
    assert auto["reliable"] is False                  # open cap → degenerate

    manual = client.post(f"/api/morphometry/{sid}/neck-plane", json=_NECK_PLANE_BODY)
    assert manual.status_code == 200, manual.text
    manual = manual.json()
    assert manual["neck_source"] == "manual"
    assert manual["reliable"] is True
    assert 2.0 < manual["neck_mm"] < 4.0

    # The plane itself is on record, not just the numbers it produced.
    assert read_state(sid, "morpho.neck_source") == "manual"
    assert float(read_state(sid, "morpho.plane_origin_y")) == 3.0
    assert float(read_state(sid, "morpho.plane_normal_y")) == 1.0
    assert float(read_state(sid, "morpho.plane_seed_y")) == 7.0

    # Re-measuring the session replays the plane instead of falling back.
    again = client.get(f"/api/morphometry/{sid}").json()
    assert again["neck_source"] == "manual"
    assert again["reliable"] is True
    assert again["neck_mm"] == manual["neck_mm"]
    assert again["max_diameter_mm"] == manual["max_diameter_mm"]


def test_manual_neck_plane_survives_save_and_restore():
    """Save → restore (the «Reanudar» path) must come back with the manual sac."""
    from services.sessions import rehydrate_session, snapshot_session

    client, sid = _session_with_synthetic_tree()
    manual = client.post(f"/api/morphometry/{sid}/neck-plane", json=_NECK_PLANE_BODY).json()

    snapshot_session(sid)
    restored = rehydrate_session(sid)

    after = client.get(f"/api/morphometry/{restored}").json()
    assert after["neck_source"] == "manual"
    assert after["reliable"] is True
    assert after["neck_mm"] == manual["neck_mm"]
    assert after["volume_mm3"] == manual["volume_mm3"]


def test_morphometry_persists_every_field_the_report_reads():
    """The PDF/DICOM-SR read morphometry from session state, not from the API.

    Regression: `surface_area_mm2` and `compactness` were never written, so the
    report silently printed «0.00 mm²» and «0.000» — next to a "1.0 = esfera
    perfecta" reference — while the UI showed the real values.
    """
    from services.report_generator import build_report_data_from_session

    client, sid = _session_with_synthetic_tree()
    api = client.post(f"/api/morphometry/{sid}/neck-plane", json=_NECK_PLANE_BODY).json()

    morpho = build_report_data_from_session(session_id=sid).morphometrics
    for field in (
        "volume_mm3", "surface_area_mm2", "max_diameter_mm", "neck_diameter_mm",
        "dome_height_mm", "dome_to_neck_ratio", "aspect_ratio", "compactness",
    ):
        assert morpho[field] > 0.0, f"el informe leería {field} como 0"

    # …and the numbers must be the ones the clinician saw on screen.
    assert morpho["surface_area_mm2"] == pytest.approx(api["surface_area_mm2"], abs=0.01)
    assert morpho["compactness"] == pytest.approx(api["compactness"], abs=1e-4)
    assert 0.0 <= morpho["compactness"] <= 1.0     # PDF prints it as "1.0 = esfera"


def test_neck_origin_is_exposed_and_sits_on_the_neck_plane():
    """Device planning needs the neck centre, and must not re-derive it.

    Regression: the API exposed only `centroid` and `principal_axis`, so the
    frontend approximated the neck as centroid − axis·(dome/2). That landed on
    the parent vessel (0 % neck coverage) and collapsed onto the centroid —
    inside the dome — whenever the dome height was not measured.
    """
    from services.sessions import read_state

    client, sid = _session_with_synthetic_tree()

    # Automatic run: still has to publish a neck origin for the planners.
    auto = client.get(f"/api/morphometry/{sid}").json()
    assert auto["neck_origin"] is not None

    manual = client.post(f"/api/morphometry/{sid}/neck-plane", json=_NECK_PLANE_BODY).json()
    no = manual["neck_origin"]
    assert no is not None

    # Same point the perforator analysis uses — one source of truth.
    assert no["x"] == pytest.approx(float(read_state(sid, "morpho.neck_origin_x")), abs=1e-6)
    assert no["y"] == pytest.approx(float(read_state(sid, "morpho.neck_origin_y")), abs=1e-6)
    assert no["z"] == pytest.approx(float(read_state(sid, "morpho.neck_origin_z")), abs=1e-6)

    # The neck plane sits at y = 3 with normal +Y (see _NECK_PLANE_BODY), so a
    # point *on the neck* projects onto the plane, not up inside the dome.
    assert no["y"] == pytest.approx(3.0, abs=1.5), \
        f"el punto de colocación no cae en el plano del cuello: {no}"
