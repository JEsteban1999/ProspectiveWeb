/* Sheet — right-side drawer with translucent blur panel and 40% scrim.

   Rendered through a portal on <body>: `position: fixed` is resolved against
   the nearest ancestor with a transform, filter or backdrop-filter, not the
   viewport. The topbar is a glass bar (backdrop-filter), so a sheet opened from
   the user menu collapsed to the topbar's 66 px and clipped its own form. */

import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

export function Sheet({
  open,
  onClose,
  title,
  width = 420,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  width?: number;
  children: ReactNode;
}) {
  if (!open) return null;
  return createPortal(
    <div style={{ position: "fixed", inset: 0, zIndex: 100 }}>
      <div
        onClick={onClose}
        style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.4)" }}
      />
      <div
        className="fade-rise"
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          width,
          maxWidth: "94vw",
          background: "color-mix(in srgb, var(--background) 88%, transparent)",
          backdropFilter: "blur(12px)",
          borderLeft: "1px solid var(--border)",
          borderRadius: "var(--radius-xl) 0 0 var(--radius-xl)",
          boxShadow: "var(--shadow-lg)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", padding: "18px 22px", borderBottom: "1px solid var(--border)" }}>
          <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: "var(--tracking-title)", color: "var(--foreground)", flex: 1 }}>
            {title}
          </span>
          <button
            onClick={onClose}
            aria-label="Cerrar"
            style={{ border: "none", background: "transparent", cursor: "pointer", color: "var(--muted-foreground)", padding: 6 }}
          >
            <Icon name="STATUS_FAIL" size={15} />
          </button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 22px" }}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}
