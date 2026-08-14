/* Paso 5 — Decisión terapéutica. POST /api/treatment-decision (motor de 8 factores). */

import { useState } from "react";
import { api } from "../../api/client";
import { ANEURYSM_LOCATIONS } from "../../api/types";
import type { AneurysmLocation } from "../../api/types";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Input } from "../Input";
import { PanelHead, SectionLabel, ErrorNote } from "../PanelHead";
import { Select } from "../Select";
import { usePlanning } from "../../store/planning";

function ScoreBar({ label, pct, fill }: { label: string; pct: number; fill: string }) {
  return (
    <div style={{ display: "flex", gap: 6, marginTop: 6, alignItems: "center" }}>
      <span style={{ fontSize: 11, fontWeight: 700, width: 40, color: "var(--brand-subtle-foreground)" }}>{label}</span>
      <div style={{ flex: 1, height: 10, borderRadius: 5, background: "color-mix(in srgb, var(--brand-deep) 20%, transparent)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: fill, transition: "width var(--dur-base) var(--ease-out)" }} />
      </div>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, width: 34, textAlign: "right", color: "var(--brand-subtle-foreground)" }}>
        {pct}%
      </span>
    </div>
  );
}

/** Whole years from an ISO date of birth to today ("" when unknown/invalid). */
function ageFromDob(dob?: string | null): string {
  if (!dob) return "";
  const born = new Date(dob);
  if (Number.isNaN(born.getTime())) return "";
  const today = new Date();
  let years = today.getFullYear() - born.getFullYear();
  const m = today.getMonth() - born.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < born.getDate())) years -= 1;
  return years >= 0 && years <= 120 ? String(years) : "";
}

export function TreatmentPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, treatment, patient } = planning;

  const [location, setLocation] = useState<AneurysmLocation>(ANEURYSM_LOCATIONS[0]);
  const [ruptured, setRuptured] = useState(false);
  // Pre-filled from the patient record — no reason to re-type what we know.
  const [age, setAge] = useState<string>(() => ageFromDob(patient?.dob));
  const [comorbid, setComorbid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.treatmentDecision({
        session_id: sessionId,
        location,
        is_ruptured: ruptured,
        patient_age: age ? Number(age) : null,
        has_comorbidities: comorbid,
      });
      planning.setTreatment(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en la decisión terapéutica");
    } finally {
      setBusy(false);
    }
  };

  const t = treatment;

  return (
    <div className="fade-rise">
      <PanelHead title="Decisión terapéutica" desc="Compara clipaje y tratamiento endovascular ponderando 8 factores." />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <Select
          label="Localización"
          options={ANEURYSM_LOCATIONS}
          value={location}
          onChange={(e) => setLocation(e.target.value as AneurysmLocation)}
        />
        <Select
          label="Estado"
          options={[
            { value: "no", label: "No roto (electivo)" },
            { value: "si", label: "Roto (SAH)" },
          ]}
          value={ruptured ? "si" : "no"}
          onChange={(e) => setRuptured(e.target.value === "si")}
        />
      </div>
      <SectionLabel style={{ marginTop: 14 }}>Contexto clínico</SectionLabel>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, alignItems: "end" }}>
        <Input label="Edad del paciente" type="number" min={0} max={120} placeholder="—" value={age} onChange={(e) => setAge(e.target.value)} />
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--foreground)", height: "var(--control-md)", cursor: "pointer" }}>
          <input type="checkbox" checked={comorbid} onChange={(e) => setComorbid(e.target.checked)} />
          Comorbilidad quirúrgica
        </label>
      </div>
      {/* These two are recorded, not scored — saying so prevents reading the
          recommendation as if it had already accounted for them. */}
      <div style={{ display: "flex", gap: 6, marginTop: 6, fontSize: 11, color: "var(--muted-foreground)", lineHeight: 1.45 }}>
        <Icon name="INFO" size={13} color="var(--muted-foreground)" />
        <span>
          No se ponderan en el cálculo: la evidencia citada (ISAT, AHA/ASA) fija su
          dirección pero no una puntuación. Se registran y aparecen en el informe
          junto a la recomendación.
        </span>
      </div>

      <Button style={{ marginTop: 14, width: "100%" }} variant={t ? "outline" : "default"} onClick={() => void run()} disabled={busy || !sessionId}>
        {busy ? "Evaluando…" : t ? "Re-evaluar" : "Evaluar CLIP vs ENDOVASCULAR"}
      </Button>
      <ErrorNote>{error}</ErrorNote>

      {t && (
        <>
          <div style={{ background: "var(--brand-subtle)", borderRadius: "var(--radius-lg)", padding: "16px 18px", margin: "16px 0" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 15, fontWeight: 800, color: "var(--brand-subtle-foreground)", flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>
                Recomendación: {t.recommendation}
              </span>
              <span style={{ flexShrink: 0, whiteSpace: "nowrap" }}>
                <Badge variant="subtle">Confianza {t.confidence.toLowerCase()}</Badge>
              </span>
            </div>
            <div style={{ marginTop: 12 }}>
              <ScoreBar label="CLIP" pct={t.clip_pct} fill="var(--brand-deep)" />
              <ScoreBar label="ENDO" pct={t.endo_pct} fill="var(--brand-slate)" />
            </div>
          </div>

          <SectionLabel>Factores contribuyentes</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {t.factors.map((f) => (
              <div key={f.name} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: "2px 6px",
                    borderRadius: 5,
                    flexShrink: 0,
                    marginTop: 1,
                    background: f.direction === "neutral" ? "var(--muted)" : "var(--brand-subtle)",
                    color: f.direction === "neutral" ? "var(--muted-foreground)" : "var(--brand-subtle-foreground)",
                  }}
                >
                  {f.direction === "clip" ? "CLIP" : f.direction === "endo" ? "ENDO" : "—"}
                  {f.points > 0 ? ` +${f.points}` : ""}
                </span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--foreground)" }}>{f.name}</div>
                  <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>{f.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <Button style={{ marginTop: 18, width: "100%" }} onClick={onNext} disabled={!t} trailingIcon={<Icon name="CLIPS" />}>
        Planificar dispositivos
      </Button>
    </div>
  );
}
