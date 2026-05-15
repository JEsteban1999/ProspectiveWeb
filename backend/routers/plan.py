"""Stent planning router."""
from __future__ import annotations

from fastapi import APIRouter

from models import PlanRequest, PlanResult, StentLibraryItem

router = APIRouter(prefix="/api", tags=["planning"])

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
    # ── MOCK: realistic coverage for a flow diverter on an 8.5mm dome ────
    return PlanResult(
        stent_mesh_url="/static/sample-meshes/stent_deployed.vtp",
        coverage_pct=52.3,
        neck_diameter_covered_mm=3.8,
        deployed=True,
        warning=None,
    )
