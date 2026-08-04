/* Pacientes — stat tiles + searchable patient table (GET /api/patients),
   create / edit / delete a patient, and view its past planning sessions. */

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import type { PatientSummary, PatientSessionInfo, StudySummary } from "../api/types";
import { Badge, riskVariant } from "../components/Badge";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Input } from "../components/Input";
import { Select } from "../components/Select";
import { Sheet } from "../components/Sheet";
import { Topbar } from "../components/Topbar";
import { ErrorNote, Card } from "../components/PanelHead";
import { useAuth } from "../store/auth";
import { NuevoCasoSheet, NuevoEstudioSheet } from "./NuevoCaso";

const STEP_LABELS = ["Carga", "Segmentación", "Detección", "Morfometría", "Decisión", "Dispositivos", "Informe"];

const BLANK = {
  surname: "", given_name: "", hospital_id: "", sex: "F", dob: "",
  institution: "", ocupacion: "",
  antecedentes_patologicos: "", antecedentes_toxicologicos: "", antecedentes_quirurgicos: "",
  antecedentes_alergicos: "", antecedentes_farmacologicos: "", notes: "",
};

function PatientSheet({
  open,
  patientId,
  onClose,
  onSaved,
}: {
  open: boolean;
  patientId: number | null;   // null → create, otherwise edit
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = patientId !== null;
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ ...BLANK });
  const [sessions, setSessions] = useState<PatientSessionInfo[]>([]);
  const [studies, setStudies] = useState<StudySummary[]>([]);
  const [studyOpen, setStudyOpen] = useState(false);

  const reloadStudies = () => {
    if (patientId !== null) api.patientStudies(patientId).then(setStudies).catch(() => {});
  };

  // Load the full record + studies + past sessions when opening in edit mode.
  useEffect(() => {
    if (!open) return;
    setError(null);
    if (patientId === null) {
      setForm({ ...BLANK });
      setSessions([]);
      setStudies([]);
      return;
    }
    setLoading(true);
    Promise.all([api.getPatient(patientId), api.patientSessions(patientId), api.patientStudies(patientId)])
      .then(([p, s, st]) => {
        setForm({
          surname: p.surname ?? "", given_name: p.given_name ?? "", hospital_id: p.hospital_id ?? "",
          sex: p.sex || "F", dob: p.dob ?? "", institution: p.institution ?? "", ocupacion: p.ocupacion ?? "",
          antecedentes_patologicos: p.antecedentes_patologicos ?? "",
          antecedentes_toxicologicos: p.antecedentes_toxicologicos ?? "",
          antecedentes_quirurgicos: p.antecedentes_quirurgicos ?? "",
          antecedentes_alergicos: p.antecedentes_alergicos ?? "",
          antecedentes_farmacologicos: p.antecedentes_farmacologicos ?? "",
          notes: p.notes ?? "",
        });
        setSessions(s);
        setStudies(st);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando el paciente"))
      .finally(() => setLoading(false));
  }, [open, patientId]);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (editing) await api.updatePatient(patientId!, form);
      else await api.createPatient(form);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar el paciente");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
    <Sheet open={open} onClose={onClose} title={editing ? "Editar paciente" : "Nuevo paciente"} width={480}>
      {loading ? (
        <div style={{ fontSize: 13, color: "var(--muted-foreground)", padding: "20px 0" }}>Cargando…</div>
      ) : (
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Input label="Apellidos" placeholder="Restrepo" value={form.surname} onChange={set("surname")} required />
            <Input label="Nombre" placeholder="María" value={form.given_name} onChange={set("given_name")} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Input label="N.º historia clínica" placeholder="HC-00000" value={form.hospital_id} onChange={set("hospital_id")} />
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

          {editing && (
            <div style={{ marginTop: 4 }}>
              <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--muted-foreground)", flex: 1 }}>
                  Casos / estudios ({studies.length})
                </div>
                <button
                  type="button"
                  onClick={() => setStudyOpen(true)}
                  style={{ display: "inline-flex", alignItems: "center", gap: 5, background: "transparent", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "4px 10px", fontSize: 12, fontWeight: 600, color: "var(--brand-deep)", cursor: "pointer" }}
                >
                  <Icon name="STEP_PLAN" size={12} /> Nuevo estudio
                </button>
              </div>
              {studies.length === 0 && (
                <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 4 }}>
                  Aún no hay casos/estudios. Añade uno con "Nuevo estudio".
                </div>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {studies.map((st) => {
                  const mods = [st.mod_tac && "TAC", st.mod_angio && "Angio", st.mod_rm && "RM", st.mod_pangio && "Pangio"].filter(Boolean).join(" · ");
                  return (
                    <Card key={st.id} style={{ padding: "10px 12px" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--foreground)" }}>{st.dx_principal || "Estudio"}</div>
                      <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 4, lineHeight: 1.6 }}>
                        {st.acquired_at && <>Fecha: {st.acquired_at}<br /></>}
                        {st.tipo_aneurisma && <>Tipo: {st.tipo_aneurisma} · </>}
                        {st.region_anatomica && <>{st.region_anatomica} </>}
                        {st.lateralidad && <>({st.lateralidad}) </>}
                        {st.tratamiento_propuesto && <><br />Tratamiento: {st.tratamiento_propuesto}</>}
                        {mods && <><br />Imágenes: {mods}</>}
                        {st.angiographer && <> · Angiógrafo: {st.angiographer}</>}
                      </div>
                    </Card>
                  );
                })}
              </div>
            </div>
          )}

          {editing && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--muted-foreground)", marginBottom: 8 }}>
                Sesiones de estudio ({sessions.length})
              </div>
              {sessions.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
                  Aún no hay sesiones guardadas para este paciente.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {sessions.map((s) => (
                    <Card key={s.session_id} style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--foreground)", flex: 1 }}>
                          {s.label || `Sesión ${new Date(s.updated_at).toLocaleDateString()}`}
                        </span>
                        {s.rupture_risk_label && (
                          <Badge variant={riskVariant(s.rupture_risk_label as never)}>{s.rupture_risk_label}</Badge>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 4, fontFamily: "var(--font-mono)" }}>
                        {new Date(s.updated_at).toLocaleString()} · Paso: {STEP_LABELS[s.current_step] ?? s.current_step}
                        {s.max_diameter_mm != null && ` · Ø ${s.max_diameter_mm.toFixed(1)} mm`}
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          )}

          <ErrorNote>{error}</ErrorNote>
          <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
            <Button type="submit" style={{ flex: 1 }} disabled={busy || !form.surname}>
              {busy ? "Guardando…" : editing ? "Guardar cambios" : "Crear paciente"}
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>Cancelar</Button>
          </div>
        </form>
      )}
    </Sheet>
    <NuevoEstudioSheet
      open={studyOpen}
      patientId={patientId}
      patientName={form.surname || form.given_name ? `${form.surname}${form.surname && form.given_name ? ", " : ""}${form.given_name}` : undefined}
      onClose={() => setStudyOpen(false)}
      onCreated={reloadStudies}
    />
    </>
  );
}

