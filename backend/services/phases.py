"""PHASES score computation (Greving et al., Lancet Neurology 2014).

Factors: Population, Hypertension, Age, Size, Earlier SAH, Site.
"""
from __future__ import annotations

from models.phases import PhasesRequest, PhasesResult

# Population points
_POP = {"other": 0, "japan": 3, "finland": 5}
# Site points: ICA=0, MCA=2, ACA/PComm/posterior=4
_SITE = {"ica": 0, "mca": 2, "aca_pcom_posterior": 4}

# 5-year rupture risk (%) indexed by total PHASES score (Greving 2014, Table).
_RISK_5YR = {
    0: 0.4, 1: 0.5, 2: 0.7, 3: 0.9, 4: 1.3, 5: 1.7, 6: 2.4,
    7: 3.2, 8: 4.3, 9: 5.9, 10: 7.8, 11: 10.2, 12: 13.0, 13: 17.0,
}


def _size_points(size_mm: float) -> int:
    if size_mm < 7.0:
        return 0
    if size_mm < 10.0:
        return 3
    if size_mm < 20.0:
        return 5
    return 6


def compute_phases(req: PhasesRequest) -> PhasesResult:
    pop = _POP.get(req.population, 0)
    htn = 1 if req.hypertension else 0
    age = 1 if req.age_years >= 70 else 0
    size = _size_points(req.size_mm)
    sah = 4 if req.earlier_sah else 0
    site = _SITE.get(req.site, 0)

    total = pop + htn + age + size + sah + site
    # Clamp lookup to the published table range [0, 13].
    risk = _RISK_5YR.get(max(0, min(13, total)), 17.0)
    band = "high" if risk >= 7.0 else "moderate" if risk >= 2.0 else "low"

    return PhasesResult(
        population_pts=pop,
        hypertension_pts=htn,
        age_pts=age,
        size_pts=size,
        sah_pts=sah,
        site_pts=site,
        total_score=total,
        risk_5yr_pct=risk,
        risk_band=band,
    )
