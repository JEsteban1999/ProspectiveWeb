"""Tests for the criteria-based clip selector.

The behaviour these pin down, in the order it matters:

1. The answer is never silence. The old recommender returned an empty list for a
   1 mm neck and for a 20 mm neck alike, which reads as "no results" when it
   actually means "nothing made fits this patient". Every path here ends in
   either usable clips or a manufacturing specification.
2. The recommendation moves with the case. A selector that returns the same
   clips whatever the neck, the depth or the location is not a selector.
3. A clip that cannot physically be used never outranks one that can.
4. The specification to manufacture is derived from measurements, and says which
   of its numbers are assumptions.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_clipsel_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import vtk
from fastapi.testclient import TestClient

from main import app
from services.clip_fit import verify_all, vessel_beyond_neck
from services.clip_selection import (
    ClipCase,
    derive_manufacture_spec,
    evaluate_clip,
    select_clips,
)
from services.clips import CLIP_CATALOGUE, ClipShape
from services.database import Base, engine
from services.segmentation import write_vtp
from services.sessions import create_session, session_subdir, write_state

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


def _clip(name: str):
    return next(c for c in CLIP_CATALOGUE if c.name == name)


def _case(**kw) -> ClipCase:
    base = dict(neck_mm=5.0, ar=1.2, dome_height_mm=6.0, neck_source="rim")
    base.update(kw)
    return ClipCase(**base)  # type: ignore[arg-type]


# ── 1. The answer is never empty ──────────────────────────────────────────── #

class TestNeverSilent:
    def test_a_neck_too_small_for_any_clip_yields_a_specification(self):
        # 1 mm neck: the shortest blade in the catalogue is 5 mm, which is more
        # than 3x the neck, so every clip is rejected as oversized.
        sel = select_clips(_case(neck_mm=1.0))
        assert sel.outcome == "manufacture"
        assert sel.recommended == []
        assert sel.manufacture is not None
        assert sel.manufacture.blade_length_mm >= 2.0
        assert sel.manufacture.reasons, "a rejection has to say why"

    def test_a_neck_too_large_for_any_clip_yields_a_specification(self):
        sel = select_clips(_case(neck_mm=20.0))
        assert sel.outcome == "manufacture"
        assert sel.manufacture is not None
        # Must overshoot the neck, or it cannot close on it.
        assert sel.manufacture.blade_length_mm > 20.0

    def test_no_measured_neck_asks_for_one_instead_of_guessing(self):
        sel = select_clips(_case(neck_mm=0.0))
        assert sel.outcome == "unmeasured"
        assert sel.manufacture is None
        assert "cuello" in sel.summary.lower()

    def test_an_unreliable_neck_is_treated_as_no_neck(self):
        # The morphometry nulls its numbers on an open detector cap; a plausible
        # looking neck there would drive a confident, wrong recommendation.
        sel = select_clips(_case(neck_mm=6.0, neck_reliable=False))
        assert sel.outcome == "unmeasured"


# ── 2. The recommendation moves with the case ─────────────────────────────── #

class TestRecommendationVariesWithTheCase:
    def test_neck_width_changes_which_clips_are_offered(self):
        small = {c.clip.name for c in select_clips(_case(neck_mm=3.0)).recommended}
        large = {c.clip.name for c in select_clips(_case(neck_mm=9.0)).recommended}
        assert small and large
        assert small != large, "the neck is the primary driver of clip choice"

    def test_a_deep_dome_prefers_a_shape_that_can_reach_the_neck(self):
        shallow = select_clips(_case(neck_mm=5.0, ar=1.0, dome_height_mm=5.0))
        deep = select_clips(_case(neck_mm=5.0, ar=2.2, dome_height_mm=11.0))
        # The deep case has to raise the reach question at all.
        deep_keys = {c.key for cand in deep.recommended for c in cand.criteria}
        assert "reach" in deep_keys
        assert "reach" not in {c.key for cand in shallow.recommended for c in cand.criteria}

    def test_the_anatomical_region_changes_the_shape_preference(self):
        # Paraclinoid ICA is a deep field and argues for a bayonet; ACoA is a
        # narrow one between the A2s and argues for a straight clip.
        ica = select_clips(_case(neck_mm=5.0, region="Carótida paraclinoidea"))
        acoa = select_clips(_case(neck_mm=5.0, region="ACoA"))
        assert ica.recommended and acoa.recommended
        assert ica.recommended[0].clip.shape != acoa.recommended[0].clip.shape

    def test_an_unparsed_region_says_so_rather_than_inventing_a_preference(self):
        sel = select_clips(_case(region="zona rara sin nombre reconocible"))
        assert any("no se reconoció" in c for c in sel.caveats)
        assert "shape" not in {c.key for cand in sel.recommended for c in cand.criteria}


# ── 3. An unusable clip never outranks a usable one ───────────────────────── #

class TestFailuresDominate:
    def test_a_failed_criterion_zeroes_the_score(self):
        # A 5 mm blade cannot close on a 9 mm neck at any price.
        cand = evaluate_clip(_clip("Yasargil Mini recto"), _case(neck_mm=9.0))
        assert cand.failures
        assert cand.score == 0.0
        assert cand.verdict == "fail"

    def test_rejected_clips_are_reported_with_their_reason(self):
        sel = select_clips(_case(neck_mm=9.0))
        assert sel.rejected, "the near misses are what make the list trustworthy"
        for cand in sel.rejected:
            assert cand.failures
            assert cand.headline == cand.failures[0].detail

    def test_every_recommended_clip_is_actually_viable(self):
        for neck in (2.5, 4.0, 6.0, 8.0, 12.0):
            sel = select_clips(_case(neck_mm=neck))
            for cand in sel.recommended:
                assert cand.viable, f"{cand.clip.name} was recommended with a failed criterion"

    def test_recommended_clips_come_back_best_first(self):
        sel = select_clips(_case(neck_mm=6.0))
        scores = [c.score for c in sel.recommended]
        assert scores == sorted(scores, reverse=True)


# ── 4. The manufacturing specification ────────────────────────────────────── #

class TestManufactureSpec:
    def test_blade_length_scales_with_the_neck(self):
        a = derive_manufacture_spec(_case(neck_mm=4.0), [])
        b = derive_manufacture_spec(_case(neck_mm=12.0), [])
        assert b.blade_length_mm > a.blade_length_mm
        for spec, neck in ((a, 4.0), (b, 12.0)):
            assert spec.blade_length_mm >= neck + 1.0

    def test_the_window_is_sized_from_the_measured_parent_artery(self):
        spec = derive_manufacture_spec(
            _case(neck_mm=6.0, region="ACM bifurcación", parent_artery_mm=3.4), []
        )
        assert spec.shape == ClipShape.FENESTRATED
        assert spec.fenestration_mm > 3.4, "the window must clear the vessel, not pinch it"

    def test_without_a_parent_artery_the_window_is_left_undimensioned(self):
        # Inventing a window diameter is how you strangle a branch.
        spec = derive_manufacture_spec(
            _case(neck_mm=6.0, region="ACM bifurcación", parent_artery_mm=0.0), []
        )
        assert spec.fenestration_mm == 0.0
        assert any("vaso padre" in n for n in spec.confidence_notes)

    def test_the_spec_declares_which_numbers_are_assumptions(self):
        spec = derive_manufacture_spec(_case(neck_mm=7.0), [])
        joined = " ".join(spec.confidence_notes)
        assert "proporciones medianas" in joined
        assert "fuerza de cierre" in joined.lower()

    def test_an_automatic_neck_warns_before_ordering_a_part(self):
        spec = derive_manufacture_spec(_case(neck_mm=7.0, neck_source="auto"), [])
        assert any("automática" in n for n in spec.confidence_notes)


# ── 5. Geometric verification ─────────────────────────────────────────────── #

def _neighbour_tube(x: float) -> vtk.vtkPolyData:
    line = vtk.vtkLineSource()
    line.SetPoint1(x, -15.0, 0.0)
    line.SetPoint2(x, 15.0, 0.0)
    line.SetResolution(60)
    line.Update()
    tube = vtk.vtkTubeFilter()
    tube.SetInputData(line.GetOutput())
    tube.SetRadius(1.5)
    tube.SetNumberOfSides(20)
    tube.CappingOn()
    tube.Update()
    return tube.GetOutput()


class TestGeometricVerification:
    def test_the_neck_region_is_excluded_before_testing_collision(self):
        # Without this every clip "collides", because the neck IS vessel.
        sac = vtk.vtkSphereSource()
        sac.SetRadius(4.0)
        sac.SetCenter(0.0, 0.0, 4.0)
        sac.SetThetaResolution(30)
        sac.SetPhiResolution(30)
        sac.Update()
        kept = vessel_beyond_neck(sac.GetOutput(), (0.0, 0.0, 0.0), 5.0)
        # The sac sits entirely inside the exclusion sphere, so nothing remains.
        assert kept.GetNumberOfPoints() < sac.GetOutput().GetNumberOfPoints()

    def test_a_long_blade_fouling_a_neighbour_is_marked_down(self):
        case = _case(neck_mm=5.0, ar=1.2)
        vessel = _neighbour_tube(6.0)
        short = evaluate_clip(_clip("Yasargil Recto 7mm"), case)
        long_ = evaluate_clip(_clip("Sugita Recto XXL"), case)
        verify_all([short, long_], case, vessel, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))

        assert short.verified is not None and long_.verified is not None
        # The short blade never reaches the neighbour; the long one mostly does.
        assert short.verified.clean_rolls > long_.verified.clean_rolls
        assert short.score > long_.score

    def test_the_number_of_clean_approach_angles_is_reported(self):
        # Reporting only the best pose made a clip clean at every angle look
        # identical to one clean at exactly one.
        case = _case(neck_mm=5.0, ar=1.2)
        cand = evaluate_clip(_clip("Sugita Recto XXL"), case)
        verify_all([cand], case, _neighbour_tube(6.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        assert cand.verified is not None
        assert cand.verified.n_rolls > 1
        assert 0 <= cand.verified.clean_rolls <= cand.verified.n_rolls
        assert "orientaciones" in cand.verified.note

    def test_a_mesh_with_nothing_outside_the_neck_admits_it(self):
        # A sac-only crop cannot prove a clip clears its neighbours; claiming a
        # clean check there would be a safety statement nobody earned.
        case = _case(neck_mm=5.0)
        sac = vtk.vtkSphereSource()
        sac.SetRadius(3.0)
        sac.SetThetaResolution(20)
        sac.SetPhiResolution(20)
        sac.Update()
        cand = evaluate_clip(_clip("Yasargil Recto 7mm"), case)
        verify_all([cand], case, sac.GetOutput(), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        assert cand.verified is not None
        assert "no se pudo" in cand.verified.note


# ── 6. The API contract ───────────────────────────────────────────────────── #

def _session(neck_mm: float = 5.0, with_plane: bool = True) -> str:
    sid = create_session()
    write_state(sid, "morpho.neck_mm", str(neck_mm))
    write_state(sid, "morpho.ar", "1.4")
    write_state(sid, "morpho.dome_height_mm", str(neck_mm * 1.4))
    write_state(sid, "morpho.max_diameter_mm", str(neck_mm * 1.8))
    write_state(sid, "morpho.neck_source", "rim")
    if with_plane:
        for k, v in (("origin_x", "0"), ("origin_y", "0"), ("origin_z", "0"),
                     ("normal_x", "0"), ("normal_y", "0"), ("normal_z", "1")):
            write_state(sid, f"morpho.plane_{k}", v)
        write_vtp(_neighbour_tube(6.0), session_subdir(sid, "meshes") / "vessel_tree.vtp")
    return sid


class TestEndpoint:
    def test_unknown_session_is_a_404(self):
        assert client.get("/api/clips/selection/no-existe").status_code == 404

    def test_a_session_without_morphometry_reports_unmeasured(self):
        sid = create_session()
        r = client.get(f"/api/clips/selection/{sid}")
        assert r.status_code == 200, r.text
        assert r.json()["outcome"] == "unmeasured"

    def test_the_selection_carries_its_criteria_and_the_case_it_judged(self):
        sid = _session(neck_mm=5.0)
        r = client.get(f"/api/clips/selection/{sid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["outcome"] in ("stock", "marginal")
        assert body["case"]["neck_mm"] == 5.0
        assert body["recommended"], "a 5 mm neck is well inside the catalogue"
        top = body["recommended"][0]
        assert top["criteria"], "a recommendation without reasons is a number"
        assert {"key", "label", "verdict", "detail"} <= set(top["criteria"][0])
        assert body["caveats"]

    def test_geometry_is_verified_when_a_neck_plane_and_a_mesh_exist(self):
        sid = _session(neck_mm=5.0, with_plane=True)
        body = client.get(f"/api/clips/selection/{sid}").json()
        assert any(c["fit"] is not None for c in body["recommended"])

    def test_without_a_marked_plane_the_criteria_still_apply(self):
        sid = _session(neck_mm=5.0, with_plane=False)
        body = client.get(f"/api/clips/selection/{sid}").json()
        assert body["recommended"]
        assert all(c["fit"] is None for c in body["recommended"])

    def test_an_impossible_neck_returns_a_manufacturing_spec_over_the_api(self):
        sid = _session(neck_mm=20.0, with_plane=False)
        body = client.get(f"/api/clips/selection/{sid}").json()
        assert body["outcome"] == "manufacture"
        assert body["manufacture"]["blade_length_mm"] > 20.0
        assert body["manufacture"]["label"]

    def test_the_manufacture_endpoint_writes_a_downloadable_stl(self):
        sid = _session(neck_mm=20.0, with_plane=False)
        r = client.post(f"/api/clips/manufacture/{sid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "clip_a_medida.stl" in (body["stl_url"] or "")
        # Cache-busted, or the browser serves the previous spec's geometry.
        assert "?v=" in body["stl_url"]
        stl = session_subdir(sid, "exports") / "clip_a_medida.stl"
        assert stl.exists() and stl.stat().st_size > 0

    def test_the_manufacture_endpoint_refuses_without_a_neck(self):
        sid = create_session()
        r = client.post(f"/api/clips/manufacture/{sid}")
        assert r.status_code == 409
        assert "cuello" in r.json()["detail"].lower()
