/* Paso 1 — Carga DICOM. POST /api/upload + GET /api/thresholds/{sid}.
   Soporta archivos sueltos y carpetas completas (selector + drag & drop),
   igual que la carga por directorio de la app de escritorio. */

import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { UploadResult } from "../../api/types";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Metric } from "../Metric";
import { PanelHead, SectionLabel, ErrorNote, Card } from "../PanelHead";
import { ProgressBar } from "../ProgressBar";
import { usePlanning } from "../../store/planning";

/* Recorre recursivamente las entradas de un drop (FileSystemEntry API) para
   que arrastrar una CARPETA suba todos los .dcm de dentro — el navegador no
   expande directorios por sí solo. */
function walkEntry(entry: FileSystemEntry, out: File[]): Promise<void> {
  return new Promise((resolve) => {
    if (entry.isFile) {
      (entry as FileSystemFileEntry).file(
        (f) => { out.push(f); resolve(); },
        () => resolve()
      );
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      const readBatch = () => {
        reader.readEntries(
          async (batch) => {
            if (batch.length === 0) { resolve(); return; }
            for (const e of batch) await walkEntry(e, out);
            readBatch(); // readEntries devuelve lotes de ≤100
          },
          () => resolve()
        );
      };
      readBatch();
    } else {
      resolve();
    }
  });
}

export function UploadPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const fileInput = useRef<HTMLInputElement>(null);
  const dirInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [nFiles, setNFiles] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  // React strips the non-standard `webkitdirectory` attribute, so set the DOM
  // properties imperatively. All three variants for cross-browser folder pick.
  useEffect(() => {
    const el = dirInput.current;
    if (!el) return;
    el.setAttribute("webkitdirectory", "");
    el.setAttribute("directory", "");
    el.setAttribute("mozdirectory", "");
  }, []);

  const doUpload = async (files: File[]) => {
    if (files.length === 0) {
      setError("No se recibió ningún archivo. Si arrastraste una carpeta, prueba con el botón «Seleccionar carpeta».");
      return;
    }
    setBusy(true);
    setNFiles(files.length);
    setError(null);
    // A new upload invalidates any previous segmentation/detection/morphometry.
    planning.resetDownstream();
    planning.setSegmentation(null);
    try {
      const res = await api.upload(files);
      setResult(res);
      planning.setSession(res.session_id);
      const primary = res.series[0] ?? null;
      planning.setSeries(primary);
      if (primary) {
        try {
          planning.setThresholds(await api.thresholds(res.session_id));
        } catch {
          planning.setThresholds(null); // thresholds are recomputed at segment time
        }
      } else {
        setError("No se detectó ninguna serie DICOM en los archivos subidos.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al subir los archivos");
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    // webkitGetAsEntry debe llamarse síncronamente dentro del handler
    const entries = Array.from(e.dataTransfer.items ?? [])
      .map((i) => i.webkitGetAsEntry?.())
      .filter((x): x is FileSystemEntry => x != null);
    if (entries.length > 0) {
      void (async () => {
        const files: File[] = [];
        for (const entry of entries) await walkEntry(entry, files);
        await doUpload(files);
      })();
    } else {
      void doUpload(Array.from(e.dataTransfer.files));
    }
  };

  const series = planning.series;

  return (
    <div className="fade-rise">
      <PanelHead
        title="Carga DICOM"
        desc="Sube la serie del estudio (carpeta o arrastrando los archivos)."
        right={series && <Badge variant="success">Cargado</Badge>}
      />

      <div
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        style={{
          border: `1.5px dashed ${dragOver ? "var(--primary)" : "var(--border)"}`,
          borderRadius: "var(--radius-lg)",
          padding: "24px 20px",
          textAlign: "center",
          background: dragOver ? "var(--brand-subtle)" : "var(--muted)",
          cursor: "pointer",
          transition: "background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out)",
        }}
      >
        <input
          ref={fileInput}
          type="file"
          multiple
          style={{ display: "none" }}
          onChange={(e) => void doUpload(Array.from(e.target.files ?? []))}
        />
        <input
          ref={dirInput}
          type="file"
          multiple
          style={{ display: "none" }}
          onChange={(e) => void doUpload(Array.from(e.target.files ?? []))}
        />
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 10, color: "var(--muted-foreground)" }}>
          <Icon name="FOLDER" size={30} />
        </div>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--foreground)" }}>
          Arrastra la carpeta DICOM aquí
        </div>
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginTop: 4 }}>
          o el conjunto de archivos .dcm — CTA · MRA · DSA / Enhanced XA
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
        <Button variant="outline" size="sm" style={{ flex: 1 }} onClick={() => fileInput.current?.click()} disabled={busy}>
          Seleccionar archivos
        </Button>
        <Button variant="outline" size="sm" style={{ flex: 1 }} onClick={() => dirInput.current?.click()} disabled={busy}>
          Seleccionar carpeta
        </Button>
      </div>

      {busy && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 6 }}>
            Subiendo {nFiles} archivo{nFiles === 1 ? "" : "s"} y detectando series…
          </div>
          <ProgressBar />
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>

      {series && (
        <Card style={{ marginTop: 16 }}>
          <SectionLabel>
            Serie detectada{result && result.series.length > 1 ? ` (1 de ${result.series.length})` : ""}
          </SectionLabel>
          <Metric label="Modalidad" value={series.modality} />
          <Metric label="Cortes" value={series.slices} />
          <Metric
            label="Espaciado"
            value={`${series.spacing.x.toFixed(2)} × ${series.spacing.y.toFixed(2)} × ${series.spacing.z.toFixed(2)}`}
            unit=" mm"
          />
          <Metric label="Descripción" value={series.description} />
          {result && <Metric label="Archivos subidos" value={result.total_files} />}
          {series.is_projection && (
            <div style={{ marginTop: 10, fontSize: 12, color: "var(--warning)", display: "flex", gap: 8, alignItems: "flex-start" }}>
              <Icon name="STATUS_WARN" size={14} />
              {series.projection_warning}
            </div>
          )}
        </Card>
      )}

      <Button
        style={{ marginTop: 18, width: "100%" }}
        onClick={onNext}
        disabled={!series}
        trailingIcon={<Icon name="STEP_SEGMENT" />}
      >
        Continuar a segmentación
      </Button>
    </div>
  );
}
