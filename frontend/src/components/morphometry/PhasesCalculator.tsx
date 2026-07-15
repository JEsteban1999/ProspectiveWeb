/* PHASES calculator — 5-year rupture risk (Greving 2014). POST /api/phases.
   The Size factor auto-fills from the morphometric max diameter. */

import { useState } from "react";
import { api } from "../../api/client";
import type { PhasesPopulation, PhasesResult, PhasesSite } from "../../api/types";
import { Button } from "../Button";
import { Input } from "../Input";
import { Select } from "../Select";
import { Metric } from "../Metric";
import { ErrorNote, SectionLabel } from "../PanelHead";

const POPULATIONS: { value: PhasesPopulation; label: string }[] = [
  { value: "other", label: "Otra población" },
  { value: "japan", label: "Japón" },
  { value: "finland", label: "Finlandia" },
];
const SITES: { value: PhasesSite; label: string }[] = [
  { value: "ica", label: "ACI (carótida interna)" },
  { value: "mca", label: "ACM (cerebral media)" },
  { value: "aca_pcom_posterior", label: "ACA / ACoP / Posterior" },
];

const BAND_COLOR: Record<PhasesResult["risk_band"], string> = {
  low: "var(--success)",
  moderate: "var(--warning)",
  high: "var(--destructive)",
};
const BAND_BG: Record<PhasesResult["risk_band"], string> = {
  low: "var(--success-bg)",
  moderate: "var(--warning-bg)",
  high: "color-mix(in srgb, var(--destructive) 12%, transparent)",
};
const BAND_LABEL: Record<PhasesResult["risk_band"], string> = {
  low: "Riesgo bajo", moderate: "Riesgo moderado", high: "Riesgo alto",
};

export function PhasesCalculator({ maxDiameterMm }: { maxDiameterMm: number }) {
  const [population, setPopulation] = useState<PhasesPopulation>("other");
  const [hypertension, setHypertension] = useState(false);
  const [age, setAge] = useState("60");
  const [size, setSize] = useState(maxDiameterMm > 0 ? maxDiameterMm.toFixed(1) : "");
  const [earlierSah, setEarlierSah] = useState(false);
  const [site, setSite] = useState<PhasesSite>("ica");
  const [result, setResult] = useState<PhasesResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const compute = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.phases({
        population,
        hypertension,
        age_years: Number(age) || 0,
        size_mm: Number(size) || 0,
        earlier_sah: earlierSah,
        site,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error calculando PHASES");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 14, lineHeight: 1.5 }}>
        Riesgo de rotura a 5 años (Greving et al., <i>Lancet Neurology</i> 2014). El tamaño se
        auto-rellena desde la morfometría.
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Select label="Población" options={POPULATIONS} value={population} onChange={(e) => setPopulation(e.target.value as PhasesPopulation)} />
        <Select label="Localización" options={SITES} value={site} onChange={(e) => setSite(e.target.value as PhasesSite)} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Edad (años)" type="number" min={0} max={120} value={age} onChange={(e) => setAge(e.target.value)} />
          <Input label="Tamaño (mm)" type="number" step="0.1" value={size} onChange={(e) => setSize(e.target.value)} />
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--foreground)", cursor: "pointer" }}>
          <input type="checkbox" checked={hypertension} onChange={(e) => setHypertension(e.target.checked)} />
          Hipertensión arterial
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--foreground)", cursor: "pointer" }}>
          <input type="checkbox" checked={earlierSah} onChange={(e) => setEarlierSah(e.target.checked)} />
          HSA previa (otro aneurisma)
        </label>
      </div>

      <Button style={{ marginTop: 14, width: "100%" }} onClick={() => void compute()} disabled={busy}>
        {busy ? "Calculando…" : "Calcular PHASES"}
      </Button>
      <ErrorNote>{error}</ErrorNote>

      {result && (
        <>
          <div
            style={{
              marginTop: 16,
              padding: "16px 18px",
              borderRadius: "var(--radius-lg)",
              background: BAND_BG[result.risk_band],
              border: `1px solid ${BAND_COLOR[result.risk_band]}`,
              display: "flex",
              alignItems: "center",
              gap: 16,
            }}
          >
            <div style={{ textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 34, fontWeight: 800, color: BAND_COLOR[result.risk_band], lineHeight: 1 }}>
                {result.total_score}
              </div>
              <div style={{ fontSize: 10, color: "var(--muted-foreground)", marginTop: 2 }}>PHASES</div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: BAND_COLOR[result.risk_band] }}>
                {result.risk_5yr_pct.toFixed(1)}%
              </div>
              <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
                {BAND_LABEL[result.risk_band]} · rotura a 5 años
              </div>
            </div>
          </div>

          <SectionLabel style={{ marginTop: 16 }}>Desglose de factores</SectionLabel>
          <Metric label="Población" value={`+${result.population_pts}`} />
          <Metric label="Hipertensión" value={`+${result.hypertension_pts}`} />
          <Metric label="Edad (≥70)" value={`+${result.age_pts}`} />
          <Metric label="Tamaño" value={`+${result.size_pts}`} />
          <Metric label="HSA previa" value={`+${result.sah_pts}`} />
          <Metric label="Localización" value={`+${result.site_pts}`} />
        </>
      )}
    </div>
  );
}
