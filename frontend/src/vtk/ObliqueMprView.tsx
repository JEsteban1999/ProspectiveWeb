/* ObliqueMprView — oblique (tilted) MPR reslice with tilt/position/axis controls.
   The plane is resampled server-side; sliders are debounced so a drag doesn't
   fire one reslice per pixel. */

import { useEffect, useState } from "react";
import { api } from "../api/client";

export function ObliqueMprView({ sessionId, wc, ww }: { sessionId: string; wc?: number; ww?: number }) {
  const [tilt, setTilt] = useState(20);
  const [pos, setPos] = useState(0.5);
  const [axis, setAxis] = useState<"x" | "y">("x");
  const [debounced, setDebounced] = useState({ tilt: 20, pos: 0.5, axis: "x" as "x" | "y" });

  useEffect(() => {
    const t = setTimeout(() => setDebounced({ tilt, pos, axis }), 80);
    return () => clearTimeout(t);
  }, [tilt, pos, axis]);

  const src = api.sliceObliqueUrl(sessionId, debounced.tilt, debounced.pos, debounced.axis, wc, ww);

  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", background: "var(--viewer-bg)" }}>
      <div style={{ flex: 1, position: "relative", display: "flex", alignItems: "center", justifyContent: "center", minHeight: 0 }}>
        <img src={src} alt="oblicuo" draggable={false} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", userSelect: "none" }} />
        <span style={{ position: "absolute", top: 10, left: 12, fontSize: 11, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.85)" }}>
          Oblicuo · {debounced.tilt}° · eje {debounced.axis.toUpperCase()}
        </span>
      </div>

      <div style={{ flexShrink: 0, padding: "10px 16px", display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--border)", background: "var(--background)" }}>
        <Control label={`Inclinación ${tilt}°`}>
          <input type="range" min={-80} max={80} value={tilt} onChange={(e) => setTilt(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--brand-mist)" }} />
        </Control>
        <Control label={`Posición ${(pos * 100).toFixed(0)}%`}>
          <input type="range" min={0} max={1} step={0.01} value={pos} onChange={(e) => setPos(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--brand-mist)" }} />
        </Control>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "var(--muted-foreground)", width: 84 }}>Eje de giro</span>
          {(["x", "y"] as const).map((a) => (
            <button
              key={a}
              onClick={() => setAxis(a)}
              style={{
                padding: "4px 14px", fontSize: 12, borderRadius: "var(--radius-md)", cursor: "pointer",
                border: "1px solid var(--border)",
                background: axis === a ? "var(--brand-subtle)" : "transparent",
                color: axis === a ? "var(--brand-subtle-foreground)" : "var(--muted-foreground)",
                fontWeight: axis === a ? 700 : 500,
              }}
            >
              {a.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Control({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <span style={{ fontSize: 12, color: "var(--muted-foreground)", width: 120, fontFamily: "var(--font-mono)" }}>{label}</span>
      {children}
    </div>
  );
}
