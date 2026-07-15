/* Paso 7 — Informe y exportación. POST /api/report · /api/export/stl · /api/sessions/save. */

import { useState } from "react";
import { api } from "../../api/client";
import type { ReportResult } from "../../api/types";
import { riskVariant } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Input } from "../Input";
import { Metric } from "../Metric";
import { PanelHead, SectionLabel, ErrorNote, Card } from "../PanelHead";
import { Separator } from "../Separator";
import { useAuth } from "../../store/auth";
import { usePlanning } from "../../store/planning";

export function ReportPanel({ onFinish }: { onFinish: () => void }) {
  const { user } = useAuth();
  const { sessionId, patient, morphometry, treatment } = usePlanning();
  const [surgeon, setSurgeon] = useState(user?.full_name ?? "");
  const [notes, setNotes] = useState("");
  const [report, setReport] = useState<ReportResult | null>(null);
  const [stl, setStl] = useState<ReportResult | null>(null);
  const [busy, setBusy] = useState<"pdf" | "stl" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const genPdf = async () => {
    if (!sessionId) return;
    setBusy("pdf");
    setError(null);
    try {
      setReport(
        await api.report({
          session_id: sessionId,
          patient_name: patient?.full_name ?? "",
          patient_dob: patient?.dob ?? "",
          patient_sex: patient?.sex ?? "",
          hospital_id: patient?.hospital_id ?? "",
          surgeon_name: surgeon,
          institution: patient?.institution ?? user?.institution ?? "",
          clinical_notes: notes,
          include_3d_screenshot: false,
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error generando el informe");
    } finally {
      setBusy(null);
    }
  };

  const genStl = async () => {
    if (!sessionId) return;
    setBusy("stl");
    setError(null);
    try {
      setStl(await api.exportStl({ session_id: sessionId }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error exportando STL");
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (!sessionId) return;
    setBusy("save");
    setError(null);
    try {
      await api.saveSession({
        session_id: sessionId,
        label: patient ? `Planificación ${patient.full_name}` : "Planificación",
        patient_id: patient?.id ?? null,
        current_step: 5,
      });
      onFinish();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error guardando la sesión");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="fade-rise">
      <PanelHead title="Informe y exportación" desc="POST /api/report · POST /api/export/stl" />

      <Card style={{ padding: "16px 18px" }}>
        <SectionLabel>Resumen del caso</SectionLabel>
        <Metric label="Paciente" value={patient?.full_name ?? "—"} />
        {morphometry && (
          <>
            <Metric label="Ø máximo" value={morphometry.max_diameter_mm.toFixed(1)} unit=" mm" />
            <Metric
              label="Riesgo (morfometría)"
              value={morphometry.rupture_risk_label}
              badge={[morphometry.rupture_risk_label, riskVariant(morphometry.rupture_risk_label)]}
            />
          </>
        )}
        {treatment && (
          <Metric
            label="Recomendación"
            value={treatment.recommendation}
            badge={[`Confianza ${treatment.confidence.toLowerCase()}`, "subtle"]}
          />
        )}
      </Card>

      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
        <Input label="Cirujano responsable" value={surgeon} onChange={(e) => setSurgeon(e.target.value)} placeholder="Dr. …" />
        <Input label="Notas clínicas" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Observaciones para el informe…" />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
        <Button leadingIcon={<Icon name="DOC" />} onClick={() => void genPdf()} disabled={busy !== null}>
          {busy === "pdf" ? "Generando…" : "Generar informe PDF"}
        </Button>
        {report?.pdf_url && (
          <a href={report.pdf_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, textAlign: "center" }}>
            Descargar PDF {report.page_count ? `(${report.page_count} páginas)` : ""} →
          </a>
        )}
        <Button variant="outline" leadingIcon={<Icon name="SAVE" />} onClick={() => void genStl()} disabled={busy !== null}>
          {busy === "stl" ? "Exportando…" : "Exportar malla STL"}
        </Button>
        {stl?.stl_url && (
          <a href={stl.stl_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, textAlign: "center" }}>
            Descargar STL →
          </a>
        )}
        <Separator style={{ margin: "6px 0" }} />
        <Button variant="secondary" leadingIcon={<Icon name="SAVE" />} onClick={() => void save()} disabled={busy !== null}>
          {busy === "save" ? "Guardando…" : "Guardar sesión (POST /api/sessions/save)"}
        </Button>
      </div>

      <ErrorNote>{error}</ErrorNote>

      <div style={{ marginTop: 14, textAlign: "center", fontSize: 11, color: "var(--muted-foreground)" }}>
        La sesión se vincula al paciente y estudio en la base de datos.
      </div>
    </div>
  );
}
