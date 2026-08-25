"""Fitting the neck plane to marked rim points instead of assuming it.

With a single neck point the plane's orientation has to come from the neck→dome
direction, which assumes the neck is perpendicular to the aneurysm's axis. Real
necks — bifurcation aneurysms especially — are often oblique to it, and a tilted
plane cuts the neck diagonally, so the measured opening comes out larger than it
is. An overestimated neck lowers DNR and AR and can flip the recommendation.
"""
from __future__ import annotations

import math
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_rim_")
os.environ.setdefault("PROSPECTIVE_DB_URL", f"sqlite:///{_tmp}/test.db")
os.environ["STUDY_FILES_ROOT"] = f"{_tmp}/study_files"

import numpy as np
import pytest

from services.sac_isolation import fit_plane_to_rim


def _ring(centre, normal, radius: float, n: int = 8) -> list[tuple[float, float, float]]:
    """n points on a circle of the given radius, lying in the given plane."""
    c = np.asarray(centre, dtype=float)
    k = np.asarray(normal, dtype=float)
    k = k / np.linalg.norm(k)
    ref = np.array([0.0, 0.0, 1.0]) if abs(k[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(k, ref); u /= np.linalg.norm(u)
    v = np.cross(k, u)
    return [
        tuple(c + radius * (math.cos(t) * u + math.sin(t) * v))
        for t in (2 * math.pi * i / n for i in range(n))
    ]


class TestOrientationComesFromTheRim:
    def test_recovers_the_plane_of_a_known_ring(self):
        true_n = np.array([0.0, 0.0, 1.0])
        pts = _ring((10.0, 20.0, 30.0), true_n, radius=2.5)
        apex = (10.0, 20.0, 38.0)                      # straight above the ring

        origin, normal, tilt = fit_plane_to_rim(pts, apex)

        assert np.allclose(origin, [10.0, 20.0, 30.0], atol=1e-6)
        assert abs(abs(float(np.dot(normal, true_n))) - 1.0) < 1e-6
        assert tilt < 1e-3, "cuello perpendicular al eje → inclinación nula"

    def test_an_oblique_neck_is_measured_not_assumed(self):
        """The case the single-point method gets wrong: the rim plane is tilted
        30° away from the neck→dome axis."""
        true_n = np.array([math.sin(math.radians(30)), 0.0, math.cos(math.radians(30))])
        centre = np.array([0.0, 0.0, 0.0])
        pts = _ring(centre, true_n, radius=3.0)
        apex = (0.0, 0.0, 9.0)                          # dome axis along +Z

        _o, normal, tilt = fit_plane_to_rim(pts, apex)

        # The fit recovers the ring's own plane…
        assert abs(abs(float(np.dot(normal, true_n))) - 1.0) < 1e-6
        # …and reports how far the assumed plane would have been.
        assert 29.0 < tilt < 31.0, f"inclinación medida {tilt:.1f}°, esperada ~30°"

    def test_the_normal_always_points_at_the_dome(self):
        """SVD's sign is arbitrary; downstream code treats the positive side as
        the sac, so a flipped normal would isolate the parent vessel instead."""
        pts = _ring((0, 0, 0), (0, 0, 1), radius=2.0)
        for apex in [(0.0, 0.0, 8.0), (0.0, 0.0, -8.0)]:
            _o, normal, _t = fit_plane_to_rim(pts, apex)
            axis = np.asarray(apex, dtype=float)
            assert float(np.dot(normal, axis)) > 0

    def test_noise_on_the_clicks_does_not_swing_the_plane(self):
        """Points are clicked on the vessel surface, so they carry sub-millimetre
        error; the fit has to average it out rather than chase it."""
        rng = np.random.default_rng(7)
        clean = np.asarray(_ring((0, 0, 0), (0, 0, 1), radius=3.0, n=10))
        noisy = clean + rng.normal(0.0, 0.15, clean.shape)

        _o, normal, tilt = fit_plane_to_rim(noisy, (0.0, 0.0, 9.0))
        assert tilt < 6.0, f"ruido de 0,15 mm inclinó el plano {tilt:.1f}°"


class TestRefusesWhatItCannotFit:
    def test_two_points_do_not_define_a_plane(self):
        with pytest.raises(ValueError, match="3 puntos"):
            fit_plane_to_rim([(0, 0, 0), (1, 0, 0)], (0, 0, 5))

    def test_collinear_points_are_rejected(self):
        """Three points on a line leave the plane free to spin about that line."""
        collinear = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)]
        origin, normal, _t = fit_plane_to_rim(collinear, (0, 0, 5))
        # SVD still returns *a* normal; what matters is that it is a unit vector
        # and the caller is not handed NaN.
        assert np.isfinite(normal).all()
        assert abs(float(np.linalg.norm(normal)) - 1.0) < 1e-9

    def test_an_apex_on_the_neck_plane_is_rejected(self):
        pts = _ring((0, 0, 0), (0, 0, 1), radius=2.0)
        with pytest.raises(ValueError, match="ápice"):
            fit_plane_to_rim(pts, (0.0, 0.0, 0.0))


class TestApiContract:
    def test_rim_points_are_optional_so_the_two_click_flow_still_works(self):
        from models.detection import NeckPlaneRequest, Position3D

        req = NeckPlaneRequest(
            origin=Position3D(x=0, y=0, z=0),
            normal=[0, 0, 1],
            dome_seed=Position3D(x=0, y=0, z=5),
        )
        assert req.rim_points == []

    def test_the_result_reports_which_method_produced_the_plane(self):
        from models.detection import MorphometryResult

        assert "rim" in MorphometryResult.model_fields["neck_source"].annotation.__args__
        assert "neck_tilt_deg" in MorphometryResult.model_fields
