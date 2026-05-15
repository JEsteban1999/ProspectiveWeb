"""Aneurysm candidate detector — adapted from prospective/processing/aneurysm_detector.py.

Pure VTK + NumPy, zero Qt dependencies.  Algorithm v6.

Algorithm
---------
1. Pre-filter: remove disconnected noise components (< 5 % of largest component).
2. Pre-smoothing (optional, for XA/3DRA): Laplacian passes on a temporary copy.
3. Compute Mean + Gaussian curvature (vtkCurvatures).
4. Threshold on Gaussian curvature ≥ p85 (primary gate).
5. Connected-component analysis (vtkPolyDataConnectivityFilter).
6. Per-region hard gates:
   - positive_gauss_frac ≥ 0.50  (eliminates bifurcation saddles)
   - compactness ≥ 0.20           (eliminates elongated vessel arcs)
   - sphericity ≥ 0.28            (eliminates curved vessel segments)
7. Composite score with size-factor bias (peaks at Ø 8 mm).
8. Spatial deduplication (merge_dist_mm = 10 mm).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import vtk

try:
    from vtkmodules.util import numpy_support as ns
except ImportError:
    from vtk.util import numpy_support as ns  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────── #
# Data classes                                                                  #
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class AneurysmCandidate:
    """A single aneurysm candidate extracted from the vascular mesh."""

    index: int                              # 1-based rank
    centroid: tuple[float, float, float]    # (x, y, z) in mm
    radius_mm: float                        # estimated from surface area
    diameter_mm: float                      # = 2 × radius_mm
    mean_curvature: float
    gauss_curvature: float
    positive_gauss_frac: float
    compactness: float
    sphericity: float
    n_points: int
    score: float                            # composite detection score [0–1]
    poly_data: vtk.vtkPolyData = field(repr=False)
    cv_gauss: float       = 0.0
    normal_isotropy: float = 0.5


@dataclass
class DetectionResult:
    """Full result from AneurysmDetector.detect()."""

    candidates: list[AneurysmCandidate]

    n_regions_total:       int   = 0
    n_failed_points:       int   = 0
    n_failed_size:         int   = 0
    n_failed_mean_curv:    int   = 0
    n_failed_pgf:          int   = 0
    n_failed_compact:      int   = 0
    n_failed_sphericity:   int   = 0
    n_merged:              int   = 0
    n_removed_components:  int   = 0
    gauss_threshold:       float = 0.0
    mean_curv_gate:        float = 0.0


# ──────────────────────────────────────────────────────────────────────────── #
# Detector                                                                      #
# ──────────────────────────────────────────────────────────────────────────── #

class AneurysmDetector:
    """
    Detect aneurysm candidates on a pre-segmented vascular mesh (v6).

    Parameters
    ----------
    gauss_percentile:
        Percentile gate on Gaussian curvature (primary criterion).
    mean_curv_gate_percentile:
        Per-region mean curvature gate.
    min_radius_mm / max_radius_mm:
        Size filter.
    min_points:
        Minimum vertex count per region.
    merge_dist_mm:
        Merge duplicate candidates whose centroids are within this distance.
    max_candidates:
        Maximum returned candidates, ordered by score.
    min_positive_gauss_frac:
        Hard gate — fraction of Gauss+ vertices required.
    min_compactness:
        Hard gate — area/sphere_area ratio required.
    min_sphericity:
        Hard gate — min(bbox)/max(bbox) required.
    pre_smooth_iterations:
        Laplacian passes before curvature computation (0 = off for CTA, 25 for XA).
    """

    def __init__(
        self,
        gauss_percentile:          float = 85.0,
        mean_curv_gate_percentile: float = 75.0,
        min_radius_mm:             float = 1.5,
        max_radius_mm:             float = 15.0,
        min_points:                int   = 8,
        merge_dist_mm:             float = 10.0,
        max_candidates:            int   = 8,
        min_positive_gauss_frac:   float = 0.50,
        min_compactness:           float = 0.20,
        min_sphericity:            float = 0.28,
        pre_smooth_iterations:     int   = 0,
    ) -> None:
        self.gauss_percentile          = gauss_percentile
        self.mean_curv_gate_percentile = mean_curv_gate_percentile
        self.min_radius_mm             = min_radius_mm
        self.max_radius_mm             = max_radius_mm
        self.min_points                = min_points
        self.merge_dist_mm             = merge_dist_mm
        self.max_candidates            = max_candidates
        self.min_positive_gauss_frac   = min_positive_gauss_frac
        self.min_compactness           = min_compactness
        self.min_sphericity            = min_sphericity
        self.pre_smooth_iterations     = pre_smooth_iterations

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def detect(self, poly_data: vtk.vtkPolyData) -> DetectionResult:
        """Run detection.  Returns DetectionResult (never raises)."""
        if poly_data is None or poly_data.GetNumberOfPoints() == 0:
            logger.warning("AneurysmDetector: empty mesh")
            return DetectionResult(candidates=[])

        logger.info(
            "Aneurysm detection — %d verts / %d tris",
            poly_data.GetNumberOfPoints(), poly_data.GetNumberOfPolys(),
        )

        # ── 0. Pre-filter: remove small disconnected noise components ───── #
        n_removed_components = 0
        n_orig_pts = poly_data.GetNumberOfPoints()

        pre_conn = vtk.vtkPolyDataConnectivityFilter()
        pre_conn.SetInputData(poly_data)
        pre_conn.SetExtractionModeToAllRegions()
        pre_conn.ColorRegionsOn()
        pre_conn.Update()
        n_comps = pre_conn.GetNumberOfExtractedRegions()

        if n_comps > 1:
            region_ids = ns.vtk_to_numpy(
                pre_conn.GetOutput().GetPointData().GetScalars()
            ).astype(np.int32)
            counts = np.bincount(region_ids.clip(0), minlength=n_comps)
            min_comp_pts = max(self.min_points * 5, int(counts.max() * 0.05))
            large_ids = [int(i) for i, c in enumerate(counts) if c >= min_comp_pts]
            n_removed_components = n_comps - len(large_ids)

            if n_removed_components > 0 and large_ids:
                sel = vtk.vtkPolyDataConnectivityFilter()
                sel.SetInputData(poly_data)
                sel.SetExtractionModeToSpecifiedRegions()
                sel.InitializeSpecifiedRegionList()
                for rid in large_ids:
                    sel.AddSpecifiedRegion(rid)
                sel.Update()

                cl = vtk.vtkCleanPolyData()
                cl.SetInputConnection(sel.GetOutputPort())
                cl.Update()
                poly_data = cl.GetOutput()

                logger.info(
                    "Pre-filter: removed %d/%d components (threshold >=%d pts) "
                    "— %d -> %d verts",
                    n_removed_components, n_comps, min_comp_pts,
                    n_orig_pts, poly_data.GetNumberOfPoints(),
                )

                if poly_data.GetNumberOfPoints() == 0:
                    logger.warning("Pre-filter removed all geometry — empty result")
                    return DetectionResult(
                        candidates=[], n_removed_components=n_removed_components
                    )

        # ── 0b. Pre-smoothing (XA / 3DRA — v6) ───────────────────────── #
        curvature_input = poly_data
        if self.pre_smooth_iterations > 0:
            smoother = vtk.vtkSmoothPolyDataFilter()
            smoother.SetInputData(poly_data)
            smoother.SetNumberOfIterations(self.pre_smooth_iterations)
            smoother.SetRelaxationFactor(0.10)
            smoother.FeatureEdgeSmoothingOff()
            smoother.BoundarySmoothingOff()
            smoother.Update()

            renorm = vtk.vtkPolyDataNormals()
            renorm.SetInputConnection(smoother.GetOutputPort())
            renorm.ComputePointNormalsOn()
            renorm.ComputeCellNormalsOff()
            renorm.SplittingOff()
            renorm.Update()
            curvature_input = renorm.GetOutput()
            logger.info(
                "Pre-smooth: %d Laplacian iterations on %d-vert mesh",
                self.pre_smooth_iterations, curvature_input.GetNumberOfPoints(),
            )

        # ── 0c. Triangulation guard ────────────────────────────────────── #
        tri_guard = vtk.vtkTriangleFilter()
        tri_guard.SetInputData(curvature_input)
        tri_guard.Update()
        curvature_input = tri_guard.GetOutput()

        # ── 1. Curvature arrays ────────────────────────────────────────── #
        mean_filter = vtk.vtkCurvatures()
        mean_filter.SetInputData(curvature_input)
        mean_filter.SetCurvatureTypeToMean()
        mean_filter.Update()
        mean_poly = mean_filter.GetOutput()

        gauss_filter = vtk.vtkCurvatures()
        gauss_filter.SetInputData(curvature_input)
        gauss_filter.SetCurvatureTypeToGaussian()
        gauss_filter.Update()

        mean_arr  = ns.vtk_to_numpy(
            mean_poly.GetPointData().GetArray("Mean_Curvature")
        ).astype(np.float64)

        gauss_arr = ns.vtk_to_numpy(
            gauss_filter.GetOutput().GetPointData().GetArray("Gauss_Curvature")
        ).astype(np.float64)

        # ── 2. Attach both arrays to mean_poly ─────────────────────────── #
        gauss_vtk = ns.numpy_to_vtk(gauss_arr.astype(np.float32), deep=True,
                                    array_type=vtk.VTK_FLOAT)
        gauss_vtk.SetName("Gauss_Curvature")
        mean_poly.GetPointData().AddArray(gauss_vtk)

        # ── 3. Threshold on GAUSSIAN curvature (primary gate) ──────────── #
        thresh_gauss = float(np.percentile(gauss_arr, self.gauss_percentile))
        thresh_gauss = max(thresh_gauss, 0.0)

        mean_curv_gate = float(np.percentile(mean_arr, self.mean_curv_gate_percentile))

        logger.info(
            "Gauss threshold p%.0f = %.4f  |  mean-curv gate p%.0f = %.4f",
            self.gauss_percentile, thresh_gauss,
            self.mean_curv_gate_percentile, mean_curv_gate,
        )

        mean_poly.GetPointData().SetActiveScalars("Gauss_Curvature")

        thresh = vtk.vtkThreshold()
        thresh.SetInputData(mean_poly)
        thresh.SetInputArrayToProcess(
            0, 0, 0, vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "Gauss_Curvature"
        )
        thresh.SetThresholdFunction(vtk.vtkThreshold.THRESHOLD_UPPER)
        thresh.SetUpperThreshold(thresh_gauss)
        thresh.SetAllScalars(0)
        thresh.Update()

        geom = vtk.vtkGeometryFilter()
        geom.SetInputConnection(thresh.GetOutputPort())
        geom.Update()
        high_gauss = geom.GetOutput()

        if high_gauss.GetNumberOfPoints() == 0:
            logger.info("No positive Gaussian curvature regions found")
            return DetectionResult(
                candidates=[], gauss_threshold=thresh_gauss,
                mean_curv_gate=mean_curv_gate,
            )

        # ── 4. Connected components ────────────────────────────────────── #
        conn = vtk.vtkPolyDataConnectivityFilter()
        conn.SetInputData(high_gauss)
        conn.SetExtractionModeToAllRegions()
        conn.Update()
        n_regions = conn.GetNumberOfExtractedRegions()
        logger.info("Connected regions: %d", n_regions)

        # ── 5. Analyse each region ─────────────────────────────────────── #
        candidates: list[AneurysmCandidate] = []
        n_fail_pts    = 0
        n_fail_size   = 0
        n_fail_mean   = 0
        n_fail_pgf    = 0
        n_fail_compact= 0
        n_fail_sph    = 0

        for i in range(n_regions):
            sel = vtk.vtkPolyDataConnectivityFilter()
            sel.SetInputData(high_gauss)
            sel.SetExtractionModeToSpecifiedRegions()
            sel.InitializeSpecifiedRegionList()
            sel.AddSpecifiedRegion(i)
            sel.Update()

            _cl = vtk.vtkCleanPolyData()
            _cl.SetInputConnection(sel.GetOutputPort())
            _cl.Update()
            region = _cl.GetOutput()

            n_pts = region.GetNumberOfPoints()
            if n_pts < self.min_points:
                n_fail_pts += 1
                continue

            mass = vtk.vtkMassProperties()
            mass.SetInputData(region)
            mass.Update()
            area   = mass.GetSurfaceArea()
            radius = math.sqrt(area / (4.0 * math.pi)) if area > 0 else 0.0

            if radius < self.min_radius_mm or radius > self.max_radius_mm:
                n_fail_size += 1
                continue

            bounds = region.GetBounds()
            cx = (bounds[0] + bounds[1]) / 2.0
            cy = (bounds[2] + bounds[3]) / 2.0
            cz = (bounds[4] + bounds[5]) / 2.0

            r_mean_arr  = ns.vtk_to_numpy(
                region.GetPointData().GetArray("Mean_Curvature")
            ).astype(np.float64)
            r_gauss_arr = ns.vtk_to_numpy(
                region.GetPointData().GetArray("Gauss_Curvature")
            ).astype(np.float64)

            mean_curv_region  = float(np.mean(r_mean_arr))
            gauss_curv_region = float(np.mean(r_gauss_arr))

            if mean_curv_region < mean_curv_gate:
                n_fail_mean += 1
                continue

            dx = bounds[1] - bounds[0]
            dy = bounds[3] - bounds[2]
            dz = bounds[5] - bounds[4]
            dims = sorted([dx, dy, dz])
            max_dim = dims[2]

            positive_gauss_frac = float(np.mean(r_gauss_arr > 0))

            if positive_gauss_frac < self.min_positive_gauss_frac:
                n_fail_pgf += 1
                continue

            r_bbox = max_dim / 2.0 if max_dim > 0 else 0.0
            sphere_area_bbox = 4.0 * math.pi * r_bbox ** 2
            compactness = (
                min(1.0, area / sphere_area_bbox)
                if sphere_area_bbox > 0
                else 0.0
            )

            if compactness < self.min_compactness:
                n_fail_compact += 1
                continue

            sphericity = (dims[0] / dims[2]) if dims[2] > 0 else 0.0

            if sphericity < self.min_sphericity:
                n_fail_sph += 1
                continue

            # v5: cv_gauss
            mean_abs_gauss = abs(gauss_curv_region)
            std_gauss      = float(np.std(r_gauss_arr))
            cv_gauss       = float(np.clip(std_gauss / (mean_abs_gauss + 1e-6), 0.0, 10.0))

            # v5: normal_isotropy
            normal_isotropy = 0.5
            normals_vtk = region.GetPointData().GetNormals()
            if normals_vtk is not None and normals_vtk.GetNumberOfTuples() > 2:
                nrm  = ns.vtk_to_numpy(normals_vtk).astype(np.float64)
                nlen = np.linalg.norm(nrm, axis=1, keepdims=True)
                nlen = np.where(nlen > 1e-8, nlen, 1.0)
                nrm  = nrm / nlen
                cov_n   = np.cov(nrm.T)
                eigvals = np.sort(np.linalg.eigvalsh(cov_n))
                max_eig = eigvals[2]
                min_eig = max(eigvals[0], 0.0)
                normal_isotropy = float(min_eig / max_eig) if max_eig > 1e-10 else 0.0

            # Composite score
            norm_mean = float(np.clip(
                (mean_curv_region - mean_curv_gate) / (abs(mean_curv_gate) + 1e-6) / 5.0,
                0.0, 1.0,
            ))
            norm_gauss = float(np.clip(
                (gauss_curv_region - thresh_gauss) / (abs(thresh_gauss) + 1e-6) / 5.0,
                0.0, 1.0,
            ))

            if radius < 1.0:
                size_factor = 0.0
            elif radius < 2.0:
                size_factor = (radius - 1.0) * 0.5
            else:
                size_factor = max(0.0, 1.0 - abs(radius - 4.0) / 6.0)

            cv_penalty = float(np.clip((cv_gauss - 0.8) / 2.2, 0.0, 1.0))

            base_score = (0.05 * norm_mean
                          + 0.10 * norm_gauss
                          + 0.25 * positive_gauss_frac
                          + 0.08 * compactness
                          + 0.07 * sphericity
                          + 0.15 * normal_isotropy
                          + 0.30 * size_factor)
            score = float(np.clip(base_score * (1.0 - 0.20 * cv_penalty), 0.0, 1.0))

            candidates.append(
                AneurysmCandidate(
                    index=0,
                    centroid=(cx, cy, cz),
                    radius_mm=radius,
                    diameter_mm=radius * 2.0,
                    mean_curvature=mean_curv_region,
                    gauss_curvature=gauss_curv_region,
                    positive_gauss_frac=positive_gauss_frac,
                    compactness=compactness,
                    sphericity=sphericity,
                    n_points=n_pts,
                    score=score,
                    poly_data=region,
                    cv_gauss=cv_gauss,
                    normal_isotropy=normal_isotropy,
                )
            )

        # ── 6. Sort by score ───────────────────────────────────────────── #
        candidates.sort(key=lambda c: c.score, reverse=True)

        # ── 7. Merge spatial duplicates ────────────────────────────────── #
        n_merged = 0
        merged: list[AneurysmCandidate] = []
        for c in candidates:
            pt = np.array(c.centroid)
            duplicate = any(
                float(np.linalg.norm(pt - np.array(m.centroid))) < self.merge_dist_mm
                for m in merged
            )
            if duplicate:
                n_merged += 1
            else:
                merged.append(c)
        candidates = merged[: self.max_candidates]

        for rank, c in enumerate(candidates, start=1):
            c.index = rank

        logger.info(
            "Detection done — %d candidates | %d regions | "
            "%d fail-size | %d fail-mean | %d fail-pgf | %d fail-compact | "
            "%d fail-sph | %d merged | %d noise-comps removed",
            len(candidates), n_regions, n_fail_size, n_fail_mean,
            n_fail_pgf, n_fail_compact, n_fail_sph, n_merged,
            n_removed_components,
        )

        return DetectionResult(
            candidates=candidates,
            n_regions_total=n_regions,
            n_failed_points=n_fail_pts,
            n_failed_size=n_fail_size,
            n_failed_mean_curv=n_fail_mean,
            n_failed_pgf=n_fail_pgf,
            n_failed_compact=n_fail_compact,
            n_failed_sphericity=n_fail_sph,
            n_merged=n_merged,
            n_removed_components=n_removed_components,
            gauss_threshold=thresh_gauss,
            mean_curv_gate=mean_curv_gate,
        )
