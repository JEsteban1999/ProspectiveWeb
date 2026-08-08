"""Interactive mesh-editing router: ROI crop (box/sphere) and grow-from-seeds.

Both operate on the working vessel mesh (`vessel_tree.vtp`) so that downstream
steps (detection, morphometry) transparently use the edited result. Crop reads
and rewrites the mesh; grow rebuilds it from seed points on the volume.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from models.mesh_edit import (
    GrowRequest, GrowResult, MeshCropRequest, MeshCropResult,
)
from services.grow import grow_from_seeds
from services.mesh_crop import clip_box, clip_sphere
from services.segmentation import (
    read_vtp, write_vtp,
    level_to_smooth_iters, level_to_cleanup_verts,
)
from services.sessions import mesh_url, session_exists, session_subdir, write_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["mesh-edit"])


def _versioned(session_id: str, name: str) -> str:
    return f"{mesh_url(session_id, name)}?v={int(time.time() * 1000)}"


# ── POST /mesh-crop/{session_id} ────────────────────────────────────────────── #

def _run_crop(vessel_path: Path, req: MeshCropRequest) -> "tuple[object, int, int, int]":
    mesh = read_vtp(vessel_path)
    n_before = mesh.GetNumberOfPoints()
    if n_before == 0:
        raise ValueError("La malla vascular está vacía.")

    c = (req.center.x, req.center.y, req.center.z)
    if req.mode == "sphere":
        out = clip_sphere(mesh, c, req.radius, invert=req.invert)
    else:
        hs = req.half_size
        hx = hs.x if hs else req.radius
        hy = hs.y if hs else req.radius
        hz = hs.z if hs else req.radius
        out = clip_box(
            mesh,
            c[0] - hx, c[0] + hx,
            c[1] - hy, c[1] + hy,
            c[2] - hz, c[2] + hz,
            invert=req.invert,
        )

    n_after = out.GetNumberOfPoints()
    if n_after == 0:
        raise ValueError(
            "El recorte deja la malla vacía. Ajusta el centro, el radio o invierte la operación."
        )
    write_vtp(out, vessel_path)
    return out, n_before, n_after, out.GetNumberOfPolys()


@router.post(
    "/mesh-crop/{session_id}",
    response_model=MeshCropResult,
    summary="Crop the vessel mesh to a box/sphere ROI",
    description=(
        "Non-destructive ROI crop of the working vessel mesh. `mode='sphere'` keeps "
        "geometry within `radius` of the picked centre; `mode='box'` uses an "
        "axis-aligned box (`half_size` per axis, or `radius` as a cube half-side). "
        "`invert=true` removes the ROI instead (useful to delete a bone/noise blob). "
        "The result overwrites `vessel_tree.vtp`; re-run segmentation to restore."
    ),
)
async def mesh_crop(session_id: str, req: MeshCropRequest) -> MeshCropResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    vessel_path = session_subdir(session_id, "meshes") / "vessel_tree.vtp"
    if not vessel_path.exists():
        raise HTTPException(
            status_code=409, detail="No hay malla vascular. Ejecuta la segmentación primero."
        )

    try:
        _out, n_before, n_after, n_faces = await asyncio.to_thread(
            _run_crop, vessel_path, req
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Mesh crop failed")
        raise HTTPException(status_code=500, detail=f"Error al recortar la malla: {exc}")

    write_state(session_id, "seg.n_vertices", str(n_after))
    write_state(session_id, "seg.n_faces", str(n_faces))

    return MeshCropResult(
        mesh_url=_versioned(session_id, "vessel_tree.vtp"),
        vertices=n_after,
        faces=n_faces,
        removed_vertices=max(0, n_before - n_after),
    )


# ── POST /segment/grow/{session_id} ─────────────────────────────────────────── #

def _band_from_seeds(volume: np.ndarray, seed_voxels: list[tuple[int, int, int]]) -> tuple[float, float]:
    """Narrow HU band around the vessel intensity sampled at the seeds.

    Samples a small neighbourhood at each seed and takes a high percentile (the
    vessel is the bright part even if the click is slightly off-centre), then
    builds a window around the seeds' brightness: low enough to follow dimmer
    connected vessel, high enough for bright cores, but bounded so it excludes
    bone (typically brighter) and background/tissue (dimmer).
    """
    nz, ny, nx = volume.shape
    seed_vals: list[float] = []
    for (z, y, x) in seed_voxels:
        z0, z1 = max(0, z - 2), min(nz, z + 3)
        y0, y1 = max(0, y - 2), min(ny, y + 3)
        x0, x1 = max(0, x - 2), min(nx, x + 3)
        nb = volume[z0:z1, y0:y1, x0:x1]
        if nb.size:
            seed_vals.append(float(np.percentile(nb, 75)))
    if not seed_vals:
        return 80.0, 600.0
    v_lo = float(np.min(seed_vals))
    v_hi = float(np.max(seed_vals))
    center = 0.5 * (v_lo + v_hi)
    spread = max(v_hi - v_lo, abs(center) * 0.35)   # at least ±35% of the value
    lower = v_lo - spread * 0.6
    upper = v_hi + spread * 0.6
    return round(lower, 1), round(upper, 1)


def _run_grow(session_id: str, meshes_dir: Path, req: GrowRequest) -> GrowResult:
    """Load full-res volume, map world seeds → voxels, region-grow, write mesh."""
    from routers.segment import _maybe_downsample
    from services.mpr import _get_volume, ensure_volume_cached

    meta = ensure_volume_cached(session_id)
    volume = np.asarray(_get_volume(session_id))
    spacing = tuple(float(s) for s in meta["spacing"])  # (sz, sy, sx)

    # Grow at FULL resolution: thin vessels are only a few voxels wide, so the
    # downsample used for global thresholding would break their connectivity and
    # drop distal branches. The grown region is small, so this stays fast.
    # (Cap only very large volumes to keep marching cubes bounded.)
    seg_volume, seg_spacing, _factor = _maybe_downsample(volume, spacing, max_axis=400)
    sz, sy, sx = seg_spacing

    # World (mm) → voxel index. Mesh space has origin 0 and axis-aligned spacing.
    seeds: list[tuple[int, int, int]] = []
    for p in req.seeds:
        seeds.append((
            int(round(p.z / sz)),
            int(round(p.y / sy)),
            int(round(p.x / sx)),
        ))

    # Band: either the user's sliders, or derived from the vessel intensity at the
    # seeds — a narrow window that excludes bone (brighter) and tissue (dimmer),
    # so a single click on a vessel gives a clean tree without tuning thresholds.
    lower, upper = req.lower, req.upper
    if req.auto_band:
        lower, upper = _band_from_seeds(seg_volume, seeds)

    result = grow_from_seeds(
        seg_volume, seg_spacing, seeds,
        lower_hu=lower,
        upper_hu=upper,
        smooth_iterations=level_to_smooth_iters(req.smoothing),
        target_reduction=0.30,   # keep thin-vessel detail (was 0.70)
        keep_top_n=0,            # keep ALL seed-connected growth (multi-seed)
        morpho_closing_mm=1.0,   # bridge small intensity gaps along the vessel
    )

    vtp_path = meshes_dir / "vessel_tree.vtp"
    write_vtp(result.poly_data, vtp_path)

    # Persist state so detection/morphometry can run on the grown mesh. Volume
    # geometry uses the FULL-RES shape/spacing (mesh coords are physical mm).
    write_state(session_id, "seg.mesh_url", mesh_url(session_id, "vessel_tree.vtp"))
    write_state(session_id, "seg.n_vertices", str(result.n_vertices))
    write_state(session_id, "seg.n_faces", str(result.n_triangles))
    write_state(session_id, "seg.threshold_lower", str(lower))
    write_state(session_id, "seg.threshold_upper", str(upper))
    write_state(session_id, "seg.strategy", "grow_from_seeds")
    write_state(session_id, "dicom.volume_z", str(volume.shape[0]))
    write_state(session_id, "dicom.volume_y", str(volume.shape[1]))
    write_state(session_id, "dicom.volume_x", str(volume.shape[2]))
    write_state(session_id, "dicom.spacing_z", str(spacing[0]))
    write_state(session_id, "dicom.spacing_y", str(spacing[1]))
    write_state(session_id, "dicom.spacing_x", str(spacing[2]))

    return GrowResult(
        mesh_url=_versioned(session_id, "vessel_tree.vtp"),
        vertices=result.n_vertices,
        faces=result.n_triangles,
        n_voxels=result.n_voxels,
        fragments_removed=result.n_fragments_removed,
        seeds=len(seeds),
        band_lower=round(float(lower), 1),
        band_upper=round(float(upper), 1),
    )


@router.post(
    "/segment/grow/{session_id}",
    response_model=GrowResult,
    summary="Grow a vessel mesh from seed points",
    description=(
        "Region-growing segmentation (SimpleITK ConnectedThreshold) starting from "
        "one or more seed points placed on the volume, expanding through connected "
        "voxels within [lower, upper] HU. Builds a fresh `vessel_tree.vtp` — an "
        "alternative to threshold segmentation for cases where a global threshold "
        "leaks into bone. Requires that a DICOM volume has been uploaded."
    ),
)
async def segment_grow(session_id: str, req: GrowRequest) -> GrowResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    dicom_dir = session_subdir(session_id, "dicom")
    if not dicom_dir.exists() or not any(dicom_dir.iterdir()):
        raise HTTPException(
            status_code=422, detail="No hay DICOM en la sesión. Sube los archivos primero."
        )
    meshes_dir = session_subdir(session_id, "meshes")

    try:
        return await asyncio.to_thread(_run_grow, session_id, meshes_dir, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Grow-from-seeds failed")
        raise HTTPException(status_code=500, detail=f"Error en crecimiento por semillas: {exc}")
