/* ConfirmDialog — modal de confirmación con teclado.

   Las confirmaciones de borrado y la de salida estaban escritas tres veces, y
   ninguna escuchaba Escape ni movía el foco: el teclado se quedaba en la página
   de debajo y la única salida era el ratón. */

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { Button } from "./Button";

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancelar",
  destructive = false,
  busy = false,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Paints the confirm action as a destructive one (borrados, salir sin guardar). */
  destructive?: boolean;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      // Escape siempre cancela; Enter confirma salvo mientras la acción corre.
      if (e.key === "Escape") { e.stopPropagation(); onCancel(); }
      else if (e.key === "Enter" && !busy) { e.preventDefault(); onConfirm(); }
    };
    document.addEventListener("keydown", onKey);
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, busy, onCancel, onConfirm]);

  if (!open) return null;

  return createPortal(
    <div
      onClick={onCancel}
      style={{ position: "fixed", inset: 0, zIndex: 400, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{ outline: "none", width: 420, maxWidth: "90%", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-lg)", padding: "22px 24px" }}
      >
        <div style={{ fontSize: 16, fontWeight: 800, color: "var(--foreground)" }}>{title}</div>
        <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.55 }}>
          {children}
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 20, justifyContent: "flex-end" }}>
          <Button variant="outline" onClick={onCancel} disabled={busy}>{cancelLabel}</Button>
          <Button variant={destructive ? "destructive" : "default"} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
