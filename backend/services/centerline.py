"""Vessel centerline extraction — port of the desktop processing/centerline.py.

Algorithm
---------
1. **Voxelise** the vessel mesh with ``vtkSelectEnclosedPoints`` at a
   configurable resolution (default 0.8 mm/voxel).
2. **Euclidean Distance Transform** (scipy EDT) on the binary mask → local
   vessel radius at every interior voxel.
3. **Dijkstra shortest path** on the EDT-weighted grid (cost = step / radius) —
   the minimum-cost path follows the medial axis (tube centre).
4. **Smooth** the raw voxel path (Gaussian) and re-sample at a fixed arc-length
   interval, computing a per-point radius.
5. Return geometry + clinical metrics (arc length, tortuosity, radii) and a
   vtkPolyData tube of varying radius for the 3D viewer.
"""
from __future__ import annotations

import heapq
import logging
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import vtk
from scipy.ndimage import distance_transform_edt, gaussian_filter1d
from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy

logger = logging.getLogger(__name__)


@dataclass
class CenterlineResult:
    """Output of :func:`extract_centerline`."""

    points: np.ndarray       # (N, 3) world-space mm coordinates
    radii:  np.ndarray       # (N,)   local radius in mm

    arc_length_mm:    float = 0.0
    chord_length_mm:  float = 0.0
    tortuosity:       float = 1.0   # arc / chord (>= 1)
    tortuosity_index: float = 0.0   # (arc - chord) / chord (>= 0)
    mean_radius_mm:   float = 0.0
    min_radius_mm:    float = 0.0
    max_radius_mm:    float = 0.0

    poly_data: vtk.vtkPolyData | None = field(default=None, repr=False)


