/* Perforantes — GET /api/perforators/{session}. Card auxiliar bajo morfometría. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { PerforatorsResult } from "../../api/types";
import { Icon } from "../Icon";
import { SectionLabel, Card } from "../PanelHead";
import { usePlanning } from "../../store/planning";

export function PerforatorsPanel() {
  const { sessionId } = usePlanning();
  const [result, setResult] = useState<PerforatorsResult | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    api.perforators(sessionId).then(setResult).catch(() => setError(true));
  }, [sessionId]);

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon name="MARK_PERF" size={15} color="var(--muted-foreground)" />
        <SectionLabel style={{ marginBottom: 0 }}>
          Perforantes {result ? `(radio ${result.search_radius_mm.toFixed(0)} mm)` : ""}
        </SectionLabel>
      </div>
      {result && result.candidates.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 4 }}>
          Distancia al cuello del aneurisma y riesgo por proximidad. El calibre del vaso no se mide.
        </div>
      )}
      <div style={{ marginTop: 10 }}>
        {error && (
          <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
            No disponible — ejecuta primero la detección y morfometría.
          </div>
        )}
        {result && result.candidates.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
            Sin perforantes detectadas cerca del cuello.
          </div>
        )}
        {result?.candidates.map((p) => (
          <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderBottom: "1px solid var(--border)" }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: p.risk_color, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: "var(--foreground)", flex: 1 }}>
              {p.id}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--muted-foreground)" }} title="Distancia al cuello del aneurisma">
              {p.distance_to_neck_mm.toFixed(1)} mm
            </span>
            <span style={{ fontSize: 11, fontWeight: 700, color: p.risk_color }}>{p.risk_label}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
