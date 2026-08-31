"""The NAVARRO™ family: the jaw is the blade, and resizing must spare the spring.

Three things these pin down, each of which was a real trap:

1. **The name states the jaw, not the clip.** A 7 mm NAVARRO is 21.30 mm long.
   Measuring the envelope and calling it the blade makes the selector reject, as
   "oversized ×5.3", the very clip that fits a 4 mm neck.
2. **Resizing scales the jaw only.** A uniform scale also scales the spring, and
   the closing force is then no longer the family's — silently, since nothing in
   a mesh records a spring rate.
3. **A design band is not a measurement.** The force is 120–200 g by design and
   uncharacterised, so no clip in this family may report the force criterion as
   met, however well the band happens to sit.
"""
from __future__ import annotations

import math
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_navarro_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import pytest
import vtk

from services import navarro
from services.clip_selection import (
    ClipCase,
    evaluate_clip,
    ideal_jaw_mm,
    select_clips,
    suggest_custom_jaw,
)

# Other suites point NAVARRO_ROOT at an empty directory to test the built-in
# catalogue in isolation, and pytest runs them all in one process. So this suite
# states its own root per test rather than trusting whatever the environment
# holds by the time it runs — import order is not something to depend on.
@pytest.fixture(autouse=True)
def _real_library():
    before = os.environ.get("NAVARRO_ROOT")
    os.environ["NAVARRO_ROOT"] = str(navarro.DEFAULT_ROOT)
    yield
    if before is None:
        os.environ.pop("NAVARRO_ROOT", None)
    else:
        os.environ["NAVARRO_ROOT"] = before


pytestmark = pytest.mark.skipif(
    not navarro.list_variants(root=navarro.DEFAULT_ROOT),
    reason="La biblioteca NAVARRO™ no está en esta máquina",
)


def _bounds(poly) -> tuple[float, ...]:
    b = [0.0] * 6
    poly.GetBounds(b)
    return tuple(b)


def _straight(jaw: int):
    return next(v for v in navarro.list_variants()
                if v.angle_deg == 0 and v.jaw_mm == jaw)


# ── 1. The jaw is the blade ───────────────────────────────────────────────── #

class TestJawIsTheBlade:
    def test_the_family_is_read_from_the_stl_exports(self):
        vs = navarro.list_variants()
        assert len(vs) >= 42
        assert all(v.path.suffix.lower() == ".stl" for v in vs), (
            "los .obj están en centímetros y sin soldar: no deben entrar"
        )

    def test_the_spec_reports_the_jaw_not_the_overall_length(self):
        spec = navarro.to_spec(_straight(7))
        assert spec.blade_length_mm == 7.0
        # The part really is 21.30 mm long; that is what must NOT be the blade.
        assert _bounds(navarro.load_mesh(_straight(7)))[5] == pytest.approx(9.5, abs=0.1)

    def test_total_length_is_the_jaw_plus_the_constant_body(self):
        for jaw in navarro.STOCK_JAW_MM:
            v = _straight(jaw)
            b = _bounds(navarro.load_mesh(v))
            assert (b[5] - b[4]) == pytest.approx(jaw + navarro.BODY_LENGTH_MM, abs=0.1)

    def test_a_clip_that_fits_is_not_rejected_as_oversized(self):
        # The regression in one line: 7 mm of jaw suits a 4 mm neck; 21.30 mm of
        # envelope does not, and the difference is a `fail`.
        case = ClipCase(neck_mm=4.0, ar=1.3, dome_height_mm=5.2, neck_source="rim")
        cand = evaluate_clip(navarro.to_spec(_straight(7)), case)
        assert cand.viable, cand.headline


# ── 2. Resizing spares the spring ─────────────────────────────────────────── #

