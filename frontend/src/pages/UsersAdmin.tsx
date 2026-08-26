/* Usuarios — admin-only management of all accounts: list, edit role / name /
   status (active), and delete. Mirrors the desktop user-admin panel.
   Backed by GET/PUT/DELETE /api/auth/users. */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { UserAdminInfo } from "../api/types";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { FileField } from "../components/FileField";
import { Icon } from "../components/Icon";
import { Input } from "../components/Input";
import { Select } from "../components/Select";
import { Sheet } from "../components/Sheet";
import { Topbar } from "../components/Topbar";
import { ErrorNote } from "../components/PanelHead";
import { useAuth } from "../store/auth";

const SPECIALTIES = [
  "Neurocirugía", "Neurorradiología intervencionista", "Neurología",
  "Radiología", "Anestesiología", "Medicina interna", "Otra",
];
const POSITIONS = [
  "Neurocirujano/a", "Neurorradiólogo/a", "Residente de Neurocirugía",
  "Residente de Radiología", "Fellow", "Médico adjunto",
  "Estudiante de medicina", "Investigador/a", "Otro",
];
const GROUP_LABEL: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
  color: "var(--muted-foreground)", margin: "20px 0 2px",
};

const ROLE_OPTS = [
  { value: "admin", label: "Administrador" },
  { value: "medico", label: "Médico" },
  { value: "residente", label: "Residente" },
  { value: "viewer", label: "Observador" },
];
const ROLE_LABEL: Record<string, string> = Object.fromEntries(ROLE_OPTS.map((r) => [r.value, r.label]));
const roleVariant = (r: string): "destructive" | "default" | "secondary" | "subtle" =>
  r === "admin" ? "destructive" : r === "medico" ? "default" : r === "residente" ? "secondary" : "subtle";

function EditUserSheet({
  open, user, onClose, onSaved,
}: { open: boolean; user: UserAdminInfo | null; onClose: () => void; onSaved: () => void }) {
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("viewer");
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !user) return;
    setFullName(user.full_name || "");
    setRole(user.role || "viewer");
    setActive(user.is_active);
    setError(null);
  }, [open, user]);

  const submit = async () => {
    if (!user) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateUser(user.id, { full_name: fullName.trim(), role, is_active: active });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar el usuario");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Editar usuario" width={440}>
      {user && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ fontSize: 13, color: "var(--muted-foreground)" }}>
            Cuenta <b style={{ color: "var(--foreground)", fontFamily: "var(--font-mono)" }}>@{user.username}</b>
          </div>
          <Input label="Nombre completo" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Nombre y apellidos" />
          <Select label="Rol" options={ROLE_OPTS} value={role} onChange={(e) => setRole(e.target.value)} />
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--foreground)", cursor: "pointer" }}>
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Cuenta activa (puede iniciar sesión)
          </label>
          <ErrorNote>{error}</ErrorNote>
          <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
            <Button style={{ flex: 1 }} disabled={busy} onClick={submit}>{busy ? "Guardando…" : "Guardar cambios"}</Button>
            <Button variant="outline" onClick={onClose}>Cancelar</Button>
          </div>
        </div>
      )}
    </Sheet>
  );
}

/* Admin-created account — same professional fields as self-registration, plus a
   role selector. The account is created ACTIVE (no approval step). */
