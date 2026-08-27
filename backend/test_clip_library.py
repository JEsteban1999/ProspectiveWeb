"""Tests for the global, persistent clip library.

Two things matter here beyond CRUD:

1. **What is measured is really measured.** Blade length comes from the mesh, so
   a clip built to a known length has to come back at that length — including
   when the file was exported at an arbitrary orientation, which is the case an
   axis-aligned bounding box gets wrong.
2. **What cannot be measured is refused, not invented.** Closing force is a
   property of the spring; a stock clip without one cannot be scored against a
   neck, so the import says no instead of storing a zero that silently sinks the
   clip to the bottom of every ranking.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_cliplib_")
os.environ["CLIP_LIBRARY_ROOT"] = os.path.join(_tmp, "clip_library")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import pytest
import vtk

from services import clip_library
from services.clip_selection import ClipCase, select_clips
from services.devices import apply_transform, make_clip_shaped, write_stl


@pytest.fixture(autouse=True)
def _clean_library():
    clip_library.clear_library()
    yield
    clip_library.clear_library()


def _stl_bytes(length_mm: float, shape: str = "STRAIGHT", rotate: bool = False) -> bytes:
    """A clip of known blade length, optionally exported at an odd orientation."""
    poly = make_clip_shaped(length_mm, 1.2, 1.0, shape)
    if rotate:
        t = vtk.vtkTransform()
        t.RotateZ(37.0)
        t.RotateX(24.0)
        poly = apply_transform(poly, t)
    path = os.path.join(_tmp, f"probe_{length_mm}_{shape}_{rotate}.stl")
    write_stl(poly, path)
    with open(path, "rb") as fh:
        return fh.read()


def _add(name="Clip", kind="stock", length=9.0, force=110.0, **kw):
    return clip_library.add_clip(
        raw=_stl_bytes(length, kw.pop("shape_geom", "STRAIGHT")),
        source_filename=f"{name}.stl",
        name=name, kind=kind, closing_force_g=force, **kw,
    )


# ── Measurement ───────────────────────────────────────────────────────────── #

class TestMeasurement:
    def test_blade_length_comes_back_at_the_length_it_was_built_to(self):
        clip = _add(length=9.0)
        # The sweep overlaps its segments slightly, so allow a small tolerance.
        assert clip.blade_length_mm == pytest.approx(9.0, abs=1.0)

    def test_an_odd_export_orientation_does_not_inflate_the_length(self):
        # The point of an ORIENTED bounding box: axis-aligned bounds would
        # measure the diagonal of a tilted clip as its blade length.
        straight = clip_library.add_clip(
            raw=_stl_bytes(9.0), source_filename="a.stl", name="recto",
            kind="stock", closing_force_g=110.0,
        )
        tilted = clip_library.add_clip(
            raw=_stl_bytes(9.0, rotate=True), source_filename="b.stl", name="girado",
            kind="stock", closing_force_g=110.0,
        )
        assert tilted.blade_length_mm == pytest.approx(straight.blade_length_mm, abs=0.6)

    def test_a_longer_clip_measures_longer(self):
        short = _add(name="corto", length=6.0)
        long_ = _add(name="largo", length=15.0)
        assert long_.blade_length_mm > short.blade_length_mm + 5.0

    def test_the_stored_width_is_the_envelope_not_one_blade(self):
        # Two blades plus the jaw gap. Recording it as a blade width would make
        # the selector think the blade is three times thicker than it is.
        clip = _add(length=9.0)
        assert clip.envelope_width_mm > 1.2

    def test_the_shape_hint_separates_a_bent_blade_from_a_flat_one(self):
        straight = make_clip_shaped(9.0, 1.2, 1.0, "STRAIGHT").GetBounds()
        angled = make_clip_shaped(9.0, 1.2, 1.0, "ANGLED", 90.0).GetBounds()
        s_shape, _ = clip_library.suggest_shape(
            straight[1] - straight[0], straight[3] - straight[2], straight[5] - straight[4]
        )
        a_shape, why = clip_library.suggest_shape(
            max(angled[1] - angled[0], angled[5] - angled[4]),
            angled[3] - angled[2],
            min(angled[1] - angled[0], angled[5] - angled[4]),
        )
        assert s_shape == "STRAIGHT"
        assert a_shape in ("ANGLED", "CURVED")
        assert why, "a suggestion has to say what it is based on"


# ── What must be declared ─────────────────────────────────────────────────── #

class TestDeclaredSpecification:
    def test_a_stock_clip_without_a_closing_force_is_refused(self):
        with pytest.raises(ValueError, match="fuerza de cierre"):
            _add(force=0.0)

    def test_a_template_may_omit_the_closing_force(self):
        # A design that has not been made yet has no spring to measure.
        clip = _add(name="plantilla", kind="template", force=0.0)
        assert clip.kind == "template"
        assert clip.closing_force_g == 0.0

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="Tipo de clip"):
            _add(kind="inventado")

    def test_an_unsupported_format_is_refused(self):
        with pytest.raises(ValueError, match="Formato"):
            clip_library.add_clip(
                raw=b"not a mesh", source_filename="clip.txt", name="x",
                kind="stock", closing_force_g=100.0,
            )

    def test_a_mesh_that_cannot_be_read_leaves_nothing_behind(self):
        with pytest.raises(Exception):
            clip_library.add_clip(
                raw=b"garbage", source_filename="clip.stl", name="x",
                kind="stock", closing_force_g=100.0,
            )
        assert clip_library.list_clips() == []


# ── Persistence and feeding the selector ──────────────────────────────────── #

class TestLibraryFeedsTheSelector:
    def test_a_stock_clip_joins_the_catalogue_the_selector_scores(self):
        from services.clips import CLIP_CATALOGUE

        before = len(clip_library.catalogue_with_library())
        assert before == len(CLIP_CATALOGUE)
        _add(name="Clip del hospital", length=9.0, force=110.0)
        assert len(clip_library.catalogue_with_library()) == before + 1
        assert any(c.name == "Clip del hospital" for c in clip_library.catalogue_with_library())

    def test_a_template_never_competes_as_stock(self):
        # A design nobody has manufactured is not something to reach for in theatre.
        _add(name="Plantilla A", kind="template", force=0.0)
        names = [c.name for c in clip_library.catalogue_with_library()]
        assert "Plantilla A" not in names

    def test_an_institution_clip_can_be_recommended_for_a_real_case(self):
        # A 20 mm neck has nothing in the built-in catalogue; a long enough clip
        # in the library has to turn that "manufacture" into a real option.
        assert select_clips(ClipCase(neck_mm=20.0, neck_source="rim")).outcome == "manufacture"
        _add(name="Clip XXL institucional", length=27.0, force=160.0)
        after = select_clips(ClipCase(neck_mm=20.0, neck_source="rim"))
        assert after.outcome in ("stock", "marginal")
        assert any("institucional" in c.clip.name for c in after.recommended)

    def test_entries_survive_being_re_read_from_disk(self):
        clip = _add(name="Persistente")
        again = clip_library.get_clip(clip.id)
        assert again is not None
        assert again.name == "Persistente"
        assert clip_library.mesh_path(again).exists()

    def test_deleting_removes_the_entry_and_its_geometry(self):
        clip = _add(name="Efímero")
        path = clip_library.mesh_path(clip)
        assert path.exists()
        assert clip_library.delete_clip(clip.id) is True
        assert clip_library.get_clip(clip.id) is None
        assert not path.exists()

    def test_deleting_something_that_is_not_there_reports_it(self):
        assert clip_library.delete_clip("no-existe") is False
