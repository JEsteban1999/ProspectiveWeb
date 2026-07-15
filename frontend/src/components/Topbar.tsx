/* Topbar — translucent app header.
   Left: clickable logo (→ home) + PROSPECTIVE + WEB chip + breadcrumb.
   Right: slot, theme toggle, user menu (dropdown with profile + admin + logout). */

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import logo from "../assets/logo.png";
import { ThemeToggle } from "./ThemeToggle";
import { Icon } from "./Icon";
import { Badge } from "./Badge";
import { useAuth } from "../store/auth";
import { useNav } from "../store/nav";
import { api } from "../api/client";

const ROLE_LABEL: Record<string, string> = {
  admin: "Administrador",
  medico: "Médico",
  residente: "Residente",
  viewer: "Observador",
};

function UserMenu() {
  const { user, logout } = useAuth();
  const nav = useNav();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const isAdmin = user?.role === "admin";

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Refresh the pending-requests badge whenever the menu opens (admin only).
  useEffect(() => {
    if (open && isAdmin) api.listPending().then((p) => setPending(p.length)).catch(() => setPending(0));
  }, [open, isAdmin]);

  if (!user) return null;

  const doLogout = () => {
    setOpen(false);
    logout();
    nav.go("login");
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Menú de usuario"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          height: 40,
          padding: "0 8px 0 6px",
          borderRadius: "var(--radius-full)",
          border: "1px solid var(--border)",
          background: open ? "var(--accent)" : "transparent",
          color: "var(--foreground)",
          cursor: "pointer",
          fontFamily: "var(--font-sans)",
          fontSize: 13,
          transition: "background var(--dur-fast) var(--ease-out)",
        }}
      >
        <span
          style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 12 }}
        >
          {user.avatar_initials}
        </span>
        <span style={{ fontWeight: 600, maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {user.username}
        </span>
        {isAdmin && pending > 0 && <Badge variant="destructive">{pending}</Badge>}
        <span style={{ color: "var(--muted-foreground)", fontSize: 10, transform: open ? "rotate(180deg)" : "none", transition: "transform var(--dur-fast)" }}>▾</span>
      </button>

      {open && (
        <div
          className="fade-rise"
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            right: 0,
            width: 250,
            background: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-lg)",
            boxShadow: "var(--shadow-md)",
            padding: 8,
            zIndex: 300,
          }}
        >
          {/* Profile header */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px 12px" }}>
            <span
              style={{ width: 38, height: 38, borderRadius: "50%", flexShrink: 0, background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14 }}
            >
              {user.avatar_initials}
            </span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {user.full_name || user.username}
              </div>
              <div style={{ fontSize: 11, color: "var(--muted-foreground)" }}>
                @{user.username} · {ROLE_LABEL[user.role] ?? user.role}
              </div>
            </div>
          </div>

          <div style={{ height: 1, background: "var(--border)", margin: "2px 0" }} />

          <MenuItem icon="STEP_PATIENT" label="Pacientes" onClick={() => { setOpen(false); nav.go("patients"); }} />
          {isAdmin && (
            <MenuItem
              icon="USERS"
              label="Solicitudes de registro"
              badge={pending > 0 ? pending : undefined}
              onClick={() => { setOpen(false); nav.go("pending"); }}
            />
          )}
          {isAdmin && (
            <MenuItem
              icon="SHIELD"
              label="Auditoría (SkullChain)"
              onClick={() => { setOpen(false); nav.go("audit"); }}
            />
          )}

          <div style={{ height: 1, background: "var(--border)", margin: "2px 0" }} />

          <MenuItem icon="LOCK" label="Cerrar sesión" danger onClick={doLogout} />
        </div>
      )}
    </div>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  badge,
  danger,
}: {
  icon: Parameters<typeof Icon>[0]["name"];
  label: string;
  onClick: () => void;
  badge?: number;
  danger?: boolean;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "9px 10px",
        border: "none",
        borderRadius: "var(--radius-md)",
        background: hover ? "var(--accent)" : "transparent",
        color: danger ? "var(--destructive)" : "var(--foreground)",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        fontSize: 13,
        fontWeight: 500,
        textAlign: "left",
      }}
    >
      <Icon name={icon} size={15} color={danger ? "var(--destructive)" : "var(--muted-foreground)"} />
      <span style={{ flex: 1 }}>{label}</span>
      {badge !== undefined && <Badge variant="destructive">{badge}</Badge>}
    </button>
  );
}

export function Topbar({ crumb, children }: { crumb?: string; children?: ReactNode }) {
  const nav = useNav();
  return (
    <div
      style={{
        height: 66,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 24px",
        background: "color-mix(in srgb, var(--background) 92%, transparent)",
        backdropFilter: "blur(8px)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      {/* Clickable brand → home (patients) */}
      <button
        onClick={() => nav.go("patients")}
        title="Ir a pacientes"
        style={{ display: "flex", alignItems: "center", gap: 12, background: "transparent", border: "none", cursor: "pointer", padding: 0 }}
      >
        <img className="logo-mark" src={logo} alt="SkullApp" style={{ height: 46 }} />
        <span style={{ fontWeight: 800, fontSize: 20, letterSpacing: "var(--tracking-title)", color: "var(--foreground)" }}>
          PROSPECTIVE
        </span>
        <span style={{ fontSize: 11, color: "var(--muted-foreground)", background: "var(--muted)", padding: "3px 8px", borderRadius: 6, fontWeight: 700, letterSpacing: "0.04em" }}>
          WEB
        </span>
      </button>
      {crumb && (
        <>
          <span style={{ color: "var(--border)", fontSize: 18 }}>/</span>
          <span style={{ fontSize: 13, color: "var(--muted-foreground)" }}>{crumb}</span>
        </>
      )}
      <div style={{ flex: 1 }} />
      {children}
      <ThemeToggle size="sm" />
      <UserMenu />
    </div>
  );
}
