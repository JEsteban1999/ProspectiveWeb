/* Sesión de planificación — rail de flujo (7 pasos) · visor 3D + MPR · panel del paso. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PatientSummary } from "../api/types";
import { Badge, riskVariant } from "../components/Badge";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import type { IconName } from "../components/Icon";
import { Topbar } from "../components/Topbar";
import { SectionLabel, Card, Collapsible } from "../components/PanelHead";
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

const STEPS: { key: string; icon: IconName; label: string; short: string }[] = [
  { key: "upload", icon: "STEP_PATIENT", label: "Carga DICOM", short: "Carga" },
  { key: "segment", icon: "STEP_SEGMENT", label: "Segmentación", short: "Segm." },
  { key: "detect", icon: "STEP_DETECT", label: "Detección", short: "Detec." },
  { key: "morpho", icon: "STEP_MORPHO", label: "Morfometría", short: "Morfo." },
  { key: "treatment", icon: "STEP_PLAN", label: "Decisión", short: "Decis." },
  { key: "devices", icon: "CLIPS", label: "Dispositivos", short: "Disp." },
  { key: "report", icon: "STEP_EXPORT", label: "Informe", short: "Informe" },
];

/** What each step needs before it can say anything true, or null when it's ready.
 *
 *  The rail used to unlock a step just because it had been visited, so a resumed
 *  session whose detection replay failed landed on «Informe» fully unlocked and
 *  produced a PDF with no measurements in it. Gating on the actual results also
 *  turns the disabled state into an instruction instead of a dead end. */
function missingFor(
  i: number,
  p: Pick<ReturnType<typeof usePlanning>, "series" | "segmentation" | "candidates" | "morphometry">,
): string | null {
  switch (i) {
    case 0: return null;
    case 1: return p.series ? null : "Carga una serie DICOM primero";
    case 2: return p.segmentation ? null : "Segmenta el vaso primero";
    case 3: return p.candidates.length > 0 ? null : "Detecta un candidato primero";
    default: return p.morphometry ? null : "Calcula la morfometría primero";
  }
}

