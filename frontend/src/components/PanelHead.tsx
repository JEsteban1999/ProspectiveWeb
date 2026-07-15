/* PanelHead — step panel title + endpoint description + right slot. */

import type { ReactNode } from "react";

export function PanelHead({ title, desc, right }: { title: string; desc?: string; right?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "var(--tracking-title)", color: "var(--foreground)" }}>
          {title}
        </div>
        {desc && <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginTop: 3 }}>{desc}</div>}
      </div>
      {right}
    </div>
  );
}

/* SectionLabel — small uppercase tracking label (CANDIDATOS, SERIE DETECTADA…) */
export function SectionLabel({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "var(--tracking-label)",
        textTransform: "uppercase",
        color: "var(--muted-foreground)",
        marginBottom: 8,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/* ErrorNote — inline error box for failed API calls. */
export function ErrorNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <div
      style={{
        marginTop: 12,
        padding: "10px 14px",
        borderRadius: "var(--radius-md)",
        background: "color-mix(in srgb, var(--destructive) 10%, transparent)",
        border: "1px solid color-mix(in srgb, var(--destructive) 35%, transparent)",
        color: "var(--destructive)",
        fontSize: 12,
      }}
    >
      {children}
    </div>
  );
}

/* Card — standard elevated surface (radius 14, shadow sm, border 1px). */
export function Card({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-sm)",
        padding: "14px 16px",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