class TestResizeJaw:
    def test_the_jaw_reaches_the_requested_length(self):
        src = _straight(7)
        out = navarro.resize_jaw(navarro.load_mesh(src), 7, 12.5, 0.0)
        b = _bounds(out)
        assert (b[5] - navarro.JAW_ROOT_Z_MM) == pytest.approx(12.5, abs=0.15)

    def test_the_body_is_left_exactly_as_drawn(self):
        # The whole point: the spring must not change, or the closing force is no
        # longer the one the family will be characterised with.
        src = _straight(7)
        before = _bounds(navarro.load_mesh(src))
        after = _bounds(navarro.resize_jaw(navarro.load_mesh(src), 7, 18.0, 0.0))
        assert after[4] == pytest.approx(before[4], abs=1e-6)   # Zmin: body end
        assert after[0] == pytest.approx(before[0], abs=1e-6)   # X width unchanged
        assert after[1] == pytest.approx(before[1], abs=1e-6)
        assert after[2] == pytest.approx(before[2], abs=1e-6)   # Y depth unchanged
        assert after[3] == pytest.approx(before[3], abs=1e-6)

    def test_a_stretched_jaw_matches_the_drawn_size_it_imitates(self):
        # Stretching the 7 mm design to 22 mm should land on the 22 mm design.
        grown = navarro.resize_jaw(navarro.load_mesh(_straight(7)), 7, 22, 0.0)
        drawn = navarro.load_mesh(_straight(22))
        gb, db = _bounds(grown), _bounds(drawn)
        assert gb[5] == pytest.approx(db[5], abs=0.2), "la punta debe caer en el mismo sitio"
        assert gb[4] == pytest.approx(db[4], abs=0.05)

    def test_an_angled_jaw_grows_along_its_own_axis(self):
        v = next(x for x in navarro.list_variants() if x.angle_deg == 90 and x.jaw_mm == 7)
        out = navarro.resize_jaw(navarro.load_mesh(v), 7, 14.0, 90.0)
        b = _bounds(out)
        # A 90° jaw runs in +X, so growing it must extend X and leave Z alone.
        assert b[1] == pytest.approx(2.5 + 14.0, abs=0.3)
        assert b[5] == pytest.approx(_bounds(navarro.load_mesh(v))[5], abs=0.05)

    def test_the_mesh_stays_a_closed_solid_after_stretching(self):
        # A stretch that tore the surface would be useless for collision testing.
        out = navarro.resize_jaw(navarro.load_mesh(_straight(10)), 10, 17.0, 0.0)
        tri = vtk.vtkTriangleFilter()
        tri.SetInputData(out)
        tri.Update()
        fe = vtk.vtkFeatureEdges()
        fe.SetInputData(tri.GetOutput())
        fe.BoundaryEdgesOn()
        fe.NonManifoldEdgesOn()
        fe.FeatureEdgesOff()
        fe.ManifoldEdgesOff()
        fe.Update()
        assert fe.GetOutput().GetNumberOfCells() == 0

    def test_build_jaw_says_whether_it_had_to_stretch(self):
        _m, src, exact = navarro.build_jaw(0.0, 13.0)
        assert exact and src.jaw_mm == 13
        _m2, _src2, exact2 = navarro.build_jaw(0.0, 13.7)
        assert not exact2


# ── 3. A design band is not a measurement ─────────────────────────────────── #

class TestProvisionalForce:
    def test_the_force_travels_as_a_band(self):
        spec = navarro.to_spec(_straight(10))
        assert spec.force_band == (120.0, 200.0)
        assert spec.force_provisional is True

    def test_the_force_criterion_is_never_reported_as_met(self):
        # However well 120–200 g sits, nobody can claim the criterion is met
        # before the manufacturer characterises the spring.
        for neck in (3.0, 5.0, 8.0, 12.0):
            case = ClipCase(neck_mm=neck, ar=1.3, dome_height_mm=neck * 1.3, neck_source="rim")
            cand = evaluate_clip(navarro.to_spec(_straight(10)), case)
            force = next(c for c in cand.criteria if c.key == "force")
            assert force.verdict != "ok", f"cuello {neck}: la fuerza no está caracterizada"

    def test_the_band_is_shown_rather_than_a_midpoint(self):
        case = ClipCase(neck_mm=5.0, ar=1.3, dome_height_mm=6.5, neck_source="rim")
        cand = evaluate_clip(navarro.to_spec(_straight(7)), case)
        force = next(c for c in cand.criteria if c.key == "force")
        assert "120" in force.detail and "200" in force.detail
        assert "160" not in force.detail, "un punto medio inventa una precisión que no hay"


# ── 4. The family reaches the selector ────────────────────────────────────── #