export function Workspace({
  patient,
  initialStep = 0,
  onBack,
  onOpenPatient,
  onFinish,
}: {
  patient: PatientSummary | null;
  initialStep?: number;
  onBack: () => void;
  /** Open this patient's sheet — their cases and archived studies. */
  onOpenPatient: () => void;
  onFinish: () => void;
}) {
  const planning = usePlanning();
  const {
    morphometry, sessionId, caseId, caseLabel, imagingStudyId,
    centerlineMesh, measurements, setPickMode, setMprSeedMode, markSaved,
  } = planning;
  const [stepIdx, setStepIdx] = useState(initialStep);
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
      markSaved();
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
  };
  const next = () => go(Math.min(stepIdx + 1, STEPS.length - 1));

  // Teclado: Escape cancela el modo de marcado activo (antes había que volver al
  // panel y pulsar el mismo botón otra vez, con el banner ocupando el visor), y
  // 1–7 saltan de paso. Se ignora mientras se escribe en un campo.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      if (e.key === "Escape") {
        setPickMode(null);
        setMprSeedMode(false);
        return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= STEPS.length) {
        const i = n - 1;
        if (i === stepIdx || !missingFor(i, planning)) { e.preventDefault(); go(i); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepIdx, planning.series, planning.segmentation, planning.candidates, planning.morphometry]);

  const panel = {
    upload: <UploadPanel onNext={next} />,
    segment: <SegmentPanel onNext={next} />,
    detect: <DetectPanel onNext={next} />,
    morpho: (
      // Morfometría queda siempre a la vista; las tres herramientas auxiliares
      // se pliegan y recuerdan su estado, para que la columna no pase de mil
      // píxeles de scroll con la línea central enterrada al fondo.
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <MorphometryPanel onNext={next} />
        <Collapsible title="Perforantes" subtitle="Proximidad al cuello del aneurisma" storageKey="ws.morpho.perforators">
          <PerforatorsPanel />
        </Collapsible>
        <Collapsible
          title="Línea central del vaso"
          subtitle="Longitud, tortuosidad y calibre · base del stent guiado"
          storageKey="ws.morpho.centerline"
          badge={centerlineMesh ? <Badge variant="success">Extraída</Badge> : undefined}
        >
          <CenterlinePanel />
        </Collapsible>
        <Collapsible
          title="Mediciones 3D"
          subtitle="Distancia entre dos puntos del modelo"
          storageKey="ws.morpho.measurements"
          badge={measurements.length > 0 ? <Badge variant="subtle">{measurements.length}</Badge> : undefined}
        >
          <MeasurementPanel />
        </Collapsible>
      </div>
    ),
    treatment: <TreatmentPanel onNext={next} />,
    devices: <DevicesPanel onNext={next} />,
    report: <ReportPanel onFinish={onFinish} />,
  }[step];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar
        crumbs={[
          { label: "Pacientes", onClick: onBack },
          // The patient and the case both lead back to the patient sheet, which
          // is where their cases and archived studies live. Before this the only
          // way out was the button on the right, which drops you in the full
          // list having forgotten which case you were planning.
          { label: patient ? patient.full_name : "Sesión", onClick: patient ? onOpenPatient : undefined },
          ...(caseLabel ? [{ label: caseLabel, onClick: patient ? onOpenPatient : undefined }] : []),
        ]}
      >
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

      {/* Barra de pasos compacta — sustituye al rail cuando este se oculta bajo
          820 px. Antes simplemente desaparecía y no quedaba ninguna forma de
          cambiar de paso: el usuario se quedaba encerrado donde estuviera. */}
      <div
        className="ws-steps-compact"
        role="tablist"
        aria-label="Flujo de planificación"
        style={{
          display: "none", gap: 4, padding: "8px 12px", overflowX: "auto",
          background: "var(--background)", borderBottom: "1px solid var(--border)",
        }}
      >
        {STEPS.map((s, i) => {
          const active = i === stepIdx;
          const missing = missingFor(i, planning);
          const locked = !active && !!missing;
          return (
            <button
              key={s.key}
              role="tab"
              aria-selected={active}
              disabled={locked}
              title={missing ?? s.label}
              onClick={() => !locked && go(i)}
              style={{
                display: "flex", alignItems: "center", gap: 6, flexShrink: 0,
                padding: "6px 11px", borderRadius: "var(--radius-full)",
                border: "1px solid " + (active ? "transparent" : "var(--border)"),
                background: active ? "var(--brand-deep)" : "var(--card)",
                color: active ? "#fff" : locked ? "var(--muted-foreground)" : "var(--foreground)",
                cursor: locked ? "not-allowed" : "pointer",
                opacity: locked ? 0.5 : 1,
                fontFamily: "var(--font-sans)", fontSize: 12,
                fontWeight: active ? 700 : 500, whiteSpace: "nowrap",
              }}
            >
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, opacity: .8 }}>{i + 1}</span>
              {s.short}
            </button>
          );
        })}
      </div>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Rail de flujo — ancho fluido; en pantallas estrechas colapsa a iconos
            y bajo 820px se oculta (ver styles/responsive.css). */}
        <div className="ws-rail" style={{ width: "clamp(176px, 15vw, 232px)", flexShrink: 0, background: "var(--background)", borderRight: "1px solid var(--border)", padding: "18px 12px", overflowY: "auto" }}>
          <div title="Atajos: 1–7 para cambiar de paso · Esc cancela el marcado">
            <SectionLabel className="ws-rail-label" style={{ margin: "0 6px 14px" }}>
              Flujo de planificación
            </SectionLabel>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {STEPS.map((s, i) => {
              const active = i === stepIdx;
              const missing = missingFor(i, planning);
              const done = !missing && i < stepIdx;
              // Never lock the step the user is standing on — that would strand a
              // resumed session whose replay came back empty.
              const locked = !active && !!missing;
              return (
                <button
                  key={s.key}
                  disabled={locked}
                  title={missing ?? s.label}
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