class CenterlineExtractor:
    """Extract the medial-axis centreline of a vessel mesh between two points."""

    def __init__(
        self,
        voxel_size_mm: float = 0.8,
        smooth_sigma: float = 1.5,
        resample_spacing_mm: float = 0.5,
        progress_cb: Callable[[float], None] | None = None,
    ) -> None:
        self.voxel_size_mm       = voxel_size_mm
        self.smooth_sigma        = smooth_sigma
        self.resample_spacing_mm = resample_spacing_mm
        self._progress           = progress_cb or (lambda _: None)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    # Cap the probe grid so a large mesh at a fine voxel size can't blow up
    # memory / the vtkSelectEnclosedPoints pass. If exceeded, the voxel size is
    # raised (coarser but bounded).
    _MAX_VOXELS = 12_000_000

    # Perpendicular margin (mm) added around the source→target box when cropping
    # the voxel grid. Must cover realistic vessel bowing off the straight line.
    _CROP_MARGIN_MM = 20.0

    def extract(
        self,
        poly_data: vtk.vtkPolyData,
        source_mm: tuple[float, float, float],
        target_mm: tuple[float, float, float],
    ) -> CenterlineResult:
        mesh_bounds = poly_data.GetBounds()

        # First try a grid cropped to the region of interest (fast for local
        # picks); fall back to the full mesh bounds if no path is found there.
        crop_bounds = self._crop_bounds(source_mm, target_mm, mesh_bounds)
        raw_path = mask = dt = origin = None
        vs = self.voxel_size_mm
        for bounds in (crop_bounds, mesh_bounds):
            self._clamp_voxel_size(bounds)
            self._progress(0.05)
            mask, origin, vs = self._voxelise(poly_data, bounds)
            if not mask.any():
                continue
            self._progress(0.25)
            dt = distance_transform_edt(mask).astype(np.float32) * vs   # mm
            src_idx = self._world_to_idx(source_mm, origin, vs, mask.shape)
            tgt_idx = self._world_to_idx(target_mm, origin, vs, mask.shape)
            src_idx = self._snap_to_best_center(src_idx, mask, dt)
            tgt_idx = self._snap_to_best_center(tgt_idx, mask, dt)
            self._progress(0.35)
            raw_path = self._dijkstra(dt, mask, src_idx, tgt_idx)
            if len(raw_path) >= 2:
                break

        if not mask.any():
            raise ValueError(
                "La malla no encierra volumen (¿superficie abierta?). "
                "No se puede extraer la línea central."
            )
        if not raw_path or len(raw_path) < 2:
            raise ValueError(
                "No se encontró un camino entre los puntos indicados. "
                "Verifique que ambos puntos estén dentro del mismo vaso."
            )

        self._progress(0.80)
        pts_world  = self._path_to_world(raw_path, origin, vs)
        pts_smooth = self._smooth_path(pts_world)
        pts_final, radii = self._resample_with_radii(pts_smooth, dt, origin, vs, mask.shape)

        self._progress(0.95)
        result = self._compute_metrics(pts_final, radii)
        result.poly_data = build_tube(pts_final, radii)
        self._progress(1.0)
        logger.info(
            "Centerline: arc=%.1fmm tort=%.3f Ø_mean=%.2fmm",
            result.arc_length_mm, result.tortuosity, result.mean_radius_mm * 2,
        )
        return result

    # ------------------------------------------------------------------ #
    # Step 1 — voxelisation                                                #
    # ------------------------------------------------------------------ #

    def _crop_bounds(self, src, tgt, mesh_bounds):
        """AABB of source+target expanded by the crop margin, clamped to mesh."""
        m = self._CROP_MARGIN_MM
        lo = [min(src[i], tgt[i]) - m for i in range(3)]
        hi = [max(src[i], tgt[i]) + m for i in range(3)]
        return (
            max(lo[0], mesh_bounds[0]), min(hi[0], mesh_bounds[1]),
            max(lo[1], mesh_bounds[2]), min(hi[1], mesh_bounds[3]),
            max(lo[2], mesh_bounds[4]), min(hi[2], mesh_bounds[5]),
        )

    def _clamp_voxel_size(self, bds) -> None:
        pad = self.voxel_size_mm * 2
        while True:
            vs = self.voxel_size_mm
            nx = max(4, int((bds[1] - bds[0] + 2 * pad) / vs) + 1)
            ny = max(4, int((bds[3] - bds[2] + 2 * pad) / vs) + 1)
            nz = max(4, int((bds[5] - bds[4] + 2 * pad) / vs) + 1)
            if nx * ny * nz <= self._MAX_VOXELS or vs >= 3.0:
                break
            self.voxel_size_mm = round(vs * 1.25, 2)
            pad = self.voxel_size_mm * 2
            logger.info("Centerline: grid too large, voxel size raised to %.2f mm", self.voxel_size_mm)

    def _voxelise(self, poly_data: vtk.vtkPolyData, bds):
        vs  = self.voxel_size_mm
        pad = vs * 2

        origin = np.array([bds[0] - pad, bds[2] - pad, bds[4] - pad])
        nx = max(4, int((bds[1] - bds[0] + 2 * pad) / vs) + 1)
        ny = max(4, int((bds[3] - bds[2] + 2 * pad) / vs) + 1)
        nz = max(4, int((bds[5] - bds[4] + 2 * pad) / vs) + 1)

        xi = origin[0] + np.arange(nx) * vs
        yi = origin[1] + np.arange(ny) * vs
        zi = origin[2] + np.arange(nz) * vs
        gx, gy, gz = np.meshgrid(xi, yi, zi, indexing="ij")
        pts_arr = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()]).astype(np.float32)

        vtk_pts = vtk.vtkPoints()
        vtk_pts.SetData(numpy_to_vtk(pts_arr, deep=True))
        probe_pd = vtk.vtkPolyData()
        probe_pd.SetPoints(vtk_pts)

        enc = vtk.vtkSelectEnclosedPoints()
        enc.SetInputData(probe_pd)
        enc.SetSurfaceData(poly_data)
        enc.SetTolerance(0.001)
        enc.Update()

        inside = vtk_to_numpy(enc.GetOutput().GetPointData().GetArray("SelectedPoints"))
        mask = inside.reshape((nx, ny, nz)).astype(bool)
        return mask, origin, vs

    # ------------------------------------------------------------------ #
    # Coordinate helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _world_to_idx(pt_mm, origin, vs, shape):
        i = int(round((pt_mm[0] - origin[0]) / vs))
        j = int(round((pt_mm[1] - origin[1]) / vs))
        k = int(round((pt_mm[2] - origin[2]) / vs))
        i = max(0, min(i, shape[0] - 1))
        j = max(0, min(j, shape[1] - 1))
        k = max(0, min(k, shape[2] - 1))
        return (i, j, k)

    @staticmethod
    def _snap_to_best_center(idx, mask, dt):
        """Snap *idx* to the interior voxel closest to the vessel axis."""
        inside = np.argwhere(mask)
        if len(inside) == 0:
            raise ValueError("Interior de la malla vacío — revise la calidad de la malla.")

        idx_arr = np.array(idx, dtype=np.float64)
        for radius in (8, 20):
            chebyshev = np.max(np.abs(inside - idx_arr), axis=1)
            candidates = inside[chebyshev <= radius]
            if len(candidates) == 0:
                continue
            dt_vals = dt[candidates[:, 0], candidates[:, 1], candidates[:, 2]]
            max_dt  = dt_vals.max()
            near_max = candidates[dt_vals >= max_dt * 0.90]
            nm_arr   = near_max.astype(np.float64)
            sq_dists = np.sum((nm_arr - idx_arr) ** 2, axis=1)
            return tuple(near_max[np.argmin(sq_dists)])

        dists = np.sum((inside - idx_arr) ** 2, axis=1)
        return tuple(inside[np.argmin(dists)])

    # ------------------------------------------------------------------ #
    # Dijkstra on EDT-weighted grid                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _dijkstra(dt, mask, src, tgt):
        shape = dt.shape
        INF   = float("inf")
        EPS   = 0.1

        cost = np.full(shape, INF, dtype=np.float32)
        cost[src] = 0.0

        stride = (shape[1] * shape[2], shape[2], 1)
        def flat(idx):
            return idx[0] * stride[0] + idx[1] * stride[1] + idx[2]

        prev = np.full(shape[0] * shape[1] * shape[2], -1, dtype=np.int32)
        heap = [(0.0, src)]

        offsets = [
            (di, dj, dk)
            for di in (-1, 0, 1) for dj in (-1, 0, 1) for dk in (-1, 0, 1)
            if not (di == dj == dk == 0)
        ]
        step_d = {o: math.sqrt(o[0] ** 2 + o[1] ** 2 + o[2] ** 2) for o in offsets}

        while heap:
            c, cur = heapq.heappop(heap)
            if c > cost[cur]:
                continue
            if cur == tgt:
                break
            ci, cj, ck = cur
            for di, dj, dk in offsets:
                ni, nj, nk = ci + di, cj + dj, ck + dk
                if not (0 <= ni < shape[0] and 0 <= nj < shape[1] and 0 <= nk < shape[2]):
                    continue
                if not mask[ni, nj, nk]:
                    continue
                r = float(dt[ni, nj, nk])
                new_c = c + step_d[(di, dj, dk)] / (r + EPS)
                if new_c < cost[ni, nj, nk]:
                    cost[ni, nj, nk] = new_c
                    prev[flat((ni, nj, nk))] = flat(cur)
                    heapq.heappush(heap, (new_c, (ni, nj, nk)))

        if cost[tgt] == INF:
            return []

        path = []
        cur_flat = flat(tgt)
        while cur_flat >= 0:
            i = cur_flat // stride[0]
            j = (cur_flat % stride[0]) // stride[1]
            k = cur_flat % stride[1]
            path.append((i, j, k))
            cur_flat = int(prev[cur_flat])
        path.reverse()
        return path

    # ------------------------------------------------------------------ #
    # Smooth & resample                                                    #
    # ------------------------------------------------------------------ #

    def _path_to_world(self, path, origin, vs):
        arr = np.array(path, dtype=np.float32)
        return arr * vs + origin

    def _smooth_path(self, pts):
        sigma_voxels = self.smooth_sigma / self.voxel_size_mm
        smoothed = np.column_stack([
            gaussian_filter1d(pts[:, ax], sigma_voxels, mode="nearest")
            for ax in range(3)
        ])
        smoothed[0]  = pts[0]
        smoothed[-1] = pts[-1]
        return smoothed

    def _resample_with_radii(self, pts, dt, origin, vs, shape):
        spacing = self.resample_spacing_mm
        diffs   = np.diff(pts, axis=0)
        segs    = np.linalg.norm(diffs, axis=1)
        cumlen  = np.concatenate([[0.0], np.cumsum(segs)])
        total   = cumlen[-1]
        if total < 1e-3:
            return pts, np.zeros(len(pts))

        n_out = max(2, int(total / spacing) + 1)
        t_out = np.linspace(0.0, total, n_out)
        resampled = np.column_stack([
            np.interp(t_out, cumlen, pts[:, ax]) for ax in range(3)
        ])

        radii = np.zeros(n_out, dtype=np.float32)
        for idx, pt in enumerate(resampled):
            vi = max(0, min(int(round((pt[0] - origin[0]) / vs)), shape[0] - 1))
            vj = max(0, min(int(round((pt[1] - origin[1]) / vs)), shape[1] - 1))
            vk = max(0, min(int(round((pt[2] - origin[2]) / vs)), shape[2] - 1))
            radii[idx] = dt[vi, vj, vk]

        nonzero = radii > 0.0
        if nonzero.any() and not nonzero.all():
            idxs = np.arange(n_out, dtype=float)
            radii = np.interp(idxs, idxs[nonzero], radii[nonzero])
        radii = np.maximum(radii, vs * 0.5)
        return resampled, radii

    # ------------------------------------------------------------------ #
    # Metrics                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_metrics(pts, radii):
        segs       = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        arc        = float(segs.sum())
        chord      = float(np.linalg.norm(pts[-1] - pts[0]))
        tortuosity = arc / chord if chord > 1e-6 else 1.0
        ti         = (arc - chord) / chord if chord > 1e-6 else 0.0
        return CenterlineResult(
            points           = pts,
            radii            = radii,
            arc_length_mm    = arc,
            chord_length_mm  = chord,
            tortuosity       = tortuosity,
            tortuosity_index = ti,
            mean_radius_mm   = float(radii.mean()) if len(radii) else 0.0,
            min_radius_mm    = float(radii.min())  if len(radii) else 0.0,
            max_radius_mm    = float(radii.max())  if len(radii) else 0.0,
        )


