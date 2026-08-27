/* Perforantes — GET /api/perforators/{session}. Card auxiliar bajo morfometría.

   La lista daba distancias («prf-003 · 4,2 mm · Medio») sin nada que dijera A
   QUÉ vaso se refería cada fila. Ahora cada perforante se puede mostrar en la
   escena 3D con su color de gravedad, pulsando su fila.

   Ninguna se muestra de entrada: hasta doce marcadores apareciendo sin pedirlos
   alrededor del cuello tapan justo la geometría sobre la que se apoyan. El
   usuario enciende las que quiere mirar y las apaga al terminar. */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { PerforatorsResult } from "../../api/types";
import { Icon } from "../Icon";
import { SectionLabel, Card } from "../PanelHead";
import { usePlanning } from "../../store/planning";

export function PerforatorsPanel() {
  const { sessionId, setPerforators, visiblePerforators, togglePerforator, setVisiblePerforators } = usePlanning();
  const [result, setResult] = useState<PerforatorsResult | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    api.perforators(sessionId)
      .then((r) => {
        if (!alive) return;
        setResult(r);
        // Publish to the store so the 3D viewer can mark them.
        const z = r.zone_radii_mm;
        setPerforators(
          r.candidates,
          z && z.length === 3 ? [z[0], z[1], z[2]] : null,
        );
      })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [sessionId, setPerforators]);

  // Leaving the panel must not leave stale markers in a scene the user is now
  // using for something else.
  useEffect(() => () => setVisiblePerforators([]), [setVisiblePerforators]);

  const zones = result?.zone_radii_mm;
  const all = result?.candidates ?? [];
  const allShown = all.length > 0 && visiblePerforators.length === all.length;

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon name="MARK_PERF" size={15} color="var(--muted-foreground)" />
        <SectionLabel style={{ marginBottom: 0 }}>
          Perforantes {result ? `(radio ${result.search_radius_mm.toFixed(0)} mm)` : ""}
        </SectionLabel>
        {/* Encender doce marcadores de uno en uno para comparar, y apagarlos
            luego, es el gesto que más se repite en cuanto hay más de dos. */}
        {all.length > 1 && (
          <button
            type="button"
            onClick={() => setVisiblePerforators(allShown ? [] : all.map((c) => c.id))}
            style={{
              marginLeft: "auto", padding: "3px 8px", fontSize: 10, fontWeight: 700,
              borderRadius: "var(--radius-sm)", border: "1px solid var(--border)",
              background: "transparent", color: "var(--muted-foreground)",
              cursor: "pointer", fontFamily: "var(--font-sans)", whiteSpace: "nowrap",
            }}
          >
            {allShown ? "Ocultar todas" : "Mostrar todas"}
          </button>
        )}
      </div>
      {result && result.candidates.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 4 }}>
          Distancia al cuello del aneurisma y riesgo por proximidad. El calibre del vaso no se mide.
          {zones && zones.length === 3 && (
            <> Zonas: alto &lt;{zones[0]} mm · medio {zones[0]}–{zones[1]} mm · bajo {zones[1]}–{zones[2]} mm.</>
          )}
          <br />
          Pulsa una fila para mostrarla u ocultarla en el visor 3D.
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
        {result?.candidates.map((p) => {
          const active = visiblePerforators.includes(p.id);
          return (
            <button
              key={p.id}
              type="button"
              aria-pressed={active}
              title={
                active
                  ? `Ocultar ${p.id} en el visor 3D`
                  : `Mostrar ${p.id} en el visor 3D (${p.distance_to_neck_mm.toFixed(1)} mm del cuello)`
              }
              onClick={() => togglePerforator(p.id)}
              style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                padding: "7px 8px", margin: 0, textAlign: "left", cursor: "pointer",
                borderRadius: "var(--radius-sm)",
                border: "1px solid transparent",
                borderBottom: "1px solid var(--border)",
                borderColor: active ? p.risk_color : undefined,
                background: active ? "color-mix(in srgb, var(--foreground) 7%, transparent)" : "transparent",
                fontFamily: "var(--font-sans)",
              }}
            >
              <span
                style={{
                  width: active ? 13 : 9, height: active ? 13 : 9, borderRadius: "50%",
                  background: p.risk_color, flexShrink: 0,
                  boxShadow: active ? `0 0 0 3px color-mix(in srgb, ${p.risk_color} 30%, transparent)` : undefined,
                }}
              />
              <span style={{ fontSize: 12, color: "var(--foreground)", flex: 1, fontWeight: active ? 700 : 400 }}>
                {p.id}
              </span>
              <span
                style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--muted-foreground)" }}
                title="Distancia al cuello del aneurisma"
              >
                {p.distance_to_neck_mm.toFixed(1)} mm
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: p.risk_color }}>{p.risk_label}</span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
