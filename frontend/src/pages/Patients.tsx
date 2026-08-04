/* Pacientes — stat tiles + searchable patient table (GET /api/patients),
   new-patient drawer (POST /api/patients). */

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import type { PatientSummary } from "../api/types";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Input } from "../components/Input";
import { Select } from "../components/Select";
import { Sheet } from "../components/Sheet";
import { Topbar } from "../components/Topbar";
import { ErrorNote, Card } from "../components/PanelHead";
import { useAuth } from "../store/auth";

function NewPatientSheet({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (p: PatientSummary) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    surname: "", given_name: "", hospital_id: "", sex: "F", dob: "",
    institution: "", ocupacion: "",
    antecedentes_patologicos: "", antecedentes_toxicologicos: "", antecedentes_quirurgicos: "",
    antecedentes_alergicos: "", antecedentes_farmacologicos: "", notes: "",
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.createPatient(form);
      onCreated(created);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear el paciente");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Nuevo paciente" width={460}>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Apellidos" placeholder="Restrepo" value={form.surname} onChange={set("surname")} required />
          <Input label="Nombre" placeholder="María" value={form.given_name} onChange={set("given_name")} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="ID hospital" placeholder="HC-00000" value={form.hospital_id} onChange={set("hospital_id")} />
          <Select label="Sexo" options={["F", "M", "O"]} value={form.sex} onChange={set("sex")} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Fecha de nacimiento" type="date" value={form.dob} onChange={set("dob")} />
          <Input label="Institución" placeholder="Hospital…" value={form.institution} onChange={set("institution")} />
        </div>
        <Input label="Ocupación" placeholder="—" value={form.ocupacion} onChange={set("ocupacion")} />
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--muted-foreground)", marginTop: 6 }}>
          Antecedentes
        </div>
        <Input label="Patológicos" placeholder="HTA, tabaquismo…" value={form.antecedentes_patologicos} onChange={set("antecedentes_patologicos")} />
        <Input label="Toxicológicos" placeholder="Tabaco, alcohol…" value={form.antecedentes_toxicologicos} onChange={set("antecedentes_toxicologicos")} />
        <Input label="Quirúrgicos" placeholder="—" value={form.antecedentes_quirurgicos} onChange={set("antecedentes_quirurgicos")} />
        <Input label="Alérgicos" placeholder="—" value={form.antecedentes_alergicos} onChange={set("antecedentes_alergicos")} />
        <Input label="Farmacológicos" placeholder="—" value={form.antecedentes_farmacologicos} onChange={set("antecedentes_farmacologicos")} />
        <Input label="Notas" placeholder="Notas clínicas libres…" value={form.notes} onChange={set("notes")} />
        <ErrorNote>{error}</ErrorNote>
        <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
          <Button type="submit" style={{ flex: 1 }} disabled={busy || !form.surname}>
            {busy ? "Creando…" : "Crear paciente"}
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>Cancelar</Button>
        </div>
      </form>
    </Sheet>
  );
}

