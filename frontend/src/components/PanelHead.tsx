/* PanelHead — step panel title + endpoint description + right slot. */

import { useState } from "react";
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
export function SectionLabel({ children, style, className }: { children: ReactNode; style?: React.CSSProperties; className?: string }) {
  return (
    <div
      className={className}
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

/* Collapsible — sección plegable con estado recordado por sesión.

   El paso de Morfometría renderiza cuatro paneles seguidos en una columna de
   300–384 px: pasaba de mil píxeles de scroll y las herramientas de línea
   central —de donde sale el stent guiado— quedaban enterradas al fondo. */
export function Collapsible({
  title,
  subtitle,
  storageKey,
  defaultOpen = false,
  badge,
  children,
}: {
  title: string;
  subtitle?: string;
  /** Clave de sessionStorage; recuerda si la sección quedó abierta. */
  storageKey: string;
  defaultOpen?: boolean;
  badge?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(() => {
    // sessionStorage puede lanzar (ventana privada, cookies bloqueadas); en ese
    // caso simplemente se usa el valor por defecto.
    try {
      const v = sessionStorage.getItem(storageKey);
      return v === null ? defaultOpen : v === "1";
    } catch {
      return defaultOpen;
    }
  });

  const toggle = () => {
    const next = !open;
    setOpen(next);
    try { sessionStorage.setItem(storageKey, next ? "1" : "0"); } catch { /* sin persistencia */ }
  };

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", background: "var(--background)", overflow: "hidden" }}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        style={{
          display: "flex", alignItems: "center", gap: 10, width: "100%",
          padding: "11px 14px", border: "none", background: "transparent",
          cursor: "pointer", textAlign: "left", fontFamily: "var(--font-sans)",
        }}
      >
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "block", fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>{title}</span>
          {subtitle && (
            <span className="truncate" style={{ display: "block", fontSize: 11, color: "var(--muted-foreground)", marginTop: 2 }}>
              {subtitle}
            </span>
          )}
        </span>
        {badge}
        <span style={{ color: "var(--muted-foreground)", fontSize: 12, flexShrink: 0 }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && <div style={{ padding: "0 14px 16px", borderTop: "1px solid var(--border)" }}>
        <div style={{ paddingTop: 14 }}>{children}</div>
      </div>}
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
export function Card({ children, style, className, onClick }: {
  children: ReactNode;
  style?: React.CSSProperties;
  className?: string;
  /** Makes the card selectable (a clip candidate, a row that opens something). */
  onClick?: () => void;
}) {
  return (
    <div
      className={className}
      onClick={onClick}
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