function DeleteConfirm({
  patient,
  onCancel,
  onConfirm,
}: {
  patient: PatientSummary;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <div
      onClick={onCancel}
      style={{ position: "fixed", inset: 0, zIndex: 300, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 380, maxWidth: "90%", background: "var(--card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-lg)", padding: "22px 24px" }}
      >
        <div style={{ fontSize: 16, fontWeight: 800, color: "var(--foreground)" }}>Eliminar paciente</div>
        <div style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.5 }}>
          ¿Seguro que quieres eliminar a <b style={{ color: "var(--foreground)" }}>{patient.full_name}</b>? Se
          borrarán también sus estudios y sesiones de planificación. Esta acción no se puede deshacer.
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 20, justifyContent: "flex-end" }}>
          <Button variant="outline" onClick={onCancel} disabled={busy}>Cancelar</Button>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={async () => { setBusy(true); await onConfirm(); }}
          >
            {busy ? "Eliminando…" : "Eliminar"}
          </Button>
        </div>
      </div>
    </div>
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
  const [sheetPatientId, setSheetPatientId] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [caseSheet, setCaseSheet] = useState(false);
  const [toDelete, setToDelete] = useState<PatientSummary | null>(null);
  const [q, setQ] = useState("");
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [pendingCount, setPendingCount] = useState(0);

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

  const openCreate = () => { setSheetPatientId(null); setSheetOpen(true); };
  const openEdit = (id: number) => { setSheetPatientId(id); setSheetOpen(true); };

  const confirmDelete = async () => {
    if (!toDelete) return;
    try {
      await api.deletePatient(toDelete.id);
      setToDelete(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al eliminar el paciente");
      setToDelete(null);
    }
  };

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

  const iconBtn: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", justifyContent: "center", width: 30, height: 30,
    borderRadius: "var(--radius-md)", border: "1px solid var(--border)", background: "var(--card)", cursor: "pointer",
  };

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
            <Button variant="outline" leadingIcon={<Icon name="STEP_PATIENT" />} onClick={openCreate} style={{ marginRight: 10 }}>
              Nuevo paciente
            </Button>
            <Button leadingIcon={<Icon name="STEP_PLAN" />} onClick={() => setCaseSheet(true)}>
              Nuevo caso
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
                  {["Paciente", "HC", "Sexo / Nac.", "Institución", "Estudios", "Creado", "Acciones"].map((h, i) => (
                    <th
                      key={i}
                      style={{ textAlign: i === 4 ? "center" : i === 6 ? "right" : "left", padding: "11px 16px", background: "var(--muted)", color: "var(--muted-foreground)", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".04em", borderBottom: "1px solid var(--border)" }}
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
                    <td style={{ padding: "8px 16px", textAlign: "right", whiteSpace: "nowrap" }}>
                      <span style={{ display: "inline-flex", gap: 6 }}>
                        <button
                          title="Editar"
                          style={iconBtn}
                          onClick={(e) => { e.stopPropagation(); openEdit(p.id); }}
                          onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--brand-deep)")}
                          onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                        >
                          <Icon name="EDIT" size={14} color="var(--muted-foreground)" />
                        </button>
                        <button
                          title="Eliminar"
                          style={iconBtn}
                          onClick={(e) => { e.stopPropagation(); setToDelete(p); }}
                          onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--destructive, #ef4444)"; e.currentTarget.style.background = "var(--destructive-bg, rgba(239,68,68,0.08))"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.background = "var(--card)"; }}
                        >
                          <span style={{ fontSize: 14, color: "var(--destructive, #ef4444)", lineHeight: 1 }}>✕</span>
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <PatientSheet open={sheetOpen} patientId={sheetPatientId} onClose={() => setSheetOpen(false)} onSaved={load} />
      <NuevoCasoSheet open={caseSheet} onClose={() => setCaseSheet(false)} onCreated={() => load()} />
      {toDelete && <DeleteConfirm patient={toDelete} onCancel={() => setToDelete(null)} onConfirm={confirmDelete} />}
    </div>
  );
}
