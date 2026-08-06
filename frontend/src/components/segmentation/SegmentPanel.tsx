/* Paso 2 — Segmentación vascular. POST /api/segment.

   Umbral FIJO para todos los casos: en vez de calcular un preset por caso (que
   variaba por modalidad y no era reutilizable), se arranca siempre desde la
   misma banda vascular con contraste y el clínico la afina con la vista previa
   de HU en tiempo real sobre los cortes MPR. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Metric } from "../Metric";
import { PanelHead, SectionLabel, ErrorNote, Card } from "../PanelHead";
import { ProgressBar } from "../ProgressBar";
import { Slider } from "../Slider";
import { MeshEditTools } from "./MeshEditTools";
import { PreprocessSection } from "./PreprocessSection";
import { usePlanning } from "../../store/planning";

/* Banda vascular con contraste, la misma para cualquier estudio. Por debajo de
   ~150 es fondo/tejido blando; por encima de ~500 entra hueso denso/calcio. */
export const SEG_LOWER_DEFAULT = 150;
export const SEG_UPPER_DEFAULT = 500;

export function SegmentPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, series, segmentation, setPreviewBand } = planning;

  const [lower, setLower] = useState(SEG_LOWER_DEFAULT);
  const [upper, setUpper] = useState(SEG_UPPER_DEFAULT);
  const [smoothing, setSmoothing] = useState(3);
  const [cleanup, setCleanup] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live threshold preview on the MPR views (debounced) — tints the voxels the
  // current band would capture, so the clinician tunes it before segmenting.
  useEffect(() => {
    const t = setTimeout(() => setPreviewBand([lower, upper]), 160);
    return () => clearTimeout(t);
  }, [lower, upper, setPreviewBand]);

  // Clear the preview when leaving the segmentation step.
  useEffect(() => () => setPreviewBand(null), [setPreviewBand]);

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
      setPreviewBand(null);   // mesh now shows; drop the threshold overlay
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

      <SectionLabel style={{ marginBottom: 10 }}>Umbral de intensidad</SectionLabel>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 12 }}>
        Banda vascular por defecto para cualquier estudio. Ajústala viendo en los cortes MPR
        qué se captura (resaltado en verde) antes de segmentar.
      </div>
      <div>
        <Slider label="Umbral inferior" min={-500} max={1500} value={lower} onChange={setLower} unit=" HU" />
        <div style={{ height: 14 }} />
        <Slider label="Umbral superior" min={-500} max={3000} value={upper} onChange={setUpper} unit=" HU" />
        <div style={{ height: 14 }} />
        <Slider label="Suavizado" min={0} max={10} value={smoothing} onChange={setSmoothing} />
        <div style={{ height: 14 }} />
        <Slider label="Limpieza de fragmentos" min={0} max={10} value={cleanup} onChange={setCleanup} />
      </div>
      <div style={{ marginTop: 6, textAlign: "right" }}>
        <button
          onClick={() => { setLower(SEG_LOWER_DEFAULT); setUpper(SEG_UPPER_DEFAULT); }}
          style={{ background: "transparent", border: "none", color: "var(--brand-deep)", fontSize: 11, cursor: "pointer", padding: 0 }}
        >
          Restablecer umbral por defecto ({SEG_LOWER_DEFAULT}–{SEG_UPPER_DEFAULT} HU)
        </button>
      </div>

      <PreprocessSection />

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

      <MeshEditTools />

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
