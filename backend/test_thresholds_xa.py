"""Umbrales XA/3DRA — casos reales de la carpeta Archivos DICOM.

Reproduce con volúmenes sintéticos las distribuciones de intensidad observadas
en los estudios reales, para fijar el comportamiento del auto-umbral.
"""
from __future__ import annotations

import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="prospective_thr_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

import numpy as np
from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.sessions import create_session, session_subdir, write_state
from services.thresholds import compute_auto_thresholds, voxel_fraction

Base.metadata.create_all(bind=engine)
client = TestClient(app)


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

    def test_captures_a_vessel_sized_fraction(self):
        """En 3DRA sin sustracción los vasos son ~1 % del volumen, no el 9 %
        que daría la banda p90–p99 (medido en las 4 series reales de
        'Archivos DICOM/DICOM-20260714T160737Z-1-001')."""
        vol = self._vol()
        lower, upper, _ = compute_auto_thresholds(vol, "XA", 0.0, 200.0)
        frac = voxel_fraction(vol, lower, upper)
        assert 0.0005 < frac < 0.05, f"fracción {frac:.3%} fuera de rango vascular"


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
    """Ventana ancha (>2000), 3DRA no sustraído (case 3).

    Regresión: la Rama 3 devolvía [p90, p99] = ~9% de vóxeles (bloque
    tejido+cráneo). Ahora aísla la cola brillante [p99, p99.9] (~1% = vasos),
    igual que la Rama 4. El tejido de fondo NO debe caer dentro de la banda.
    """

    def test_band_pass_targets_bright_tail(self):
        # Fondo (tejido) ≈ -300, 10 % de vóxeles brillantes (vasos+hueso) 300..7000.
        vol = _volume_like(p50=-300.0, bright_frac=0.10, bright_lo=300.0, bright_hi=7000.0, seed=3)
        lower, upper, strategy = compute_auto_thresholds(vol, "XA", -271.0, 2215.0)
        assert strategy == "xa_band_pass"
        assert lower < upper
        # El inferior queda muy por encima del tejido de fondo (~-300)…
        assert lower > 0.0
        # …y la banda captura una fracción pequeña (vasos), no el ~9% de antes.
        assert voxel_fraction(vol, lower, upper) < 0.03


class TestThresholdsEndpointUsesVolume:
    """Regresión: GET /api/thresholds derivaba la banda SOLO de WC/WW ('fast
    path'), así que toda la lógica basada en vóxeles era código muerto y una DSA
    se segmentaba con la ventana de display. Debe leer el volumen cacheado."""

    def _session_with_cached_volume(self, vol: np.ndarray, wc: float, ww: float) -> str:
        sid = create_session()
        meshes = session_subdir(sid, "meshes")
        np.save(meshes / "_volume.npy", vol.astype(np.float32))
        (meshes / "_volume_meta.json").write_text(json.dumps({
            "shape": list(vol.shape), "spacing": [1.0, 1.0, 1.0],
            "wc": wc, "ww": ww, "modality": "XA",
        }))
        write_state(sid, "dicom.modality", "XA")
        write_state(sid, "dicom.window_center", str(wc))
        write_state(sid, "dicom.window_width", str(ww))
        return sid

    def test_dsa_detected_through_endpoint(self):
        rng = np.random.default_rng(7)
        bg = np.full(59_700, -1024.0, dtype=np.float32)
        bright = rng.uniform(2000.0, 19000.0, 300).astype(np.float32)
        vol = np.concatenate([bg, bright]).reshape(60, 10, 100)
        sid = self._session_with_cached_volume(vol, wc=0.0, ww=1000.0)

        d = client.get(f"/api/thresholds/{sid}").json()
        # Con el 'fast path' esto daba xa_wc_ww [-200, 450].
        assert d["strategy"] == "dsa", d
        assert d["is_dsa"] is True
        assert d["lower"] > 0

    def test_display_window_ignored_through_endpoint(self):
        vol = _volume_like(p50=-362.0, bright_frac=0.12, bright_lo=200.0,
                           bright_hi=9000.0, n=60_000).reshape(60, 10, 100)
        sid = self._session_with_cached_volume(vol, wc=0.0, ww=200.0)

        d = client.get(f"/api/thresholds/{sid}").json()
        assert d["strategy"] == "xa_window_mismatch", d
        assert d["upper"] > 90.0, "no puede devolver la banda de la ventana de display"

    def test_falls_back_to_wc_ww_without_volume(self):
        sid = create_session()
        write_state(sid, "dicom.modality", "XA")
        write_state(sid, "dicom.window_center", "0")
        write_state(sid, "dicom.window_width", "200")
        r = client.get(f"/api/thresholds/{sid}")
        # Sin volumen no puede hacer magia, pero debe responder (no 500).
        assert r.status_code == 200
        assert r.json()["strategy"] == "xa_wc_ww"
