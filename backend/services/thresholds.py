"""Auto-threshold computation service.

Extracted from prospective/ui/widgets/segmentation_panel.py — pure Python/NumPy,
zero Qt dependencies. All logic is identical to the desktop version (same tests pass).

Strategy hint strings (for UI display):
  "dsa"           — DSA subtraction detected
  "xa_band_pass"  — 3DRA wide WW → p90–p99 band
  "xa_wc_ww"      — 3DRA narrow WW → calibrated WC/WW
  "ct_stats"      — CTA with contrast → WC-based formula clamped [150, 500] HU
  "ct_wc_ww"      — CT fallback → pure WC/WW
  "mr_percentile" — MR → p90–p99 of non-background voxels
  "wc_ww"         — generic fallback
"""
from __future__ import annotations

import numpy as np

# Modalities treated as X-ray angiography (XA)
_XA_MODALITIES = {"XA", "RF", "DX", "CR", "DR"}


# ── Public entry point ─────────────────────────────────────────────────────── #

def compute_auto_thresholds(
    volume: "np.ndarray | None",
    modality: str,
    window_center: float,
    window_width: float,
) -> tuple[float, float, str]:
    """Universal threshold computation for any DICOM modality.

    Returns (lower, upper, strategy).
    """
    mod = (modality or "").upper()

    if mod in _XA_MODALITIES:
        lower, upper, is_dsa = _xa_thresholds(volume, window_center, window_width)
        if is_dsa:
            strategy = "dsa"
        elif window_width > 2000 and volume is not None:
            strategy = "xa_band_pass"
        else:
            strategy = "xa_wc_ww"
        return lower, upper, strategy

    if mod == "CT":
        return _ct_thresholds(volume, window_center, window_width)

    if mod == "MR":
        return _mr_thresholds(volume, window_center, window_width)

    # Unknown / fallback
    if volume is not None:
        flat  = volume.ravel().astype("float32")
        lower = float(np.percentile(flat, 90))
        upper = float(np.percentile(flat, 99))
        return lower, upper, "wc_ww"
    lower = max(-200.0, window_center - window_width * 0.35)
    upper = window_center + window_width * 0.45
    return lower, upper, "wc_ww"


def strategy_hint(strategy: str, lower: float, upper: float, is_dsa: bool) -> str:
    """Return a human-readable Spanish hint for the chosen strategy."""
    hints = {
        "dsa": (
            f"DSA detectada: fondo sustraído ≈ −1024 HU. "
            f"Umbral inferior = p99.9 ({lower:.0f} HU) — captura sólo vóxeles vasculares. "
            f"Superior = 95% del máximo ({upper:.0f} HU)."
        ),
        "xa_band_pass": (
            f"3DRA estándar (WW amplio). Banda p90–p99: "
            f"inferior = {lower:.0f} HU, superior = {upper:.0f} HU."
        ),
        "xa_wc_ww": (
            f"3DRA ventana calibrada. Derivado de WC/WW: "
            f"inferior = {lower:.0f} HU, superior = {upper:.0f} HU."
        ),
        "ct_stats": (
            f"CTA con contraste (>2% vóxeles > 150 HU). "
            f"Umbral inferior fijado a {lower:.0f} HU para capturar vasos y excluir parénquima. "
            f"Superior = {upper:.0f} HU."
        ),
        "ct_wc_ww": (
            f"CT sin volumen — derivado de WC/WW: "
            f"inferior = {lower:.0f} HU, superior = {upper:.0f} HU."
        ),
        "mr_percentile": (
            f"MR: p90–p99 de vóxeles no-fondo: "
            f"inferior = {lower:.0f}, superior = {upper:.0f}."
        ),
        "wc_ww": (
            f"Modalidad desconocida — derivado de WC/WW: "
            f"inferior = {lower:.0f}, superior = {upper:.0f}."
        ),
    }
    return hints.get(strategy, f"Inferior = {lower:.0f}, Superior = {upper:.0f}.")


# ── XA / 3DRA ─────────────────────────────────────────────────────────────── #

def _xa_thresholds(
    volume: "np.ndarray | None",
    window_center: float,
    window_width: float,
) -> tuple[float, float, bool]:
    """XA/3DRA threshold — 4-branch logic (matches desktop segmentation_panel.py)."""
    if volume is not None:
        flat = volume.ravel().astype("float32")
        p90  = float(np.percentile(flat, 90))
        p99  = float(np.percentile(flat, 99))
        vmax = float(flat.max())

        # Branch 1: DSA subtraction (p99 < 0, max >> 0)
        if p99 < 0 and vmax > 500:
            p999  = float(np.percentile(flat, 99.9))
            lower = max(p999, 50.0)
            upper = vmax * 0.95
            return lower, upper, True

        # Branch 2: Raw 16-bit 3DRA (no HU rescale)
        if p90 > 5_000 and vmax > 50_000:
            lower = p99
            upper = float(np.percentile(flat, 99.9))
            return lower, upper, False

        # Branch 3: Standard 3DRA, wide WW
        if window_width > 2000:
            return p90, p99, False

    # Branch 4: Narrow WW or no volume
    lower = max(-200.0, window_center - window_width * 0.35)
    upper = window_center + window_width * 0.45
    return lower, upper, False


# ── CT ────────────────────────────────────────────────────────────────────── #

def _ct_thresholds(
    volume: "np.ndarray | None",
    wc: float,
    ww: float,
) -> tuple[float, float, str]:
    """CT/CTA threshold — WC-based formula clamped to [150, 500] HU."""
    if volume is not None:
        flat        = volume.ravel().astype("float32")
        frac_bright = float(np.mean(flat > 150))

        if frac_bright >= 0.02:
            # CTA with contrast: WC-based formula, floor at 150 HU
            lower = float(np.clip(wc - ww * 0.10, 150.0, 500.0))
            return lower, 1500.0, "ct_stats"

        # Non-contrast CT: 80th percentile of tissue voxels
        tissue = flat[flat > -100]
        if len(tissue) > 0:
            lower = float(np.clip(np.percentile(tissue, 80), 20.0, 150.0))
            return lower, 1500.0, "ct_stats"

    # Fallback: pure WC/WW
    lower = float(max(wc - ww * 0.10, 150.0))
    return lower, 1500.0, "ct_wc_ww"


# ── MR ────────────────────────────────────────────────────────────────────── #

def _mr_thresholds(
    volume: "np.ndarray | None",
    wc: float,
    ww: float,
) -> tuple[float, float, str]:
    """MR threshold — p90–p99 of non-background voxels."""
    if volume is not None:
        flat   = volume.ravel().astype("float32")
        vmin   = float(flat.min())
        cutoff = vmin + (float(flat.max()) - vmin) * 0.10
        tissue = flat[flat > cutoff]
        if len(tissue) > 0:
            lower = float(np.percentile(tissue, 90))
            upper = float(np.percentile(tissue, 99))
            return lower, upper, "mr_percentile"

    lower = max(-200.0, wc - ww * 0.35)
    upper = wc + ww * 0.45
    return lower, upper, "wc_ww"


# ── Voxel fraction helper ──────────────────────────────────────────────────── #

def voxel_fraction(volume: "np.ndarray", lower: float, upper: float) -> float:
    """Return the fraction of voxels inside [lower, upper] (0–1)."""
    flat = volume.ravel().astype("float32")
    return float(np.mean((flat >= lower) & (flat <= upper)))
