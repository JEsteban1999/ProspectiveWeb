/* Paso 2 — Segmentación vascular. POST /api/segment.

   Umbral ADAPTATIVO por percentil: la banda de arranque y el rango de los
   sliders se derivan de la distribución de intensidad DEL PROPIO volumen (una
   sola regla universal, no presets por modalidad), así arrancan en el sitio
   correcto para cualquier escala (TC HU, 3DRA crudo, RM). El clínico la afina
   viendo la malla 3D formándose casi en tiempo real (vista previa gruesa) y el
   tinte verde en los cortes MPR. */

import { useEffect, useRef, useState } from "react";
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

/* Fallback si aún no hay volumen para calcular la banda adaptativa. */
export const SEG_LOWER_DEFAULT = 150;
export const SEG_UPPER_DEFAULT = 500;

export function SegmentPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, series, segmentation, setPreviewBand, setPreviewMeshUrl } = planning;

  const [lower, setLower] = useState(SEG_LOWER_DEFAULT);
  const [upper, setUpper] = useState(SEG_UPPER_DEFAULT);
  const [smoothing, setSmoothing] = useState(3);
  const [cleanup, setCleanup] = useState(7);   // level 7 → top-N isolation, mesh limpia
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Slider range + suggested band, adapted to this volume's intensity scale.
  const [range, setRange] = useState<{ min: number; max: number }>({ min: -500, max: 3000 });
  const suggested = useRef<{ lower: number; upper: number } | null>(null);
  const [previewing, setPreviewing] = useState(false);

  // On entering the step (fresh volume, no mesh yet), fetch the adaptive band.
  useEffect(() => {
    if (!sessionId || segmentation) return;
    let alive = true;
    api.suggestedBand(sessionId).then((b) => {
      if (!alive) return;
      suggested.current = { lower: b.lower, upper: b.upper };
      setLower(Math.round(b.lower));
      setUpper(Math.round(b.upper));
      const pad = Math.max(1, (b.vmax - b.vmin) * 0.05);
      setRange({ min: Math.floor(b.vmin - pad), max: Math.ceil(b.vmax + pad) });
    }).catch(() => { /* keep fallback defaults */ });
    return () => { alive = false; };
  }, [sessionId, segmentation]);

  // Live 2D tint on the MPR slices (fast, debounced). Only while tuning the
  // initial threshold — after segmenting, the grow panel drives the tint.
  useEffect(() => {
    if (segmentation) return;
    const t = setTimeout(() => setPreviewBand([lower, upper]), 140);
    return () => clearTimeout(t);
  }, [lower, upper, segmentation, setPreviewBand]);

  // Live 3D coarse-mesh preview (debounced) — the "casi en tiempo real" of the
  // desktop: shows the vascular tree forming as the sliders move.
  useEffect(() => {
    if (!sessionId || segmentation) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      setPreviewing(true);
      try {
        const res = await api.segmentPreview(sessionId, { lower, upper, cleanup, downsample: 3 });
        if (!cancelled) setPreviewMeshUrl(res.mesh_url);
      } catch {
        if (!cancelled) setPreviewMeshUrl(null);   // empty band → no mesh
      } finally {
        if (!cancelled) setPreviewing(false);
      }
    }, 420);
    return () => { cancelled = true; clearTimeout(t); };
  }, [lower, upper, cleanup, sessionId, segmentation, setPreviewMeshUrl]);

  // Clear the previews when leaving the segmentation step.
  useEffect(() => () => { setPreviewBand(null); setPreviewMeshUrl(null); }, [setPreviewBand, setPreviewMeshUrl]);

  const resetBand = () => {
    const s = suggested.current;
    setLower(Math.round(s ? s.lower : SEG_LOWER_DEFAULT));
    setUpper(Math.round(s ? s.upper : SEG_UPPER_DEFAULT));
  };

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
      setPreviewBand(null);       // final mesh now shows
      setPreviewMeshUrl(null);
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
        Umbral de intensidad
        {previewing && !segmentation && (
          <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 500, color: "var(--muted-foreground)" }}>
            · actualizando vista previa…
          </span>
        )}
      </SectionLabel>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 12 }}>
        Banda de arranque adaptada a este volumen. Mueve los sliders y observa la
        malla 3D formándose (vista previa) y el tinte verde en los cortes MPR.
      </div>
      <div>
        <Slider label="Umbral inferior" min={range.min} max={range.max} value={lower} onChange={setLower} unit="" />
        <div style={{ height: 14 }} />
        <Slider label="Umbral superior" min={range.min} max={range.max} value={upper} onChange={setUpper} unit="" />
        <div style={{ height: 14 }} />
        <Slider label="Suavizado" min={0} max={10} value={smoothing} onChange={setSmoothing} />
        <div style={{ height: 14 }} />
        <Slider label="Limpieza" min={0} max={10} value={cleanup} onChange={setCleanup} />
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: -4, marginBottom: 8, lineHeight: 1.45 }}>
          {cleanup === 0
            ? "Sin filtrar: se conserva todo, incluido el ruido."
            : cleanup <= 4
              ? "Filtra por tamaño: descarta motas y conserva cualquier fragmento que pueda ser un vaso."
              : "Aísla las estructuras mayores: malla más limpia, pero puede dejar fuera una rama suelta."}
        </div>
      </div>
      <div style={{ marginTop: 6, textAlign: "right" }}>
        <button
          onClick={resetBand}
          style={{ background: "transparent", border: "none", color: "var(--brand-deep)", fontSize: 11, cursor: "pointer", padding: 0 }}
        >
          Restablecer banda sugerida
        </button>
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted-foreground)", lineHeight: 1.5 }}>
        En estudios con hueso/cráneo, el umbral por sí solo no separa el vaso: sube "Limpieza"
        para aislar el árbol principal, o usa <b style={{ color: "var(--foreground)" }}>Crecer desde
        semillas</b> (abajo) para crecer solo el vaso conectado y dejar fuera el hueso.
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
          {/* What the cleanup threw away. Without this the loss is invisible:
              a whole branch can vanish and the mesh still looks plausible. */}
          <Metric
            label="Volumen conservado"
            value={(segmentation.kept_fraction * 100).toFixed(1)}
            unit=" %"
            badge={
              segmentation.largest_removed_mm3 >= 20
                ? ["Revisar", "warning"]
                : ["Limpio", "success"]
            }
          />
          {segmentation.fragments_removed > 0 && (
            <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 6, lineHeight: 1.5 }}>
              Se descartaron {segmentation.fragments_removed.toLocaleString("es")} fragmentos
              sueltos; el mayor medía {segmentation.largest_removed_mm3.toFixed(1)} mm³.
              {segmentation.largest_removed_mm3 >= 20 && (
                <> Un fragmento de ese tamaño puede ser un segmento de vaso desconectado:
                baja la limpieza si echas en falta alguna rama.</>
              )}
            </div>
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
