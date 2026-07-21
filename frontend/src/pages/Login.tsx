/* Login — cinematic dark brand panel + form panel. Real JWT auth. */

import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import logo from "../assets/logo.png";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { Icon } from "../components/Icon";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../store/auth";
import { ApiError } from "../api/client";

export function Login({ onLogin, onSignup, notice }: { onLogin: () => void; onSignup: () => void; notice?: string | null }) {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(user, pass);
      onLogin();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Credenciales incorrectas");
      } else if (err instanceof ApiError && err.status === 403) {
        // Account pending approval / rejected / disabled — show server message.
        setError(err.message);
      } else {
        setError("No se pudo conectar con el servidor. ¿Está el backend en marcha?");
      }
      setShake(true);
      setTimeout(() => setShake(false), 500);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", height: "100%", background: "var(--canvas)" }}>
      {/* Brand panel — cinematic dark backdrop with radial vignette.
          Cede espacio y desaparece bajo 900px (ver styles/responsive.css). */}
      <div
        className="login-media"
        style={{
          flex: "1 1 62%",
          position: "relative",
          overflow: "hidden",
          background: "radial-gradient(130% 100% at 30% 20%, #16222e 0%, #0a121c 55%, #05090f 100%)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "48px 56px",
        }}
      >
        {/* Looping surgical video — dimmed behind the vignette */}
        <video
          src="/media/intro.mp4"
          autoPlay
          muted
          loop
          playsInline
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", opacity: 0.4 }}
        />
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(120% 100% at 30% 20%, rgba(22,34,46,0.55) 0%, rgba(10,18,28,0.82) 55%, rgba(5,9,15,0.92) 100%)" }} />
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(55% 55% at 65% 60%, rgba(78,102,120,0.22), transparent 72%)" }} />
        <button
          onClick={() => navigate("/")}
          title="Ir a la página principal"
          style={{ position: "relative", display: "flex", alignItems: "center", gap: 12, background: "transparent", border: "none", cursor: "pointer", padding: 0 }}
        >
          <img src={logo} alt="SkullApp" style={{ height: 30, filter: "invert(1) brightness(1.7)" }} />
          <span style={{ color: "#fff", fontWeight: 800, fontSize: 20, letterSpacing: "-0.02em" }}>PROSPECTIVE</span>
        </button>
        <div style={{ position: "relative" }}>
          <div style={{ color: "rgba(168,184,198,0.75)", fontSize: 13, letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 14 }}>
            Plataforma web de planificación
          </div>
          <div style={{ color: "#fff", fontSize: 38, fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1.1, maxWidth: 460 }}>
            Detección y simulación quirúrgica de aneurismas cerebrales
          </div>
          <div style={{ color: "rgba(235,235,235,0.6)", fontSize: 14, marginTop: 18, maxWidth: 440, lineHeight: 1.6 }}>
            Carga DICOM, segmentación vascular 3D, morfometría, evaluación de riesgo y planificación de dispositivos — en el navegador.
          </div>
        </div>
        <div style={{ position: "relative", display: "flex", gap: 26, color: "rgba(168,184,198,0.8)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
          <span>26 endpoints REST</span>
          <span>·</span>
          <span>VTK · SimpleITK</span>
          <span>·</span>
          <span>SKULLAPP</span>
        </div>
      </div>

      {/* Form panel */}
      <div className="login-form" style={{ flex: "1 1 38%", display: "flex", flexDirection: "column", padding: "0 clamp(24px, 4vw, 72px)", minWidth: 320 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 24 }}>
          <button
            onClick={() => navigate("/")}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "transparent", border: "none", cursor: "pointer", color: "var(--muted-foreground)", fontSize: 13, fontWeight: 600, fontFamily: "var(--font-sans)", padding: 0 }}
          >
            ← Página principal
          </button>
          <ThemeToggle />
        </div>
        <div
          className={shake ? "shake" : undefined}
          style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", maxWidth: 380, width: "100%", margin: "0 auto" }}
        >
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "var(--tracking-title)", color: "var(--foreground)" }}>
            Iniciar sesión
          </div>
          <div style={{ fontSize: 14, color: "var(--muted-foreground)", marginTop: 6, marginBottom: 28 }}>
            Introduce tus credenciales para acceder a la plataforma.
          </div>
          {notice && (
            <div style={{ marginBottom: 18, padding: "10px 14px", borderRadius: "var(--radius-md)", background: "var(--success-bg)", border: "1px solid color-mix(in srgb, var(--success) 40%, transparent)", color: "var(--success)", fontSize: 12 }}>
              {notice}
            </div>
          )}
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Input
              label="Usuario"
              icon={<Icon name="USER" />}
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder="admin"
              autoComplete="username"
              invalid={!!error}
            />
            <Input
              label="Contraseña"
              icon={<Icon name="LOCK" />}
              type="password"
              value={pass}
              onChange={(e) => setPass(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              invalid={!!error}
              hint={error ?? undefined}
            />
            <Button type="submit" size="lg" style={{ marginTop: 6 }} disabled={busy || !user || !pass}>
              {busy ? "Verificando…" : "Entrar"}
            </Button>
          </form>
          <div style={{ marginTop: 20, textAlign: "center", fontSize: 13, color: "var(--muted-foreground)" }}>
            ¿No tienes cuenta?{" "}
            <button
              type="button"
              onClick={onSignup}
              style={{ background: "transparent", border: "none", color: "var(--brand-deep)", fontWeight: 700, cursor: "pointer", fontSize: 13, padding: 0 }}
            >
              Crear cuenta profesional
            </button>
          </div>
          <div style={{ marginTop: 16, padding: "10px 14px", borderRadius: "var(--radius-md)", background: "var(--muted)", fontSize: 12, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
            Demo: admin / admin123
          </div>
        </div>
        <div style={{ textAlign: "center", paddingBottom: 24, fontSize: 11, color: "var(--muted-foreground)" }}>
          PROSPECTIVE™ Web · SkullApp — Laboratorio de Imagen Médica
        </div>
      </div>
    </div>
  );
}
