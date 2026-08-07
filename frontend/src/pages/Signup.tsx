/* Signup — professional self-registration. Creates a pending account that an
   admin must approve. Shares the two-column identity of the Login page: a
   cinematic brand panel on the left and a theme-aware form panel on the right. */

import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import logo from "../assets/logo.png";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { FileField } from "../components/FileField";
import { Input } from "../components/Input";
import { Select } from "../components/Select";
import { ThemeToggle } from "../components/ThemeToggle";

const SPECIALTIES = [
  "Neurocirugía",
  "Neurorradiología intervencionista",
  "Neurología",
  "Radiología",
  "Anestesiología",
  "Medicina interna",
  "Otra",
];
const POSITIONS = [
  "Neurocirujano/a",
  "Neurorradiólogo/a",
  "Residente de Neurocirugía",
  "Residente de Radiología",
  "Fellow",
  "Médico adjunto",
  "Estudiante de medicina",
  "Investigador/a",
  "Otro",
];

const GROUP_LABEL: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--muted-foreground)",
  margin: "22px 0 2px",
};

export function Signup({ onBack, onDone }: { onBack: () => void; onDone: (msg: string) => void }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    full_name: "", national_id: "", professional_id: "",
    specialty: SPECIALTIES[0], university: "", hospital: "",
    position: POSITIONS[0], orcid: "",
    username: "", password: "", confirm: "",
  });
  const [photo, setPhoto] = useState<File | null>(null);
  const [cv, setCv] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!form.full_name.trim()) return setError("El nombre completo es obligatorio.");
    if (form.username.trim().length < 3) return setError("El usuario debe tener al menos 3 caracteres.");
    if (form.password.length < 8) return setError("La contraseña debe tener al menos 8 caracteres.");
    if (form.password !== form.confirm) return setError("Las contraseñas no coinciden.");

    setBusy(true);
    try {
      const res = await api.signup({
        username: form.username.trim(),
        password: form.password,
        full_name: form.full_name.trim(),
        national_id: form.national_id.trim(),
        professional_id: form.professional_id.trim(),
        specialty: form.specialty,
        university: form.university.trim(),
        hospital: form.hospital.trim(),
        position: form.position,
        orcid: form.orcid.trim(),
      }, photo, cv);
      onDone(res.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo enviar la solicitud. ¿Está el backend en marcha?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", height: "100%", background: "var(--canvas)" }}>
      {/* Brand panel — same cinematic identity as the login. */}
      <div
        className="login-media"
        style={{
          flex: "1 1 56%",
          position: "relative",
          overflow: "hidden",
          background: "radial-gradient(130% 100% at 30% 20%, #16222e 0%, #0a121c 55%, #05090f 100%)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "48px 56px",
        }}
      >
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
            Registro profesional
          </div>
          <div style={{ color: "#fff", fontSize: 38, fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1.1, maxWidth: 460 }}>
            Únete al equipo clínico de PROSPECTIVE
          </div>
          <div style={{ color: "rgba(235,235,235,0.6)", fontSize: 14, marginTop: 18, maxWidth: 440, lineHeight: 1.6 }}>
            Crea tu cuenta profesional para planificar cirugías de aneurisma con datos objetivos y modelos 3D. Un administrador la revisará antes de darte acceso.
          </div>
        </div>
        <div style={{ position: "relative", display: "flex", gap: 26, color: "rgba(168,184,198,0.8)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
          <span>Acceso revisado</span>
          <span>·</span>
          <span>Datos cifrados</span>
          <span>·</span>
          <span>SKULLAPP</span>
        </div>
      </div>

      {/* Form panel — theme-aware, scrollable (the form is long). */}
      <div className="login-form" style={{ flex: "1 1 44%", display: "flex", flexDirection: "column", minWidth: 340, overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "24px clamp(24px, 3.5vw, 60px) 0" }}>
          <button
            onClick={onBack}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "transparent", border: "none", cursor: "pointer", color: "var(--muted-foreground)", fontSize: 13, fontWeight: 600, fontFamily: "var(--font-sans)", padding: 0 }}
          >
            ← Volver al login
          </button>
          <ThemeToggle />
        </div>

        <div style={{ maxWidth: 480, width: "100%", margin: "0 auto", padding: "18px clamp(24px, 3.5vw, 60px) 40px" }}>
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "var(--tracking-title)", color: "var(--foreground)" }}>
            Crear cuenta profesional
          </div>
          <div style={{ fontSize: 14, color: "var(--muted-foreground)", marginTop: 6 }}>
            Regístrate para acceder a PROSPECTIVE.
          </div>

          <form onSubmit={submit}>
            <div style={GROUP_LABEL}>Datos personales</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Input label="Nombre completo *" value={form.full_name} onChange={set("full_name")} placeholder="Dr. …" />
              <Input label="Cédula o ID" value={form.national_id} onChange={set("national_id")} />
              <FileField label="Foto de perfil" accept="image/*" file={photo} onPick={setPhoto} />
            </div>

            <div style={GROUP_LABEL}>Datos profesionales</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <Input label="ID profesional" value={form.professional_id} onChange={set("professional_id")} />
              <Select label="Especialidad" options={SPECIALTIES} value={form.specialty} onChange={set("specialty")} />
              <Input label="Universidad" value={form.university} onChange={set("university")} />
              <Input label="Hospital / Centro" value={form.hospital} onChange={set("hospital")} />
              <Select label="Cargo" options={POSITIONS} value={form.position} onChange={set("position")} />
              <Input label="ORCID" value={form.orcid} onChange={set("orcid")} placeholder="0000-0002-1825-0097" />
            </div>
            <div style={{ marginTop: 12 }}>
              <FileField label="Currículum (CV)" accept=".pdf,.doc,.docx" file={cv} onPick={setCv} />
            </div>

            <div style={GROUP_LABEL}>Credenciales de acceso</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Input label="Usuario *" value={form.username} onChange={set("username")} autoComplete="username" />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <Input label="Contraseña *" type="password" value={form.password} onChange={set("password")} autoComplete="new-password" />
                <Input label="Confirmar *" type="password" value={form.confirm} onChange={set("confirm")} autoComplete="new-password" />
              </div>
            </div>

            <div style={{ marginTop: 18, padding: "10px 14px", borderRadius: "var(--radius-md)", background: "var(--warning-bg)", border: "1px solid color-mix(in srgb, var(--warning) 40%, transparent)", color: "var(--warning)", fontSize: 12 }}>
              Tu cuenta quedará <b>pendiente de aprobación</b> hasta que un administrador la active.
            </div>

            {error && (
              <div style={{ marginTop: 12, fontSize: 12, color: "var(--destructive, #f87171)" }}>{error}</div>
            )}

            <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
              <Button type="button" variant="outline" onClick={onBack}>
                Cancelar
              </Button>
              <Button type="submit" style={{ flex: 1 }} disabled={busy}>
                {busy ? "Enviando…" : "Enviar solicitud de registro"}
              </Button>
            </div>
          </form>

          <div style={{ textAlign: "center", marginTop: 20, fontSize: 11, color: "var(--muted-foreground)" }}>
            PROSPECTIVE™ Web · SkullApp — Laboratorio de Imagen Médica
          </div>
        </div>
      </div>
    </div>
  );
}
