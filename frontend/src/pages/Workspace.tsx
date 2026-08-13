/* Sesión de planificación — rail de flujo (7 pasos) · visor 3D + MPR · panel del paso. */

import { useState } from "react";
import { api } from "../api/client";
import type { PatientSummary } from "../api/types";
import { Badge, riskVariant } from "../components/Badge";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import type { IconName } from "../components/Icon";
import { Topbar } from "../components/Topbar";
import { SectionLabel, Card } from "../components/PanelHead";
import { UploadPanel } from "../components/upload/UploadPanel";
import { SegmentPanel } from "../components/segmentation/SegmentPanel";
import { DetectPanel } from "../components/planning/DetectPanel";
import { MorphometryPanel } from "../components/morphometry/MorphometryPanel";
import { PerforatorsPanel } from "../components/perforators/PerforatorsPanel";
import { CenterlinePanel } from "../components/vessels/CenterlinePanel";
import { MeasurementPanel } from "../components/vessels/MeasurementPanel";
import { TreatmentPanel } from "../components/planning/TreatmentPanel";
import { DevicesPanel } from "../components/planning/DevicesPanel";
import { ReportPanel } from "../components/planning/ReportPanel";
import { Viewer, MprStrip } from "../vtk/Viewer";
import { usePlanning } from "../store/planning";

const STEPS: { key: string; icon: IconName; label: string }[] = [
  { key: "upload", icon: "STEP_PATIENT", label: "Carga DICOM" },
  { key: "segment", icon: "STEP_SEGMENT", label: "Segmentación" },
  { key: "detect", icon: "STEP_DETECT", label: "Detección" },
  { key: "morpho", icon: "STEP_MORPHO", label: "Morfometría" },
  { key: "treatment", icon: "STEP_PLAN", label: "Decisión" },
  { key: "devices", icon: "CLIPS", label: "Dispositivos" },
  { key: "report", icon: "STEP_EXPORT", label: "Informe" },
];

