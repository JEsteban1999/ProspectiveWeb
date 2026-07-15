/* Sesión de planificación — rail de flujo (7 pasos) · visor 3D + MPR · panel del paso. */

import { useState } from "react";
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
  onBack,
  onFinish,
}: {
  patient: PatientSummary | null;
  onBack: () => void;
  onFinish: () => void;
}) {
  const { morphometry } = usePlanning();
  const [stepIdx, setStepIdx] = useState(0);
  const [maxStep, setMaxStep] = useState(0);
  const step = STEPS[stepIdx].key;

  const go = (i: number) => {
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
      </div>
    ),
    treatment: <TreatmentPanel onNext={next} />,
    devices: <DevicesPanel onNext={next} />,
    report: <ReportPanel onFinish={onFinish} />,
  }[step];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar crumb={`Pacientes / ${patient ? patient.full_name : "Sesión"}`}>
        <Button variant="ghost" size="sm" onClick={onBack} leadingIcon={<Icon name="HOME" />}>
          Pacientes
        </Button>
      </Topbar>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Rail de flujo */}
        <div style={{ width: 232, flexShrink: 0, background: "var(--background)", borderRight: "1px solid var(--border)", padding: "18px 14px", overflowY: "auto" }}>
          <SectionLabel style={{ margin: "0 6px 14px" }}>Flujo de planificación</SectionLabel>
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
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: active ? 700 : 500 }}>{s.label}</div>
                  </div>
                  <Icon name={s.icon} size={14} color={active ? "var(--brand-subtle-foreground)" : "var(--muted-foreground)"} />
                </button>
              );
            })}
          </div>

          {patient && (
            <Card style={{ marginTop: 22, padding: "12px 12px" }}>
              <SectionLabel style={{ marginBottom: 6 }}>Paciente</SectionLabel>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>{patient.full_name}</div>
              <div style={{ fontSize: 11, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
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

        {/* Panel del paso */}
        <div style={{ width: 384, flexShrink: 0, background: "var(--background)", borderLeft: "1px solid var(--border)", overflowY: "auto", padding: "20px 20px 40px" }}>
          {panel}
        </div>
      </div>
    </div>
  );
}
