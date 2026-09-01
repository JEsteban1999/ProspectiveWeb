"""The clip to have made: what it is built from, and what leaves the building.

Three things these pin down:

1. **What goes to a workshop is a solid.** The old STL came from a box builder —
   348 triangles with 696 boundary edges. An open surface is not a solid and no
   workshop or printer can take it. Anything meant to be MADE comes from the
   drawn designs, which are watertight.
2. **A shape the family cannot build is never silently substituted.** Asking for
   a fenestrated clip used to return the nearest ANGLE — a straight clip — while
   the spec still read "Fenestrado, ventana 3.7 mm".
3. **The workshop copy carries no patient data.** Checked with a real PDF text
   extractor and a positive control, because an earlier attempt at this check
   passed on a document it could not actually read.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_mfg_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from pathlib import Path

import pytest
import vtk
from fastapi.testclient import TestClient

from main import app
from services import navarro
from services.clip_dossier import render_dossier
from services.clip_manufacture import (
    MATERIAL,
    build_manufacture_mesh,
    external_dossier,
    family_shapes,
    internal_dossier,
    resolve_perfect_clip,
)
from services.clip_selection import ClipCase, derive_manufacture_spec
from services.clips import ClipShape
from services.database import Base, engine
from services.sessions import create_session, write_state

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)

_HAS_NAVARRO = bool(navarro.list_variants(root=navarro.DEFAULT_ROOT))


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


def _case(neck=6.0, region="", parent=3.2):
    return ClipCase(neck_mm=neck, ar=1.5, dome_height_mm=neck * 1.5, region=region,
                    parent_artery_mm=parent, neck_source="rim")


def _perfect(neck=6.0, region=""):
    c = _case(neck, region)
    return c, resolve_perfect_clip(c, derive_manufacture_spec(c, []))


# ── 1. What goes out is a solid ───────────────────────────────────────────── #

@pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
class TestTheSTLIsManufacturable:
    def test_the_mesh_is_watertight(self):
        # The box builder produced 696 boundary edges; nobody can make that.
        _c, pc = _perfect(neck=6.0, region="pericallosa")
        assert pc.can_manufacture, pc.fallback_reason
        mesh, _src, _exact = build_manufacture_mesh(pc)
        tri = vtk.vtkTriangleFilter()
        tri.SetInputData(mesh)
        tri.Update()
        fe = vtk.vtkFeatureEdges()
        fe.SetInputData(tri.GetOutput())
        fe.BoundaryEdgesOn()
        fe.NonManifoldEdgesOn()
        fe.FeatureEdgesOff()
        fe.ManifoldEdgesOff()
        fe.Update()
        assert fe.GetOutput().GetNumberOfCells() == 0, "el STL no es un sólido cerrado"

    def test_it_carries_the_real_design_not_a_stand_in(self):
        _c, pc = _perfect(neck=6.0, region="pericallosa")
        mesh, _src, _exact = build_manufacture_mesh(pc)
        assert mesh.GetNumberOfPoints() > 5000, "esto es el diseño real, no cajas"

    def test_the_jaw_matches_what_was_specified(self):
        c, pc = _perfect(neck=6.0, region="pericallosa")
        assert pc.navarro_jaw_mm == pytest.approx(pc.spec.blade_length_mm)

    def test_a_commercial_fallback_has_nothing_to_build(self):
        # A catalogue clip is bought, not made; offering an STL would be a lie.
        _c, pc = _perfect(neck=6.0, region="ACM bifurcacion")
        assert pc.source == "commercial"
        with pytest.raises(ValueError):
            build_manufacture_mesh(pc)


# ── 2. Shapes the family does not have ────────────────────────────────────── #

@pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
class TestShapesOutsideTheFamily:
    def test_the_available_shapes_are_read_off_the_disk(self):
        # So the curved and fenestrated series arrive by dropping in files.
        shapes = family_shapes()
        assert ClipShape.STRAIGHT in shapes
        assert ClipShape.FENESTRATED not in shapes, "aún no hay serie fenestrada"
        assert ClipShape.CURVED not in shapes, "aún no hay serie curva"

    def test_a_fenestrated_case_is_not_served_a_straight_clip(self):
        _c, pc = _perfect(neck=6.0, region="ACM bifurcacion")
        assert pc.spec.shape == ClipShape.FENESTRATED
        assert pc.source != "navarro", "no hay diseño fenestrado; no puede fabricarse"
        assert "fenestrado" in pc.fallback_reason.lower()

    def test_the_commercial_substitute_is_of_the_shape_asked_for(self):
        from services.clips import CLIP_CATALOGUE

        _c, pc = _perfect(neck=6.0, region="ACM bifurcacion")
        assert pc.source == "commercial"
        match = next(c for c in CLIP_CATALOGUE if c.name == pc.commercial_name)
        assert match.shape == ClipShape.FENESTRATED

    def test_a_substitute_that_cannot_close_the_neck_is_not_offered(self):
        # None of the six fenestrated clips reaches 13 mm of blade, so a 12 mm
        # neck has no substitute — and the 7 mm one used to be offered anyway.
        _c, pc = _perfect(neck=12.0, region="Carotida paraclinoidea")
        assert pc.source == "unavailable"
        assert not pc.commercial_name
        assert "se queda corto" in pc.fallback_reason

    def test_a_shape_the_family_has_is_built_by_the_family(self):
        _c, pc = _perfect(neck=6.0, region="pericallosa")
        assert pc.source == "navarro"
        assert pc.navarro_series


# ── 3. The two dossiers ───────────────────────────────────────────────────── #

def _pdf_text(path) -> str:
    import pymupdf

    return "\n".join(page.get_text() for page in pymupdf.open(str(path)))


@pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
class TestDossiers:
    def _both(self, tmp_path, neck=6.0, region="pericallosa"):
        case, pc = _perfect(neck, region)
        i = render_dossier(
            internal_dossier(pc, case, part_no="PR-TEST-0001", patient="Ceron, Cesar",
                             case_label="Aneurisma ACM", session_id="sess-abc123"),
            Path(tmp_path) / "interno.pdf")
        e = render_dossier(external_dossier(pc, part_no="PR-TEST-0001"),
                           Path(tmp_path) / "taller.pdf")
        return _pdf_text(i), _pdf_text(e)

    def test_the_extractor_can_read_these_documents(self, tmp_path):
        # Positive control. An earlier version of this check "passed" on a PDF
        # whose text it could not read at all, which proved nothing.
        ti, te = self._both(tmp_path)
        for term in ("PR-TEST-0001", "Titanio", "Tolerancia"):
            assert term in ti and term in te, f"el extractor no lee '{term}'"

    def test_the_workshop_copy_carries_no_patient_data(self, tmp_path):
        _ti, te = self._both(tmp_path)
        for leak in ("Ceron", "Cesar", "sess-abc123", "Paciente"):
            assert leak not in te, f"fuga al taller: {leak}"

    def test_the_internal_copy_records_where_the_order_came_from(self, tmp_path):
        # Without this the order cannot be re-derived or audited a year later.
        ti, _te = self._both(tmp_path)
        for term in ("Ceron", "sess-abc123", "Cuello medido", "borde marcado"):
            assert term in ti, f"falta en la copia interna: {term}"

    def test_both_carry_the_dimensions_and_the_material(self, tmp_path):
        ti, te = self._both(tmp_path)
        for doc in (ti, te):
            assert "Longitud de mordaza" in doc
            assert MATERIAL.split()[0] in doc

    def test_both_demand_the_force_be_measured(self, tmp_path):
        # The force is a target, never a property of the model.
        ti, te = self._both(tmp_path)
        for doc in (ti, te):
            assert "VERIFICAR EN LA PIEZA" in doc
            assert "medir la pieza terminada" in doc.lower()

    def test_the_ten_millimetre_opening_is_stated(self, tmp_path):
        ti, te = self._both(tmp_path)
        for doc in (ti, te):
            assert "10.0 mm" in doc and "Apertura" in doc


# ── The endpoint ──────────────────────────────────────────────────────────── #

def _session(neck=6.0) -> str:
    sid = create_session()
    write_state(sid, "morpho.neck_mm", str(neck))
    write_state(sid, "morpho.ar", "1.5")
    write_state(sid, "morpho.dome_height_mm", str(neck * 1.5))
    write_state(sid, "morpho.max_diameter_mm", str(neck * 1.8))
    write_state(sid, "morpho.parent_artery_mm", "3.2")
    write_state(sid, "morpho.neck_source", "rim")
    return sid


@pytest.mark.skipif(not _HAS_NAVARRO, reason="biblioteca NAVARRO no instalada")
class TestEndpoint:
    def test_it_returns_an_stl_and_both_dossiers(self):
        r = client.post(f"/api/clips/manufacture/{_session()}")
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["source"] == "navarro"
        assert b["stl_url"] and "?v=" in b["stl_url"]
        assert b["dossier_internal_url"] and b["dossier_workshop_url"]
        assert b["part_no"].startswith("PR-")

    def test_a_case_with_no_registered_region_is_still_buildable(self):
        # The endpoint reads the region from the clinical case, not from session
        # state; with none registered the shape is judged on geometry alone and
        # the family can serve it.
        b = client.post(f"/api/clips/manufacture/{_session()}").json()
        assert b["source"] == "navarro"
        assert b["piece_label"].startswith("NAVARRO")

    def test_a_commercial_fallback_offers_dossiers_but_no_stl(self):
        # Driven at the service level: a fenestrated case has no NAVARRO design.
        from services.clip_dossier import render_dossier

        case, pc = _perfect(neck=6.0, region="ACM bifurcacion")
        assert pc.source == "commercial"
        assert pc.commercial_name
        with pytest.raises(ValueError):
            build_manufacture_mesh(pc)
        # The workshop copy still exists: it documents what was ordered.
        out = render_dossier(external_dossier(pc, part_no="PR-X"),
                             Path(_tmp) / "fallback.pdf")
        assert out.stat().st_size > 0

    def test_the_part_number_is_stable_for_the_same_case(self):
        sid = _session()
        a = client.post(f"/api/clips/manufacture/{sid}").json()["part_no"]
        b = client.post(f"/api/clips/manufacture/{sid}").json()["part_no"]
        assert a == b, "el número de pieza tiene que ser reconciliable entre pedidos"

    def test_without_a_neck_it_refuses(self):
        assert client.post(f"/api/clips/manufacture/{create_session()}").status_code == 409

    def test_an_unknown_session_is_a_404(self):
        assert client.post("/api/clips/manufacture/no-existe").status_code == 404
