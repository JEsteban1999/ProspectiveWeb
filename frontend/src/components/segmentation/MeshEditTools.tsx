/* Herramientas de malla — refinamiento interactivo tras la segmentación:
   · Crecer desde semillas (region growing, POST /api/segment/grow)
   · Recortar malla por ROI caja/esfera (POST /api/mesh-crop)
   Ambas operan sobre vessel_tree.vtp; picking 3D reutiliza la infra del visor. */

import { useState } from "react";
import { api } from "../../api/client";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { SectionLabel, ErrorNote, Card } from "../PanelHead";
import { Slider } from "../Slider";
import { SEG_LOWER_DEFAULT, SEG_UPPER_DEFAULT } from "./SegmentPanel";
import { usePlanning } from "../../store/planning";

export function MeshEditTools() {
  const {
    sessionId, segmentation,
    pickMode, setPickMode,
    growSeeds, setGrowSeeds, cropCenter, setCropCenter,
    setSegmentation, setCandidates, setSelectedCandidate,
    setMorphometry, setTreatment, setCenterlineMesh,
  } = usePlanning();

  const [lower, setLower] = useState(SEG_LOWER_DEFAULT);
  const [upper, setUpper] = useState(SEG_UPPER_DEFAULT);
  const [shape, setShape] = useState<"sphere" | "box">("sphere");
  const [radius, setRadius] = useState(10);
  const [invert, setInvert] = useState(false);
  const [busy, setBusy] = useState<"grow" | "crop" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  if (!segmentation) return null;

  // Anything derived from the old mesh is invalid once it changes.
  const clearDownstream = () => {
    setCandidates([]);
    setSelectedCandidate(0);
    setMorphometry(null);
    setTreatment(null);
    setCenterlineMesh(null);
  };

  const runGrow = async () => {
    if (!sessionId || growSeeds.length === 0) return;
    setBusy("grow");
    setError(null);
    setNote(null);
    setPickMode(null);
    try {
      const res = await api.segmentGrow(sessionId, {
        seeds: growSeeds.map(([x, y, z]) => ({ x, y, z })),
        lower, upper, smoothing: 5, cleanup: 5,
      });
      setSegmentation({
        mesh_url: res.mesh_url,
        voxel_fraction: null,
        strategy: "grow_from_seeds",
        is_dsa: false,
        vertices: res.vertices,
        faces: res.faces,
      });
      clearDownstream();
      setGrowSeeds([]);
      setNote(`Malla regenerada: ${res.vertices.toLocaleString("es")} vértices · ${res.n_voxels.toLocaleString("es")} vóxeles${res.fragments_removed ? ` · ${res.fragments_removed} fragmento(s) descartado(s)` : ""}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en el crecimiento por semillas");
    } finally {
      setBusy(null);
    }
  };

  const runCrop = async () => {
    if (!sessionId || !cropCenter) return;
    setBusy("crop");
    setError(null);
    setNote(null);
    setPickMode(null);
    const [x, y, z] = cropCenter;
    try {
      const res = await api.meshCrop(sessionId, {
        mode: shape,
        center: { x, y, z },
        radius,
        invert,
      });
      setSegmentation({ ...segmentation, mesh_url: res.mesh_url, vertices: res.vertices, faces: res.faces });
      clearDownstream();
      setCropCenter(null);
      setNote(`Malla recortada: ${res.vertices.toLocaleString("es")} vértices (${res.removed_vertices.toLocaleString("es")} eliminados).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al recortar la malla");
    } finally {
      setBusy(null);
    }
  };

  const toolBtn = (active: boolean): React.CSSProperties => ({
    flex: 1, padding: "6px 10px", fontSize: 12, fontWeight: 600, cursor: "pointer",
    borderRadius: "var(--radius-md)", border: "1px solid var(--border)",
    background: active ? "var(--brand-subtle)" : "var(--card)",
    color: active ? "var(--brand-subtle-foreground)" : "var(--foreground)",
  });

  return (
    <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
      <SectionLabel style={{ marginBottom: 10 }}>Herramientas de malla</SectionLabel>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 14 }}>
        Refina la malla segmentada: crece un árbol conectado desde semillas o recorta una región (ruido/hueso).
      </div>

      {/* ── Grow from seeds ─────────────────────────────────────────────── */}
      <Card style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)", marginBottom: 4 }}>
          Crecer desde semillas
        </div>
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginBottom: 10 }}>
          Coloca semillas sobre el vaso real; crece solo lo conectado dentro del rango HU.
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button
            onClick={() => setPickMode(pickMode === "grow_seed" ? null : "grow_seed")}
            style={toolBtn(pickMode === "grow_seed")}
          >
            {pickMode === "grow_seed" ? "Colocando… (clic en el visor)" : `+ Semilla (${growSeeds.length})`}
          </button>
          <button
            onClick={() => { setGrowSeeds([]); if (pickMode === "grow_seed") setPickMode(null); }}
            disabled={growSeeds.length === 0}
            style={{ ...toolBtn(false), flex: "0 0 auto", opacity: growSeeds.length === 0 ? 0.5 : 1 }}
          >
            Limpiar
          </button>
        </div>
        <Slider label="HU inferior" min={-200} max={1500} value={lower} onChange={setLower} unit=" HU" />
        <div style={{ height: 10 }} />
        <Slider label="HU superior" min={0} max={3000} value={upper} onChange={setUpper} unit=" HU" />
        <div style={{ height: 12 }} />
        <Button
          variant="outline"
          onClick={() => void runGrow()}
          disabled={busy !== null || growSeeds.length === 0}
          leadingIcon={<Icon name="GROWTH" />}
          style={{ width: "100%" }}
        >
          {busy === "grow" ? "Creciendo…" : "Regenerar malla desde semillas"}
        </Button>
      </Card>

      {/* ── ROI crop ────────────────────────────────────────────────────── */}
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)", marginBottom: 4 }}>
          Recortar malla (ROI)
        </div>
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginBottom: 10 }}>
          Elige un centro y conserva o elimina la geometría dentro de una esfera o caja.
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button
            onClick={() => setPickMode(pickMode === "crop_center" ? null : "crop_center")}
            style={toolBtn(pickMode === "crop_center")}
          >
            {pickMode === "crop_center"
              ? "Clic en el visor…"
              : cropCenter
                ? `Centro: (${cropCenter.map((v) => v.toFixed(0)).join(", ")})`
                : "Elegir centro"}
          </button>
          {cropCenter && (
            <button onClick={() => setCropCenter(null)} style={{ ...toolBtn(false), flex: "0 0 auto" }}>
              Quitar
            </button>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button onClick={() => setShape("sphere")} style={toolBtn(shape === "sphere")}>Esfera</button>
          <button onClick={() => setShape("box")} style={toolBtn(shape === "box")}>Caja</button>
        </div>
        <Slider label={shape === "sphere" ? "Radio" : "Medio-lado"} min={2} max={80} value={radius} onChange={setRadius} unit=" mm" />
        <div style={{ height: 12 }} />
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <button onClick={() => setInvert(false)} style={toolBtn(!invert)}>Conservar dentro</button>
          <button onClick={() => setInvert(true)} style={toolBtn(invert)}>Eliminar dentro</button>
        </div>
        <Button
          variant="outline"
          onClick={() => void runCrop()}
          disabled={busy !== null || !cropCenter}
          leadingIcon={<Icon name="CUT" />}
          style={{ width: "100%" }}
        >
          {busy === "crop" ? "Recortando…" : "Recortar malla"}
        </Button>
      </Card>

      {note && (
        <div style={{ marginTop: 12, fontSize: 12, color: "var(--brand-subtle-foreground, #2f7d5b)", background: "var(--brand-subtle, rgba(54,214,168,0.1))", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "8px 12px" }}>
          {note}
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>
    </div>
  );
}