class TestInSelection:
    def test_the_family_joins_the_catalogue_without_an_import_step(self):
        from services.clip_library import catalogue_with_library

        names = [c.name for c in catalogue_with_library()]
        assert sum(1 for n in names if "NAVARRO" in n) >= 42

    def test_a_neck_the_built_in_catalogue_cannot_serve_now_has_an_answer(self):
        # The built-in blades stop at 20 mm, so a 20 mm neck used to come back
        # as "manufacture" with nothing to reach for.
        sel = select_clips(ClipCase(neck_mm=20.0, ar=1.3, dome_height_mm=26.0,
                                    neck_source="rim"))
        assert sel.outcome in ("stock", "marginal")
        assert any("NAVARRO" in c.clip.name for c in sel.recommended)

    def test_made_to_order_clips_are_labelled_as_such(self):
        sel = select_clips(ClipCase(neck_mm=14.0, ar=1.3, dome_height_mm=18.0,
                                    neck_source="rim"))
        nav = [c for c in sel.recommended if "NAVARRO" in c.clip.name]
        assert nav, "esperaba NAVARRO entre los recomendados para un cuello grande"
        assert all(c.clip.availability == "made_to_order" for c in nav)
        assert any("bajo pedido" in c for c in sel.caveats)

    def test_the_uncharacterised_force_is_surfaced_at_case_level(self):
        sel = select_clips(ClipCase(neck_mm=14.0, ar=1.3, dome_height_mm=18.0,
                                    neck_source="rim"))
        assert any("sin caracterizar" in c for c in sel.caveats)


# ── 5. The automatic custom jaw ───────────────────────────────────────────── #

class TestCustomJaw:
    def test_a_neck_below_the_smallest_drawn_size_gets_an_exact_jaw(self):
        case = ClipCase(neck_mm=3.0, ar=1.3, dome_height_mm=3.9, neck_source="rim")
        cj = suggest_custom_jaw(case, None)
        assert cj is not None
        assert cj.jaw_mm == pytest.approx(ideal_jaw_mm(case), abs=0.1)
        assert cj.jaw_mm < min(navarro.STOCK_JAW_MM)

    def test_a_neck_above_the_largest_drawn_size_gets_one_too(self):
        case = ClipCase(neck_mm=20.0, ar=1.3, dome_height_mm=26.0, neck_source="rim")
        cj = suggest_custom_jaw(case, None)
        assert cj is not None and cj.jaw_mm > max(navarro.STOCK_JAW_MM)

    def test_nothing_is_offered_when_a_drawn_size_already_fits(self):
        # Machining a special to save a fraction of a millimetre is not a service.
        case = ClipCase(neck_mm=5.2, ar=1.3, dome_height_mm=6.8, neck_source="rim")
        assert suggest_custom_jaw(case, None) is None

    def test_the_suggestion_explains_itself(self):
        case = ClipCase(neck_mm=3.0, ar=1.3, dome_height_mm=3.9, neck_source="rim")
        cj = suggest_custom_jaw(case, None)
        assert cj is not None
        assert "mordaza" in cj.reason and "3.0" in cj.reason


# ── 6. The endpoint ───────────────────────────────────────────────────────── #

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from services.database import Base, engine  # noqa: E402
from services.sessions import create_session, session_subdir, write_state  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


class TestEndpoint:
    def test_a_drawn_size_comes_back_as_designed(self):
        sid = create_session()
        r = client.post(f"/api/clips/navarro/{sid}?jaw_mm=13&angle_deg=0")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["nearest_drawn_mm"] == 13.0
        assert "tal cual" in body["reason"]

    def test_a_custom_size_says_it_was_stretched(self):
        sid = create_session()
        body = client.post(f"/api/clips/navarro/{sid}?jaw_mm=11.5&angle_deg=0").json()
        assert body["jaw_mm"] == 11.5
        assert "estirada" in body["reason"]
        assert "CAD paramétrico" in body["reason"]

    def test_both_a_viewer_mesh_and_an_stl_are_written(self):
        sid = create_session()
        body = client.post(f"/api/clips/navarro/{sid}?jaw_mm=9&angle_deg=45").json()
        assert body["mesh_url"] and body["stl_url"]
        assert "?v=" in body["mesh_url"], "sin token la vista previa anterior queda en caché"
        exports = list(session_subdir(sid, "exports").glob("navarro_*.stl"))
        assert exports and exports[0].stat().st_size > 0

    def test_an_unknown_session_is_a_404(self):
        assert client.post("/api/clips/navarro/no-existe?jaw_mm=9").status_code == 404

    def test_an_absurd_jaw_is_refused_by_the_contract(self):
        sid = create_session()
        assert client.post(f"/api/clips/navarro/{sid}?jaw_mm=0.1").status_code == 422
        assert client.post(f"/api/clips/navarro/{sid}?jaw_mm=999").status_code == 422


