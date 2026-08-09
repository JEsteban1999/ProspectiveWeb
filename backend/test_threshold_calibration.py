"""Calibración del filtro HU (mín/máx) por tipo de caso — spec ejecutable.

Revisión sobre TODOS los volúmenes reales de `Archivos DICOM` (2026-08-09):
la banda auto se mide por la FRACCIÓN de vóxeles que captura, que es lo que
determina si el preview arranca sobre los vasos o sobre la cabeza entera.

Volúmenes reales medidos (modalidad real leída del DICOM):

    caso            modalidad  rama                 banda           %vox
    case9           XA (DSA)   dsa                  [372, 17509]    0.40 %
    case3           XA (3DRA)  xa_band_pass         [1470, 4717]    0.90 %
    DICOM-2026      XA (3DRA)  xa_window_mismatch   [1599, 4999]    0.89 %
    BETANCO 605/610 CT (CTA)   ct_stats             [150, 1500]     8.5 %
    CAMACHO 606     CT (CTA)   ct_stats             [150, 1500]     6.6 %
    DIAZ Serie 3    CT (CTA)   ct_stats             [150, 1500]     3.4 %

Conclusión de la revisión:
  - XA/3DRA (sustraído o no): la banda aísla los vasos (~0.4–1 %). Óptimo.
  - CTA: [150, 1500] es la banda de vaso estándar; captura vasos + hueso porque
    el contraste (200–450 HU) y el hueso (300–2000 HU) SE SOLAPAN en HU. Ningún
    umbral global los separa — la semilla (region-grow) desconecta el hueso.
    El suelo de 150 HU es correcto: subirlo solo quita tejido de volumen parcial
    y hueso trabecular (marginal) a costa de perder vasos distales tenues.

Estos tests fijan esa calibración con distribuciones sintéticas que reproducen
las intensidades reales medidas, para que un cambio futuro no la degrade.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_calib_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np

from services.thresholds import compute_auto_thresholds, voxel_fraction


def _bg_plus_tail(p50: float, std: float, bright_frac: float,
                  bright_lo: float, bright_hi: float,
                  n: int = 200_000, seed: int = 0) -> np.ndarray:
    """Fondo gaussiano (tejido) + una cola brillante (vasos/hueso)."""
    rng = np.random.default_rng(seed)
    n_bright = int(n * bright_frac)
    bg = rng.normal(p50, std, n - n_bright)
    bright = rng.uniform(bright_lo, bright_hi, n_bright)
    return np.concatenate([bg, bright]).astype(np.float32)


# ── XA / 3DRA — la banda debe aislar los vasos (fracción pequeña) ──────────── #

class TestXaCalibrationTargetsVessels:
    """Sustraído o no, la banda XA captura una fracción de tamaño-vaso (<1.5 %)."""

    def test_dsa_subtracted_case9(self):
        # Fondo sustraído ≈ -1024, cola vascular < 0.5 %; p99 negativo → rama dsa.
        rng = np.random.default_rng(9)
        bg = np.full(199_000, -1024.0, np.float32)
        bright = rng.uniform(2000.0, 19000.0, 1000).astype(np.float32)
        vol = np.concatenate([bg, bright])
        lo, up, strat = compute_auto_thresholds(vol, "XA", 0.0, 1000.0)
        assert strat == "dsa"
        assert 0.0 < voxel_fraction(vol, lo, up) < 0.015

    def test_non_subtracted_wide_ww_case3(self):
        # 3DRA no sustraído (WW ancha): tejido -400, cola vasos+hueso.
        vol = _bg_plus_tail(p50=-400.0, std=150.0, bright_frac=0.02,
                            bright_lo=1500.0, bright_hi=5000.0, seed=3)
        lo, up, strat = compute_auto_thresholds(vol, "XA", -343.0, 7577.0)
        assert strat == "xa_band_pass"
        assert voxel_fraction(vol, lo, up) < 0.02

    def test_display_window_mismatch_dicom2026(self):
        # WC=0/WW=200 es un preset de display cuyo techo (90) queda por debajo de
        # los vóxeles con contraste (p90 real ≈ 200) → se ignora y se usa [p99,p99.9].
        vol = _bg_plus_tail(p50=-362.0, std=130.0, bright_frac=0.12,
                            bright_lo=200.0, bright_hi=9000.0, seed=14)
        lo, up, strat = compute_auto_thresholds(vol, "XA", 0.0, 200.0)
        assert strat == "xa_window_mismatch"
        assert voxel_fraction(vol, lo, up) < 0.02


# ── CTA — banda de vaso estándar [150, 1500]; vasos + hueso (físico) ───────── #

class TestCtaCalibration:
    """CTA con contraste: suelo 150 HU, techo 1500 HU. La fracción incluye hueso
    porque contraste y hueso se solapan en HU — no es un fallo de calibración."""

    def _cta_volume(self, bone_vessel_frac: float, seed: int) -> np.ndarray:
        # Parénquima ≈ 40 HU (mayoría) + hueso/vasos 150..1200 en la cola.
        return _bg_plus_tail(p50=40.0, std=25.0, bright_frac=bone_vessel_frac,
                             bright_lo=150.0, bright_hi=1200.0, seed=seed)

    def test_contrast_branch_floor_and_ceiling(self):
        vol = self._cta_volume(bone_vessel_frac=0.08, seed=1)   # BETANCO ~8.5 %
        lo, up, strat = compute_auto_thresholds(vol, "CT", 90.0, 750.0)
        assert strat == "ct_stats"
        assert lo == 150.0          # suelo de vaso estándar de CTA
        assert up == 1500.0         # techo excluye metal/hueso muy denso
        # Captura vasos + hueso (solapan): fracción moderada, ni fondo ni todo.
        assert 0.02 <= voxel_fraction(vol, lo, up) <= 0.15

    def test_weaker_enhancement_still_ct_stats(self):
        vol = self._cta_volume(bone_vessel_frac=0.035, seed=2)  # DIAZ ~3.4 %
        lo, up, strat = compute_auto_thresholds(vol, "CT", 90.0, 750.0)
        assert strat == "ct_stats"
        assert lo == 150.0 and up == 1500.0

    def test_non_contrast_ct_uses_tissue_percentile(self):
        # Sin contraste (<2 % > 150 HU) → suelo derivado del tejido, acotado ≤150.
        rng = np.random.default_rng(5)
        vol = rng.normal(40.0, 30.0, 200_000).astype(np.float32)  # solo parénquima
        lo, up, strat = compute_auto_thresholds(vol, "CT", 40.0, 400.0)
        assert strat == "ct_stats"
        assert 20.0 <= lo <= 150.0
