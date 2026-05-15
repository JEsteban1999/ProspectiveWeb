"""Treatment-strategy decision engine — CLIP vs ENDOVASCULAR.

Adapted from prospective/processing/treatment_decision.py — pure Python, zero Qt dependencies.
All logic is identical to the desktop version (same factor weights, thresholds and references).

References
----------
- Molyneux et al., ISAT 2002 (NEJM) — ruptured aneurysms
- Spetzler et al., BRAT 2013 — unruptured aneurysms
- Dhar et al. 2008 — bottleneck factor / shape indices
- Raghavan et al. 2005 — undulation index
- AHA/ASA Guidelines 2015 — aneurysm management
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Location constants ─────────────────────────────────────────────────────── #

LOCATION_UNKNOWN   = "Desconocida / No especificada"
LOCATION_MCA       = "ACM — Arteria Cerebral Media"
LOCATION_ACA_ACOA  = "ACA / ACoA — Arteria Comunicante Anterior"
LOCATION_ICA_PROX  = "ACI proximal (segm. cavernoso / clinoideo)"
LOCATION_ICA_DIST  = "ACI distal (PCOM / oftálmica)"
LOCATION_PCOM      = "ACoP — Arteria Comunicante Posterior"
LOCATION_BASILAR   = "Basilar (punta, tronco o AICA)"
LOCATION_PICA      = "PICA / Vertebral"
LOCATION_OTHER     = "Otra localización"

LOCATIONS: list[str] = [
    LOCATION_UNKNOWN, LOCATION_MCA, LOCATION_ACA_ACOA, LOCATION_ICA_PROX,
    LOCATION_ICA_DIST, LOCATION_PCOM, LOCATION_BASILAR, LOCATION_PICA, LOCATION_OTHER,
]


# ── Internal dataclasses ───────────────────────────────────────────────────── #

@dataclass
class _Factor:
    name:      str
    detail:    str
    direction: str  # "clip" | "endo" | "neutral"
    points:    int


@dataclass
class _Decision:
    clip_raw:          int
    endo_raw:          int
    balance:           int
    clip_pct:          int
    endo_pct:          int
    recommendation:    str
    recommendation_key: str
    confidence:        str
    icon:              str
    factors: list[_Factor] = field(default_factory=list)
    notes:   list[str]     = field(default_factory=list)


# ── Public engine ──────────────────────────────────────────────────────────── #

def compute_decision(
    neck_mm:           float,
    aspect_ratio:      float,
    dnr:               float,
    max_diameter_mm:   float,
    bottleneck_factor: float,
    undulation_index:  float,
    location:          str  = LOCATION_UNKNOWN,
    ruptured:          bool = False,
) -> dict[str, Any]:
    """Compute CLIP vs ENDOVASCULAR recommendation.

    All morpho inputs accept 0.0 as "not available" — factors are skipped
    when the input is zero so that partial morpho data still yields a result.

    Returns a dict matching TreatmentDecisionResult Pydantic model fields.
    """
    clip_pts = 0
    endo_pts = 0
    factors: list[_Factor] = []
    notes:   list[str]     = []

    def _add(name: str, detail: str, direction: str, pts: int) -> None:
        nonlocal clip_pts, endo_pts
        factors.append(_Factor(name, detail, direction, pts))
        if direction == "clip":
            clip_pts += pts
        elif direction == "endo":
            endo_pts += pts

    # ── Special case: very small aneurysm (< 3 mm) ────────────────────── #
    if 0 < max_diameter_mm < 3.0:
        notes.append(
            "Aneurisma muy pequeño (<3 mm): el riesgo procedimental generalmente "
            "supera el riesgo de ruptura. Se recomienda seguimiento con imagen."
        )
        return _to_dict(_Decision(
            clip_raw=0, endo_raw=0, balance=0,
            clip_pct=50, endo_pct=50,
            recommendation="VIGILANCIA ACTIVA",
            recommendation_key="surveillance",
            confidence="Alta",
            icon="👁",
            factors=[], notes=notes,
        ))

    # ── Factor 1: Neck diameter ────────────────────────────────────────── #
    if neck_mm > 0:
        if neck_mm < 4.0:
            _add(
                f"Cuello estrecho ({neck_mm:.1f} mm < 4 mm)",
                "Cuello < 4 mm: retención óptima del coil sin stent de soporte.",
                "endo", 25,
            )
        elif neck_mm <= 5.0:
            _add(
                f"Cuello intermedio ({neck_mm:.1f} mm, 4–5 mm)",
                "Cuello borderline: posible stent-assisted coiling o clipping.",
                "endo", 5,
            )
        else:
            _add(
                f"Cuello ancho ({neck_mm:.1f} mm > 5 mm)",
                "Cuello ≥ 5 mm: retención de coil difícil; clipping o flow diverter.",
                "clip", 25,
            )

    # ── Factor 2: Aspect Ratio (AR = dome_height / neck) ──────────────── #
    if aspect_ratio > 0:
        if aspect_ratio > 2.0:
            _add(
                f"Aspect Ratio alto (AR = {aspect_ratio:.2f} > 2.0)",
                "AR > 2: domo profundo relativo al cuello — geometría favorable para coiling.",
                "endo", 20,
            )
        elif aspect_ratio > 1.3:
            _add(
                f"Aspect Ratio moderado (AR = {aspect_ratio:.2f}, 1.3–2.0)",
                "AR 1.3–2.0: geometría ligeramente favorable para coiling.",
                "endo", 10,
            )
        else:
            _add(
                f"Aspect Ratio bajo (AR = {aspect_ratio:.2f} < 1.3)",
                "AR < 1.3: saco corto y ancho — acceso quirúrgico favorable.",
                "clip", 10,
            )

    # ── Factor 3: Dome-to-Neck Ratio (DNR) ────────────────────────────── #
    if dnr > 0:
        if dnr > 2.0:
            _add(
                f"DNR favorable para coiling (DNR = {dnr:.2f} > 2.0)",
                "DNR > 2: domo amplio relativo al cuello — buena retención de coils.",
                "endo", 15,
            )
        elif dnr > 1.5:
            _add(
                f"DNR moderado (DNR = {dnr:.2f}, 1.5–2.0)",
                "DNR 1.5–2.0: leve preferencia por coiling.",
                "endo", 8,
            )
        else:
            _add(
                f"DNR bajo (DNR = {dnr:.2f} < 1.5)",
                "DNR < 1.5: cuello ancho relativo al domo — clipping más efectivo.",
                "clip", 15,
            )

    # ── Factor 4: Maximum diameter ─────────────────────────────────────── #
    if max_diameter_mm > 0:
        if max_diameter_mm > 25.0:
            _add(
                f"Aneurisma gigante (Ø = {max_diameter_mm:.1f} mm > 25 mm)",
                "Gigante (>25 mm): flow diverter (PED) es tratamiento de elección.",
                "endo", 20,
            )
            notes.append(
                "Aneurisma gigante: considerar flow diverter (Pipeline, Surpass) "
                "o bypass quirúrgico con exclusión."
            )
        elif max_diameter_mm >= 12.0:
            _add(
                f"Aneurisma grande (Ø = {max_diameter_mm:.1f} mm, 12–25 mm)",
                "Grande (12–25 mm): ligera preferencia endovascular; valorar complejidad.",
                "endo", 5,
            )
        elif max_diameter_mm < 5.0:
            _add(
                f"Aneurisma pequeño (Ø = {max_diameter_mm:.1f} mm < 5 mm)",
                "Pequeño (<5 mm): clipping más fiable para exclusión completa.",
                "clip", 8,
            )
        # 5–12 mm: neutral (no factor added)

    # ── Factor 5: Bottleneck Factor (BF = max_dome_diam / neck) ──────── #
    if bottleneck_factor > 0:
        if bottleneck_factor > 2.0:
            _add(
                f"Bottleneck Factor alto (BF = {bottleneck_factor:.2f} > 2.0)",
                "BF > 2: cuello muy estrecho relativo al domo — ideal para coiling.",
                "endo", 12,
            )
        elif bottleneck_factor > 1.5:
            _add(
                f"Bottleneck Factor moderado (BF = {bottleneck_factor:.2f}, 1.5–2.0)",
                "BF 1.5–2.0: cuello moderadamente estrecho.",
                "endo", 6,
            )
        elif bottleneck_factor <= 1.2:
            _add(
                f"Bottleneck Factor bajo (BF = {bottleneck_factor:.2f} ≤ 1.2)",
                "BF ≤ 1.2: domo ancho (no hay efecto de cuello) — clipping favorable.",
                "clip", 8,
            )

    # ── Factor 6: Undulation Index (UI — dome irregularity) ───────────── #
    if undulation_index > 0:
        if undulation_index > 0.20:
            _add(
                f"Domo muy irregular (UI = {undulation_index:.3f} > 0.20)",
                "UI > 0.20: morfología lobulada; riesgo de llenado incompleto con coils.",
                "clip", 10,
            )
        elif undulation_index > 0.10:
            _add(
                f"Domo moderadamente irregular (UI = {undulation_index:.3f}, 0.10–0.20)",
                "UI 0.10–0.20: cierta irregularidad; leve preferencia por clipping.",
                "clip", 5,
            )
        elif undulation_index < 0.05:
            _add(
                f"Domo regular (UI = {undulation_index:.3f} < 0.05)",
                "Domo esférico regular — favorable para empaquetado con coils.",
                "endo", 5,
            )

    # ── Factor 7: Location (clinical input) ───────────────────────────── #
    loc = (location or "").strip()
    if loc == LOCATION_MCA:
        _add(
            "Localización ACM (Arteria Cerebral Media)",
            "ACM: acceso quirúrgico directo — clipping de elección en la mayoría de centros.",
            "clip", 20,
        )
    elif loc == LOCATION_ACA_ACOA:
        _add(
            "Localización ACA / ACoA",
            "ACoA: abordaje quirúrgico bien establecido; ligera preferencia por clipping.",
            "clip", 10,
        )
    elif loc == LOCATION_ICA_PROX:
        _add(
            "Localización ACI proximal (cavernoso / clinoideo)",
            "ACI proximal: acceso endovascular más seguro en la mayoría de casos.",
            "endo", 10,
        )
    elif loc == LOCATION_ICA_DIST:
        _add(
            "Localización ACI distal (PCOM / oftálmica)",
            "ACI distal: factible por ambas vías; leve preferencia endovascular.",
            "endo", 5,
        )
    elif loc == LOCATION_PCOM:
        _add(
            "Localización ACoP (Comunicante Posterior)",
            "PCOM: tratable por ambas vías; el tamaño y morfología determinan la estrategia.",
            "neutral", 0,
        )
    elif loc == LOCATION_BASILAR:
        _add(
            "Localización Basilar (punta, tronco o AICA)",
            "Basilar: acceso quirúrgico de alta complejidad — endovascular de elección.",
            "endo", 25,
        )
    elif loc == LOCATION_PICA:
        _add(
            "Localización PICA / Vertebral",
            "Circulación posterior: endovascular preferido por acceso quirúrgico difícil.",
            "endo", 20,
        )

    # ── Factor 8: Rupture status ───────────────────────────────────────── #
    if ruptured:
        _add(
            "Aneurisma roto (HSA activa)",
            "Roto: ISAT 2002 demostró superioridad de coiling en aneurismas accesibles.",
            "endo", 15,
        )
        notes.append(
            "Aneurisma roto: el coiling es de primera elección si la morfología lo permite "
            "(ISAT 2002). Si no es factible endovascularmente, clipping de urgencia."
        )

    # ── Compute percentages ────────────────────────────────────────────── #
    total = clip_pts + endo_pts
    if total == 0:
        clip_pct = endo_pct = 50
    else:
        clip_pct = round(clip_pts / total * 100)
        endo_pct = 100 - clip_pct

    balance = clip_pts - endo_pts

    # ── Confidence & recommendation ────────────────────────────────────── #
    abs_bal    = abs(balance)
    confidence = "Alta" if abs_bal >= 50 else "Moderada" if abs_bal >= 25 else "Baja"

    if balance >= 20:
        rec, rec_key, icon = "CLIPPING QUIRÚRGICO", "clip", "✂"
    elif balance <= -20:
        rec, rec_key, icon = "TRATAMIENTO ENDOVASCULAR", "endo", "💊"
    else:
        rec, rec_key, icon = "DISCUSIÓN MULTIDISCIPLINARIA", "mdt", "👥"
        if confidence == "Baja":
            notes.append(
                "Resultado ambiguo: se recomienda presentar el caso en sesión "
                "neuroendovascular multidisciplinaria antes de decidir la estrategia."
            )

    logger.debug(
        "TreatmentDecision: clip=%d endo=%d balance=%d → %s (%s)",
        clip_pts, endo_pts, balance, rec_key, confidence,
    )

    return _to_dict(_Decision(
        clip_raw=clip_pts, endo_raw=endo_pts, balance=balance,
        clip_pct=clip_pct, endo_pct=endo_pct,
        recommendation=rec, recommendation_key=rec_key,
        confidence=confidence, icon=icon,
        factors=factors, notes=notes,
    ))


# ── Serialiser ─────────────────────────────────────────────────────────────── #

def _to_dict(d: _Decision) -> dict[str, Any]:
    """Convert _Decision to a dict matching TreatmentDecisionResult fields."""
    factor_dicts = [
        {
            "name":      f.name,
            "detail":    f.detail,
            "direction": f.direction,
            "points":    f.points,
        }
        for f in d.factors
    ]
    return {
        "clip_pct":           d.clip_pct,
        "endo_pct":           d.endo_pct,
        "balance":            d.balance,
        "recommendation":     d.recommendation,
        "recommendation_key": d.recommendation_key,
        "confidence":         d.confidence,
        "icon":               d.icon,
        "factors":            factor_dicts,
        "clip_factors":       [f.name for f in d.factors if f.direction == "clip"],
        "endo_factors":       [f.name for f in d.factors if f.direction == "endo"],
    }
