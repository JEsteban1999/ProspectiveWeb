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
