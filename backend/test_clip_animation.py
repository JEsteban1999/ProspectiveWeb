"""Showing a clip go on: the pieces, the hinge, and the run in.

Two families with incompatible layouts have to work through one code path — the
synthetic catalogue clips hinge at one end of the blade, the NAVARRO™ exports
near the middle of the part — so nothing here may be declared per family. The
hinge and the opening axis are read off whatever mesh arrives.

The first test in `TestTheClipSitsOnTheNeck` guards a defect this work exposed:
NAVARRO clips were being posed with the jaw pointing straight up the neck
normal, i.e. driven into the aneurysm, because the exports use a different frame
from the one `pose_transform` expects.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_anim_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
import pytest
import vtk
from fastapi.testclient import TestClient

from main import app
from services import navarro
from services.clip_animation import (
    APPROACH_STANDOFF_MIN_MM,
    blade_swing_deg,
    default_approach,
    jaw_geometry,
    split_blades,
)
from services.database import Base, engine
from services.devices import apply_transform, make_clip_shaped, pose_transform
from services.segmentation import write_vtp
from services.sessions import create_session, session_subdir

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)

_HAS_NAVARRO = bool(navarro.list_variants(root=navarro.DEFAULT_ROOT))


# Other suites point NAVARRO_ROOT at an empty directory to exercise the built-in
# catalogue alone, and pytest runs them all in one process. This suite states its
# own root per test rather than trusting whatever the environment holds by then.
@pytest.fixture(autouse=True)
def _real_library():
    before = os.environ.get("NAVARRO_ROOT")
    os.environ["NAVARRO_ROOT"] = str(navarro.DEFAULT_ROOT)
    navarro.clear_cache()
    yield
    navarro.clear_cache()
    if before is None:
        os.environ.pop("NAVARRO_ROOT", None)
    else:
        os.environ["NAVARRO_ROOT"] = before


def _pts(poly):
    return np.array([poly.GetPoint(i) for i in range(poly.GetNumberOfPoints())])


def _synthetic(blade=10.0):
    return make_clip_shaped(blade, 1.4, 1.0, "STRAIGHT")


# ── The frame defect this work uncovered ──────────────────────────────────── #

class TestTheClipSitsOnTheNeck:
    """A clip closes ACROSS the neck; it does not point into the dome.

    `pose_transform` aligns a device's local +Z to the neck normal, and the
    synthetic clips are drawn for that — blade length in the plane, blade depth
    along the normal. The NAVARRO™ exports use +Z for the clip's long axis, so
    posed unchanged the jaw ran straight up the normal: measured on a neck at
    z = 0 with the dome above, the 10 mm clip reached +12.5 mm along the normal,
    driving its blades 12.5 mm into the aneurysm.
    """

    def _reach_along_normal(self, poly):
        world = apply_transform(poly, pose_transform((0, 0, 0), (0, 0, 1), 0.0))
        return _pts(world)[:, 2]

    def test_a_synthetic_clip_lies_in_the_neck_plane(self):
        z = self._reach_along_normal(_synthetic(10.0))
        assert abs(z).max() < 3.0, "la hoja sintética debe quedar en el plano del cuello"

    @pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
    def test_a_navarro_clip_does_not_drive_into_the_dome(self):
        z = self._reach_along_normal(navarro.mesh_for_id("navarro:t1:0:10.0"))
        # The dome sits on the +normal side; a clip reaching far up it is impaling
        # the sac, not clipping its neck.
        assert z.max() < 4.0, f"el clip se adentra {z.max():.1f} mm en el domo"

    @pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
    def test_the_blade_spans_the_neck_instead(self):
        world = apply_transform(navarro.mesh_for_id("navarro:t1:0:10.0"),
                                pose_transform((0, 0, 0), (0, 0, 1), 0.0))
        P = _pts(world)
        in_plane = np.linalg.norm(P[:, :2], axis=1).max()
        assert in_plane > 8.0, "la hoja tiene que cruzar el cuello"


# ── Reading the mechanism off the mesh ────────────────────────────────────── #

class TestJawGeometryIsDerived:
    def test_a_synthetic_clip_is_read_correctly(self):
        g = jaw_geometry(_synthetic(10.0))
        assert g["open_axis"] != g["long_axis"]
        assert g["lever_mm"] > 5.0

    @pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
    def test_every_navarro_size_reads_the_same_way(self):
        # A real family hinges in one place; a reading that wandered between
        # sizes would mean the derivation, not the design, was moving.
        seen = []
        for jaw in navarro.STOCK_JAW_MM:
            g = jaw_geometry(navarro.mesh_for_id(f"navarro:t1:0:{jaw}.0"))
            seen.append((g["open_axis"], g["long_axis"], g["jaw_direction"], g["hinge"]))
        axes = {(a, l, d) for a, l, d, _h in seen}
        assert len(axes) == 1, f"la derivación cambia entre tallas: {axes}"
        hinges = [h for *_r, h in seen]
        assert max(hinges) - min(hinges) < 1.0, f"la bisagra se mueve: {hinges}"

    @pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
    def test_the_lever_grows_with_the_jaw(self):
        short = jaw_geometry(navarro.mesh_for_id("navarro:t1:0:7.0"))["lever_mm"]
        long_ = jaw_geometry(navarro.mesh_for_id("navarro:t1:0:22.0"))["lever_mm"]
        assert long_ > short + 10.0

    def test_the_opening_never_passes_the_stated_ceiling(self):
        # The designer states the tips part by at most 10 mm — a property of the
        # mechanism, not of the blade in front of it. A 22 mm jaw opens no
        # further than a 10 mm one.
        from services.clip_animation import MAX_TIP_OPENING_MM, tip_opening_mm

        assert tip_opening_mm(7.0) == pytest.approx(7.0)
        assert tip_opening_mm(22.0) == pytest.approx(MAX_TIP_OPENING_MM)
        assert tip_opening_mm(200.0) == pytest.approx(MAX_TIP_OPENING_MM)

    def test_a_longer_blade_needs_less_swing_for_the_same_opening(self):
        # Same 10 mm at the tips over a longer lever is a smaller angle. Getting
        # this backwards would open a long clip like a pair of scissors.
        g = jaw_geometry(_synthetic(10.0))
        assert blade_swing_deg(g, 22.0) < blade_swing_deg(g, 10.0) * 1.05

    def test_the_opening_is_only_a_guess_below_the_ceiling(self):
        from services.clip_animation import opening_is_specified

        assert opening_is_specified(22.0), "por encima del tope no se supone nada"
        assert not opening_is_specified(7.0), "por debajo sigue siendo inferido"


# ── Splitting ─────────────────────────────────────────────────────────────── #

class TestSplitBlades:
    def _split(self, poly):
        body, a, b, geom = split_blades(poly)
        return body, a, b, geom

    def test_both_blades_come_away_with_geometry(self):
        _body, a, b, _g = self._split(_synthetic(10.0))
        assert a.GetNumberOfPoints() > 20 and b.GetNumberOfPoints() > 20

    def test_the_blades_land_on_opposite_sides_of_the_gap(self):
        _body, a, b, g = self._split(_synthetic(10.0))
        ax = g["open_axis"]
        assert _pts(a)[:, ax].mean() * _pts(b)[:, ax].mean() < 0

    @pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
    def test_a_navarro_clip_splits_into_three_real_pieces(self):
        body, a, b, _g = self._split(navarro.mesh_for_id("navarro:t1:0:10.0"))
        for name, part in (("cuerpo", body), ("hoja+", a), ("hoja-", b)):
            assert part.GetNumberOfPoints() > 100, f"{name} salió vacía"

    @pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
    def test_the_blades_sit_on_the_jaw_side_of_the_hinge(self):
        _body, a, b, g = self._split(navarro.mesh_for_id("navarro:t1:0:10.0"))
        la, d, hinge = g["long_axis"], g["jaw_direction"], g["hinge"]
        for part in (a, b):
            beyond = (_pts(part)[:, la] - hinge) * d
            assert beyond.max() > 1.0, "una hoja quedó detrás de la bisagra"


# ── The approach ──────────────────────────────────────────────────────────── #

class TestDefaultApproach:
    def test_it_backs_off_against_the_normal(self):
        # The normal points at the dome, so the only direction certain to be
        # clear of the sac is the opposite one.
        entry, target = default_approach((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 24.0)
        assert target == (0.0, 0.0, 0.0)
        assert entry[2] < 0.0

    def test_it_stands_far_enough_back_to_be_seen_arriving(self):
        entry, _t = default_approach((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 5.0)
        assert abs(entry[2]) >= APPROACH_STANDOFF_MIN_MM

    def test_a_longer_clip_starts_further_out(self):
        short, _ = default_approach((0, 0, 0), (0, 0, 1), 10.0)
        long_, _ = default_approach((0, 0, 0), (0, 0, 1), 40.0)
        assert abs(long_[2]) > abs(short[2])


# ── The endpoint ──────────────────────────────────────────────────────────── #

def _session() -> str:
    sid = create_session()
    src = vtk.vtkSphereSource()
    src.SetRadius(6.0)
    src.SetThetaResolution(20)
    src.SetPhiResolution(20)
    src.Update()
    write_vtp(src.GetOutput(), session_subdir(sid, "meshes") / "vessel_tree.vtp")
    return sid


def _body(clip_id="yasargil-recto-9mm", traj=False):
    out = {
        "session_id": "x",
        "placements": [{"clip_id": clip_id, "position": {"x": 0, "y": 0, "z": 0},
                        "normal": [0, 0, 1], "rotation_deg": 0}],
    }
    if traj:
        out["trajectory_entry"] = {"x": 0, "y": -40, "z": 0}
        out["trajectory_target"] = {"x": 0, "y": 0, "z": 0}
    return out


class TestEndpoint:
    def test_it_returns_three_meshes_and_a_hinge(self):
        sid = _session()
        r = client.post(f"/api/clips/animation/{sid}", json=_body())
        assert r.status_code == 200, r.text
        b = r.json()
        for k in ("body_url", "blade_a_url", "blade_b_url"):
            assert b[k] and "?v=" in b[k], f"{k} sin token de caché"
        assert b["swing_deg"] > 0
        assert len(b["hinge_axis"]) == 3

    def test_the_opening_is_declared_as_assumed(self):
        # A closed STL records no mechanism; the UI must not imply otherwise.
        sid = _session()
        assert client.post(f"/api/clips/animation/{sid}", json=_body()).json()["mechanics_assumed"] is True

    def test_a_marked_corridor_is_used_when_there_is_one(self):
        sid = _session()
        b = client.post(f"/api/clips/animation/{sid}", json=_body(traj=True)).json()
        assert b["approach_is_default"] is False
        assert b["approach_entry"]["y"] == -40

    def test_without_a_corridor_it_falls_back_and_says_so(self):
        sid = _session()
        b = client.post(f"/api/clips/animation/{sid}", json=_body()).json()
        assert b["approach_is_default"] is True
        assert b["approach_entry"]["z"] < 0

    @pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
    def test_it_works_for_a_navarro_clip_too(self):
        sid = _session()
        b = client.post(f"/api/clips/animation/{sid}", json=_body("navarro:t1:0:10.0")).json()
        assert b["swing_deg"] > 0
        assert "NAVARRO" in b["clip_name"]

    def test_no_placement_is_refused(self):
        sid = _session()
        r = client.post(f"/api/clips/animation/{sid}",
                        json={"session_id": "x", "placements": []})
        assert r.status_code == 422

    def test_an_unknown_session_is_a_404(self):
        assert client.post("/api/clips/animation/no-existe", json=_body()).status_code == 404
