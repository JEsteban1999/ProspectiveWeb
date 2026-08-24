/* Paso 3 — Detección de candidatos. POST /api/detect/{session}. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { PanelHead, ErrorNote } from "../PanelHead";
import { ProgressBar } from "../ProgressBar";
import { usePlanning } from "../../store/planning";
import type { DetectionDiagnostics } from "../../api/types";

/** Turn the rejection counts into the one sentence that matters.
 *
 *  Measured over the corpus, the size gate accounts for 61-94% of rejections,
 *  and its share grows with how complete the mesh is: on a whole vascular tree
 *  the high-curvature patches merge across several vessels, so their equivalent
 *  radius exceeds the bound and every one of them is discarded. That is why
 *  cropping the region of interest before detecting works so well. */
function explainEmpty(d: DetectionDiagnostics): { reason: string; advice: string } {
  if (d.regions_analyzed === 0) {
    return {
      reason: "La malla no tiene regiones de curvatura suficientes para analizar.",
      advice: "Suele indicar una malla demasiado escasa: baja la limpieza o segmenta a resolución completa.",
    };
  }
  const gates: [number, string, string][] = [
    [d.rejected_size,
     `su tamaño quedó fuera del rango de ${d.min_radius_mm}–${d.max_radius_mm} mm`,
     "En una malla completa los parches de curvatura se fusionan entre vasos y superan el radio máximo. Recorta la región de interés alrededor del aneurisma y vuelve a detectar."],
    [d.rejected_mean_curvature,
     "su curvatura media no llegó al mínimo",
     "La superficie es demasiado plana ahí: revisa el umbral de segmentación, puede estar capturando hueso o tejido."],
    [d.rejected_positive_gauss,
     "no tenían bastante superficie convexa",
     "Son salientes alargados más que domos. Un recorte alrededor de la zona sospechosa ayuda."],
    [d.rejected_compactness,
     "su forma era demasiado irregular",
     "Suele venir de una malla ruidosa: sube un punto la limpieza o suaviza algo más."],
    [d.rejected_too_few_points,
     "eran demasiado pequeñas",
     "Prueba a segmentar a resolución completa para que los domes finos tengan más superficie."],
    [d.rejected_sphericity, "no eran bastante esféricas",
     "Recorta la región de interés y repite la detección."],
  ];
  gates.sort((a, b) => b[0] - a[0]);
  const [n, why, advice] = gates[0]!;
  const pct = Math.round((100 * n) / Math.max(d.regions_analyzed, 1));
  return {
    reason: `Se analizaron ${d.regions_analyzed.toLocaleString("es")} regiones de alta curvatura y ninguna pasó los filtros de forma. El motivo dominante: ${n.toLocaleString("es")} (${pct} %) se descartaron porque ${why}.`,
    advice,
  };
}

export function DetectPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, candidates, selectedCandidate } = planning;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ran, setRan] = useState(candidates.length > 0);
  const [diag, setDiag] = useState<DetectionDiagnostics | null>(null);

  const run = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.detect(sessionId);
      planning.setCandidates(res.candidates);
      planning.setSelectedCandidate(0);
      setRan(true);
      setDiag(res.diagnostics ?? null);
      if (!res.found) setError("No se encontraron candidatos aneurismáticos en la malla.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en la detección");
    } finally {
      setBusy(false);
    }
  };

  // Run automatically the first time the step opens.
  useEffect(() => {
    if (!ran && sessionId && !busy) void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fade-rise">
      <PanelHead
        title="Candidatos detectados"
        desc="Localiza candidatos aneurismáticos por curvatura de la superficie."
        right={ran && <Badge variant="subtle">{candidates.length} encontrados</Badge>}
      />

      {busy && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 6 }}>
            Analizando curvatura de la malla…
          </div>
          <ProgressBar />
        </div>
      )}

      {ran && candidates.length > 1 && (
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginBottom: 10 }}>
          Ordenados por relevancia. El <b>principal</b> es el más probable; revise con criterio clínico los de <b>baja confianza</b> (posibles falsos positivos).
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {candidates.map((c, i) => {
          const on = selectedCandidate === i;
          return (
            <div
              key={c.id}
              onClick={() => planning.setSelectedCandidate(i)}
              style={{
                cursor: "pointer",
                border: `1px solid ${on ? "var(--primary)" : "var(--border)"}`,
                background: on ? "var(--brand-subtle)" : "var(--card)",
                borderRadius: "var(--radius-lg)",
                padding: "12px 14px",
                transition: "all var(--dur-fast) var(--ease-out)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--muted-foreground)" }}>{c.id}</span>
                {i === 0 && <Badge variant="success">Principal</Badge>}
                {c.confidence < 0.5 && <Badge variant="warning">Baja confianza</Badge>}
                <div style={{ flex: 1 }} />
                {on && <Icon name="STATUS_OK" size={15} color="var(--brand-deep)" />}
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
                <span style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
                  Ø{" "}
                  <b style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}>
                    {c.max_diameter_mm.toFixed(1)} mm
                  </b>
                </span>
                <span style={{ fontSize: 12, color: "var(--muted-foreground)", flex: 1 }}>Confianza</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--foreground)" }}>
                  {(c.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div style={{ height: 4, borderRadius: 2, background: "var(--muted)", marginTop: 6, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${c.confidence * 100}%`, background: c.confidence < 0.5 ? "var(--warning)" : "var(--primary)" }} />
              </div>
            </div>
          );
        })}
      </div>

      <ErrorNote>{error}</ErrorNote>

      {/* An empty result is a finding, not a failure — but only if it says why. */}
      {ran && !busy && candidates.length === 0 && diag && (() => {
        const { reason, advice } = explainEmpty(diag);
        return (
          <div style={{
            marginTop: 10, padding: "12px 14px", borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)", background: "var(--card)",
            fontSize: 12, lineHeight: 1.55, color: "var(--muted-foreground)",
          }}>
            <div style={{ fontWeight: 700, color: "var(--foreground)", marginBottom: 4 }}>
              Por qué no se encontró nada
            </div>
            <div>{reason}</div>
            <div style={{ marginTop: 6, color: "var(--foreground)" }}>{advice}</div>
            {diag.removed_components > 0 && (
              <div style={{ marginTop: 6 }}>
                Antes de analizar se descartaron {diag.removed_components.toLocaleString("es")} fragmentos
                sueltos de la malla.
              </div>
            )}
          </div>
        );
      })()}

      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <Button variant="outline" onClick={() => void run()} disabled={busy || !sessionId} leadingIcon={<Icon name="REFRESH" />}>
          Re-detectar
        </Button>
        <Button
          style={{ flex: 1 }}
          onClick={onNext}
          disabled={candidates.length === 0}
          trailingIcon={<Icon name="STEP_MORPHO" />}
        >
          Analizar morfometría
        </Button>
      </div>
    </div>
  );
}