# ──────────────────────────────────────────────────────────────────────────── #
# Rendering helpers                                                              #
# ──────────────────────────────────────────────────────────────────────────── #

def build_polyline(pts: np.ndarray, radii: np.ndarray) -> vtk.vtkPolyData:
    """A polyline vtkPolyData carrying a per-point 'Radius' scalar."""
    vtk_pts = vtk.vtkPoints()
    vtk_pts.SetData(numpy_to_vtk(pts.astype(np.float64), deep=True))

    lines = vtk.vtkCellArray()
    lines.InsertNextCell(len(pts))
    for i in range(len(pts)):
        lines.InsertCellPoint(i)

    pd = vtk.vtkPolyData()
    pd.SetPoints(vtk_pts)
    pd.SetLines(lines)

    r_arr = numpy_to_vtk(radii.astype(np.float32), deep=True)
    r_arr.SetName("Radius")
    pd.GetPointData().AddArray(r_arr)
    pd.GetPointData().SetActiveScalars("Radius")
    return pd


def build_tube(pts: np.ndarray, radii: np.ndarray) -> vtk.vtkPolyData:
    """A tube surface of varying radius (≈ vessel caliber) for the 3D viewer."""
    line_pd = build_polyline(pts, radii)

    rmin = float(radii.min()) if len(radii) else 0.5
    rmax = float(radii.max()) if len(radii) else 0.5

    tube = vtk.vtkTubeFilter()
    tube.SetInputData(line_pd)
    tube.SetNumberOfSides(14)
    tube.CappingOn()
    if rmax - rmin > 1e-3 and rmin > 1e-3:
        # Radius varies along the vessel → follow the caliber.
        tube.SetVaryRadiusToVaryRadiusByScalar()
        tube.SetRadius(rmin)
        tube.SetRadiusFactor(rmax / rmin)
    else:
        # Uniform caliber → constant-radius tube (avoids "scalar range is zero").
        tube.SetVaryRadiusToVaryRadiusOff()
        tube.SetRadius(max(rmin, 0.25))
    tube.Update()
    return tube.GetOutput()


def extract_centerline(
    poly_data: vtk.vtkPolyData,
    source_mm: tuple[float, float, float],
    target_mm: tuple[float, float, float],
    voxel_size_mm: float = 0.8,
    progress_cb: Callable[[float], None] | None = None,
) -> CenterlineResult:
    """Convenience wrapper around :class:`CenterlineExtractor`."""
    return CenterlineExtractor(
        voxel_size_mm=voxel_size_mm,
        progress_cb=progress_cb,
    ).extract(poly_data, source_mm, target_mm)
