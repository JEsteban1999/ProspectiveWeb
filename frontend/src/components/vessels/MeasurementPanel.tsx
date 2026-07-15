/* 3D caliper measurements (Feature 3) — pick two points on the mesh; the
   Euclidean distance is computed client-side and drawn as a ruler. Mirrors the
   desktop MeasurementPanel: list, per-row label/visibility/delete, summary, CSV. */

import { Button } from "../Button";
import { Icon } from "../Icon";
import { PanelHead, SectionLabel } from "../PanelHead";
import { usePlanning } from "../../store/planning";

export function MeasurementPanel() {
  const {
    segmentation, pickMode, measurements, measurePending,
    setPickMode, setMeasurements, setMeasurePending,
  } = usePlanning();

  const hasMesh = !!segmentation?.mesh_url;
  const active = pickMode === "measure";
  const dists = measurements.map((m) => m.distance);

  const startMeasure = () => {
    if (active) { setPickMode(null); setMeasurePending(null); }
    else setPickMode("measure");
  };

  const remove = (id: number) => setMeasurements(measurements.filter((m) => m.id !== id));
  const toggle = (id: number) =>
    setMeasurements(measurements.map((m) => (m.id === id ? { ...m, visible: !m.visible } : m)));
  const rename = (id: number, label: string) =>
    setMeasurements(measurements.map((m) => (m.id === id ? { ...m, label } : m)));
  const clearAll = () => { setMeasurements([]); setMeasurePending(null); setPickMode(null); };

  const exportCsv = () => {
    const rows = [
      ["#", "Etiqueta", "xA", "yA", "zA", "xB", "yB", "zB", "Distancia_mm"],
      ...measurements.map((m) => [
        m.id, m.label,
        m.a[0].toFixed(3), m.a[1].toFixed(3), m.a[2].toFixed(3),
        m.b[0].toFixed(3), m.b[1].toFixed(3), m.b[2].toFixed(3),
        m.distance.toFixed(4),
      ]),
    ];
    const csv = rows.map((r) => r.join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "mediciones.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fade-rise">
      <PanelHead title="Mediciones 3D" desc="Distancia euclídea entre dos puntos del modelo" />

      {!hasMesh && (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", padding: "8px 0 12px" }}>
          Segmenta el vaso primero para poder medir sobre él.
        </div>
      )}

      <div style={{ fontSize: 12, color: "var(--muted-foreground)", margin: "2px 0 10px", lineHeight: 1.5 }}>
        Pulsa <b>Nueva medición</b> y haz clic en dos puntos de la escena 3D.
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <Button variant={active ? "default" : "outline"} size="sm" style={{ flex: 3 }} disabled={!hasMesh} onClick={startMeasure} leadingIcon={<Icon name="RULER" size={14} />}>
          {active ? (measurePending ? "Clic 2º punto…" : "Clic 1º punto…") : "Nueva medición"}
        </Button>
        <Button variant="outline" size="sm" style={{ flex: 1 }} disabled={measurements.length === 0} onClick={exportCsv}>CSV</Button>
        <Button variant="outline" size="sm" style={{ flex: 1 }} disabled={measurements.length === 0} onClick={clearAll}>✕</Button>
      </div>

      {measurements.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {measurements.map((m) => (
            <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", borderRadius: "var(--radius-md)", border: "1px solid var(--border)", opacity: m.visible ? 1 : 0.5 }}>
              <input
                value={m.label}
                onChange={(e) => rename(m.id, e.target.value)}
                style={{ width: 54, fontSize: 12, background: "transparent", border: "none", color: "var(--foreground)", fontWeight: 600 }}
              />
              <span style={{ flex: 1, fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--foreground)" }}>
                {m.distance.toFixed(2)} <span style={{ fontSize: 10, color: "var(--muted-foreground)" }}>mm</span>
              </span>
              <button onClick={() => toggle(m.id)} title="Mostrar/ocultar" style={{ background: "none", border: "none", cursor: "pointer", padding: 2, opacity: m.visible ? 1 : 0.4 }}>
                <Icon name="EYE" size={15} color="var(--muted-foreground)" />
              </button>
              <button onClick={() => remove(m.id)} title="Eliminar" style={{ background: "none", border: "none", cursor: "pointer", padding: 2, color: "var(--muted-foreground)", fontSize: 14 }}>✕</button>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", padding: "6px 0" }}>Sin mediciones.</div>
      )}

      {measurements.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <SectionLabel>Resumen</SectionLabel>
          <div style={{ display: "flex", gap: 12, fontSize: 12, marginTop: 6, fontFamily: "var(--font-mono)" }}>
            <span>n={measurements.length}</span>
            <span>mín {Math.min(...dists).toFixed(1)}</span>
            <span>máx {Math.max(...dists).toFixed(1)}</span>
            <span>media {(dists.reduce((a, b) => a + b, 0) / dists.length).toFixed(1)} mm</span>
          </div>
        </div>
      )}
    </div>
  );
}
