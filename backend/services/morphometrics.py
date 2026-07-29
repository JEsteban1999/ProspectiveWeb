"""Aneurysm morphometric analysis — adapted from prospective/processing/morphometrics.py.

Pure VTK + NumPy + SciPy, zero Qt dependencies.

Computes all clinical indices used for cerebral aneurysm planning:
  • Volume, surface area, equivalent sphere diameter
  • Max diameter, bounding-box dimensions
  • Neck diameter (plane-slicing PCA axis), dome height
  • DNR, AR, BF, compactness (Wadell sphericity)
  • UI (ConvexHull), EI, NSI, SR (0 when parent artery unknown)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import vtk

try:
    from vtkmodules.util import numpy_support as ns
except ImportError:
    from vtk.util import numpy_support as ns  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


@dataclass
class MorphometricResult:
    """All morphometric measurements for one aneurysm candidate."""

    # ── Volumetric ────────────────────────────────────────────────────── #
    volume_mm3: float
    surface_area_mm2: float
    eq_sphere_diam_mm: float

    # ── Bounding-box dimensions ───────────────────────────────────────── #
    bbox_l_mm: float           # longest axis (≈ max diameter)
    bbox_w_mm: float           # intermediate axis
    bbox_h_mm: float           # shortest axis
    max_diameter_mm: float     # = bbox_l_mm

    # ── Neck / dome (via plane slicing) ──────────────────────────────── #
    neck_diameter_mm: float
    dome_height_mm: float
    neck_plane_pos: float      # parametric position along principal axis [0–1]

    # ── Clinical ratios ───────────────────────────────────────────────── #
    dome_to_neck_ratio: float
    aspect_ratio: float
    compactness: float         # Wadell sphericity

    # ── Shape-complexity indices ──────────────────────────────────────── #
    bottleneck_factor:  float = 0.0
    undulation_index:   float = 0.0
    ellipticity_index:  float = 0.0
    non_sphericity_idx: float = 0.0
    size_ratio:         float = 0.0

    # ── PCA axes ─────────────────────────────────────────────────────── #
    principal_axis: tuple[float, float, float] = field(default=(0.0, 0.0, 1.0))
    centroid: tuple[float, float, float]       = field(default=(0.0, 0.0, 0.0))

    # ── Reliability guard (Tier 1) ────────────────────────────────────── #
    # A trustworthy analysis needs a *closed* (watertight) sac mesh.  When the
    # input is an open surface patch (e.g. the detector's curvature cap), the
    # volume-based metrics and the plane-slice neck degenerate; we flag that
    # here and null the affected fields instead of emitting absurd numbers.
    reliable:         bool = True   # False → volume/neck metrics not trustworthy
    watertight:       bool = True   # mesh had no boundary (open) edges
    reliability_note: str  = ""     # human-readable reason when reliable is False

    # ── Derived labels ────────────────────────────────────────────────── #
    @property
    def rupture_risk_label(self) -> str:
        """Heuristic risk label (not a clinical diagnosis).

        Thresholds: Dhar 2008, Raghavan 2005, Greving 2014.
        """
        sr_alto     = self.size_ratio > 0 and self.size_ratio >= 3.0
        sr_moderado = self.size_ratio > 0 and self.size_ratio >= 2.0
        if (self.aspect_ratio >= 1.6 or self.dome_to_neck_ratio >= 2.0
                or self.undulation_index >= 0.25 or sr_alto):
            return "Alto"
        if (self.aspect_ratio >= 1.3 or self.dome_to_neck_ratio >= 1.6
                or self.ellipticity_index >= 0.35
                or self.undulation_index >= 0.10 or sr_moderado):
            return "Moderado"
        return "Bajo"


class MorphometricAnalyzer:
    """
    Compute morphometric indices from a vtkPolyData aneurysm mesh.

    Parameters
    ----------
    n_slices:
        Number of cross-sections sampled along the principal axis.
    neck_search_fraction:
        Fraction of the dome length (from base) within which to search
        for the minimum cross-section (neck).
    """

    def __init__(
        self,
        n_slices: int = 40,
        neck_search_fraction: float = 0.40,
    ) -> None:
        self.n_slices = n_slices
        self.neck_search_fraction = neck_search_fraction

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        poly_data: vtk.vtkPolyData,
        neck_plane: Optional[tuple] = None,
    ) -> MorphometricResult:
        """Run all measurements.  Raises ValueError on empty mesh.

        Parameters
        ----------
        neck_plane:
            Optional ``(origin, normal, neck_diam_mm)`` giving a *known* neck
            plane (semi-automatic Tier 2 flow).  When supplied, the neck is
            taken as ``neck_diam_mm`` (measured from the clip contour by the
            caller) instead of being re-searched via plane slicing — which
            degenerates on the grazing mesh extremity.  ``dome_height`` is then
            the sac's extent beyond the plane along ``+normal``.
        """
        if poly_data is None or poly_data.GetNumberOfPoints() == 0:
            raise ValueError("Empty mesh — run aneurysm detection first.")

        logger.info(
            "Morphometric analysis — %d pts / %d tris",
            poly_data.GetNumberOfPoints(), poly_data.GetNumberOfPolys(),
        )

        volume_mm3, surface_area_mm2 = self._mass_properties(poly_data)

        bounds = poly_data.GetBounds()
        dims = sorted([
            bounds[1] - bounds[0],
            bounds[3] - bounds[2],
            bounds[5] - bounds[4],
        ], reverse=True)
        bbox_l, bbox_w, bbox_h = dims

        centroid, principal_axis = self._pca_axis(poly_data)

        if neck_plane is not None:
            # ── Known neck plane (semi-automatic Tier 2) ──────────────────── #
            n_origin = np.asarray(neck_plane[0], dtype=np.float64)
            n_normal = np.asarray(neck_plane[1], dtype=np.float64)
            n_normal = n_normal / (np.linalg.norm(n_normal) or 1.0)
            neck_diam = float(neck_plane[2])
            pts = ns.vtk_to_numpy(poly_data.GetPoints().GetData()).astype(np.float64)
            beyond = (pts - n_origin) @ n_normal          # >0 = dome side
            dome_height = float(max(0.0, beyond.max()))
            neck_pos = 0.0                                 # neck at base of clipped sac
            # The user's plane defines the neck→dome axis; use it downstream.
            principal_axis = n_normal
            centroid = n_origin
        else:
            neck_diam, dome_height, neck_pos = self._find_neck(
                poly_data, centroid, principal_axis
            )

        max_diam    = bbox_l
        eq_diam     = (2.0 * (3.0 * volume_mm3 / (4.0 * math.pi)) ** (1.0 / 3.0)
                       if volume_mm3 > 0 else 0.0)
        dnr         = max_diam / neck_diam  if neck_diam >= 0.1 else 0.0
        ar          = dome_height / neck_diam if neck_diam >= 0.1 else 0.0
        compactness = self._wadell_sphericity(volume_mm3, surface_area_mm2)

        bf  = self._bottleneck_factor(poly_data, centroid, principal_axis, neck_pos, neck_diam)
        # Physical bound: the widest dome cross-section cannot exceed the max
        # diameter, so BF ≤ DNR.  The plane-slice perimeter can be inflated when
        # a slice catches multiple loops (parent stub in the clipped sac); clamp.
        if dnr > 0.0:
            bf = min(bf, dnr)
        ui  = self._undulation_index(poly_data, volume_mm3)
        ei  = self._ellipticity_index(volume_mm3, surface_area_mm2)
        nsi = max(0.0, 1.0 - compactness)

        # ── Reliability guard (Tier 1) ─────────────────────────────────── #
        # Volume-based metrics and the plane-slice neck are only trustworthy on
        # a closed, physically plausible sac.  Open surface patches (the
        # detector's curvature cap) give a garbage vtkMassProperties volume and
        # a degenerate grazing "neck".  We guard the two groups independently so
        # a closed sac with a merely-degenerate auto-neck keeps its valid volume
        # while only the neck-derived ratios are nulled (→ prompt a neck plane).
        n_boundary      = self._boundary_edge_count(poly_data)
        watertight      = n_boundary == 0
        bbox_vol        = bbox_l * bbox_w * bbox_h
        vol_ok          = 0.0 < volume_mm3 <= bbox_vol * 1.05
        volume_reliable = watertight and vol_ok
        # A user-supplied neck plane is measured from the clip contour → trusted;
        # otherwise the auto neck must be on a closed mesh and above the floor.
        neck_reliable   = (neck_plane is not None) or (watertight and 0.1 <= neck_diam <= max_diam)
        reliable        = volume_reliable and neck_reliable

        reasons = []
        if not watertight:
            reasons.append(f"malla abierta ({n_boundary} aristas de borde)")
        if watertight and not vol_ok:
            reasons.append("volumen no plausible")
        if not neck_reliable and watertight:
            reasons.append("cuello no medible automáticamente")
        note = ""
        if not reliable:
            note = ("Medición no fiable: " + "; ".join(reasons)
                    + ". Define un plano de cuello para medir sobre un saco cerrado.")
            logger.warning("Morphometry unreliable — %s", note)
        if not volume_reliable:
            # Volume group depends on a closed, plausible mesh.
            volume_mm3  = 0.0
            eq_diam     = 0.0
            compactness = 0.0
            ui = ei = nsi = 0.0
        if not neck_reliable:
            # Neck group (neck, dome, DNR, AR, BF) needs a valid neck.
            neck_diam   = 0.0
            dome_height = 0.0
            neck_pos    = 0.0
            dnr = ar = bf = 0.0

        result = MorphometricResult(
            volume_mm3         = volume_mm3,
            surface_area_mm2   = surface_area_mm2,
            eq_sphere_diam_mm  = eq_diam,
            bbox_l_mm          = bbox_l,
            bbox_w_mm          = bbox_w,
            bbox_h_mm          = bbox_h,
            max_diameter_mm    = max_diam,
            neck_diameter_mm   = neck_diam,
            dome_height_mm     = dome_height,
            neck_plane_pos     = neck_pos,
            dome_to_neck_ratio = dnr,
            aspect_ratio       = ar,
            compactness        = compactness,
            bottleneck_factor  = bf,
            undulation_index   = ui,
            ellipticity_index  = ei,
            non_sphericity_idx = nsi,
            principal_axis     = tuple(principal_axis),
            centroid           = tuple(centroid),
            reliable           = reliable,
            watertight         = watertight,
            reliability_note   = note,
        )

        logger.info(
            "Morphometrics done — V=%.1f mm3  D_max=%.1f mm  "
            "D_neck=%.1f mm  DNR=%.2f  AR=%.2f  BF=%.2f  UI=%.3f  EI=%.3f",
            volume_mm3, max_diam, neck_diam, dnr, ar, bf, ui, ei,
        )
        return result

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _mass_properties(poly_data: vtk.vtkPolyData) -> tuple[float, float]:
        tri = vtk.vtkTriangleFilter()
        tri.SetInputData(poly_data)
        tri.Update()

        mp = vtk.vtkMassProperties()
        mp.SetInputConnection(tri.GetOutputPort())
        mp.Update()

        return abs(float(mp.GetVolume())), float(mp.GetSurfaceArea())

    @staticmethod
    def _boundary_edge_count(poly_data: vtk.vtkPolyData) -> int:
        """Number of boundary (open) edges.  0 → watertight closed surface."""
        fe = vtk.vtkFeatureEdges()
        fe.SetInputData(poly_data)
        fe.BoundaryEdgesOn()
        fe.FeatureEdgesOff()
        fe.NonManifoldEdgesOff()
        fe.ManifoldEdgesOff()
        fe.Update()
        return int(fe.GetOutput().GetNumberOfCells())

    @staticmethod
    def _pca_axis(poly_data: vtk.vtkPolyData) -> tuple[np.ndarray, np.ndarray]:
        pts = ns.vtk_to_numpy(poly_data.GetPoints().GetData()).astype(np.float64)
        centroid = pts.mean(axis=0)
        cov = np.cov((pts - centroid).T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        principal = eigvecs[:, np.argmax(eigvals)]
        return centroid, principal

    def _find_neck(
        self,
        poly_data: vtk.vtkPolyData,
        centroid: np.ndarray,
        axis: np.ndarray,
    ) -> tuple[float, float, float]:
        pts  = ns.vtk_to_numpy(poly_data.GetPoints().GetData()).astype(np.float64)
        proj = (pts - centroid) @ axis
        p_min, p_max = proj.min(), proj.max()
        extent = p_max - p_min

        if extent < 1e-3:
            bounds   = poly_data.GetBounds()
            fallback = min(
                bounds[1] - bounds[0],
                bounds[3] - bounds[2],
                bounds[5] - bounds[4],
            )
            return fallback, extent, 0.0

        search_end = p_min + extent * self.neck_search_fraction
        positions  = np.linspace(p_min, search_end, self.n_slices)

        best_perim = float("inf")
        best_pos   = p_min
        best_diam  = extent

        for pos in positions:
            plane_origin = centroid + pos * axis
            perim, diam  = self._slice_perimeter(poly_data, plane_origin, axis)
            if perim > 0 and perim < best_perim:
                best_perim = perim
                best_pos   = pos
                best_diam  = diam

        dome_height = p_max - best_pos
        neck_pos    = (best_pos - p_min) / extent if extent > 0 else 0.0
        return best_diam, dome_height, float(neck_pos)

    @staticmethod
    def _slice_perimeter(
        poly_data: vtk.vtkPolyData,
        origin: np.ndarray,
        normal: np.ndarray,
    ) -> tuple[float, float]:
        plane = vtk.vtkPlane()
        plane.SetOrigin(origin.tolist())
        plane.SetNormal(normal.tolist())

        cutter = vtk.vtkCutter()
        cutter.SetInputData(poly_data)
        cutter.SetCutFunction(plane)
        cutter.GenerateValues(1, 0.0, 0.0)
        cutter.Update()
        cut = cutter.GetOutput()

        if cut.GetNumberOfPoints() < 3:
            return 0.0, 0.0

        pts  = ns.vtk_to_numpy(cut.GetPoints().GetData()).astype(np.float64)
        diff = pts - np.roll(pts, -1, axis=0)
        perim = float(np.sum(np.linalg.norm(diff, axis=1)))
        diam  = perim / math.pi if perim > 0 else 0.0
        return perim, diam

    # ------------------------------------------------------------------ #
    # Shape-complexity indices                                            #
    # ------------------------------------------------------------------ #

    def _bottleneck_factor(
        self,
        poly_data: vtk.vtkPolyData,
        centroid: np.ndarray,
        axis: np.ndarray,
        neck_pos_frac: float,
        neck_diam: float,
    ) -> float:
        if neck_diam < 0.1:
            return 0.0

        pts  = ns.vtk_to_numpy(poly_data.GetPoints().GetData()).astype(np.float64)
        proj = (pts - centroid) @ axis
        p_min, p_max = proj.min(), proj.max()
        extent = p_max - p_min
        if extent < 1e-3:
            return 0.0

        neck_abs   = p_min + neck_pos_frac * extent
        dome_start = neck_abs + extent * 0.05
        dome_end   = p_max   - extent * 0.02

        if dome_start >= dome_end:
            return 0.0

        positions  = np.linspace(dome_start, dome_end, 30)
        max_dome_d = neck_diam

        for pos in positions:
            origin = centroid + pos * axis
            _, d   = self._slice_perimeter(poly_data, origin, axis)
            if d > max_dome_d:
                max_dome_d = d

        return max_dome_d / neck_diam

    @staticmethod
    def _undulation_index(poly_data: vtk.vtkPolyData, volume_mm3: float) -> float:
        """UI = 1 - V_sac / V_convex_hull.  Returns 0.0 if scipy unavailable."""
        try:
            from scipy.spatial import ConvexHull  # type: ignore[import]
            pts = ns.vtk_to_numpy(poly_data.GetPoints().GetData()).astype(np.float64)
            if pts.shape[0] < 4:
                return 0.0
            hull = ConvexHull(pts)
            convex_vol = float(hull.volume)
            if convex_vol <= 0:
                return 0.0
            return float(max(0.0, 1.0 - volume_mm3 / convex_vol))
        except Exception:
            return 0.0

    @staticmethod
    def _ellipticity_index(volume: float, area: float) -> float:
        """EI = 1 - (18pi)^(1/3) * V^(2/3) / A  (Dhar et al. 2008)."""
        if area <= 0 or volume <= 0:
            return 0.0
        return 1.0 - (18.0 * math.pi) ** (1.0 / 3.0) * volume ** (2.0 / 3.0) / area

    @staticmethod
    def _wadell_sphericity(volume: float, area: float) -> float:
        """Wadell compactness: pi^(1/3) * (6V)^(2/3) / A."""
        if area <= 0 or volume <= 0:
            return 0.0
        return math.pi ** (1.0 / 3.0) * (6.0 * volume) ** (2.0 / 3.0) / area
