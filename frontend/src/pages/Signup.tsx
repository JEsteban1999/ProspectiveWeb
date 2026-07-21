/* Signup — professional self-registration. Creates a pending account that an
   admin must approve. Cinematic dark layout with looping surgical video, like
   the desktop SignUpDialog. */

import { useState } from "react";
import type { FormEvent } from "react";
import logo from "../assets/logo.png";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
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
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "rgba(168,184,198,0.85)",
  margin: "18px 0 4px",
};

export function Signup({ onBack, onDone }: { onBack: () => void; onDone: (msg: string) => void }) {
  const [form, setForm] = useState({
    full_name: "", national_id: "", professional_id: "",
    specialty: SPECIALTIES[0], university: "", hospital: "",
    position: POSITIONS[0], orcid: "",
    username: "", password: "", confirm: "",
  });
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
      });
      onDone(res.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo enviar la solicitud. ¿Está el backend en marcha?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ position: "relative", height: "100%", overflow: "hidden", background: "#05090f" }}>
      {/* Looping surgical video background */}
      <video
        src="/media/intro.mp4"
        autoPlay
        muted
        loop
        playsInline
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", opacity: 0.35 }}
      />
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(120% 100% at 30% 20%, rgba(10,18,28,0.75), rgba(5,9,15,0.92))" }} />

      {/* Header */}
      <div style={{ position: "relative", height: 56, display: "flex", alignItems: "center", padding: "0 28px" }}>
        <img src={logo} alt="" style={{ height: 26, filter: "invert(1) brightness(1.7)" }} />
        <span style={{ marginLeft: 12, color: "#fff", fontWeight: 800, fontSize: 18, letterSpacing: "-0.02em" }}>PROSPECTIVE</span>
        <div style={{ flex: 1 }} />
        <button onClick={onBack} style={{ background: "transparent", border: "none", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
          ← Volver al login
        </button>
        <div style={{ marginLeft: 14 }}><ThemeToggle size="sm" /></div>
      </div>

      {/* Card */}
      <div style={{ position: "relative", display: "flex", justifyContent: "center", padding: "10px 20px 40px", height: "calc(100% - 56px)", overflowY: "auto" }}>
        <div
          className="fade-rise"
          style={{
            width: 540,
            maxWidth: "100%",
            background: "rgba(18,26,36,0.72)",
            backdropFilter: "blur(14px)",
            border: "1px solid rgba(139,155,170,0.28)",
            borderRadius: "var(--radius-xl)",
            boxShadow: "var(--shadow-lg)",
            padding: "26px 30px 30px",
            alignSelf: "flex-start",
          }}
        >
          <div style={{ fontSize: 22, fontWeight: 800, color: "#fff", letterSpacing: "-0.02em" }}>Crear cuenta profesional</div>
          <div style={{ fontSize: 13, color: "rgba(168,184,198,0.85)", marginTop: 4 }}>
            Regístrate para acceder a PROSPECTIVE.
          </div>

          <form onSubmit={submit}>
            <div style={GROUP_LABEL}>Datos personales</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Input label="Nombre completo *" value={form.full_name} onChange={set("full_name")} placeholder="Dr. …" />
              <Input label="Cédula o ID" value={form.national_id} onChange={set("national_id")} />
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

            <div style={GROUP_LABEL}>Credenciales de acceso</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Input label="Usuario *" value={form.username} onChange={set("username")} autoComplete="username" />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <Input label="Contraseña *" type="password" value={form.password} onChange={set("password")} autoComplete="new-password" />
                <Input label="Confirmar *" type="password" value={form.confirm} onChange={set("confirm")} autoComplete="new-password" />
              </div>
            </div>

            <div style={{ marginTop: 16, padding: "10px 14px", borderRadius: "var(--radius-md)", background: "rgba(210,148,0,0.14)", border: "1px solid rgba(210,148,0,0.4)", color: "#ffcc44", fontSize: 12 }}>
              Tu cuenta quedará <b>pendiente de aprobación</b> hasta que un administrador la active.
            </div>

            {error && (
              <div style={{ marginTop: 12, fontSize: 12, color: "#f87171" }}>{error}</div>
            )}

            <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
              <Button type="button" variant="outline" onClick={onBack} style={{ background: "rgba(5,3,15,0.4)", color: "#d0d9ea", borderColor: "rgba(139,155,170,0.4)" }}>
                Cancelar
              </Button>
              <Button type="submit" style={{ flex: 1 }} disabled={busy}>
                {busy ? "Enviando…" : "Enviar solicitud de registro"}
              </Button>
            </div>
          </form>

          <div style={{ textAlign: "center", marginTop: 16, fontSize: 10, color: "rgba(139,155,170,0.6)" }}>
            Hybrid Neurovascular Planning Platform · SKULLAPP
          </div>
        </div>
      </div>
    </div>
  );
}