export function Workspace({
  patient,
  initialStep = 0,
  onBack,
  onFinish,
}: {
  patient: PatientSummary | null;
  initialStep?: number;
  onBack: () => void;
  onFinish: () => void;
}) {
  const { morphometry, sessionId, caseId, caseLabel, imagingStudyId, setPickMode, setMprSeedMode } = usePlanning();
  const [stepIdx, setStepIdx] = useState(initialStep);
  const [maxStep, setMaxStep] = useState(initialStep);
  const [saving, setSaving] = useState<"idle" | "saving" | "saved">("idle");
  // A failed save used to reset the button to "Guardar progreso" with no notice,
  // so the user believed their work was stored when it was not.
  const [saveError, setSaveError] = useState<string | null>(null);
  const step = STEPS[stepIdx].key;

  const saveProgress = async () => {
    if (!sessionId) return;
    setSaving("saving");
    setSaveError(null);
    try {
      await api.saveSession({
        session_id: sessionId,
        patient_id: patient?.id ?? null,
        // Tie the session to the case and the imaging it analysed, so the
        // gallery can show real progress instead of "Sin procesar".
        study_id: caseId,
        imaging_study_id: imagingStudyId,
        current_step: stepIdx,
        label: patient ? `${patient.full_name} · ${STEPS[stepIdx].label}` : STEPS[stepIdx].label,
      });
      setSaving("saved");
      setTimeout(() => setSaving("idle"), 1800);
    } catch (e) {
      setSaving("idle");
      setSaveError(e instanceof Error ? e.message : "No se pudo guardar el progreso");
    }
  };

  const go = (i: number) => {
    // Cancel any active 3D/MPR pick mode so a tool armed on one step (e.g. the
    // crop-centre picker) doesn't linger — and its banner persist — on the next.
    setPickMode(null);
    setMprSeedMode(false);
    setStepIdx(i);
    setMaxStep((m) => Math.max(m, i));
  };
  const next = () => go(Math.min(stepIdx + 1, STEPS.length - 1));

  const panel = {
    upload: <UploadPanel onNext={next} />,
    segment: <SegmentPanel onNext={next} />,
    detect: <DetectPanel onNext={next} />,
    morpho: (
      <div>
        <MorphometryPanel onNext={next} />
        <div style={{ height: 14 }} />
        <PerforatorsPanel />
        <div style={{ height: 14 }} />
        <CenterlinePanel />
        <div style={{ height: 14 }} />
        <MeasurementPanel />
      </div>
    ),
    treatment: <TreatmentPanel onNext={next} />,
    devices: <DevicesPanel onNext={next} />,
    report: <ReportPanel onFinish={onFinish} />,
  }[step];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar crumb={`Pacientes / ${patient ? patient.full_name : "Sesión"}${caseLabel ? ` / ${caseLabel}` : ""}`}>
        <Button
          variant="outline"
          size="sm"
          onClick={saveProgress}
          disabled={!sessionId || saving === "saving"}
          leadingIcon={<Icon name={saving === "saved" ? "STATUS_OK" : "SAVE"} />}
          style={{ marginRight: 8 }}
        >
          {saving === "saving" ? "Guardando…" : saving === "saved" ? "Guardado ✓" : "Guardar progreso"}
        </Button>
        <Button variant="ghost" size="sm" onClick={onBack} leadingIcon={<Icon name="HOME" />}>
          Pacientes
        </Button>
      </Topbar>

      {saveError && (
        <div
          role="alert"
          onClick={() => setSaveError(null)}
          style={{
            display: "flex", alignItems: "center", gap: 8, cursor: "pointer",
            padding: "8px 18px", fontSize: 12, fontWeight: 600,
            background: "color-mix(in srgb, var(--destructive) 12%, transparent)",
            color: "var(--destructive)",
            borderBottom: "1px solid color-mix(in srgb, var(--destructive) 35%, transparent)",
          }}
        >
          <Icon name="STATUS_WARN" size={14} color="var(--destructive)" />
          <span style={{ flex: 1, minWidth: 0 }}>No se pudo guardar el progreso: {saveError}</span>
          <span style={{ opacity: 0.7 }}>✕</span>
        </div>
      )}

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Rail de flujo — ancho fluido; en pantallas estrechas colapsa a iconos
            y bajo 820px se oculta (ver styles/responsive.css). */}
        <div className="ws-rail" style={{ width: "clamp(176px, 15vw, 232px)", flexShrink: 0, background: "var(--background)", borderRight: "1px solid var(--border)", padding: "18px 12px", overflowY: "auto" }}>
          <SectionLabel className="ws-rail-label" style={{ margin: "0 6px 14px" }}>Flujo de planificación</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {STEPS.map((s, i) => {
              const active = i === stepIdx;
              const done = i < maxStep;
              const locked = i > maxStep;
              return (
                <button
                  key={s.key}
                  disabled={locked}
                  onClick={() => !locked && go(i)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 11,
                    padding: "9px 10px",
                    borderRadius: "var(--radius-md)",
                    border: "none",
                    textAlign: "left",
                    fontFamily: "var(--font-sans)",
                    cursor: locked ? "not-allowed" : "pointer",
                    background: active ? "var(--brand-subtle)" : "transparent",
                    color: active
                      ? "var(--brand-subtle-foreground)"
                      : locked
                        ? "var(--muted-foreground)"
                        : "var(--foreground)",
                    opacity: locked ? 0.5 : 1,
                  }}
                >
                  <span
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: "50%",
                      flexShrink: 0,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 12,
                      fontWeight: 700,
                      background: active ? "var(--brand-deep)" : done ? "var(--success-bg)" : "var(--muted)",
                      color: active ? "#fff" : done ? "var(--success)" : "var(--muted-foreground)",
                    }}
                  >
                    {done ? <Icon name="STATUS_OK" size={13} /> : i + 1}
                  </span>
                  <div className="ws-rail-label" style={{ flex: 1, minWidth: 0 }}>
                    <div className="truncate" style={{ fontSize: 13, fontWeight: active ? 700 : 500 }}>{s.label}</div>
                  </div>
                  <Icon name={s.icon} size={14} color={active ? "var(--brand-subtle-foreground)" : "var(--muted-foreground)"} />
                </button>
              );
            })}
          </div>

          {patient && (
            <Card className="ws-patient-card" style={{ marginTop: 22, padding: "12px 12px" }}>
              <SectionLabel style={{ marginBottom: 6 }}>Paciente</SectionLabel>
              <div className="truncate" style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>{patient.full_name}</div>
              <div className="truncate" style={{ fontSize: 11, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                {patient.hospital_id || "—"} · {patient.sex || "—"}
              </div>
              {morphometry && (
                <div style={{ marginTop: 8 }}>
                  <Badge variant={riskVariant(morphometry.rupture_risk_label)}>{morphometry.rupture_risk_label}</Badge>
                </div>
              )}
            </Card>
          )}
        </div>

        {/* Visor central */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          <Viewer step={step} />
          <MprStrip />
        </div>

        {/* Panel del paso — ancho fluido con mínimo legible */}
        <div style={{ width: "clamp(300px, 27vw, 384px)", flexShrink: 0, background: "var(--background)", borderLeft: "1px solid var(--border)", overflowY: "auto", padding: "20px 18px 40px" }}>
          {panel}
        </div>
      </div>
    </div>
  );
}
