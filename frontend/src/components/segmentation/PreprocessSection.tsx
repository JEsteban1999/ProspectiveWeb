/* Preprocesamiento del volumen (avanzado, Feature 10) — recorte HU, remuestreo
   isotrópico y suavizado gaussiano (port de dicom/preprocessor.py). Se aplica
   antes de segmentar; reescribe el volumen de la sesión y limpia lo posterior. */

import { useState } from "react";
import { api } from "../../api/client";
import type { PreprocessResult } from "../../api/types";
import { Button } from "../Button";
import { SectionLabel, ErrorNote } from "../PanelHead";
import { Slider } from "../Slider";
import { usePlanning } from "../../store/planning";

/** Modalities whose voxels are true Hounsfield units (mirrors the backend). */
const HU_MODALITIES = ["CT", "CTA", "CTPA"];

export function PreprocessSection() {
  const { sessionId, series, resetDownstream } = usePlanning();
  const isHu = HU_MODALITIES.includes((series?.modality ?? "").trim().toUpperCase());
  const [open, setOpen] = useState(false);
  // Only offered pre-ticked where it means something: on a 3DRA/XA volume the
  // HU clamp flattens everything above 3000, which is where the contrast is.
  const [clip, setClip] = useState(isHu);
  const [iso, setIso] = useState(false);
  const [target, setTarget] = useState(0.5);
  const [smooth, setSmooth] = useState(false);
  const [sigma, setSigma] = useState(0.5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<PreprocessResult | null>(null);

  const apply = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.preprocess(sessionId, {
        clip_hu: clip, resample_isotropic: iso, target_spacing_mm: target,
        smooth, smooth_sigma: sigma,
      });
      setRes(r);
      resetDownstream();  // volume changed → mesh/metrics stale
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en el preprocesamiento");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", background: "transparent", border: "none", cursor: "pointer", padding: 0 }}
      >
        <SectionLabel style={{ margin: 0 }}>Preprocesamiento (avanzado)</SectionLabel>
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--muted-foreground)" }}>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 10 }}>
            Ajusta el volumen antes de segmentar. Al aplicar se reinicia la segmentación.
          </div>
          <label
            title={isHu ? undefined : "Solo aplicable a volúmenes en unidades Hounsfield (TAC)"}
            style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: isHu ? "pointer" : "not-allowed", marginBottom: isHu ? 8 : 4, opacity: isHu ? 1 : 0.55 }}
          >
            <input type="checkbox" checked={clip} disabled={!isHu} onChange={(e) => setClip(e.target.checked)} /> Recorte de HU (−1000…3000)
          </label>
          {!isHu && (
            <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginBottom: 8, lineHeight: 1.45 }}>
              No aplicable a {series?.modality || "esta modalidad"}: sus intensidades no son
              unidades Hounsfield y el recorte aplanaría todo lo que supere 3000, que es
              justo donde está el contraste.
            </div>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", marginBottom: iso ? 8 : 8 }}>
            <input type="checkbox" checked={iso} onChange={(e) => setIso(e.target.checked)} /> Remuestreo isotrópico
          </label>
          {iso && (
            <div style={{ marginBottom: 8 }}>
              <Slider label="Tamaño de vóxel objetivo" min={0.2} max={2} step={0.1} value={target} onChange={setTarget} unit=" mm" />
            </div>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", marginBottom: smooth ? 8 : 12 }}>
            <input type="checkbox" checked={smooth} onChange={(e) => setSmooth(e.target.checked)} /> Suavizado gaussiano
          </label>
          {smooth && (
            <div style={{ marginBottom: 12 }}>
              <Slider label="Sigma" min={0.1} max={2} step={0.1} value={sigma} onChange={setSigma} />
            </div>
          )}

          {res && (
            <div style={{ fontSize: 12, color: "var(--foreground)", background: "var(--brand-subtle, rgba(54,214,168,0.1))", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "8px 12px", marginBottom: 10, fontFamily: "var(--font-mono)" }}>
              {res.shape_before.join("×")} @ {res.spacing_before.join(",")} → {res.shape_after.join("×")} @ {res.spacing_after.join(",")} mm
              <div style={{ fontFamily: "var(--font-sans)", marginTop: 4 }}>{res.note}</div>
            </div>
          )}
          <ErrorNote>{error}</ErrorNote>
          <Button variant="outline" style={{ width: "100%" }} disabled={busy || !sessionId || (!clip && !iso && !smooth)} onClick={() => void apply()}>
            {busy ? "Procesando…" : "Aplicar preprocesamiento"}
          </Button>
        </div>
      )}
    </div>
  );
}
