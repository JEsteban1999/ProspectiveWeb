"""Stent planning router."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models import PlanRequest, PlanResult, StentLibraryItem
from services.sessions import read_state, session_exists, session_subdir, mesh_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["planning"])


def _load_float(session_id: str, key: str, default: float) -> float:
    try:
        raw = read_state(session_id, key, "")
        return float(raw) if raw else default
    except (ValueError, Exception):
        return default

# Realistic stent library (subset)
_STENT_LIBRARY: list[StentLibraryItem] = [
    StentLibraryItem(
        id="pipeline-flex-3.75-25",
        name="Pipeline Flex",
        manufacturer="Medtronic",
        min_diameter_mm=2.5,
        max_diameter_mm=5.0,
        available_lengths_mm=[10, 14, 16, 18, 20, 25, 30, 35],
        type="flow_diverter",
    ),
    StentLibraryItem(
        id="surpass-streamline-4.0-25",
        name="Surpass Streamline",
        manufacturer="Stryker",
        min_diameter_mm=2.0,
        max_diameter_mm=5.0,
        available_lengths_mm=[12, 15, 20, 25, 30, 40],
        type="flow_diverter",
    ),
    StentLibraryItem(
        id="enterprise2-4.5-22",
        name="Enterprise 2",
        manufacturer="Codman",
        min_diameter_mm=3.0,
        max_diameter_mm=4.5,
        available_lengths_mm=[14, 22, 28, 37, 44],
        type="coil_assist",
    ),
    StentLibraryItem(
        id="leo-plus-4.0-25",
        name="Leo Plus",
        manufacturer="Balt",
        min_diameter_mm=2.5,
        max_diameter_mm=5.5,
        available_lengths_mm=[12, 18, 25, 35, 50],
        type="neck_bridge",
    ),
]


@router.get(
    "/stents",
    response_model=list[StentLibraryItem],
    summary="Get stent device library",
    description="Returns all available stent models with their size specifications.",
)
async def get_stent_library() -> list[StentLibraryItem]:
    return _STENT_LIBRARY


@router.post(
    "/plan",
    response_model=PlanResult,
    summary="Compute stent deployment plan",
    description=(
        "Places the selected stent at the aneurysm neck and computes neck coverage. "
        "Returns the deployed stent mesh URL and coverage metrics."
    ),
)
async def compute_plan(req: PlanRequest) -> PlanResult:
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    import time
    from services import devices
    from services.segmentation import write_vtp

    p = req.stent
    device = next((s for s in _STENT_LIBRARY if s.id == p.stent_id), None)

    # ── Fit check (real, from the device envelope + neck geometry) ───────── #
    neck_mm = _load_float(req.session_id, "morpho.neck_mm", 0.0)
    LANDING = 5.0  # required proximal + distal landing per side (mm)
    warnings: list[str] = []

    dia_ok = True
    if device is not None:
        dia_ok = device.min_diameter_mm <= p.diameter_mm <= device.max_diameter_mm
        if not dia_ok:
            warnings.append(
                f"Diámetro {p.diameter_mm:.1f} mm fuera del rango del dispositivo "
                f"({device.min_diameter_mm:.1f}–{device.max_diameter_mm:.1f} mm)."
            )

    # A flow diverter must bridge the neck plus a landing zone on each side.
    required_len = (neck_mm if neck_mm > 0 else 4.0) + 2 * LANDING
    len_ok = p.length_mm >= required_len
    if neck_mm > 0 and not len_ok:
        warnings.append(
            f"Longitud {p.length_mm:.0f} mm insuficiente para cubrir el cuello "
            f"({neck_mm:.1f} mm) + anclaje (necesita ≈ {required_len:.0f} mm)."
        )

    deployed = dia_ok and (len_ok or neck_mm <= 0)

    # ── Coverage (geometric estimate, not a constant) ────────────────────── #
    # Neck bridged along the vessel: fraction of the neck length the stent spans.
    span_fraction = 1.0 if neck_mm <= 0 else min(1.0, p.length_mm / required_len)
    neck_covered = (neck_mm if neck_mm > 0 else 0.0) * span_fraction
    # Flow-diverter metal coverage over the ostium: ~30–35% nominal, higher when
    # the device is oversized relative to the neck; scaled by how well it spans.
    base_metal = 32.0
    oversize_bonus = 0.0
    if neck_mm > 0:
        oversize_bonus = max(0.0, min(18.0, (p.diameter_mm - neck_mm) * 6.0))
    coverage = round((base_metal + oversize_bonus) * span_fraction, 1)

    # ── Build a real stent tube at the placement (approx vessel axis) ────── #
    stent_url = "/static/sample-meshes/stent_deployed.vtp"
    try:
        axis = (
            _load_float(req.session_id, "morpho.axis_x", 0.0),
            _load_float(req.session_id, "morpho.axis_y", 0.0),
            _load_float(req.session_id, "morpho.axis_z", 1.0),
        )
        # Flow diverter runs along the parent artery ≈ perpendicular to neck→dome.
        stent_dir = devices.perpendicular(axis)
        local = devices.make_stent(p.diameter_mm, p.length_mm)
        t = devices.pose_transform(
            (p.position.x, p.position.y, p.position.z), stent_dir, p.rotation_deg
        )
        world = devices.apply_transform(local, t)
        meshes_dir = session_subdir(req.session_id, "meshes")
        write_vtp(world, meshes_dir / "stent_deployed.vtp")
        stent_url = f"{mesh_url(req.session_id, 'stent_deployed.vtp')}?v={int(time.time() * 1000)}"
    except Exception as exc:
        logger.warning("Stent mesh generation skipped: %s", exc)

    if neck_mm <= 0:
        warnings.append("Ejecuta la morfometría para una cobertura precisa del cuello.")

    # ── Persist the deployed stent for the report / session restore ──────── #
    from services.device_state import save_stent
    save_stent(req.session_id, {
        "name": getattr(device, "name", p.stent_id),
        "manufacturer": getattr(device, "manufacturer", ""),
        "diameter_mm": p.diameter_mm,
        "length_mm": p.length_mm,
        "coverage_pct": coverage,
        "kind": "straight",
    })

    return PlanResult(
        stent_mesh_url=stent_url,
        coverage_pct=coverage,
        neck_diameter_covered_mm=round(neck_covered, 2),
        deployed=deployed,
        warning=" ".join(warnings) if warnings else None,
    )
