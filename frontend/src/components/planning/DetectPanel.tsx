/* Paso 3 — Detección de candidatos. POST /api/detect/{session}. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { PanelHead, ErrorNote } from "../PanelHead";
import { ProgressBar } from "../ProgressBar";
import { usePlanning } from "../../store/planning";

export function DetectPanel({ onNext }: { onNext: () => void }) {
  const planning = usePlanning();
  const { sessionId, candidates, selectedCandidate } = planning;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ran, setRan] = useState(candidates.length > 0);

  const run = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.detect(sessionId);
      planning.setCandidates(res.candidates);
      planning.setSelectedCandidate(0);
      setRan(true);
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
                <div style={{ height: "100%", width: `${c.confidence * 100}%`, background: "var(--primary)" }} />
              </div>
            </div>
          );
        })}
      </div>

      <ErrorNote>{error}</ErrorNote>

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
