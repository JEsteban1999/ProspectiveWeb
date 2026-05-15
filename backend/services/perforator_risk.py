"""Perforator artery risk analysis — adapted from prospective/processing/perforator_risk.py.

Pure VTK + NumPy, zero Qt dependencies.

Algorithm: vertex-valence anomaly detection + distance-based risk zones.
Branching points have significantly higher vertex valence than straight
vessel segments.  Flagged vertices near the aneurysm neck are merged
into clusters representing probable perforator / branch origins.

Risk zones (concentric shells around neck_origin):
  zone 1 (high risk)   — r <= r_high   (default 3 mm)
  zone 2 (medium risk) — r <= r_medium  (default 5 mm)
  zone 3 (low risk)    — r <= r_low     (default 8 mm)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import vtk

try:
    from vtkmodules.util.numpy_support import vtk_to_numpy, numpy_to_vtk
except ImportError:
    from vtk.util.numpy_support import vtk_to_numpy, numpy_to_vtk  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────── #
# Data structures                                                               #
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class PerforatorCandidate:
    """A single suspected perforator / branching-point cluster."""

    index:                int
    position:             tuple[float, float, float]   # world-space centroid (mm)
    distance_to_neck_mm:  float
    risk_level:           int    # 1 = high, 2 = medium, 3 = low
    valence_score:        float  # z-score deviation from median vertex valence

    @property
    def risk_label(self) -> str:
        return {1: "Alto", 2: "Medio", 3: "Bajo"}.get(self.risk_level, "—")

    @property
    def risk_color_hex(self) -> str:
        return {1: "#ef4444", 2: "#eab308", 3: "#22c55e"}.get(self.risk_level, "#888888")


@dataclass
class PerforatorRiskResult:
    """Full output of compute_perforator_risk()."""

    candidates:    list[PerforatorCandidate]
    risk_poly:     vtk.vtkPolyData              # original mesh + 'RiskZone' scalars
    neck_origin:   tuple[float, float, float]
    zone_radii_mm: tuple[float, float, float]   # (r_high, r_medium, r_low)


# ──────────────────────────────────────────────────────────────────────────── #
# Public API                                                                    #
# ──────────────────────────────────────────────────────────────────────────── #

def compute_perforator_risk(
    vessel_poly: vtk.vtkPolyData,
    neck_origin: tuple[float, float, float],
    zone_radii: tuple[float, float, float] = (3.0, 5.0, 8.0),
    min_valence_zscore: float = 1.5,
    cluster_radius_mm: float = 2.0,
    max_candidates: int = 12,
) -> PerforatorRiskResult:
    """
    Analyse vessel_poly around neck_origin and return risk zones
    plus perforator candidates.

    Parameters
    ----------
    vessel_poly         : full vascular mesh (from segmentation)
    neck_origin         : (x, y, z) aneurysm neck centroid in mm
    zone_radii          : (r_high, r_medium, r_low) in mm
    min_valence_zscore  : z-score threshold for flagging branching topology
    cluster_radius_mm   : merge flagged vertices within this distance (mm)
    max_candidates      : maximum number of candidates returned
    """
    r_high, r_med, r_low = zone_radii
    origin = np.asarray(neck_origin, dtype=float)

    pts_arr = _vtk_points_to_numpy(vessel_poly)
    n_pts   = int(pts_arr.shape[0])

    if n_pts == 0:
        empty_poly = _tagged_poly(vessel_poly, np.zeros(0, dtype=np.int32))
        return PerforatorRiskResult([], empty_poly, tuple(origin), zone_radii)

    # ── 1. Per-vertex distance to neck ─────────────────────────────────── #
    dists = np.linalg.norm(pts_arr - origin, axis=1)

    # ── 2. Risk-zone scalar: 0 = none, 1 = high, 2 = medium, 3 = low ──── #
    zones = np.zeros(n_pts, dtype=np.int32)
    zones[dists <= r_low]  = 3
    zones[dists <= r_med]  = 2
    zones[dists <= r_high] = 1

    # ── 3. Vertex valence (# incident triangles per vertex) ────────────── #
    valences = _compute_vertex_valences(vessel_poly, n_pts)

    # ── 4. Detect branching candidates ─────────────────────────────────── #
    candidates: list[PerforatorCandidate] = []
    in_zone = dists <= r_low

    if np.count_nonzero(in_zone) >= 4:
        med_v    = float(np.median(valences))
        std_v    = float(np.std(valences)) + 1e-6
        z_scores = (valences - med_v) / std_v

        cand_mask  = (z_scores >= min_valence_zscore) & in_zone
        cand_idx   = np.where(cand_mask)[0]

        if cand_idx.size > 0:
            cand_pts    = pts_arr[cand_idx]
            cand_dists  = dists[cand_idx]
            cand_scores = z_scores[cand_idx]
            cand_zones  = zones[cand_idx]

            used = np.zeros(cand_idx.size, dtype=bool)
            cid  = 0

            for oi in np.argsort(cand_scores)[::-1]:
                if used[oi]:
                    continue
                used[oi]  = True
                rep_pt    = cand_pts[oi]
                rep_d     = float(cand_dists[oi])
                rep_score = float(cand_scores[oi])
                rep_zone  = int(cand_zones[oi])

                nn_dists = np.linalg.norm(cand_pts - rep_pt, axis=1)
                used[nn_dists <= cluster_radius_mm] = True

                candidates.append(PerforatorCandidate(
                    index               = cid,
                    position            = (float(rep_pt[0]),
                                           float(rep_pt[1]),
                                           float(rep_pt[2])),
                    distance_to_neck_mm = rep_d,
                    risk_level          = max(rep_zone, 1),
                    valence_score       = rep_score,
                ))
                cid += 1
                if cid >= max_candidates:
                    break

    candidates.sort(key=lambda c: c.distance_to_neck_mm)

    # ── 5. Tag polydata ─────────────────────────────────────────────────── #
    risk_poly = _tagged_poly(vessel_poly, zones)

    logger.info(
        "Perforator risk — neck_origin=(%.1f,%.1f,%.1f)  "
        "radii=%s  candidates=%d  (high=%d med=%d low=%d)",
        origin[0], origin[1], origin[2],
        zone_radii, len(candidates),
        sum(1 for c in candidates if c.risk_level == 1),
        sum(1 for c in candidates if c.risk_level == 2),
        sum(1 for c in candidates if c.risk_level == 3),
    )

    return PerforatorRiskResult(
        candidates    = candidates,
        risk_poly     = risk_poly,
        neck_origin   = (float(origin[0]), float(origin[1]), float(origin[2])),
        zone_radii_mm = zone_radii,
    )


def neck_origin_from_morpho(
    result,                          # MorphometricResult (duck-typed)
    aneurysm_poly: vtk.vtkPolyData,
) -> tuple[float, float, float]:
    """
    Reconstruct the aneurysm neck centroid in world space from a
    MorphometricResult and the isolated aneurysm mesh.

    Attributes read from result (duck-typed):
        centroid:       tuple[float, float, float]
        principal_axis: tuple[float, float, float]
        neck_plane_pos: float
    """
    centroid = np.asarray(result.centroid, dtype=float)
    axis     = np.asarray(result.principal_axis, dtype=float)
    axis    /= np.linalg.norm(axis) + 1e-12

    pts_arr  = _vtk_points_to_numpy(aneurysm_poly)
    if pts_arr.shape[0] == 0:
        return (float(centroid[0]), float(centroid[1]), float(centroid[2]))

    proj    = (pts_arr - centroid) @ axis
    p_min   = float(proj.min())
    p_max   = float(proj.max())
    extent  = p_max - p_min

    neck_pos = centroid + (p_min + float(result.neck_plane_pos) * extent) * axis
    return (float(neck_pos[0]), float(neck_pos[1]), float(neck_pos[2]))


# ──────────────────────────────────────────────────────────────────────────── #
# Internal helpers                                                               #
# ──────────────────────────────────────────────────────────────────────────── #

def _vtk_points_to_numpy(poly: vtk.vtkPolyData) -> np.ndarray:
    pts = poly.GetPoints()
    if pts is None or pts.GetNumberOfPoints() == 0:
        return np.empty((0, 3), dtype=float)
    return vtk_to_numpy(pts.GetData()).astype(float)


def _compute_vertex_valences(poly: vtk.vtkPolyData, n_pts: int) -> np.ndarray:
    """Return per-vertex cell count (incident triangles per vertex)."""
    poly.BuildLinks()
    valences = np.zeros(n_pts, dtype=np.int32)
    cell_ids = vtk.vtkIdList()
    for i in range(n_pts):
        poly.GetPointCells(i, cell_ids)
        valences[i] = cell_ids.GetNumberOfIds()
    return valences


def _tagged_poly(poly: vtk.vtkPolyData, zones: np.ndarray) -> vtk.vtkPolyData:
    """Return a deep copy of poly with a 'RiskZone' point-data scalar array."""
    out = vtk.vtkPolyData()
    out.DeepCopy(poly)

    if zones.size != out.GetNumberOfPoints():
        return out

    arr = numpy_to_vtk(zones.astype(np.int32), deep=True)
    arr.SetName("RiskZone")
    out.GetPointData().AddArray(arr)
    out.GetPointData().SetActiveScalars("RiskZone")
    return out
