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
import { LongitudinalChart } from "./LongitudinalChart";
import { usePlanning } from "../../store/planning";

const TABS = ["Métricas", "Índices", "PHASES", "Seguimiento"] as const;

export function MorphometryPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const {
    sessionId, morphometry,
    pickMode, setPickMode, neckOrigin, neckDome, setNeckOrigin, setNeckDome,
  } = planning;
  const [tab, setTab] = useState<string>("Métricas");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [longi, setLongi] = useState<LongitudinalResult | null>(null);
  const [neckBusy, setNeckBusy] = useState(false);

  async function recomputeWithNeckPlane() {
    if (!sessionId || !neckOrigin || !neckDome) return;
    const normal: [number, number, number] = [
      neckDome[0] - neckOrigin[0],
      neckDome[1] - neckOrigin[1],
      neckDome[2] - neckOrigin[2],
    ];
    setNeckBusy(true);
    setError(null);
    try {
      const m = await api.morphometryNeckPlane(sessionId, {
        origin: { x: neckOrigin[0], y: neckOrigin[1], z: neckOrigin[2] },
        normal,
        dome_seed: { x: neckDome[0], y: neckDome[1], z: neckDome[2] },
      });
      planning.setMorphometry(m);
      setNeckOrigin(null);
      setNeckDome(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al medir con el plano de cuello");
    } finally {
      setNeckBusy(false);
    }
  }

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
        desc="Medidas e índices del aneurisma. Todas las dimensiones en milímetros."
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

          {/* Semi-automatic neck plane — shown when the automatic analysis ran on
              an open detector cap (unreliable), or to refine a manual result. */}
          {(!m.reliable || m.neck_source === "manual") && (
            <div style={{ background: "var(--muted, rgba(120,130,140,0.08))", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "12px 14px", marginBottom: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <Icon name="STEP_PLAN" size={15} color="var(--muted-foreground)" />
                <div style={{ fontSize: 12, fontWeight: 600 }}>
                  Plano de cuello {m.neck_source === "manual" && <Badge variant="success">manual</Badge>}
                </div>
              </div>
              <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginBottom: 10 }}>
                {m.reliable
                  ? "Cuello definido manualmente. Recolócalo si es necesario."
                  : "La detección automática aísla una superficie abierta y no mide un cuello válido. Marca el cuello y el ápice del domo sobre el modelo 3D para medir sobre un saco cerrado."}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Button
                  variant={neckOrigin ? "secondary" : "default"}
                  onClick={() => setPickMode("neck_origin")}
                  disabled={pickMode === "neck_origin"}
                  leadingIcon={<Icon name={neckOrigin ? "STATUS_OK" : "TARGET"} size={14} />}
                >
                  {neckOrigin ? "Cuello ✓" : "Marcar cuello"}
                </Button>
                <Button
                  variant={neckDome ? "secondary" : "default"}
                  onClick={() => setPickMode("neck_dome")}
                  disabled={pickMode === "neck_dome"}
                  leadingIcon={<Icon name={neckDome ? "STATUS_OK" : "TARGET"} size={14} />}
                >
                  {neckDome ? "Ápice ✓" : "Marcar ápice del domo"}
                </Button>
                <Button
                  onClick={recomputeWithNeckPlane}
                  disabled={!neckOrigin || !neckDome || neckBusy}
                >
                  {neckBusy ? "Midiendo…" : "Medir saco cerrado"}
                </Button>
              </div>
              {neckBusy && <div style={{ marginTop: 8 }}><ProgressBar /></div>}
            </div>
          )}

          {m.centroid && m.principal_axis && (
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--foreground)", cursor: "pointer", margin: "4px 0 12px", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: planning.morphoOverlay ? "var(--brand-subtle)" : "transparent" }}>
              <input type="checkbox" checked={planning.morphoOverlay} onChange={(e) => planning.setMorphoOverlay(e.target.checked)} />
              Mostrar anotaciones 3D (cuello, altura de domo, Ø máximo) en el visor
            </label>
          )}

          <Tabs tabs={TABS} value={tab} onChange={setTab} />
          <div style={{ marginTop: 12 }}>
            {tab === "Métricas" && (
              <div>
                <Metric label="Ø máximo" value={m.max_diameter_mm.toFixed(1)} unit=" mm" />
                <Metric label="Cuello" value={m.reliable ? m.neck_mm.toFixed(1) : "—"} unit={m.reliable ? " mm" : ""} />
                <Metric label="Altura de domo" value={m.reliable ? m.dome_height_mm.toFixed(1) : "—"} unit={m.reliable ? " mm" : ""} />
                <Metric label="Volumen" value={m.reliable ? m.volume_mm3.toFixed(1) : "—"} unit={m.reliable ? " mm³" : ""} />
                <Metric label="Área superficie" value={m.surface_area_mm2.toFixed(1)} unit=" mm²" />
                <Metric
                  label="DNR"
                  value={m.reliable ? m.dnr.toFixed(2) : "—"}
                  badge={!m.reliable ? ["sin medir", "outline"] : m.dnr > 2.0 ? ["Alto", "destructive"] : m.dnr > 1.5 ? ["Mod", "warning"] : ["OK", "success"]}
                />
                <Metric
                  label="AR"
                  value={m.reliable ? m.ar.toFixed(2) : "—"}
                  badge={!m.reliable ? ["sin medir", "outline"] : m.ar > 1.6 ? ["Alto", "destructive"] : m.ar > 1.2 ? ["Mod", "warning"] : ["OK", "success"]}
                />
                <Metric
                  label="BF"
                  value={m.reliable ? m.bf.toFixed(2) : "—"}
                  badge={!m.reliable ? ["sin medir", "outline"] : m.bf > 1.5 ? ["Cuello ancho", "warning"] : ["OK", "success"]}
                />
              </div>
            )}
            {tab === "Índices" && (
              <div>
                <Metric label="UI · Undulación" value={m.reliable ? m.ui.toFixed(2) : "—"} badge={!m.reliable ? ["sin medir", "outline"] : m.ui > 0.15 ? ["Irregular", "warning"] : ["Bajo", "success"]} />
                <Metric label="EI · Elipticidad" value={m.reliable ? m.ei.toFixed(2) : "—"} badge={!m.reliable ? ["sin medir", "outline"] : m.ei > 0.35 ? ["Alto", "warning"] : ["Bajo", "success"]} />
                <Metric label="NSI · No-esfericidad" value={m.reliable ? m.nsi.toFixed(2) : "—"} />
                <Metric
                  label="SR · Size Ratio"
                  value={m.sr > 0 ? m.sr.toFixed(2) : "—"}
                  badge={m.sr > 3.0 ? ["Alto", "destructive"] : undefined}
                />
                <Metric label="Compacidad (Wadell)" value={m.compactness.toFixed(2)} />
                <Metric label="Ø esfera equivalente" value={m.eq_sphere_diam_mm.toFixed(1)} unit=" mm" />
              </div>
            )}
            {tab === "PHASES" && (
              <PhasesCalculator maxDiameterMm={m.max_diameter_mm} sessionId={sessionId} />
            )}
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
                {longi && longi.entries.length >= 2 && <LongitudinalChart entries={longi.entries} />}
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
