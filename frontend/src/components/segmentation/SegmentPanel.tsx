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

export function SegmentPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, series, thresholds, segmentation } = planning;

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
        desc="GET /api/thresholds · POST /api/segment (Marching Cubes)"
        right={segmentation && <Badge variant="success">Malla lista</Badge>}
      />

      <SectionLabel style={{ marginBottom: 10 }}>
        Umbral {thresholds ? `(auto · ${thresholds.strategy})` : ""}
      </SectionLabel>
      {thresholds?.hint && (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 12 }}>{thresholds.hint}</div>
      )}
      <Slider label="Umbral inferior" min={-500} max={1500} value={lower} onChange={setLower} unit=" HU" />
      <div style={{ height: 14 }} />
      <Slider label="Umbral superior" min={-500} max={3000} value={upper} onChange={setUpper} unit=" HU" />
      <div style={{ height: 14 }} />
      <Slider label="Suavizado" min={0} max={10} value={smoothing} onChange={setSmoothing} />
      <div style={{ height: 14 }} />
      <Slider label="Limpieza de fragmentos" min={0} max={10} value={cleanup} onChange={setCleanup} />

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
          disabled={busy || !sessionId}
          leadingIcon={<Icon name="GROWTH" />}
          style={{ flex: 1 }}
        >
          {segmentation ? "Re-segmentar" : "Segmentar"}
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
