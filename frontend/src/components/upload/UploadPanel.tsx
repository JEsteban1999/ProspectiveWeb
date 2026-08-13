/* Paso 1 — Carga DICOM. POST /api/upload.
   Soporta archivos sueltos y carpetas completas (selector + drag & drop),
   igual que la carga por directorio de la app de escritorio. */

import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { StudySummary, UploadResult } from "../../api/types";
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
  const [switching, setSwitching] = useState(false);
  // Durable archive: which case (Study) this upload belongs to.
  const [studies, setStudies] = useState<StudySummary[]>([]);
  const [studyId, setStudyId] = useState<number | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [archived, setArchived] = useState(false);

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
      // The backend ranks the series (real 3-D volume first, most slices) and
      // activates series[0]; mirror that choice here.
      const primary = res.series[0] ?? null;
      planning.setSeries(primary);
      if (!primary) {
        setError("No se detectó ninguna serie DICOM en los archivos subidos.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al subir los archivos");
    } finally {
      setBusy(false);
    }
  };

  // Cases (Study rows) of the active patient — an upload is archived under one
  // of them so it survives the session TTL and shows up in the gallery.
  useEffect(() => {
    const pid = planning.patient?.id;
    if (!pid) { setStudies([]); setStudyId(null); return; }
    let alive = true;
    api.patientStudies(pid)
      .then((st) => {
        if (!alive) return;
        setStudies(st);
        setStudyId((cur) => cur ?? (st.length > 0 ? st[0].id : null));
      })
      .catch(() => { if (alive) setStudies([]); });
    return () => { alive = false; };
  }, [planning.patient?.id]);

  // Copy this upload's DICOM into durable storage under the chosen case.
  const archiveStudy = async () => {
    const sid = planning.sessionId;
    if (!sid || studyId == null) return;
    setArchiving(true);
    setError(null);
    try {
      await api.archiveStudy(studyId, sid);
      setArchived(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el estudio");
    } finally {
      setArchiving(false);
    }
  };

  // Switch which series of the study we work on. Everything derived from the
  // previous series (mesh, candidates, morphometry) becomes stale, so reset it.
  const switchSeries = async (seriesId: string) => {
    const sid = planning.sessionId;
    if (!sid || seriesId === planning.series?.series_id) return;
    setSwitching(true);
    setError(null);
    try {
      const s = await api.setActiveSeries(sid, seriesId);
      planning.resetDownstream();
      planning.setSegmentation(null);
      planning.setSeries(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cambiar de serie");
    } finally {
      setSwitching(false);
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
            Serie del estudio{result && result.series.length > 1 ? ` (${result.series.length} disponibles)` : ""}
          </SectionLabel>
          {/* A study usually carries several series (localisers, 2-D cines and
              more than one 3-D acquisition). We activate the best 3-D volume,
              but the clinician must be able to pick a different acquisition. */}
          {result && result.series.length > 1 && (
            <div style={{ marginBottom: 12 }}>
              <select
                value={series.series_id}
                disabled={switching}
                onChange={(e) => void switchSeries(e.target.value)}
                style={{
                  width: "100%", padding: "8px 10px", fontSize: 12,
                  fontFamily: "var(--font-sans)", color: "var(--foreground)",
                  background: "var(--card)", border: "1px solid var(--border)",
                  borderRadius: "var(--radius-md)", cursor: switching ? "wait" : "pointer",
                }}
              >
                {/* A study often repeats the same protocol (e.g. four 3D-RA
                    acquisitions): label each one so they can be told apart. */}
                {result.series.map((s, i) => (
                  <option key={s.series_id} value={s.series_id}>
                    {i + 1}. {s.description} · {s.slices} cortes · {s.spacing.z.toFixed(2)} mm
                    {s.is_projection ? " · ⚠ proyección 2D" : ""}
                  </option>
                ))}
              </select>
              <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 6 }}>
                {switching
                  ? "Cambiando de serie…"
                  : "Se activa el volumen 3D con más cortes. Cambiar de serie reinicia segmentación y pasos posteriores."}
              </div>
            </div>
          )}
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

      {/* Durable archive — without this the DICOM is deleted by the session TTL
          and the study never appears in the gallery. */}
      {series && (
        <Card style={{ marginTop: 12 }}>
          <SectionLabel>Guardar en el archivo de estudios</SectionLabel>
          <div style={{ fontSize: 11, color: "var(--muted-foreground)", margin: "6px 0 10px", lineHeight: 1.5 }}>
            Guarda este DICOM de forma permanente como un estudio del caso clínico
            elegido (un caso puede tener varios: TAC, angiografía, control) y genera
            su vista previa. Si no lo guardas, se borrará automáticamente.
          </div>
          {studies.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--warning)", display: "flex", gap: 6, alignItems: "flex-start" }}>
              <Icon name="STATUS_WARN" size={14} />
              Este paciente no tiene ningún caso. Crea uno desde «Pacientes → Nuevo caso».
            </div>
          ) : (
            <>
              {studies.length > 1 && (
                <select
                  value={studyId ?? ""}
                  onChange={(e) => setStudyId(Number(e.target.value))}
                  style={{
                    width: "100%", padding: "8px 10px", fontSize: 12, marginBottom: 10,
                    fontFamily: "var(--font-sans)", color: "var(--foreground)",
                    background: "var(--card)", border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)", cursor: "pointer",
                  }}
                >
                  {studies.map((st) => (
                    <option key={st.id} value={st.id}>
                      {st.dx_principal || st.description || `Caso ${st.id}`}
                      {st.acquired_at ? ` · ${st.acquired_at}` : ""}
                    </option>
                  ))}
                </select>
              )}
              <Button
                variant="outline"
                style={{ width: "100%" }}
                onClick={() => void archiveStudy()}
                disabled={archiving || studyId == null}
                leadingIcon={<Icon name={archived ? "STATUS_OK" : "SAVE"} size={14} />}
              >
                {archiving ? "Guardando…" : archived ? "Estudio guardado ✓" : "Guardar estudio"}
              </Button>
            </>
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
