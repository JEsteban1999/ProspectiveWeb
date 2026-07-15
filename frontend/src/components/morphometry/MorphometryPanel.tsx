/* Paso 4 — Morfometría. GET /api/morphometry/{session} + seguimiento longitudinal. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { LongitudinalResult } from "../../api/types";
import { Badge, riskVariant } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Metric } from "../Metric";
import { PanelHead, ErrorNote } from "../PanelHead";
import { ProgressBar } from "../ProgressBar";
import { Tabs } from "../Tabs";
import { PhasesCalculator } from "./PhasesCalculator";
import { usePlanning } from "../../store/planning";

const TABS = ["Métricas", "Índices", "PHASES", "Seguimiento"] as const;

export function MorphometryPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, morphometry } = planning;
  const [tab, setTab] = useState<string>("Métricas");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [longi, setLongi] = useState<LongitudinalResult | null>(null);

  useEffect(() => {
    if (morphometry || !sessionId) return;
    setBusy(true);
    api
      .morphometry(sessionId)
      .then((m) => planning.setMorphometry(m))
      .catch((e) => setError(e instanceof Error ? e.message : "Error en morfometría"))
      .finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (tab === "Seguimiento" && sessionId && !longi) {
      api.longitudinal(sessionId).then(setLongi).catch(() => setLongi(null));
    }
  }, [tab, sessionId, longi]);

  const m = morphometry;

  return (
    <div className="fade-rise">
      <PanelHead
        title="Morfometría"
        desc="GET /api/morphometry/{session} — todas las medidas en mm"
        right={m && <Badge variant={riskVariant(m.rupture_risk_label)}>Riesgo {m.rupture_risk_label}</Badge>}
      />

      {busy && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 6 }}>
            Calculando cuello, domo e índices…
          </div>
          <ProgressBar />
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>

      {m && (
        <>
          {!m.neck_valid && m.warning && (
            <div style={{ background: "var(--warning-bg)", border: "1px solid color-mix(in srgb, var(--warning) 40%, transparent)", borderRadius: "var(--radius-lg)", padding: "12px 14px", marginBottom: 12, display: "flex", gap: 10 }}>
              <Icon name="STATUS_WARN" color="var(--warning)" size={18} />
              <div style={{ fontSize: 12, color: "var(--warning)" }}>{m.warning}</div>
            </div>
          )}

          <Tabs tabs={TABS} value={tab} onChange={setTab} />
          <div style={{ marginTop: 12 }}>
            {tab === "Métricas" && (
              <div>
                <Metric label="Ø máximo" value={m.max_diameter_mm.toFixed(1)} unit=" mm" />
                <Metric label="Cuello" value={m.neck_mm.toFixed(1)} unit=" mm" />
                <Metric label="Altura de domo" value={m.dome_height_mm.toFixed(1)} unit=" mm" />
                <Metric label="Volumen" value={m.volume_mm3.toFixed(1)} unit=" mm³" />
                <Metric label="Área superficie" value={m.surface_area_mm2.toFixed(1)} unit=" mm²" />
                <Metric
                  label="DNR"
                  value={m.dnr.toFixed(2)}
                  badge={m.dnr > 2.0 ? ["Alto", "destructive"] : m.dnr > 1.5 ? ["Mod", "warning"] : ["OK", "success"]}
                />
                <Metric
                  label="AR"
                  value={m.ar.toFixed(2)}
                  badge={m.ar > 1.6 ? ["Alto", "destructive"] : m.ar > 1.2 ? ["Mod", "warning"] : ["OK", "success"]}
                />
                <Metric
                  label="BF"
                  value={m.bf.toFixed(2)}
                  badge={m.bf > 1.5 ? ["Cuello ancho", "warning"] : ["OK", "success"]}
                />
              </div>
            )}
            {tab === "Índices" && (
              <div>
                <Metric label="UI · Undulación" value={m.ui.toFixed(2)} badge={m.ui > 0.15 ? ["Irregular", "warning"] : ["Bajo", "success"]} />
                <Metric label="EI · Elipticidad" value={m.ei.toFixed(2)} badge={m.ei > 0.35 ? ["Alto", "warning"] : ["Bajo", "success"]} />
                <Metric label="NSI · No-esfericidad" value={m.nsi.toFixed(2)} />
                <Metric
                  label="SR · Size Ratio"
                  value={m.sr > 0 ? m.sr.toFixed(2) : "—"}
                  badge={m.sr > 3.0 ? ["Alto", "destructive"] : undefined}
                />
                <Metric label="Compacidad (Wadell)" value={m.compactness.toFixed(2)} />
                <Metric label="Ø esfera equivalente" value={m.eq_sphere_diam_mm.toFixed(1)} unit=" mm" />
              </div>
            )}
            {tab === "PHASES" && <PhasesCalculator maxDiameterMm={m.max_diameter_mm} />}
            {tab === "Seguimiento" && (
              <div>
                {longi?.growth_alert && (
                  <div style={{ background: "var(--warning-bg)", border: "1px solid color-mix(in srgb, var(--warning) 40%, transparent)", borderRadius: "var(--radius-lg)", padding: "12px 14px", marginBottom: 12, display: "flex", gap: 10 }}>
                    <Icon name="GROWTH" color="var(--warning)" size={18} />
                    <div style={{ fontSize: 12, color: "var(--warning)" }}>
                      <b>Alerta de crecimiento:</b> {longi.growth_alert_message}
                    </div>
                  </div>
                )}
                {longi && longi.entries.length > 0 ? (
                  longi.entries.map((e) => (
                    <Metric
                      key={e.session_date + e.session_label}
                      label={e.session_date}
                      value={`${e.max_diameter_mm.toFixed(1)} mm · AR ${e.ar.toFixed(2)}`}
                      badge={[e.rupture_risk_label, riskVariant(e.rupture_risk_label)]}
                    />
                  ))
                ) : (
                  <div style={{ fontSize: 12, color: "var(--muted-foreground)", padding: "14px 0" }}>
                    Sin sesiones previas guardadas para este paciente. Guarda esta sesión al finalizar
                    para iniciar el seguimiento longitudinal.
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}

      <Button
        style={{ marginTop: 18, width: "100%" }}
        onClick={onNext}
        disabled={!m}
        trailingIcon={<Icon name="STEP_PLAN" />}
      >
        Decisión terapéutica
      </Button>
    </div>
  );
}
