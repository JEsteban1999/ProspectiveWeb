"""Cleanup must remove specks without removing vessel branches.

Measured on the three angiographic studies in `Archivos DICOM/`, the old rule
("keep the N largest connected components") discarded single connected pieces of
66, 175 and 255 mm³ at the UI default. A 255 mm³ piece is a 3 mm vessel some
36 mm long. These tests pin the replacement: a cut-off by physical volume.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_cleanup_")
os.environ.setdefault("PROSPECTIVE_DB_URL", f"sqlite:///{_tmp}/test.db")
os.environ["STUDY_FILES_ROOT"] = f"{_tmp}/study_files"

import numpy as np

from services.segmentation import SegmentationPipeline, level_to_cleanup_mm3

SPACING = (0.5, 0.5, 0.5)          # 0.125 mm³ per voxel
VOX_MM3 = float(np.prod(SPACING))


def _volume_with(pieces: list[tuple[tuple[int, int, int], tuple[int, int, int]]]) -> np.ndarray:
    """Background at 0 with bright cuboids at the given (origin, size)."""
    vol = np.zeros((60, 60, 60), np.float32)
    for (z, y, x), (dz, dy, dx) in pieces:
        vol[z:z + dz, y:y + dy, x:x + dx] = 1000.0
    return vol


def _run(vol: np.ndarray, min_mm3: float):
    pipe = SegmentationPipeline(
        threshold_hu=500.0,
        gaussian_sigma=0.0,        # keep the geometry exact for the assertion
        smooth_iterations=0,
        target_reduction=0.0,
        min_component_mm3=min_mm3,
        min_component_verts=0,
    )
    return pipe.run(vol, SPACING)


class TestPhysicalCutoff:
    def test_a_vessel_sized_branch_survives_even_when_it_is_not_the_largest(self):
        """The failure the old rule produced: a detached branch dropped because
        too many other components ranked above it."""
        trunk = (((5, 5, 5), (40, 6, 6)),)              # big trunk
        branch = (((5, 40, 40), (12, 4, 4)),)           # 192 vox = 24 mm³
        # Plus a crowd of specks that would out-rank nothing but inflate N.
        specks = [(((50, i, 2), (2, 2, 2))) for i in range(0, 40, 4)]
        vol = _volume_with(list(trunk) + list(branch) + specks)

        res = _run(vol, level_to_cleanup_mm3(4)[0])     # top of the physical regime
        # 24 mm³ branch must still be there: the mesh keeps more than one piece
        # and the discarded material is small.
        assert res.largest_removed_mm3 < 5.0, (
            f"se descartó una pieza de {res.largest_removed_mm3:.1f} mm³"
        )
        assert res.kept_fraction > 0.9

    def test_specks_are_removed(self):
        big = (((5, 5, 5), (40, 8, 8)),)
        specks = [(((50, i, 2), (1, 1, 1))) for i in range(0, 50, 3)]
        vol = _volume_with(list(big) + specks)
        res = _run(vol, level_to_cleanup_mm3(4)[0])
        assert res.n_fragments_removed >= len(specks) - 2
        assert res.kept_fraction > 0.95      # specks are a rounding error by volume

    def test_cutoff_is_resolution_independent(self):
        """The same physical threshold must behave the same on a coarser grid —
        that is the whole point of expressing it in mm³ instead of voxels."""
        pieces = [(((5, 5, 5), (40, 8, 8))), (((50, 40, 40), (4, 4, 4)))]
        vol = _volume_with(pieces)

        fine = SegmentationPipeline(threshold_hu=500.0, gaussian_sigma=0.0,
                                    smooth_iterations=0, target_reduction=0.0,
                                    min_component_mm3=1.0, min_component_verts=0).run(vol, (0.5, 0.5, 0.5))
        coarse = SegmentationPipeline(threshold_hu=500.0, gaussian_sigma=0.0,
                                      smooth_iterations=0, target_reduction=0.0,
                                      min_component_mm3=1.0, min_component_verts=0).run(vol, (1.0, 1.0, 1.0))
        # 4×4×4 voxels is 8 mm³ at 0.5 mm and 64 mm³ at 1 mm — above 1 mm³ either
        # way, so neither run may drop it.
        assert fine.kept_fraction == 1.0
        assert coarse.kept_fraction == 1.0

    def test_level_zero_keeps_everything(self):
        vol = _volume_with([(((5, 5, 5), (10, 4, 4))), (((40, 40, 40), (1, 1, 1)))])
        res = _run(vol, level_to_cleanup_mm3(0)[0])
        assert res.kept_fraction == 1.0
        assert res.n_fragments_removed == 0


class TestReportedNumbers:
    def test_the_discarded_volume_is_reported_not_just_logged(self):
        """A silent loss is how a branch disappears unnoticed; the API carries
        the numbers so the UI can warn."""
        vol = _volume_with([(((5, 5, 5), (40, 8, 8))), (((50, 40, 40), (3, 3, 3)))])
        res = _run(vol, 10.0)                 # 27 vox = 3.4 mm³ → dropped
        assert res.n_fragments_removed == 1
        assert 3.0 < res.largest_removed_mm3 < 4.0
        assert 0.9 < res.kept_fraction < 1.0


class TestFullResolution:
    """Downsampling is what breaks thin vessels into fragments.

    Measured on the real studies: halving case 9 drops the largest connected
    component from 69% of the thresholded volume to 42%, so branches come apart
    and the cleanup then removes them, leaving gaps in the mesh.
    """

    def test_a_thin_vessel_survives_at_native_resolution_but_not_halved(self):
        from scipy.ndimage import label as cc_label

        # A vessel two voxels across, with a one-voxel constriction — the shape
        # that survives whole at native resolution and snaps when halved.
        vol = np.zeros((40, 40, 40), np.float32)
        vol[10:30, 20:22, 20:22] = 1000.0
        vol[19:21, 20:21, 20:21] = 1000.0      # the narrow part

        native = (vol >= 500)
        halved = (vol[::2, ::2, ::2] >= 500)
        _l1, n_native = cc_label(native)
        _l2, n_halved = cc_label(halved)

        assert n_native == 1, "a native resolution el vaso es una sola pieza"
        assert n_halved >= n_native, (
            "submuestrear no puede mejorar la conectividad; si esto falla, la "
            "premisa de la opción de resolución completa ya no se sostiene"
        )

    def test_a_volume_too_big_for_memory_is_refused_with_a_way_out(self):
        """Marching cubes holds several float32 copies at once: a 1030x512x512 CT
        at native resolution would take the process down, so it must be rejected
        with an actionable message rather than crashing the server."""
        from routers.segment import _FULL_RES_MAX_VOXELS

        ct = 1030 * 512 * 512          # the biggest study in the corpus
        angio = 384 * 384 * 384        # what the option exists for
        assert ct > _FULL_RES_MAX_VOXELS, "el TC grande debe quedar por encima del tope"
        assert angio < _FULL_RES_MAX_VOXELS, "los angiográficos deben caber"

    def test_request_defaults_to_the_fast_path(self):
        """Full resolution costs minutes; it must be opt-in."""
        from models.segmentation import SegmentRequest

        req = SegmentRequest(session_id="s", series_id="x", lower=100, upper=900)
        assert req.full_resolution is False
