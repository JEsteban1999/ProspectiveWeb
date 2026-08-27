"""Clip selection: which clip fits THIS aneurysm, and why — or what to manufacture.

Why this exists next to `clips.py`
-----------------------------------
`clips.recommend_clips` scores the catalogue against two numbers (neck diameter
and aspect ratio) and returns a 0–100 composite. That has three problems this
module fixes:

1. **It only sees two variables.** Clip choice also depends on how deep the dome
   sits, whether a branch runs through the neck, the parent-artery calibre, the
   anatomical region, and how trustworthy the neck measurement is. All of those
   are already measured and stored — they were simply never fed to the scorer.

2. **It fails silently.** Its hard gate is `neck + 1 mm <= blade <= neck * 3`.
   A 1 mm neck and a 20 mm neck both come back as an empty list with nothing
   said. An empty list IS the answer "no stock clip fits" — it just has to be
   delivered as a manufacturing specification instead of as silence.

3. **A composite score is not a rationale.** "92.6" cannot be defended in front
   of a surgeon. Every candidate here carries a per-criterion verdict with the
   measurement behind it, so the panel can show *why* a clip ranks where it does
   and *what single thing* disqualified the ones that failed.

What this module is and is not
-------------------------------
The geometric criteria (blade vs neck, safety margin, fenestration calibre) are
arithmetic on measured quantities and are as good as the morphometry feeding
them. The clinical preferences (shape per region, closing-force windows) are
heuristics from the literature below, NOT validated against annotated cases —
there is no ground truth in this project to validate a ranking against. The
output is therefore assistive and always shows its reasons; it does not choose
a clip.

One limit is worth naming because it looks solvable and is not: whether a branch
actually runs through the neck cannot be seen from the isolated sac mesh. This
module infers "consider a fenestrated clip" from the anatomical region recorded
on the case, so that criterion is never a hard rejection — only a flag.

References
----------
- Lawton 2011, "Seven Aneurysms" — clip selection algorithm by location
- Molyneux et al. — neck >= 4 mm as the wide-neck threshold
- Pierot & Wakhloo 2013 — shape-based selection rationale
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from services.clips import (
    DEEP_DOME_AR_THRESHOLD,
    WIDE_NECK_THRESHOLD_MM,
    ClipShape,
    ClipSpec,
)

Verdict = Literal["ok", "warn", "fail"]

# ── Geometric limits ──────────────────────────────────────────────────────── #

# The blade has to overshoot the neck: a blade the width of the neck leaves no
# room for the residual wall and slips. 1 mm is the floor the legacy scorer used,
# kept here so the two modules agree on what is physically impossible.
BLADE_MIN_OVER_MM: float = 1.0
# Past this the clip is oversized for the target and its distal end sits in
# tissue it has no business touching.
BLADE_MAX_RATIO: float = 3.0
# Ideal blade/neck ratio, and the spread that still counts as comfortable.
COVERAGE_IDEAL: float = 1.35
COVERAGE_SIGMA: float = 0.25
COVERAGE_COMFORTABLE_LO: float = 1.15
COVERAGE_COMFORTABLE_HI: float = 2.20
# Below this the clip spans the neck but leaves nothing to grip.
SAFETY_MARGIN_WARN_MM: float = 1.5

# ── Closing-force windows by neck width ───────────────────────────────────── #
# A wider neck carries more residual wall between the blades, so it needs a
# firmer spring to stay put. Windows are (acceptable_lo, optimal_lo, optimal_hi,
# acceptable_hi) in grams. Heuristic, not measured.
_FORCE_WINDOWS: list[tuple[float, tuple[float, float, float, float]]] = [
    (4.0, (70.0, 80.0, 120.0, 150.0)),      # neck < 4 mm
    (7.0, (85.0, 100.0, 150.0, 175.0)),     # 4 mm <= neck < 7 mm
    (1e9, (105.0, 120.0, 190.0, 220.0)),    # neck >= 7 mm
]


def force_window(neck_mm: float) -> tuple[float, float, float, float]:
    """Acceptable and optimal closing-force band for a neck of this width."""
    for limit, window in _FORCE_WINDOWS:
        if neck_mm < limit:
            return window
    return _FORCE_WINDOWS[-1][1]


# ── Anatomical region → shape preference ──────────────────────────────────── #
# Keys are matched as substrings against the case's free-text region, lowercased
# and accent-stripped, because that field is typed by hand. An unrecognised
# region yields no preference rather than a penalty: a clip is not punished for
# a region we failed to parse.
_REGION_PREFERENCE: list[tuple[tuple[str, ...], dict[ClipShape, float], str]] = [
    (
        ("acom", "acoa", "comunicante anterior"),
        {ClipShape.STRAIGHT: 1.0, ClipShape.ANGLED_45: 0.9, ClipShape.CURVED: 0.85,
         ClipShape.FENESTRATED: 0.8, ClipShape.ANGLED: 0.7, ClipShape.BAYONET: 0.5},
        "ACoA: campo estrecho entre las A2; recto o angulado 45° es lo habitual",
    ),
    (
        ("acm", "cerebral media", "silviana", "m1", "m2"),
        {ClipShape.STRAIGHT: 1.0, ClipShape.CURVED: 0.95, ClipShape.FENESTRATED: 0.85,
         ClipShape.ANGLED_45: 0.7, ClipShape.ANGLED: 0.6, ClipShape.BAYONET: 0.5},
        "ACM: bifurcación superficial; recto o curvo, fenestrado si el cuello incorpora M2",
    ),
    (
        ("carotida", "ica", "paraclinoid", "paraclinoide", "oftalmica",
         "comunicante posterior", "acop"),
        {ClipShape.BAYONET: 1.0, ClipShape.ANGLED: 0.95, ClipShape.CURVED: 0.85,
         ClipShape.FENESTRATED: 0.8, ClipShape.ANGLED_45: 0.75, ClipShape.STRAIGHT: 0.6},
        "Carótida/paraclinoideo: campo profundo bajo la clinoides; bayoneta o angulado "
        "apartan el mango de la línea de visión",
    ),
    (
        ("basilar", "vertebral", "pica", "posterior", "tronco"),
        {ClipShape.ANGLED: 1.0, ClipShape.BAYONET: 0.95, ClipShape.ANGLED_45: 0.85,
         ClipShape.CURVED: 0.7, ClipShape.FENESTRATED: 0.65, ClipShape.STRAIGHT: 0.5},
        "Circulación posterior: campo profundo y estrecho; angulado o bayoneta",
    ),
    (
        ("pericallos", "callosomarginal", "aca", "a2", "a3"),
        {ClipShape.STRAIGHT: 1.0, ClipShape.CURVED: 0.9, ClipShape.ANGLED_45: 0.8,
         ClipShape.ANGLED: 0.6, ClipShape.BAYONET: 0.5, ClipShape.FENESTRATED: 0.5},
        "Pericallosa: vaso pequeño y superficial; recto corto",
    ),
]

# Regions where the neck commonly incorporates a branch, so a fenestrated clip is
# worth considering. A prompt, never a rejection: the branch itself is not
# visible in the isolated sac mesh (see the module docstring).
_BIFURCATION_HINTS: tuple[str, ...] = (
    "acom", "acoa", "comunicante", "acm", "cerebral media", "bifurcac",
    "trifurcac", "basilar", "carotida", "ica",
)

_ACCENTS = str.maketrans("áéíóúàèìòùäëïöüâêîôûñ", "aeiouaeiouaeiouaeioun")


def _norm(text: str) -> str:
    """Lowercase and strip accents so hand-typed region text still matches."""
    return (text or "").strip().lower().translate(_ACCENTS)


def _region_preference(region: str, aneurysm_type: str) -> tuple[dict[ClipShape, float] | None, str]:
    hay = f"{_norm(region)} {_norm(aneurysm_type)}"
    for keys, table, note in _REGION_PREFERENCE:
        if any(k in hay for k in keys):
            return table, note
    return None, ""


# ── The case ──────────────────────────────────────────────────────────────── #

@dataclass(frozen=True)
class ClipCase:
    """Everything about one aneurysm that changes which clip fits.

    Only `neck_mm` is required. Every other field degrades to "not considered"
    rather than to a wrong assumption, because a session can reach the devices
    step with a partial measurement and a half-filled case record.
    """
    neck_mm: float
    dome_height_mm: float = 0.0
    max_diameter_mm: float = 0.0
    ar: float = 0.0
    dnr: float = 0.0
    bf: float = 0.0
    parent_artery_mm: float = 0.0
    neck_source: str = "auto"          # auto | manual | rim
    neck_tilt_deg: float = 0.0
    neck_reliable: bool = True
    region: str = ""
    laterality: str = ""
    aneurysm_type: str = ""

    @property
    def is_wide_neck(self) -> bool:
        return self.neck_mm >= WIDE_NECK_THRESHOLD_MM

    @property
    def is_deep_dome(self) -> bool:
        return self.ar >= DEEP_DOME_AR_THRESHOLD

    @property
    def suggests_fenestration(self) -> bool:
        hay = f"{_norm(self.region)} {_norm(self.aneurysm_type)}"
        return any(k in hay for k in _BIFURCATION_HINTS)


# ── Criteria ──────────────────────────────────────────────────────────────── #

@dataclass(frozen=True)
class Criterion:
    """One judged aspect of a clip, carrying the number behind the verdict."""
    key: str
    label: str
    verdict: Verdict
    detail: str
    score: float          # 0–1, contribution to the ranking
    weight: float = 1.0


@dataclass
class GeometryCheck:
    """Result of actually placing the clip on the measured neck plane.

    `clean_rolls` of `n_rolls` matters as much as `collision` does. Reporting
    only the best orientation made a clip that clears the neighbouring vessel at
    every angle indistinguishable from one that clears it at exactly one — and
    the second demands an application accuracy the first does not.
    """
    collision: bool
    n_contacts: int
    span_mm: float
    neck_coverage_pct: float
    clean_rolls: int = 0
    n_rolls: int = 0
    note: str = ""

    @property
    def tight(self) -> bool:
        """Usable, but only from a narrow band of approach angles."""
        return 0 < self.clean_rolls <= max(1, self.n_rolls // 3)


@dataclass
class ClipCandidate:
    clip: ClipSpec
    criteria: list[Criterion]
    coverage_ratio: float
    safety_margin_mm: float
    score: float = 0.0                        # 0–100
    verified: GeometryCheck | None = None     # filled in by the VTK pass

    @property
    def failures(self) -> list[Criterion]:
        return [c for c in self.criteria if c.verdict == "fail"]

    @property
    def warnings(self) -> list[Criterion]:
        return [c for c in self.criteria if c.verdict == "warn"]

    @property
    def viable(self) -> bool:
        return not self.failures

    @property
    def verdict(self) -> Verdict:
        if self.failures:
            return "fail"
        return "warn" if self.warnings else "ok"

    @property
    def headline(self) -> str:
        """The single sentence the panel shows under the clip name."""
        if self.failures:
            return self.failures[0].detail
        if self.warnings:
            return self.warnings[0].detail
        return (f"Cumple todos los criterios · cobertura ×{self.coverage_ratio:.2f}, "
                f"margen {self.safety_margin_mm:.1f} mm")


def _coverage_criterion(clip: ClipSpec, case: ClipCase) -> Criterion:
    neck = case.neck_mm
    bl = clip.blade_length_mm
    cov = bl / neck if neck > 0 else 0.0
    margin = bl - neck

    if bl < neck + BLADE_MIN_OVER_MM:
        return Criterion(
            "coverage", "Cobertura", "fail",
            f"Hoja de {bl:.0f} mm insuficiente para un cuello de {neck:.1f} mm "
            f"(hacen falta ≥ {neck + BLADE_MIN_OVER_MM:.1f} mm)",
            0.0, weight=2.0,
        )
    if cov > BLADE_MAX_RATIO:
        return Criterion(
            "coverage", "Cobertura", "fail",
            f"Hoja de {bl:.0f} mm sobredimensionada (×{cov:.1f} el cuello): "
            f"el extremo distal queda sobre tejido sano",
            0.0, weight=2.0,
        )
    score = math.exp(-0.5 * ((cov - COVERAGE_IDEAL) / COVERAGE_SIGMA) ** 2)
    if margin < SAFETY_MARGIN_WARN_MM:
        return Criterion(
            "coverage", "Cobertura", "warn",
            f"Margen de seguridad corto: {margin:.1f} mm sobre el cuello (×{cov:.2f})",
            score, weight=2.0,
        )
    if not (COVERAGE_COMFORTABLE_LO <= cov <= COVERAGE_COMFORTABLE_HI):
        return Criterion(
            "coverage", "Cobertura", "warn",
            f"Relación hoja/cuello ×{cov:.2f}, fuera del rango cómodo "
            f"×{COVERAGE_COMFORTABLE_LO:.2f}–×{COVERAGE_COMFORTABLE_HI:.2f}",
            score, weight=2.0,
        )
    return Criterion(
        "coverage", "Cobertura", "ok",
        f"Cubre el cuello con {margin:.1f} mm de margen (×{cov:.2f})",
        score, weight=2.0,
    )


def _fenestration_criterion(clip: ClipSpec, case: ClipCase) -> Criterion | None:
    """Only emitted when the recorded region suggests a branch at the neck."""
    if not case.suggests_fenestration:
        return None
    is_fen = clip.shape == ClipShape.FENESTRATED
    parent = case.parent_artery_mm

    if not is_fen:
        # No criterion at all. Whether a branch runs through the neck is not
        # visible in the isolated sac mesh, so flagging every non-fenestrated
        # clip would warn on almost the whole catalogue — and a warning that
        # fires on everything stops carrying information. The prompt belongs
        # once, at case level, in `_caveats`.
        return None
    if parent <= 0:
        return Criterion(
            "fenestration", "Fenestración", "warn",
            "Fenestrado indicado, pero no hay diámetro de vaso padre medido con el que "
            "comprobar que la rama pasa por la ventana",
            0.75,
        )
    if clip.fenestration_mm <= 0:
        return Criterion(
            "fenestration", "Fenestración", "warn",
            f"Fenestrado indicado; el catálogo no declara el diámetro de ventana — "
            f"verificar que admite un vaso de {parent:.1f} mm",
            0.80,
        )
    if clip.fenestration_mm < parent:
        return Criterion(
            "fenestration", "Fenestración", "fail",
            f"Ventana de {clip.fenestration_mm:.1f} mm menor que el vaso padre "
            f"({parent:.1f} mm): estrangularía la rama",
            0.0,
        )
    return Criterion(
        "fenestration", "Fenestración", "ok",
        f"Ventana de {clip.fenestration_mm:.1f} mm admite el vaso padre ({parent:.1f} mm)",
        1.0,
    )


def _reach_criterion(clip: ClipSpec, case: ClipCase) -> Criterion | None:
    """A deep dome needs a shape that clears the sac to reach the neck."""
    if not case.is_deep_dome:
        return None
    fit = {ClipShape.ANGLED: 1.0, ClipShape.BAYONET: 0.95, ClipShape.ANGLED_45: 0.85,
           ClipShape.CURVED: 0.70, ClipShape.STRAIGHT: 0.50, ClipShape.FENESTRATED: 0.45}
    s = fit.get(clip.shape, 0.5)
    head = (f"Domo profundo (AR {case.ar:.2f}, altura {case.dome_height_mm:.1f} mm): "
            f"{clip.shape.value.lower()}")
    if s >= 0.85:
        return Criterion("reach", "Alcance", "ok", f"{head} libra el saco para alcanzar el cuello", s)
    if s >= 0.65:
        return Criterion("reach", "Alcance", "warn", f"{head} obliga a más retracción del saco", s)
    return Criterion("reach", "Alcance", "warn",
                     f"{head} es poco adecuado para este AR; considerar angulado o bayoneta", s)


def _shape_criterion(clip: ClipSpec, case: ClipCase) -> Criterion | None:
    table, note = _region_preference(case.region, case.aneurysm_type)
    if table is None:
        return None
    s = table.get(clip.shape, 0.5)
    if s >= 0.85:
        return Criterion("shape", "Forma / localización", "ok",
                         f"{clip.shape.value} adecuado. {note}", s)
    if s >= 0.60:
        return Criterion("shape", "Forma / localización", "warn",
                         f"{clip.shape.value} es viable pero no la primera opción. {note}", s)
    return Criterion("shape", "Forma / localización", "warn",
                     f"{clip.shape.value} poco habitual en esta localización. {note}", s)


def _force_criterion(clip: ClipSpec, case: ClipCase) -> Criterion:
    acc_lo, opt_lo, opt_hi, acc_hi = force_window(case.neck_mm)
    f = clip.closing_force_g
    if f < acc_lo:
        return Criterion(
            "force", "Fuerza de cierre", "fail",
            f"{f:.0f} g insuficiente para un cuello de {case.neck_mm:.1f} mm "
            f"(mínimo {acc_lo:.0f} g): riesgo de deslizamiento",
            0.0,
        )
    if f > acc_hi:
        return Criterion(
            "force", "Fuerza de cierre", "warn",
            f"{f:.0f} g por encima de lo necesario (máx. {acc_hi:.0f} g): "
            f"riesgo de lesión de la pared",
            0.30,
        )
    if opt_lo <= f <= opt_hi:
        return Criterion("force", "Fuerza de cierre", "ok",
                         f"{f:.0f} g dentro de la ventana {opt_lo:.0f}–{opt_hi:.0f} g", 1.0)
    return Criterion("force", "Fuerza de cierre", "warn",
                     f"{f:.0f} g aceptable pero fuera del óptimo {opt_lo:.0f}–{opt_hi:.0f} g", 0.60)


def recompute_score(cand: ClipCandidate) -> None:
    """Re-derive the 0–100 score after a criterion is added or changed.

    The geometric verification runs after the analytic pass, so its criterion
    lands on a candidate that was already scored.
    """
    total_w = sum(c.weight for c in cand.criteria) or 1.0
    raw = 100.0 * sum(c.score * c.weight for c in cand.criteria) / total_w
    cand.score = 0.0 if any(c.verdict == "fail" for c in cand.criteria) else round(raw, 1)


def evaluate_clip(clip: ClipSpec, case: ClipCase) -> ClipCandidate:
    """Judge one clip against one case, criterion by criterion.

    A candidate with any `fail` scores 0: the ranking must never float a clip
    that cannot physically be used above one that can.
    """
    crits: list[Criterion] = [_coverage_criterion(clip, case)]
    for maybe in (_fenestration_criterion(clip, case),
                  _reach_criterion(clip, case),
                  _shape_criterion(clip, case),
                  _force_criterion(clip, case)):
        if maybe is not None:
            crits.append(maybe)

    total_w = sum(c.weight for c in crits) or 1.0
    raw = 100.0 * sum(c.score * c.weight for c in crits) / total_w
    failed = any(c.verdict == "fail" for c in crits)
    cov = clip.blade_length_mm / case.neck_mm if case.neck_mm > 0 else 0.0

    return ClipCandidate(
        clip=clip,
        criteria=crits,
        coverage_ratio=round(cov, 3),
        safety_margin_mm=round(clip.blade_length_mm - case.neck_mm, 2),
        score=0.0 if failed else round(raw, 1),
    )


# ── Manufacturing specification ───────────────────────────────────────────── #
# Blade width/height and spring length are not free parameters: they track blade
# length across every real clip in the catalogue. Rather than invent them for a
# clip that does not exist yet, derive the proportions from the clips that do.

def _catalogue_proportions() -> tuple[float, float, float]:
    """Median width/length, height/length and spring/length across the catalogue."""
    from statistics import median

    from services.clips import CLIP_CATALOGUE
    w = median(c.blade_width_mm / c.blade_length_mm for c in CLIP_CATALOGUE)
    h = median(c.blade_height_mm / c.blade_length_mm for c in CLIP_CATALOGUE)
    s = median(c.spring_length_mm / c.blade_length_mm for c in CLIP_CATALOGUE)
    return w, h, s


@dataclass
class ManufactureSpec:
    """The clip that would fit, when no stock clip does.

    Everything here is derived from the case measurements plus the proportions
    observed across the real catalogue, so the numbers are manufacturable rather
    than notional. `confidence_notes` carries what a machinist still has to
    decide, because a spec that hides its assumptions is worse than one that
    states them.
    """
    blade_length_mm: float
    blade_width_mm: float
    blade_height_mm: float
    spring_length_mm: float
    shape: ClipShape
    angle_deg: float
    closing_force_g: float
    fenestration_mm: float          # 0.0 when a plain (non-fenestrated) clip fits
    neck_mm: float
    reasons: list[str]              # why the stock catalogue could not serve
    confidence_notes: list[str]

    @property
    def label(self) -> str:
        fen = f", ventana {self.fenestration_mm:.1f} mm" if self.fenestration_mm > 0 else ""
        return (f"{self.shape.value} de {self.blade_length_mm:.1f} mm"
                f"{fen} · {self.closing_force_g:.0f} g")


_SHAPE_ANGLE_OUT: dict[ClipShape, float] = {
    ClipShape.STRAIGHT: 0.0, ClipShape.CURVED: 0.0, ClipShape.BAYONET: 0.0,
    ClipShape.FENESTRATED: 0.0, ClipShape.ANGLED_45: 45.0, ClipShape.ANGLED: 90.0,
}


def _preferred_shape(case: ClipCase) -> ClipShape:
    """The shape the case argues for, independent of what is in stock."""
    if case.suggests_fenestration and case.parent_artery_mm > 0:
        return ClipShape.FENESTRATED
    table, _note = _region_preference(case.region, case.aneurysm_type)
    if table:
        # Best-rated shape for this region, broken toward reach when the dome is deep.
        if case.is_deep_dome:
            deep = {ClipShape.ANGLED, ClipShape.BAYONET, ClipShape.ANGLED_45}
            ranked = sorted(((v, k.name) for k, v in table.items() if k in deep), reverse=True)
            if ranked and ranked[0][0] >= 0.7:
                return ClipShape[ranked[0][1]]
        return max(table.items(), key=lambda kv: kv[1])[0]
    if case.is_deep_dome:
        return ClipShape.ANGLED
    if case.is_wide_neck:
        return ClipShape.CURVED
    return ClipShape.STRAIGHT


def derive_manufacture_spec(case: ClipCase, rejected: list[ClipCandidate]) -> ManufactureSpec:
    """Turn "nothing in stock fits" into something a workshop can build."""
    w_r, h_r, s_r = _catalogue_proportions()

    # Aim at the ideal blade/neck ratio, but never below the physical floor.
    target = max(case.neck_mm * COVERAGE_IDEAL, case.neck_mm + BLADE_MIN_OVER_MM)
    blade = math.ceil(target * 2.0) / 2.0          # round up to the next 0.5 mm

    shape = _preferred_shape(case)
    _acc_lo, opt_lo, opt_hi, _acc_hi = force_window(case.neck_mm)
    force = round((opt_lo + opt_hi) / 2.0)

    fen = 0.0
    notes: list[str] = []
    if shape == ClipShape.FENESTRATED and case.parent_artery_mm > 0:
        # Clearance so the window does not sit hard against the vessel wall.
        fen = round(case.parent_artery_mm + 0.5, 1)
    elif case.suggests_fenestration:
        # The location argues for a window but nothing here can size one. Say it
        # on the specification: quietly ordering a plain clip would drop a
        # requirement the case implied, and a workshop cannot know that.
        notes.append(
            "Esta localización suele necesitar clip fenestrado, pero no hay diámetro "
            "de vaso padre medido con el que dimensionar la ventana. Mide el vaso "
            "padre antes de fabricar, o confirma que el cuello no incorpora ninguna rama."
        )

    # Distinct reasons the stock catalogue failed, most common first.
    counts: dict[str, int] = {}
    for cand in rejected:
        for crit in cand.failures:
            key = {
                "coverage": "Ninguna hoja del catálogo cubre este cuello con margen suficiente",
                "force": "Ningún clip del catálogo alcanza la fuerza de cierre necesaria",
                "fenestration": "Ninguna ventana del catálogo admite el vaso padre",
            }.get(crit.key, crit.label)
            counts[key] = counts.get(key, 0) + 1
    reasons = [k for k, _v in sorted(counts.items(), key=lambda kv: -kv[1])]
    if not reasons:
        reasons = ["El catálogo no ofrece ninguna combinación válida para este caso"]

    notes.append(
        "Anchura, altura y muelle se derivan de las proporciones medianas del "
        "catálogo real, no de una medición del caso."
    )
    notes.append(
        f"La fuerza de cierre ({force} g) es el centro de la ventana heurística para "
        f"un cuello de {case.neck_mm:.1f} mm; confirmar con el fabricante."
    )
    if case.neck_source == "auto":
        notes.append(
            "El cuello se midió de forma automática. Marcarlo a mano o por borde "
            "antes de encargar la fabricación."
        )

    return ManufactureSpec(
        blade_length_mm=round(blade, 1),
        blade_width_mm=round(blade * w_r, 2),
        blade_height_mm=round(blade * h_r, 2),
        spring_length_mm=round(blade * s_r, 1),
        shape=shape,
        angle_deg=_SHAPE_ANGLE_OUT.get(shape, 0.0),
        closing_force_g=float(force),
        fenestration_mm=fen,
        neck_mm=round(case.neck_mm, 2),
        reasons=reasons,
        confidence_notes=notes,
    )


# ── Selection ─────────────────────────────────────────────────────────────── #

Outcome = Literal["stock", "marginal", "manufacture", "unmeasured"]


@dataclass
class ClipSelection:
    """The complete answer for one case: what to use, what not to, or what to build."""
    outcome: Outcome
    summary: str
    case: ClipCase
    recommended: list[ClipCandidate]
    rejected: list[ClipCandidate]
    manufacture: ManufactureSpec | None
    caveats: list[str]


def _caveats(case: ClipCase) -> list[str]:
    """Everything that limits how much weight this selection can bear."""
    out: list[str] = []
    if case.neck_source == "auto":
        out.append(
            "El cuello procede de la detección automática. Toda la selección cuelga "
            "de esa medida: márcalo a mano o por borde para una recomendación firme."
        )
    elif case.neck_source == "rim" and case.neck_tilt_deg >= 10.0:
        out.append(
            f"El plano del cuello está inclinado {case.neck_tilt_deg:.0f} grados respecto "
            f"al eje cuello-domo; el método de un solo punto habría medido un cuello menor."
        )
    if case.parent_artery_mm <= 0:
        out.append(
            "Sin diámetro de vaso padre medido: no se puede comprobar el calibre de "
            "ninguna ventana fenestrada."
        )
    if case.suggests_fenestration:
        out.append(
            "La localización registrada suele incorporar una rama en el cuello. Si es "
            "el caso, valora un clip fenestrado: la rama no es visible en la malla del "
            "saco aislado, así que el sistema no puede comprobarlo por geometría."
        )
    if not _region_preference(case.region, case.aneurysm_type)[0]:
        out.append(
            "La región anatómica del caso no se reconoció, así que la forma del clip "
            "se juzga solo por geometría, sin preferencia por localización."
        )
    out.append(
        "Las preferencias clínicas (forma por localización, ventanas de fuerza) son "
        "heurísticas de la literatura, no validadas contra casos anotados."
    )
    return out


def select_clips(
    case: ClipCase,
    catalogue: list[ClipSpec] | None = None,
    n: int = 6,
) -> ClipSelection:
    """Evaluate every clip against the case and decide what the answer is.

    Never returns an empty answer: when nothing in stock fits, the outcome is a
    manufacturing specification instead of silence.
    """
    from services.clips import CLIP_CATALOGUE

    if catalogue is None:
        catalogue = CLIP_CATALOGUE

    if case.neck_mm <= 0 or not case.neck_reliable:
        return ClipSelection(
            outcome="unmeasured",
            summary=(
                "No hay una medida de cuello fiable, y el cuello es la variable de la "
                "que depende toda la selección. Marca el plano del cuello en Morfometría."
            ),
            case=case, recommended=[], rejected=[], manufacture=None,
            caveats=["Sin cuello medido no se puede recomendar ni especificar un clip."],
        )

    evaluated = [evaluate_clip(c, case) for c in catalogue]
    viable = sorted([c for c in evaluated if c.viable], key=lambda c: -c.score)
    failed = sorted([c for c in evaluated if not c.viable],
                    key=lambda c: abs(c.clip.blade_length_mm - case.neck_mm * COVERAGE_IDEAL))

    recommended = viable[:n]
    # The near-misses worth showing: the ones that came closest to the ideal blade.
    rejected = failed[:n]

    if not viable:
        spec = derive_manufacture_spec(case, failed)
        return ClipSelection(
            outcome="manufacture",
            summary=(
                f"Ningún clip del inventario sirve para un cuello de {case.neck_mm:.1f} mm. "
                f"Se necesita fabricar: {spec.label}."
            ),
            case=case, recommended=[], rejected=rejected, manufacture=spec,
            caveats=_caveats(case),
        )

    clean = [c for c in recommended if c.verdict == "ok"]
    if clean:
        plural = len(clean) != 1
        return ClipSelection(
            outcome="stock",
            summary=(
                f"{len(clean)} clip{'s' if plural else ''} del inventario "
                f"cumple{'n' if plural else ''} todos los criterios para un "
                f"cuello de {case.neck_mm:.1f} mm."
            ),
            case=case, recommended=recommended, rejected=rejected, manufacture=None,
            caveats=_caveats(case),
        )

    # Usable but every one carries a caveat: offer the alternative rather than
    # letting the surgeon assume the top of the list is a clean fit.
    spec = derive_manufacture_spec(case, failed)
    plural = len(recommended) != 1
    return ClipSelection(
        outcome="marginal",
        summary=(
            f"{len(recommended)} clip{'s' if plural else ''} del inventario "
            f"{'son' if plural else 'es'} utilizable{'s' if plural else ''}, pero "
            f"ninguno sin reservas. La alternativa a medida sería: {spec.label}."
        ),
        case=case, recommended=recommended, rejected=rejected, manufacture=spec,
        caveats=_caveats(case),
    )
