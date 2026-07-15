/* Badge — status / risk pill. Variants map to the clinical color convention:
   destructive = high risk, warning = moderate, success = low/OK. */

import type { CSSProperties, ReactNode } from "react";

type Variant = "default" | "secondary" | "outline" | "subtle" | "success" | "warning" | "destructive";

const STYLES: Record<Variant, CSSProperties> = {
  default: { background: "var(--primary)", color: "var(--primary-foreground)" },
  secondary: { background: "var(--secondary)", color: "var(--secondary-foreground)" },
  outline: { background: "transparent", color: "var(--foreground)", border: "1px solid var(--border)" },
  subtle: { background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)" },
  success: { background: "var(--success-bg)", color: "var(--success)" },
  warning: { background: "var(--warning-bg)", color: "var(--warning)" },
  destructive: {
    background: "color-mix(in srgb, var(--destructive) 14%, transparent)",
    color: "var(--destructive)",
  },
};

export function Badge({ variant = "default", children, style }: { variant?: Variant; children: ReactNode; style?: CSSProperties }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 9px",
        borderRadius: "var(--radius-full)",
        fontSize: 11,
        fontWeight: 700,
        whiteSpace: "nowrap",
        ...STYLES[variant],
        ...style,
      }}
    >
      {children}
    </span>
  );
}

export type RiskLike = "Alto" | "Moderado" | "Medio" | "Bajo" | string;

/** Map a clinical risk label to its badge variant. */
export function riskVariant(risk: RiskLike): "destructive" | "warning" | "success" {
  if (risk === "Alto") return "destructive";
  if (risk === "Moderado" || risk === "Medio") return "warning";
  return "success";
}
