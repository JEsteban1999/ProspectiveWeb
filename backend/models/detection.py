"""Aneurysm detection and morphometry models.

All linear dimensions → millimetres (mm).
Ratios and indices    → dimensionless.

Clinical reference ranges (Dhar 2008, Raghavan 2005, Greving 2014):
  dome_mm:            3–30 mm    (most 5–15 mm)
  neck_mm:            2–10 mm    (typical 3–6 mm)
  ar:                 1.0–4.0    (> 1.6 → elevated rupture risk)
  bf:                 0.5–3.0    (> 1.5 → wide neck)
  dnr:                0.5–3.0
  ui:                 0.0–0.5    (> 0.15 → irregular dome, higher risk)
  ei:                 0.0–0.6    (> 0.35 → non-spherical, higher risk)
  nsi:                0.0–0.5
  sr:                 0.5–5.0    (> 3.0 → elevated risk)
  compactness:        0.0–1.0    (1 = perfect sphere)
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Position3D(BaseModel):
    x: float = Field(..., description="X coordinate in mm (patient space)")
    y: float = Field(..., description="Y coordinate in mm (patient space)")
    z: float = Field(..., description="Z coordinate in mm (patient space)")


class AneurysmCandidate(BaseModel):
    """One aneurysm candidate returned by the detection step."""

    id: str = Field(..., description="Candidate identifier (e.g. 'cand-001')")
    center_mm: Position3D = Field(..., description="Centre of mass in patient space (mm)")
    max_diameter_mm: float = Field(..., description="Bounding-box max diameter (mm)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence score")
    dome_mesh_url: str = Field(
        ..., description="URL of the isolated dome mesh (.vtp) for 3D display"
    )
    selected: bool = Field(
        False, description="True when this candidate is the user-selected one"
    )


class DetectionDiagnostics(BaseModel):
    """Why the detector kept or rejected what it did.

    The detector always computed this breakdown but never returned it, so an
    empty result was indistinguishable from a crash. It is what tells a
    clinician whether to crop the region of interest, widen the mesh or accept
    that this study has no dome to find.
    """

    regions_analyzed: int = Field(
        0, description="High-curvature regions examined before the shape gates"
    )
    rejected_too_few_points: int = 0
    rejected_size: int = Field(
        0, description="Equivalent radius outside the accepted range"
    )
    rejected_mean_curvature: int = 0
    rejected_positive_gauss: int = 0
    rejected_compactness: int = 0
    rejected_sphericity: int = 0
    merged: int = Field(0, description="Regions merged into a neighbouring candidate")
    removed_components: int = Field(
        0, description="Disconnected mesh fragments dropped before analysis"
    )
    min_radius_mm: float = Field(0.0, description="Lower bound of the size gate")
    max_radius_mm: float = Field(0.0, description="Upper bound of the size gate")


class AneurysmDetectionResult(BaseModel):
    """Result of the aneurysm detection step."""

    found: bool = Field(..., description="True when at least one candidate was found")
    candidates: list[AneurysmCandidate] = Field(
        default_factory=list,
        description="All detected aneurysm candidates, ordered by confidence (descending)",
    )
    diagnostics: DetectionDiagnostics = Field(
        default_factory=DetectionDiagnostics,
        description="Region counts per rejection reason — explains an empty result",
    )


class MorphometryResult(BaseModel):
    """Full quantitative morphometry of the selected aneurysm.

    Matches MorphometricResult from prospective/processing/morphometrics.py.
    All linear values in mm; ratios are dimensionless.
    """

    # ── Volumetric ────────────────────────────────────────────────────────── #
    volume_mm3: float = Field(..., description="Enclosed volume (mm³)")
    surface_area_mm2: float = Field(..., description="Total surface area (mm²)")
    eq_sphere_diam_mm: float = Field(
        ..., description="Diameter of the volume-equivalent sphere (mm)"
    )

    # ── Bounding-box dimensions ───────────────────────────────────────────── #
    max_diameter_mm: float = Field(..., description="Maximum bounding-box dimension (mm)")
    bbox_w_mm: float = Field(..., description="Intermediate bounding-box dimension (mm)")
    bbox_h_mm: float = Field(..., description="Shortest bounding-box dimension (mm)")

    # ── Neck / dome (via plane slicing along principal axis) ─────────────── #
    neck_mm: float = Field(..., description="Neck diameter — minimum cross-section (mm)")
    dome_height_mm: float = Field(
        ..., description="Distance from neck plane to dome apex (mm)"
    )

    # ── Primary clinical ratios ───────────────────────────────────────────── #
    dnr: float = Field(
        ..., description="Dome-to-Neck Ratio = max_diameter / neck_mm  (risk ↑ if > 2.0)"
    )
    ar: float = Field(
        ..., description="Aspect Ratio = dome_height / neck_mm  (risk ↑ if > 1.6)"
    )
    bf: float = Field(
        ..., description="Bottleneck Factor = max_diameter / neck_mm  (> 1.5 → wide neck)"
    )
    compactness: float = Field(
        ..., ge=0.0, le=1.0,
        description="Wadell sphericity — 1 = perfect sphere, 0 = highly irregular"
    )

    # ── Shape-complexity indices (Ankyras-style) ──────────────────────────── #
    ui: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Undulation Index = 1 − V_sac / V_convex_hull  (> 0.15 → irregular)"
    )
    ei: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Ellipticity Index  (> 0.35 → non-spherical, higher rupture risk)"
    )
    nsi: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Non-Sphericity Index = 1 − Wadell_sphericity  (0 = perfect sphere)"
    )
    sr: float = Field(
        0.0, ge=0.0,
        description=(
            "Size Ratio = max_diameter / parent_artery_diameter. "
            "0 when parent artery not available (> 3.0 → elevated risk)"
        ),
    )

    # ── Risk label ────────────────────────────────────────────────────────── #
    rupture_risk_label: Literal["Alto", "Moderado", "Bajo"] = Field(
        ...,
        description=(
            "Heuristic rupture-risk label derived from AR, DNR, UI, SR. "
            "NOT a clinical diagnosis — for planning reference only."
        ),
    )

    # ── Validity ──────────────────────────────────────────────────────────── #
    reliable: bool = Field(
        True,
        description=(
            "True when the analysis ran on a closed, physically plausible sac. "
            "False when the mesh was an open surface patch (detector cap): "
            "volume, neck and all derived ratios are then nulled — place a neck "
            "plane (POST .../neck-plane) to obtain a valid closed-sac measurement."
        ),
    )
    neck_source: Literal["auto", "manual", "rim"] = Field(
        "auto",
        description=(
            "'auto' = neck from automatic plane-slicing on the candidate; "
            "'manual' = plane from one neck point plus the dome apex; "
            "'rim' = plane fitted to points marked around the neck rim."
        ),
    )
    neck_tilt_deg: float = Field(
        0.0,
        description=(
            "Angle between the neck plane and the neck→dome axis, in degrees. "
            "Only meaningful with neck_source='rim'. Near 0° the single-point "
            "method would have produced the same plane; large values are the "
            "oblique necks it gets wrong."
        ),
    )
    neck_valid: bool = Field(
        ...,
        description=(
            "False when automatic neck detection failed (neck_mm < 1 mm or "
            "PCA axis mismatch on complex DSA meshes). "
            "DNR, AR, BF and rupture_risk_label are unreliable when False."
        ),
    )
    warning: str | None = Field(
        None,
        description=(
            "Human-readable warning shown in the UI when neck_valid is False "
            "or when indices fall outside clinically plausible ranges."
        ),
    )

    # ── Geometry helpers for 3D display ──────────────────────────────────── #
    centroid: Position3D | None = Field(
        None, description="Centre of mass of the aneurysm mesh in patient space (mm)"
    )
    principal_axis: list[float] | None = Field(
        None, description="Principal PCA axis as [x, y, z] unit vector"
    )
    neck_origin: Position3D | None = Field(
        None,
        description=(
            "Centre of the aneurysm neck in patient space (mm). This is the point "
            "a clip or stent must be placed on — do not re-derive it from the "
            "centroid and the dome height, which lands off the neck."
        ),
    )


class NeckPlaneRequest(BaseModel):
    """User-defined neck plane for semi-automatic closed-sac morphometry.

    The user places a point on the neck and a normal pointing toward the dome.
    The backend clips the vessel tree at this plane, keeps the dome-side
    connected component, caps the opening into a closed watertight sac, and
    measures the neck directly from the plane∩tree contour.
    """

    origin: Position3D = Field(..., description="A point on the neck plane (mm, patient space)")
    normal: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Plane normal [x, y, z] pointing toward the dome (need not be unit length)",
    )
    dome_seed: Position3D | None = Field(
        None,
        description=(
            "Optional point inside the dome to disambiguate the sac side. "
            "Defaults to origin + 3·normal."
        ),
    )
    rim_points: list[Position3D] = Field(
        default_factory=list,
        description=(
            "Optional points around the neck rim. With three or more, the plane "
            "is fitted to them instead of assuming it is perpendicular to the "
            "neck→dome axis — real necks are often oblique to that axis, and a "
            "tilted cutting plane crosses the neck diagonally and overestimates "
            "its diameter. `origin` and `normal` are then ignored."
        ),
    )
