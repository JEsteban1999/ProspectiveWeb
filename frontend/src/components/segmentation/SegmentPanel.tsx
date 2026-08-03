/* Paso 2 — Segmentación vascular. GET /api/thresholds · POST /api/segment. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Metric } from "../Metric";
import { PanelHead, SectionLabel, ErrorNote, Card } from "../PanelHead";
import { ProgressBar } from "../ProgressBar";
import { Slider } from "../Slider";
import { usePlanning } from "../../store/planning";

/* El backend identifica la estrategia de umbral con un código interno; aquí se
   traduce a algo que un clínico pueda leer. */
const STRATEGY_LABEL: Record<string, string> = {
  dsa: "angiografía sustraída (DSA)",
  xa_band_pass: "3DRA, ventana ancha",
  xa_wc_ww: "3DRA, ventana del estudio",
  xa_window_mismatch: "3DRA, calculado de la imagen",
  xa_raw16: "3DRA sin calibrar",
  ct_stats: "TC con contraste",
  ct_wc_ww: "TC, ventana del estudio",
  mr_percentile: "resonancia magnética",
  wc_ww: "ventana del estudio",
};

function strategyLabel(strategy: string): string {
  return STRATEGY_LABEL[strategy] ?? "automático";
}

export function SegmentPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, series, thresholds, thresholdsLoading, segmentation } = planning;

  // While the auto-threshold is still loading (slow first volume read), don't
  // let the clinician segment with the default 200/800 sliders — wait for the
  // real band. If it failed to load (loading done, still null), allow manual.
  const waitingThresholds = thresholdsLoading && !thresholds;

  const [lower, setLower] = useState(Math.round(thresholds?.lower ?? 200));
  const [upper, setUpper] = useState(Math.round(thresholds?.upper ?? 800));
  const [smoothing, setSmoothing] = useState(3);
  const [cleanup, setCleanup] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed sliders once the auto-thresholds arrive.
  useEffect(() => {
    if (thresholds) {
      setLower(Math.round(thresholds.lower));
      setUpper(Math.round(thresholds.upper));
    }
  }, [thresholds]);

  const run = async () => {
    if (!sessionId || !series) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.segment({
        session_id: sessionId,
        series_id: series.series_id,
        lower,
        upper,
        smoothing,
        cleanup,
      });
      planning.setSegmentation(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en la segmentación");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fade-rise">
      <PanelHead
        title="Segmentación vascular"
        desc="Aísla el árbol vascular por umbral de intensidad y reconstruye su superficie 3D."
        right={segmentation && <Badge variant="success">Malla lista</Badge>}
      />

      <SectionLabel style={{ marginBottom: 10 }}>
        Umbral {thresholds ? `· ${strategyLabel(thresholds.strategy)}` : ""}
      </SectionLabel>
      {waitingThresholds ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "var(--muted-foreground)", background: "var(--muted, rgba(120,130,140,0.08))", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "12px 14px", marginBottom: 12 }}>
          <span className="spin" style={{ width: 14, height: 14, borderRadius: "50%", border: "2px solid var(--border)", borderTopColor: "var(--primary)", display: "inline-block", flexShrink: 0 }} />
          Calculando umbral automático a partir del volumen…
        </div>
      ) : (
        thresholds?.hint && (
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 12 }}>{thresholds.hint}</div>
        )
      )}
      <div style={{ opacity: waitingThresholds ? 0.5 : 1, pointerEvents: waitingThresholds ? "none" : "auto", transition: "opacity var(--dur-fast) var(--ease-out)" }}>
        <Slider label="Umbral inferior" min={-500} max={1500} value={lower} onChange={setLower} unit=" HU" />
        <div style={{ height: 14 }} />
        <Slider label="Umbral superior" min={-500} max={3000} value={upper} onChange={setUpper} unit=" HU" />
        <div style={{ height: 14 }} />
        <Slider label="Suavizado" min={0} max={10} value={smoothing} onChange={setSmoothing} />
        <div style={{ height: 14 }} />
        <Slider label="Limpieza de fragmentos" min={0} max={10} value={cleanup} onChange={setCleanup} />
      </div>

      {busy && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 6 }}>
            Ejecutando Marching Cubes…
          </div>
          <ProgressBar />
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>

      {segmentation && (
        <Card style={{ marginTop: 16 }}>
          <Metric label="Vértices" value={segmentation.vertices.toLocaleString("es")} />
          <Metric label="Caras" value={segmentation.faces.toLocaleString("es")} />
          <Metric label="Salida" value={segmentation.mesh_url.split("/").pop() ?? ""} />
          {segmentation.voxel_fraction !== null && (
            <Metric
              label="Fracción de vóxeles"
              value={(segmentation.voxel_fraction * 100).toFixed(1)}
              unit=" %"
              badge={segmentation.voxel_fraction > 0.15 ? ["Permisivo", "warning"] : ["OK", "success"]}
            />
          )}
        </Card>
      )}

      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <Button
          variant={segmentation ? "outline" : "default"}
          onClick={() => void run()}
          disabled={busy || !sessionId || waitingThresholds}
          leadingIcon={<Icon name="GROWTH" />}
          style={{ flex: 1 }}
        >
          {waitingThresholds ? "Calculando umbral…" : segmentation ? "Re-segmentar" : "Segmentar"}
        </Button>
        {segmentation && (
          <Button onClick={onNext} trailingIcon={<Icon name="STEP_DETECT" />}>
            Detectar
          </Button>
        )}
      </div>
    </div>
  );
}