export function Patients({
  onOpenPatient,
  onOpenPending,
}: {
  onOpenPatient: (p: PatientSummary) => void;
  onOpenPending: () => void;
}) {
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);
  const [q, setQ] = useState("");
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [pendingCount, setPendingCount] = useState(0);

  // Admins get a badge with the number of pending account requests.
  useEffect(() => {
    if (!isAdmin) return;
    api.listPending().then((p) => setPendingCount(p.length)).catch(() => setPendingCount(0));
  }, [isAdmin]);

  const load = () => {
    setLoading(true);
    api
      .listPatients()
      .then(setPatients)
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando pacientes"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const rows = useMemo(
    () =>
      patients.filter(
        (p) =>
          p.full_name.toLowerCase().includes(q.toLowerCase()) ||
          p.hospital_id.toLowerCase().includes(q.toLowerCase())
      ),
    [patients, q]
  );

  const totalStudies = patients.reduce((acc, p) => acc + p.study_count, 0);
  const tiles: { k: string; v: string; s: string; icon: React.ComponentProps<typeof Icon>["name"] }[] = [
    { k: "Pacientes registrados", v: String(patients.length), s: "en la base de datos", icon: "STEP_PATIENT" },
    { k: "Estudios DICOM", v: String(totalStudies), s: "vinculados a pacientes", icon: "FOLDER" },
    { k: "Con estudios", v: String(patients.filter((p) => p.study_count > 0).length), s: "listos para planificar", icon: "STATUS_OK" },
    { k: "Sin estudios", v: String(patients.filter((p) => p.study_count === 0).length), s: "pendientes de carga", icon: "WAIT" },
  ];

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--canvas)" }}>
      <Topbar>
        <div style={{ width: 240, marginRight: 8 }}>
          <Input icon={<Icon name="SEARCH" />} placeholder="Buscar paciente o HC…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </Topbar>

      <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px 48px" }}>
        <div style={{ maxWidth: 1120, margin: "0 auto" }} className="fade-rise">
          <div style={{ display: "flex", alignItems: "flex-end", marginBottom: 22 }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "var(--tracking-title)", color: "var(--foreground)" }}>
                Pacientes
              </div>
              <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 2 }}>
                {loading ? "Cargando…" : `${rows.length} registros · ordenados por fecha de creación`}
              </div>
            </div>
            <div style={{ flex: 1 }} />
            {isAdmin && (
              <Button variant="outline" leadingIcon={<Icon name="USERS" />} onClick={onOpenPending} style={{ marginRight: 10 }}>
                Solicitudes
                {pendingCount > 0 && (
                  <span style={{ marginLeft: 2 }}>
                    <Badge variant="destructive">{pendingCount}</Badge>
                  </span>
                )}
              </Button>
            )}
            <Button leadingIcon={<Icon name="STEP_PATIENT" />} onClick={() => setSheet(true)}>
              Nuevo paciente
            </Button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            {tiles.map((t) => (
              <Card key={t.k} style={{ padding: "16px 18px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--muted-foreground)" }}>{t.k}</div>
                  <span style={{ width: 30, height: 30, borderRadius: "var(--radius-md)", background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <Icon name={t.icon} size={15} />
                  </span>
                </div>
                <div style={{ fontSize: 28, fontWeight: 800, color: "var(--foreground)", marginTop: 6, fontFamily: "var(--font-mono)" }}>
                  {loading ? "—" : t.v}
                </div>
                <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginTop: 2 }}>{t.s}</div>
              </Card>
            ))}
          </div>

          <ErrorNote>{error}</ErrorNote>

          <div style={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {["Paciente", "HC", "Sexo / Nac.", "Institución", "Estudios", "Creado", ""].map((h, i) => (
                    <th
                      key={i}
                      style={{ textAlign: i === 4 ? "center" : "left", padding: "11px 16px", background: "var(--muted)", color: "var(--muted-foreground)", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", borderBottom: "1px solid var(--border)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!loading && rows.length === 0 && (
                  <tr>
                    <td colSpan={7} style={{ padding: "28px 16px", textAlign: "center", color: "var(--muted-foreground)" }}>
                      {patients.length === 0
                        ? "No hay pacientes registrados. Crea el primero para comenzar."
                        : "Ningún paciente coincide con la búsqueda."}
                    </td>
                  </tr>
                )}
                {rows.map((p, i) => (
                  <tr
                    key={p.id}
                    onClick={() => onOpenPatient(p)}
                    style={{ cursor: "pointer", borderBottom: i < rows.length - 1 ? "1px solid var(--border)" : "none" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--accent)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <td style={{ padding: "12px 16px", fontWeight: 600, color: "var(--foreground)" }}>{p.full_name}</td>
                    <td style={{ padding: "12px 16px", fontFamily: "var(--font-mono)", color: "var(--muted-foreground)" }}>{p.hospital_id || "—"}</td>
                    <td style={{ padding: "12px 16px", color: "var(--muted-foreground)" }}>{p.sex || "—"} · {p.dob || "—"}</td>
                    <td style={{ padding: "12px 16px", color: "var(--foreground)" }}>{p.institution || "—"}</td>
                    <td style={{ padding: "12px 16px", textAlign: "center" }}>
                      <Badge variant="subtle">{p.study_count}</Badge>
                    </td>
                    <td style={{ padding: "12px 16px", color: "var(--muted-foreground)" }}>
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                    <td style={{ padding: "12px 16px", textAlign: "right", color: "var(--brand-deep)", fontWeight: 700, whiteSpace: "nowrap" }}>
                      Abrir sesión →
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <NewPatientSheet open={sheet} onClose={() => setSheet(false)} onCreated={() => load()} />
    </div>
  );
}
