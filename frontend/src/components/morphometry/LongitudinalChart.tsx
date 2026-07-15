/* LongitudinalChart — max-diameter trend across follow-up sessions (SVG). */

import type { LongitudinalEntry } from "../../api/types";

export function LongitudinalChart({ entries }: { entries: LongitudinalEntry[] }) {
  if (entries.length < 2) return null;

  const W = 320, H = 130;
  const P = { t: 12, r: 12, b: 22, l: 30 };
  const iw = W - P.l - P.r, ih = H - P.t - P.b;

  const vals = entries.map((e) => e.max_diameter_mm);
  const yLo = Math.max(0, Math.min(...vals) - 1);
  const yHi = Math.max(...vals) + 1;
  const sx = (i: number) => P.l + (i / (entries.length - 1)) * iw;
  const sy = (v: number) => P.t + (1 - (v - yLo) / (yHi - yLo || 1)) * ih;
  const path = entries.map((e, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(1)},${sy(e.max_diameter_mm).toFixed(1)}`).join(" ");

  const grew = vals[vals.length - 1] > vals[0];
  const lineColor = grew ? "var(--warning)" : "var(--success)";

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block", marginBottom: 12 }} role="img" aria-label="Tendencia de diámetro máximo">
      <line x1={P.l} y1={P.t} x2={P.l} y2={P.t + ih} stroke="var(--border)" />
      <line x1={P.l} y1={P.t + ih} x2={P.l + iw} y2={P.t + ih} stroke="var(--border)" />
      <path d={path} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" />
      {entries.map((e, i) => (
        <circle key={i} cx={sx(i)} cy={sy(e.max_diameter_mm)} r={3} fill={lineColor} />
      ))}
      <text x={P.l - 4} y={sy(yLo) + 3} textAnchor="end" fontSize={9} fill="var(--muted-foreground)">{yLo.toFixed(0)}</text>
      <text x={P.l - 4} y={sy(yHi) + 3} textAnchor="end" fontSize={9} fill="var(--muted-foreground)">{yHi.toFixed(0)}</text>
      <text x={P.l + iw / 2} y={H - 4} textAnchor="middle" fontSize={9} fill="var(--muted-foreground)">Ø máximo (mm) por sesión</text>
    </svg>
  );
}