function NewUserSheet({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const BLANK = {
    full_name: "", national_id: "", professional_id: "",
    specialty: SPECIALTIES[0], university: "", hospital: "",
    position: POSITIONS[0], orcid: "", role: "medico",
    username: "", password: "", confirm: "",
  };
  const [form, setForm] = useState({ ...BLANK });
  const [photo, setPhoto] = useState<File | null>(null);
  const [cv, setCv] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) { setForm({ ...BLANK }); setPhoto(null); setCv(null); setError(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async () => {
    setError(null);
    if (!form.full_name.trim()) return setError("El nombre completo es obligatorio.");
    if (form.username.trim().length < 3) return setError("El usuario debe tener al menos 3 caracteres.");
    if (form.password.length < 8) return setError("La contraseña debe tener al menos 8 caracteres.");
    if (form.password !== form.confirm) return setError("Las contraseñas no coinciden.");
    setBusy(true);
    try {
      await api.createUser({
        username: form.username.trim(), password: form.password, full_name: form.full_name.trim(),
        role: form.role, national_id: form.national_id.trim(), professional_id: form.professional_id.trim(),
        specialty: form.specialty, university: form.university.trim(), hospital: form.hospital.trim(),
        position: form.position, orcid: form.orcid.trim(),
      }, photo, cv);
      onCreated();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al crear el usuario");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Nuevo usuario" width={480}>
      <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginBottom: 4 }}>
        La cuenta se crea <b style={{ color: "var(--foreground)" }}>activa</b> (sin aprobación) y podrá iniciar sesión de inmediato.
      </div>

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

      <div style={GROUP_LABEL}>Acceso y rol</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Usuario *" value={form.username} onChange={set("username")} autoComplete="off" />
          <Select label="Rol" options={ROLE_OPTS} value={form.role} onChange={set("role")} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Contraseña *" type="password" value={form.password} onChange={set("password")} autoComplete="new-password" />
          <Input label="Confirmar *" type="password" value={form.confirm} onChange={set("confirm")} autoComplete="new-password" />
        </div>
      </div>

      <ErrorNote>{error}</ErrorNote>
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <Button style={{ flex: 1 }} disabled={busy} onClick={submit}>{busy ? "Creando…" : "Crear usuario"}</Button>
        <Button variant="outline" onClick={onClose}>Cancelar</Button>
      </div>
    </Sheet>
  );
}

export function UsersAdmin({ onBack }: { onBack: () => void }) {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<UserAdminInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [editUser, setEditUser] = useState<UserAdminInfo | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [toDelete, setToDelete] = useState<UserAdminInfo | null>(null);
  const [delBusy, setDelBusy] = useState(false);
  // Admin reset for the clinician who forgot theirs — parity with the desktop
  // user manager. No current password is needed, so the event is audited.
  const [toReset, setToReset] = useState<UserAdminInfo | null>(null);
  const [resetPw, setResetPw] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [resetErr, setResetErr] = useState<string | null>(null);
  const [resetDone, setResetDone] = useState<string | null>(null);

  const confirmReset = async () => {
    if (!toReset || resetPw.length < 8) return;
    setResetBusy(true);
    setResetErr(null);
    try {
      await api.resetPassword(toReset.id, resetPw);
      setResetDone(toReset.username);
      setToReset(null);
      setResetPw("");
      setTimeout(() => setResetDone(null), 3000);
    } catch (e) {
      setResetErr(e instanceof Error ? e.message : "No se pudo restablecer");
    } finally {
      setResetBusy(false);
    }
  };

  const load = () => {
    setLoading(true);
    api
      .listUsers()
      .then(setUsers)
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando usuarios"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const rows = users.filter(
    (u) =>
      u.full_name.toLowerCase().includes(q.toLowerCase()) ||
      u.username.toLowerCase().includes(q.toLowerCase())
  );

  const confirmDelete = async () => {
    if (!toDelete) return;
    setDelBusy(true);
    try {
      await api.deleteUser(toDelete.id);
      setToDelete(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar el usuario");
      setToDelete(null);
    } finally {
      setDelBusy(false);
    }
  };

  const iconBtn: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", justifyContent: "center", width: 30, height: 30,
    borderRadius: "var(--radius-md)", border: "1px solid var(--border)", background: "var(--card)", cursor: "pointer",
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar crumbs={[{ label: "Pacientes", onClick: onBack }, { label: "Administración" }, { label: "Usuarios" }]}>
        <div style={{ width: 220, marginRight: 8 }}>
          <Input icon={<Icon name="SEARCH" />} placeholder="Buscar usuario…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Button variant="ghost" size="sm" onClick={onBack} leadingIcon={<Icon name="HOME" />}>Pacientes</Button>
      </Topbar>

      <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px 48px" }}>
        <div style={{ maxWidth: 1000, margin: "0 auto" }} className="fade-rise">
          <div style={{ display: "flex", alignItems: "flex-end", marginBottom: 22 }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", color: "var(--foreground)" }}>
                Gestión de usuarios
              </div>
              <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 2 }}>
                {loading ? "Cargando…" : `${rows.length} usuario${rows.length === 1 ? "" : "s"}`}
              </div>
            </div>
            <div style={{ flex: 1 }} />
            <Button variant="outline" leadingIcon={<Icon name="REFRESH" />} onClick={load} style={{ marginRight: 10 }}>Actualizar</Button>
            <Button leadingIcon={<Icon name="USERS" />} onClick={() => setNewOpen(true)}>Nuevo usuario</Button>
          </div>

          <ErrorNote>{error}</ErrorNote>

          <div style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {["Usuario", "Rol", "Especialidad / Hospital", "Estado", "Creado", "Acciones"].map((h, i) => (
                    <th
                      key={i}
                      style={{ textAlign: i === 5 ? "right" : "left", padding: "11px 16px", background: "var(--muted)", color: "var(--muted-foreground)", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", borderBottom: "1px solid var(--border)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!loading && rows.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: "28px 16px", textAlign: "center", color: "var(--muted-foreground)" }}>
                      No hay usuarios que coincidan con la búsqueda.
                    </td>
                  </tr>
                )}
                {rows.map((u, i) => {
                  const isMe = me?.id === u.id;
                  return (
                    <tr key={u.id} style={{ borderBottom: i < rows.length - 1 ? "1px solid var(--border)" : "none" }}>
                      <td style={{ padding: "12px 16px" }}>
                        <div style={{ fontWeight: 600, color: "var(--foreground)" }}>
                          {u.full_name || u.username}
                          {isMe && <span style={{ marginLeft: 6, fontSize: 11, color: "var(--muted-foreground)" }}>(tú)</span>}
                        </div>
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--muted-foreground)" }}>@{u.username}</div>
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <Badge variant={roleVariant(u.role)}>{ROLE_LABEL[u.role] || u.role}</Badge>
                      </td>
                      <td style={{ padding: "12px 16px", color: "var(--muted-foreground)" }}>
                        {[u.specialty, u.hospital].filter(Boolean).join(" · ") || "—"}
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        {u.is_active
                          ? <Badge variant="subtle">Activo</Badge>
                          : <span style={{ fontSize: 12, color: "var(--destructive, #ef4444)", fontWeight: 600 }}>Inactivo</span>}
                      </td>
                      <td style={{ padding: "12px 16px", color: "var(--muted-foreground)" }}>
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                      </td>
                      <td style={{ padding: "8px 16px", textAlign: "right", whiteSpace: "nowrap" }}>
                        <span style={{ display: "inline-flex", gap: 6 }}>
                          <button
                            title="Editar" style={iconBtn}
                            onClick={() => { setEditUser(u); setEditOpen(true); }}
                            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--brand-deep)")}
                            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                          >
                            <Icon name="EDIT" size={14} color="var(--muted-foreground)" />
                          </button>
                          <button
                            title="Restablecer contraseña" style={iconBtn}
                            onClick={() => { setToReset(u); setResetPw(""); setResetErr(null); }}
                            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--brand-deep)")}
                            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                          >
                            <Icon name="LOCK" size={14} color="var(--muted-foreground)" />
                          </button>
                          <button
                            title={isMe ? "No puedes eliminar tu propia cuenta" : "Eliminar"}
                            style={{ ...iconBtn, opacity: isMe ? 0.4 : 1, cursor: isMe ? "not-allowed" : "pointer" }}
                            disabled={isMe}
                            onClick={() => !isMe && setToDelete(u)}
                          >
                            <span style={{ fontSize: 14, color: "var(--destructive, #ef4444)", lineHeight: 1 }}>✕</span>
                          </button>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <EditUserSheet open={editOpen} user={editUser} onClose={() => { setEditOpen(false); setEditUser(null); }} onSaved={load} />
      <NewUserSheet open={newOpen} onClose={() => setNewOpen(false)} onCreated={load} />

      {toDelete && (
        <div
          onClick={() => setToDelete(null)}
          style={{ position: "fixed", inset: 0, zIndex: 320, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: 380, maxWidth: "90%", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-lg)", padding: "22px 24px" }}
          >
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--foreground)" }}>Eliminar usuario</div>
            <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.5 }}>
              ¿Seguro que quieres eliminar la cuenta de <b style={{ color: "var(--foreground)" }}>{toDelete.full_name || toDelete.username}</b>?
              Sus pacientes se conservarán pero quedarán sin propietario. Esta acción no se puede deshacer.
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 20, justifyContent: "flex-end" }}>
              <Button variant="outline" onClick={() => setToDelete(null)} disabled={delBusy}>Cancelar</Button>
              <Button variant="destructive" disabled={delBusy} onClick={confirmDelete}>{delBusy ? "Eliminando…" : "Eliminar"}</Button>
            </div>
          </div>
        </div>
      )}

      {toReset && (
        <div
          onClick={() => setToReset(null)}
          style={{ position: "fixed", inset: 0, zIndex: 320, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: 400, maxWidth: "90%", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-lg)", padding: "22px 24px" }}
          >
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--foreground)" }}>Restablecer contraseña</div>
            <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.5 }}>
              Asigna una contraseña nueva a <b style={{ color: "var(--foreground)" }}>{toReset.full_name || toReset.username}</b>.
              Queda registrado en la auditoría; comunícasela por un canal seguro y pídele que la cambie al entrar.
            </div>
            <div style={{ marginTop: 14 }}>
              <Input
                label="Nueva contraseña (mín. 8)"
                type="password"
                value={resetPw}
                onChange={(e) => setResetPw(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void confirmReset(); }}
                autoComplete="new-password"
              />
            </div>
            <ErrorNote>{resetErr}</ErrorNote>
            <div style={{ display: "flex", gap: 10, marginTop: 20, justifyContent: "flex-end" }}>
              <Button variant="outline" onClick={() => setToReset(null)} disabled={resetBusy}>Cancelar</Button>
              <Button disabled={resetBusy || resetPw.length < 8} onClick={() => void confirmReset()}>
                {resetBusy ? "Guardando…" : "Restablecer"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {resetDone && (
        <div style={{ position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)", zIndex: 330, background: "var(--foreground)", color: "var(--background)", padding: "10px 18px", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-lg)", fontSize: 13, fontWeight: 600 }}>
          Contraseña de @{resetDone} restablecida
        </div>
      )}
    </div>
  );
}
