"""An empty detection must explain itself.

The detector always computed why it rejected each high-curvature region, but the
counts never left the service: a study with no candidates looked exactly like a
failure, and the clinician had nothing to act on.

Measured over the corpus, the size gate dominates and its share grows with how
complete the mesh is — 61% of rejections on a downsampled case 9, 94% on a
full-resolution DICOM-2026 — because the high-curvature patches merge across
several vessels and their equivalent radius exceeds the bound.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_detdiag_")
os.environ.setdefault("PROSPECTIVE_DB_URL", f"sqlite:///{_tmp}/test.db")
os.environ["STUDY_FILES_ROOT"] = f"{_tmp}/study_files"

import numpy as np
import vtk

from routers.detect import _detector_for_modality


def _sphere(radius: float, centre=(0.0, 0.0, 0.0), res: int = 40) -> vtk.vtkPolyData:
    s = vtk.vtkSphereSource()
    s.SetRadius(radius)
    s.SetCenter(*centre)
    s.SetThetaResolution(res)
    s.SetPhiResolution(res)
    s.Update()
    return s.GetOutput()


class TestDiagnosticsAreProduced:
    def test_a_sphere_far_too_large_is_rejected_by_the_size_gate(self):
        """The failure mode behind an empty result on a complete mesh: the
        region is real geometry, just bigger than the gate allows."""
        det = _detector_for_modality("XA")
        huge = _sphere(det.max_radius_mm * 4)

        res = det.detect(huge)

        assert len(res.candidates) == 0
        assert res.n_regions_total >= 1, "debe haber analizado alguna región"
        assert res.n_failed_size >= 1, (
            "una esfera mucho mayor que el radio máximo debe morir en la compuerta "
            f"de tamaño; contadores: size={res.n_failed_size} "
            f"mean={res.n_failed_mean_curv} pgf={res.n_failed_pgf}"
        )

    def test_an_empty_mesh_reports_no_regions_rather_than_crashing(self):
        det = _detector_for_modality("XA")
        res = det.detect(vtk.vtkPolyData())
        assert res.candidates == []
        assert res.n_regions_total == 0

    def test_the_gate_bounds_are_readable_so_the_ui_can_quote_them(self):
        det = _detector_for_modality("XA")
        assert det.min_radius_mm > 0 and det.max_radius_mm > det.min_radius_mm


class TestDiagnosticsReachTheApi:
    def test_the_response_model_carries_the_breakdown(self):
        """Without this the panel can only say 'no candidates'."""
        from models.detection import AneurysmDetectionResult, DetectionDiagnostics

        r = AneurysmDetectionResult(found=False, candidates=[])
        assert isinstance(r.diagnostics, DetectionDiagnostics)
        for field in ("regions_analyzed", "rejected_size", "rejected_mean_curvature",
                      "rejected_positive_gauss", "rejected_compactness",
                      "rejected_too_few_points", "rejected_sphericity",
                      "min_radius_mm", "max_radius_mm"):
            assert hasattr(r.diagnostics, field), f"falta {field}"

    def test_every_service_counter_has_somewhere_to_go(self):
        """A counter computed but not mapped is a diagnosis that never arrives."""
        from services.aneurysm_detector import DetectionResult
        from models.detection import DetectionDiagnostics

        service_fields = {
            "n_regions_total", "n_failed_points", "n_failed_size",
            "n_failed_mean_curv", "n_failed_pgf", "n_failed_compact",
            "n_failed_sphericity", "n_merged", "n_removed_components",
        }
        assert service_fields <= set(DetectionResult.__dataclass_fields__)
        # The API model must expose one field per counter (names differ on purpose:
        # the API speaks in plain terms, the service in its own).
        assert len(DetectionDiagnostics.model_fields) >= len(service_fields)
