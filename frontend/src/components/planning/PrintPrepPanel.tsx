/* Preparación para impresión 3D (Feature 7) — port de print_prep_panel.py.
   Prepara la malla vascular (rellenar agujeros, suavizar, escalar), reporta
   dimensiones/volumen/estanqueidad y ajuste a la cama, y exporta un STL listo. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { PrintBed, PrintPrepResult } from "../../api/types";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Metric } from "../Metric";
import { SectionLabel, ErrorNote, Card } from "../PanelHead";
import { Select } from "../Select";
import { Slider } from "../Slider";
import { usePlanning } from "../../store/planning";

export function PrintPrepPanel() {
  const { sessionId, segmentation } = usePlanning();
  const [beds, setBeds] = useState<PrintBed[]>([]);
  const [bedName, setBedName] = useState("");
  const [targetSize, setTargetSize] = useState(80);
  const [smoothing, setSmoothing] = useState(20);
  const [holeSize, setHoleSize] = useState(5);
  const [fillHoles, setFillHoles] = useState(true);
  const [subdivide, setSubdivide] = useState(false);
  const [result, setResult] = useState<PrintPrepResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.printBeds().then((b) => {
      setBeds(b);
      if (b.length > 0) setBedName(b[0].name);
    }).catch(() => {});
  }, []);

  const bed = beds.find((b) => b.name === bedName);

  const run = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.printPrep(sessionId, {
        target_size_mm: targetSize,
        smooth_iterations: smoothing,
        hole_size: holeSize,
        fill_holes: fillHoles,
        subdivide,
        bed_x_mm: bed?.x_mm ?? 0,
        bed_y_mm: bed?.y_mm ?? 0,
        bed_z_mm: bed?.z_mm ?? 0,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error preparando la malla");
    } finally {
      setBusy(false);
    }
  };

  if (!segmentation) {
    return (
      <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
        Segmenta el vaso primero para poder prepararlo para impresión.
      </div>
    );
  }

  const dims = result?.dimensions_mm;

  return (
    <div>
      <SectionLabel>Impresión 3D</SectionLabel>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", margin: "6px 0 12px" }}>
        Rellena agujeros, suaviza y escala la malla; verifica estanqueidad y ajuste a la cama de impresión.
      </div>

      <Slider label="Tamaño objetivo (dimensión máx.)" min={0} max={250} value={targetSize} onChange={setTargetSize} unit=" mm" />
      <div style={{ height: 12 }} />
      <Slider label="Suavizado" min={0} max={100} value={smoothing} onChange={setSmoothing} />
      <div style={{ height: 12 }} />
      <Slider label="Tamaño máx. de agujero" min={0} max={30} value={holeSize} onChange={setHoleSize} unit=" mm" />
      <div style={{ height: 12 }} />
      <div style={{ display: "flex", gap: 16, marginBottom: 12 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
          <input type="checkbox" checked={fillHoles} onChange={(e) => setFillHoles(e.target.checked)} /> Rellenar agujeros
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
          <input type="checkbox" checked={subdivide} onChange={(e) => setSubdivide(e.target.checked)} /> Subdividir
        </label>
      </div>
      <Select
        label="Cama de impresión"
        options={beds.map((b) => ({ value: b.name, label: b.x_mm > 0 ? `${b.name} — ${b.x_mm}×${b.y_mm}×${b.z_mm} mm` : b.name }))}
        value={bedName}
        onChange={(e) => setBedName(e.target.value)}
      />

      {result && (
        <Card style={{ marginTop: 14 }}>
          {dims && <Metric label="Dimensiones" value={`${dims[0].toFixed(1)} × ${dims[1].toFixed(1)} × ${dims[2].toFixed(1)}`} unit=" mm" />}
          <Metric label="Escala aplicada" value={`×${result.scale_factor.toFixed(3)}`} />
          <Metric label="Volumen sólido" value={result.volume_cm3.toFixed(2)} unit=" cm³" />
          <Metric label="Superficie" value={result.surface_area_cm2.toFixed(1)} unit=" cm²" />
          <Metric
            label="Estanqueidad"
            value={result.is_watertight ? "Hermético" : `${result.open_edge_count} bordes abiertos`}
            badge={result.is_watertight ? ["OK", "success"] : ["No hermético", "warning"]}
          />
          <div style={{ display: "flex", alignItems: "center", padding: "9px 0" }}>
            <span style={{ fontSize: 13, color: "var(--muted-foreground)", flex: 1 }}>Ajuste a la cama</span>
            <Badge variant={result.fits_in_bed ? "success" : "destructive"}>
              {result.fits_in_bed ? "Cabe" : "No cabe"}
            </Badge>
          </div>
          {result.warnings.map((w, i) => (
            <div key={i} style={{ marginTop: 6, fontSize: 12, color: "var(--warning)", display: "flex", gap: 6 }}>
              <Icon name="STATUS_WARN" color="var(--warning)" size={15} /><span>{w}</span>
            </div>
          ))}
          <a href={result.stl_url} target="_blank" rel="noreferrer" style={{ display: "block", marginTop: 10, fontSize: 12, textAlign: "center" }}>
            Descargar STL listo para imprimir →
          </a>
        </Card>
      )}
      <ErrorNote>{error}</ErrorNote>

      <Button variant="outline" style={{ marginTop: 14, width: "100%" }} onClick={() => void run()} disabled={busy} leadingIcon={<Icon name="PRINT" />}>
        {busy ? "Preparando…" : "Preparar para impresión 3D"}
      </Button>
    </div>
  );
}