# ── 7. Defects found while reviewing the integration ──────────────────────── #

class TestPlacementUsesTheRealClip:
    def test_every_navarro_clip_can_be_addressed_by_its_id(self):
        # The catalogue index was frozen at import from the BUILT-IN catalogue
        # only, so all 42 NAVARRO ids missed it and placing one silently fell
        # back to a generic 9 mm box: the plan and the report then described a
        # clip nobody had chosen.
        from routers.clips import _catalogue_index

        index = _catalogue_index()
        for spec in navarro.family_specs():
            assert spec.identifier in index, spec.name

    def test_the_id_survives_a_round_trip(self):
        # Slugging a display name carrying ™, a degree sign and a decimal point
        # is fragile; the id is structured so the geometry can be rebuilt from it.
        for spec in navarro.family_specs():
            parsed = navarro.parse_clip_id(spec.identifier)
            assert parsed is not None
            assert parsed[2] == spec.blade_length_mm

    def test_placing_one_uses_its_real_geometry(self):
        mesh = navarro.mesh_for_id("navarro:t1:0:7.0")
        b = _bounds(mesh)
        # Longest extent, not a named axis: `mesh_for_id` returns the clip in the
        # app's device frame, so which axis carries the length is not the file's
        # business. The drawn 7 mm clip is 21.30 mm long either way; a generic
        # fallback would not be.
        longest = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
        assert longest == pytest.approx(21.3, abs=0.2)
        assert mesh.GetNumberOfPoints() > 5000, "esto es la pieza real, no una caja"

    def test_an_id_that_is_not_ours_is_rejected_rather_than_guessed(self):
        assert navarro.parse_clip_id("yasargil-recto-9mm") is None
        assert navarro.parse_clip_id("navarro:t1:0") is None
        with pytest.raises(ValueError):
            navarro.mesh_for_id("custom:3")


class TestListingIsCached:
    def test_a_repeated_listing_does_not_rewalk_the_tree(self):
        navarro.clear_cache()
        navarro.list_variants()
        key = str(navarro.library_root())
        assert key in navarro._CACHE, (
            "la clave de caché la machacaba el bucle, así que nunca acertaba "
            "y acumulaba entradas basura"
        )
        assert navarro.list_variants() is navarro._CACHE[key][1]

    def test_the_cache_is_keyed_by_folder_not_by_variant(self):
        navarro.clear_cache()
        navarro.list_variants()
        assert all(isinstance(k, str) for k in navarro._CACHE)


class TestPlacingARecommendedClipEndToEnd:
    """Recommend → place → report, with the geometry that was recommended.

    The gap this closes: the panel could offer a NAVARRO clip, and placing it
    produced a generic box under a raw id. What the surgeon chose, what the
    viewer drew and what the report named were three different things.
    """

    def test_a_recommended_clip_can_be_placed_and_named(self):
        from services.device_state import read_clips
        from services.report_generator import build_report_data_from_session

        sid = create_session()
        write_state(sid, "morpho.neck_mm", "12.0")
        write_state(sid, "morpho.ar", "1.3")
        write_state(sid, "morpho.dome_height_mm", "15.6")
        write_state(sid, "morpho.neck_source", "rim")

        body = client.get(f"/api/clips/selection/{sid}").json()
        nav = next((c for c in body["recommended"] if c["clip_id"].startswith("navarro:")), None)
        assert nav is not None, "un cuello de 12 mm debería llegar a la familia NAVARRO"

        r = client.post("/api/clips/plan", json={
            "session_id": sid,
            "placements": [{"clip_id": nav["clip_id"],
                            "position": {"x": 0, "y": 0, "z": 0},
                            "normal": [0, 0, 1], "rotation_deg": 0}],
        })
        assert r.status_code == 200, r.text

        placed = read_clips(sid)
        assert len(placed) == 1
        # Named, not left as a raw id, and it is the clip that was recommended.
        assert "NAVARRO" in placed[0]["name"]
        assert placed[0]["name"] == nav["clip_name"]
        assert build_report_data_from_session(sid).clips

    def test_the_placed_geometry_is_the_designed_part(self):
        # A generic fallback would be a 9 mm box; the real 16 mm design is not.
        from services.navarro import mesh_for_id

        mesh = mesh_for_id("navarro:t1:0:16.0")
        b = _bounds(mesh)
        longest = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
        assert longest == pytest.approx(16 + navarro.BODY_LENGTH_MM, abs=0.2)
