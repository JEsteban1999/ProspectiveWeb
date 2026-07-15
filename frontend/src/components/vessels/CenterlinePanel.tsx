/* Centreline extraction panel (Feature 1) — pick two points on the vessel in
   the 3D viewer, then extract the medial-axis centreline (arc length, tortuosity,
   vessel diameter). Mirrors the desktop CenterlinePanel. */

import { useState } from "react";
import { api } from "../../api/client";
import type { CenterlineResult } from "../../api/types";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Metric } from "../Metric";
import { PanelHead, ErrorNote, SectionLabel } from "../PanelHead";
import { ProgressBar } from "../ProgressBar";
import { usePlanning } from "../../store/planning";

const RESOLUTIONS = [
  { value: "1.0", label: "1.0 mm · rápida" },
  { value: "0.8", label: "0.8 mm · recomendada" },
  { value: "0.6", label: "0.6 mm · fina (lenta)" },
];

function fmt(p: [number, number, number] | null): string {
  return p ? `(${p[0].toFixed(1)}, ${p[1].toFixed(1)}, ${p[2].toFixed(1)})` : "—";
}

function tortuosityBadge(t: number): [string, "success" | "warning" | "destructive"] {
  if (t >= 1.25) return ["Alta", "destructive"];
  if (t >= 1.1) return ["Moderada", "warning"];
  return ["Baja", "success"];
}

export function CenterlinePanel() {
  const {
    sessionId, segmentation, pickMode, clSource, clTarget,
    setPickMode, setClSource, setClTarget, setCenterlineMesh,
  } = usePlanning();

  const [voxel, setVoxel] = useState("0.8");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CenterlineResult | null>(null);

  const hasMesh = !!segmentation?.mesh_url;
  const ready = hasMesh && !!clSource && !!clTarget && !busy;

  const extract = async () => {
    if (!sessionId || !clSource || !clTarget) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.centerline(sessionId, {
        session_id: sessionId,
        source: { x: clSource[0], y: clSource[1], z: clSource[2] },
        target: { x: clTarget[0], y: clTarget[1], z: clTarget[2] },
        voxel_size_mm: Number(voxel),
      });
      setResult(res);
      setCenterlineMesh(res.centerline_mesh_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error extrayendo la línea central");
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    setResult(null);
    setError(null);
    setClSource(null);
    setClTarget(null);
    setPickMode(null);
    setCenterlineMesh(null);
  };

  const pickBtn = (which: "cl_source" | "cl_target", label: string, done: boolean) => {
    const active = pickMode === which;
    return (
      <Button
        variant={active ? "default" : "outline"}
        size="sm"
        style={{ flex: 1 }}
        disabled={!hasMesh || busy}
        onClick={() => setPickMode(active ? null : which)}
        leadingIcon={<Icon name={done ? "STATUS_OK" : which === "cl_source" ? "SEED" : "STEP_DETECT"} size={14} />}
      >
        {active ? "Clic en el vaso…" : label}
      </Button>
    );
  };

  return (
    <div className="fade-rise">
      <PanelHead
        title="Línea central del vaso"
        desc="POST /api/centerline — eje medial entre dos puntos (EDT + Dijkstra)"
      />

      {!hasMesh && (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", padding: "8px 0 14px" }}>
          Segmenta el vaso primero para poder marcar puntos sobre él.
        </div>
      )}

      <SectionLabel>Puntos extremos</SectionLabel>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", margin: "6px 0 10px", lineHeight: 1.5 }}>
        Marca origen y destino sobre el vaso; la línea central sigue el eje medial
        por mínimo coste (radio máximo).
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
        {pickBtn("cl_source", "Marcar origen", !!clSource)}
        {pickBtn("cl_target", "Marcar destino", !!clTarget)}
      </div>
      <div style={{ display: "flex", gap: 8, fontSize: 11, fontFamily: "var(--font-mono)", marginBottom: 14 }}>
        <span style={{ flex: 1, color: clSource ? "var(--success)" : "var(--muted-foreground)" }}>{fmt(clSource)}</span>
        <span style={{ flex: 1, color: clTarget ? "var(--destructive)" : "var(--muted-foreground)", textAlign: "right" }}>{fmt(clTarget)}</span>
      </div>

      <SectionLabel>Resolución</SectionLabel>
      <div style={{ display: "flex", gap: 6, margin: "8px 0 14px" }}>
        {RESOLUTIONS.map((r) => (
          <button
            key={r.value}
            onClick={() => setVoxel(r.value)}
            disabled={busy}
            style={{
              flex: 1, padding: "7px 4px", fontSize: 11, cursor: busy ? "not-allowed" : "pointer",
              borderRadius: "var(--radius-md)", border: "1px solid var(--border)",
              background: voxel === r.value ? "var(--brand-subtle)" : "transparent",
              color: voxel === r.value ? "var(--brand-subtle-foreground)" : "var(--muted-foreground)",
              fontWeight: voxel === r.value ? 700 : 500,
            }}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <Button style={{ flex: 3 }} disabled={!ready} onClick={() => void extract()} leadingIcon={<Icon name="STEP_MORPHO" />}>
          {busy ? "Calculando…" : "Extraer línea central"}
        </Button>
        <Button variant="outline" style={{ flex: 1 }} disabled={busy || (!result && !clSource)} onClick={clear}>
          Limpiar
        </Button>
      </div>

      {busy && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginBottom: 6 }}>
            Voxelizando y trazando el eje medial… (puede tardar según el tamaño del vaso)
          </div>
          <ProgressBar />
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>

      {result && (
        <div style={{ marginTop: 16 }}>
          <SectionLabel>Resultados</SectionLabel>
          <Metric label="Longitud de arco" value={result.arc_length_mm.toFixed(1)} unit=" mm" />
          <Metric label="Longitud recta" value={result.chord_length_mm.toFixed(1)} unit=" mm" />
          <Metric label="Tortuosidad" value={result.tortuosity.toFixed(3)} badge={tortuosityBadge(result.tortuosity)} />
          <Metric label="Índice de tortuosidad" value={result.tortuosity_index_pct.toFixed(1)} unit=" %" />
          <Metric label="Ø medio" value={result.mean_diameter_mm.toFixed(2)} unit=" mm" />
          <Metric label="Ø mínimo" value={result.min_diameter_mm.toFixed(2)} unit=" mm" />
          <Metric label="Ø máximo" value={result.max_diameter_mm.toFixed(2)} unit=" mm" />
          {result.warning && (
            <div style={{ marginTop: 10, fontSize: 12, color: "var(--warning)", display: "flex", gap: 8 }}>
              <Icon name="STATUS_WARN" color="var(--warning)" size={16} />
              <span>{result.warning}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
