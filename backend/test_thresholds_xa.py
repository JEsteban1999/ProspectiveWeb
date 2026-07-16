"""Umbrales XA/3DRA — casos reales de la carpeta Archivos DICOM.

Reproduce con volúmenes sintéticos las distribuciones de intensidad observadas
en los estudios reales, para fijar el comportamiento del auto-umbral.
"""
from __future__ import annotations

import numpy as np

from services.thresholds import compute_auto_thresholds, voxel_fraction


def _volume_like(p50: float, bright_frac: float, bright_lo: float, bright_hi: float,
                 n: int = 60_000, seed: int = 0) -> np.ndarray:
    """Volumen sintético: mayoría de fondo alrededor de p50 + una cola brillante."""
    rng = np.random.default_rng(seed)
    n_bright = int(n * bright_frac)
    bg = rng.normal(p50, 120.0, n - n_bright)
    bright = rng.uniform(bright_lo, bright_hi, n_bright)
    return np.concatenate([bg, bright]).astype(np.float32)


class TestXaWindowMismatch:
    """Caso real 'DICOM-20260714T160737Z-1-001': WC=0/WW=200 es un preset de
    visualización; los vasos viven en p95≈500 → max≈9000."""

    def _vol(self):
        # fondo ≈ -362, 12 % de vóxeles brillantes entre 200 y 9000
        return _volume_like(p50=-362.0, bright_frac=0.12, bright_lo=200.0, bright_hi=9000.0)

    def test_ignores_display_window(self):
        vol = self._vol()
        lower, upper, strategy = compute_auto_thresholds(vol, "XA", 0.0, 200.0)
        # La ventana WC/WW daría [-70, 90] — por debajo de los vasos.
        assert strategy == "xa_window_mismatch"
        assert upper > 90.0, "el umbral superior no puede quedar en la ventana de display"

    def test_band_sits_on_bright_voxels(self):
        vol = self._vol()
        lower, upper, _ = compute_auto_thresholds(vol, "XA", 0.0, 200.0)
        p90 = float(np.percentile(vol, 90))
        assert lower >= p90 - 1.0, "el umbral inferior debe partir del decil brillante"
        assert lower < upper

    def test_captures_a_plausible_vessel_fraction(self):
        vol = self._vol()
        lower, upper, _ = compute_auto_thresholds(vol, "XA", 0.0, 200.0)
        frac = voxel_fraction(vol, lower, upper)
        # Debe capturar estructura vascular, no el fondo entero.
        assert 0.001 < frac < 0.30


class TestXaCalibratedWindowStillHonoured:
    """Si la ventana WC/WW sí cubre los vóxeles brillantes, se respeta."""

    def test_wc_ww_used_when_consistent(self):
        # fondo ≈ 0, brillo entre 100 y 400; ventana WC=250/WW=600 → [40, 520]
        vol = _volume_like(p50=0.0, bright_frac=0.10, bright_lo=100.0, bright_hi=400.0, seed=1)
        lower, upper, strategy = compute_auto_thresholds(vol, "XA", 250.0, 600.0)
        assert strategy == "xa_wc_ww"
        assert upper >= float(np.percentile(vol, 90))


class TestXaDsaUnaffected:
    """El caso DSA (case 9) sigue entrando por su rama y no se toca."""

    def test_dsa_branch_wins(self):
        rng = np.random.default_rng(2)
        # Fondo sustraído ≈ -1024 y cola vascular < 1 % de los vóxeles, de modo
        # que p99 sigue siendo negativo (como en el case 9 real: p99 = -144).
        bg = np.full(59_700, -1024.0, dtype=np.float32)
        bright = rng.uniform(2000.0, 19000.0, 300).astype(np.float32)
        vol = np.concatenate([bg, bright])
        lower, upper, strategy = compute_auto_thresholds(vol, "XA", 0.0, 1000.0)
        assert strategy == "dsa"
        assert lower > 0 and upper > lower


class TestXaWideWindowBandPass:
    """Ventana ancha (>2000) → banda p90–p99 (casos 2 y 39)."""

    def test_band_pass(self):
        vol = _volume_like(p50=-300.0, bright_frac=0.10, bright_lo=300.0, bright_hi=7000.0, seed=3)
        lower, upper, strategy = compute_auto_thresholds(vol, "XA", -271.0, 2215.0)
        assert strategy == "xa_band_pass"
        assert lower < upper
