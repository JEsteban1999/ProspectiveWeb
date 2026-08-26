/* Nuevo Caso — formulario clínico del caso y selector de paciente.

   El antiguo NuevoCasoSheet (paciente + caso en un solo formulario) se retiró:
   duplicaba pacientes que ya existían. El flujo vivo es CasePatientPicker →
   NuevoEstudioSheet, que adjunta el caso a un paciente existente. */

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import type { PatientSummary, StudyCreate, StudySummary } from "../api/types";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Input } from "../components/Input";
import { Select } from "../components/Select";
import { Sheet } from "../components/Sheet";
import { ErrorNote } from "../components/PanelHead";

const TIPOS = ["", "Sacular", "Fusiforme", "Disecante", "Blíster", "Gigante (> 25 mm)", "Grande (10-25 mm)", "Pequeño (< 10 mm)", "Otro"];
const REGIONES = [
  "", "Arteria cerebral media (ACM)", "Arteria comunicante anterior (AComA)",
  "Arteria comunicante posterior (AComP)", "Arteria carótida interna (ACI)", "Arteria basilar",
  "Arteria cerebelosa posteroinferior (PICA)", "Arteria cerebral anterior (ACA)",
  "Arteria cerebral posterior (ACP)", "Bifurcación carotídea", "Otra",
];
const LATERALIDAD = ["", "Derecha", "Izquierda", "Bilateral", "Línea media"];
const TRATAMIENTOS = ["Clipaje", "Diversor de flujo + Clip", "Coils + Clips"];
const ANGIO_TIPO = ["", "BIPLANO", "MONOPLANO"];
const MODALIDADES: [keyof Mods, string][] = [
  ["tac", "Tomografía (TAC)"], ["angio", "Angiografía"], ["rm", "Resonancia Magnética"], ["pangio", "Panangiografía"],
];

type Mods = { tac: boolean; angio: boolean; rm: boolean; pangio: boolean };

const SECTION: React.CSSProperties = {
  fontSize: 12, fontWeight: 800, letterSpacing: ".03em", color: "var(--foreground)",
  margin: "20px 0 10px", paddingBottom: 6, borderBottom: "1px solid var(--border)",
};
const SUBTLE: React.CSSProperties = { fontSize: 11, color: "var(--muted-foreground)", marginBottom: 8 };

function textarea(value: string, onChange: (v: string) => void, ph: string, disabled = false, rows = 2): React.ReactNode {
  return (
    <textarea
      value={value}
      disabled={disabled}
      rows={rows}
      placeholder={ph}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: "100%", resize: "vertical", fontFamily: "var(--font-sans)", fontSize: 13,
        color: "var(--foreground)", background: disabled ? "var(--muted)" : "var(--card)",
        border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "8px 10px",
        opacity: disabled ? 0.6 : 1,
      }}
    />
  );
}

function checkRow(label: string, checked: boolean, onToggle: (v: boolean) => void, extra?: React.ReactNode): React.ReactNode {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--foreground)", cursor: "pointer" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onToggle(e.target.checked)} />
      <span style={{ minWidth: 150 }}>{label}</span>
      {extra}
    </label>
  );
}

export function NuevoEstudioSheet({
  open, patientId, patientName, study, onClose, onCreated,
}: { open: boolean; patientId: number | null; patientName?: string; study?: StudySummary | null; onClose: () => void; onCreated: () => void }) {
  const editing = !!study;
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({
    study_date: today, sintomas_positivos: "", dx_principal: "", dx_secundario: "",
    tipo_aneurisma: "", region_anatomica: "", lateralidad: "", angio_marca: "", angio_tipo: "",
  });
  const [trat, setTrat] = useState<Record<string, boolean>>(Object.fromEntries(TRATAMIENTOS.map((t) => [t, false])));
  const [mods, setMods] = useState<Mods>({ tac: false, angio: false, rm: false, pangio: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  // Reset (or prefill from `study` when editing) each time it opens.
  useEffect(() => {
    if (!open) return;
    if (study) {
      const [marca, tipo] = (study.angiographer || "").split(" | ");
      setF({
        study_date: study.acquired_at || today,
        sintomas_positivos: study.sintomas_positivos || "",
        dx_principal: study.dx_principal || "",
        dx_secundario: study.dx_secundario || "",
        tipo_aneurisma: study.tipo_aneurisma || "",
        region_anatomica: study.region_anatomica || "",
        lateralidad: study.lateralidad || "",
        angio_marca: marca || "",
        angio_tipo: (tipo || "").trim(),
      });
      const chosen = (study.tratamiento_propuesto || "").split(",").map((s) => s.trim());
      setTrat(Object.fromEntries(TRATAMIENTOS.map((t) => [t, chosen.includes(t)])));
      setMods({ tac: study.mod_tac, angio: study.mod_angio, rm: study.mod_rm, pangio: study.mod_pangio });
    } else {
      setF({ study_date: today, sintomas_positivos: "", dx_principal: "", dx_secundario: "", tipo_aneurisma: "", region_anatomica: "", lateralidad: "", angio_marca: "", angio_tipo: "" });
      setTrat(Object.fromEntries(TRATAMIENTOS.map((t) => [t, false])));
      setMods({ tac: false, angio: false, rm: false, pangio: false });
    }
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, patientId, study]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (patientId === null) return;
    if (!f.dx_principal.trim()) return setError("El diagnóstico principal es obligatorio.");
    const payload: StudyCreate = {
      study_date: f.study_date, sintomas_positivos: f.sintomas_positivos.trim(),
      dx_principal: f.dx_principal.trim(), dx_secundario: f.dx_secundario.trim(),
      tipo_aneurisma: f.tipo_aneurisma, region_anatomica: f.region_anatomica, lateralidad: f.lateralidad,
      tratamiento_propuesto: TRATAMIENTOS.filter((t) => trat[t]).join(", "),
      angiographer: [f.angio_marca.trim(), f.angio_tipo].filter(Boolean).join(" | "),
      mod_tac: mods.tac, mod_angio: mods.angio, mod_rm: mods.rm, mod_pangio: mods.pangio,
    };
    setBusy(true);
    try {
      if (study) await api.updateStudy(patientId, study.id, payload);
      else await api.createStudy(patientId, payload);
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar el estudio");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title={editing ? "Editar caso / estudio" : "Nuevo caso / estudio"} width={520}>
      {patientName && <div style={{ ...SUBTLE, marginBottom: 12 }}>Paciente: <b style={{ color: "var(--foreground)" }}>{patientName}</b></div>}
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Input label="Fecha del caso" type="date" value={f.study_date} onChange={set("study_date")} />

        <div style={SECTION}>Datos clínicos</div>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Síntomas positivos</div>
        {textarea(f.sintomas_positivos, (v) => setF((s) => ({ ...s, sintomas_positivos: v })), "Síntomas actuales, cefalea, déficit neurológico…", false, 3)}
        <div style={{ height: 12 }} />
        <Input label="Diagnóstico principal *" value={f.dx_principal} onChange={set("dx_principal")} placeholder="Diagnóstico principal" />
        <div style={{ height: 12 }} />
        <Input label="Diagnóstico secundario" value={f.dx_secundario} onChange={set("dx_secundario")} placeholder="Diagnóstico secundario (opcional)" />

        <div style={SECTION}>Caracterización aneurismática</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Select label="Tipo de aneurisma" options={TIPOS.map((t) => t || "— seleccionar —")} value={f.tipo_aneurisma || "— seleccionar —"} onChange={(e) => setF((s) => ({ ...s, tipo_aneurisma: e.target.value === "— seleccionar —" ? "" : e.target.value }))} />
          <Select label="Lateralidad" options={LATERALIDAD.map((t) => t || "—")} value={f.lateralidad || "—"} onChange={(e) => setF((s) => ({ ...s, lateralidad: e.target.value === "—" ? "" : e.target.value }))} />
        </div>
        <div style={{ height: 12 }} />
        <Select label="Región anatómica" options={REGIONES.map((t) => t || "— seleccionar —")} value={f.region_anatomica || "— seleccionar —"} onChange={(e) => setF((s) => ({ ...s, region_anatomica: e.target.value === "— seleccionar —" ? "" : e.target.value }))} />
        <div style={{ height: 12 }} />
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>Tratamiento propuesto</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {TRATAMIENTOS.map((t) => checkRow(t, trat[t], (on) => setTrat((s) => ({ ...s, [t]: on }))))}
        </div>

        <div style={SECTION}>Imágenes diagnósticas</div>
        <div style={SUBTLE}>Indique las modalidades del caso. El DICOM se carga en el paso 1 del pipeline al abrir el caso.</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {MODALIDADES.map(([k, label]) => checkRow(label, mods[k], (on) => setMods((s) => ({ ...s, [k]: on }))))}
        </div>
        <div style={{ height: 14 }} />
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Angiógrafo</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 160px", gap: 12 }}>
          <Input label="Marca / modelo" value={f.angio_marca} onChange={set("angio_marca")} placeholder="Marca / modelo" />
          <Select label="Tipo" options={ANGIO_TIPO.map((t) => t || "Tipo")} value={f.angio_tipo || "Tipo"} onChange={(e) => setF((s) => ({ ...s, angio_tipo: e.target.value === "Tipo" ? "" : e.target.value }))} />
        </div>

        <div style={{ height: 14 }} />
        <ErrorNote>{error}</ErrorNote>
        <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
          <Button type="submit" style={{ flex: 1 }} disabled={busy}>{busy ? "Guardando…" : editing ? "Guardar cambios" : "Crear estudio"}</Button>
          <Button type="button" variant="outline" onClick={onClose}>Cancelar</Button>
        </div>
      </form>
    </Sheet>
  );
}

/* Nuevo caso — paso 1: elegir el paciente al que pertenece el caso.
   Un caso se adjunta a UN solo paciente ya registrado; al elegirlo se abre el
   formulario del caso (NuevoEstudioSheet). Si no hay pacientes, invita a crear
   uno primero. Reemplaza al antiguo NuevoCasoSheet (que creaba paciente+caso a
   la vez y duplicaba pacientes). */
export function CasePatientPicker({
  open, patients, onPick, onClose, onCreatePatient,
}: {
  open: boolean;
  patients: PatientSummary[];
  onPick: (p: PatientSummary) => void;
  onClose: () => void;
  onCreatePatient: () => void;
}) {
  const [q, setQ] = useState("");
  const rows = patients.filter(
    (p) =>
      p.full_name.toLowerCase().includes(q.toLowerCase()) ||
      (p.hospital_id || "").toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <Sheet open={open} onClose={onClose} title="Nuevo caso — elegir paciente" width={460}>
      <div style={{ ...SUBTLE, marginBottom: 12 }}>
        Selecciona el paciente al que pertenece este caso. Un caso se adjunta a un solo paciente.
      </div>
      {patients.length === 0 ? (
        <div style={{ textAlign: "center", padding: "20px 0", color: "var(--muted-foreground)", fontSize: 13 }}>
          Aún no hay pacientes registrados.
          <div style={{ marginTop: 14 }}>
            <Button onClick={onCreatePatient} leadingIcon={<Icon name="STEP_PATIENT" size={14} />}>
              Crear el primer paciente
            </Button>
          </div>
        </div>
      ) : (
        <>
          <Input placeholder="Buscar por nombre o N.º de historia…" value={q} onChange={(e) => setQ(e.target.value)} />
          <div style={{ height: 10 }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 320, overflowY: "auto" }}>
            {rows.length === 0 && (
              <div style={{ fontSize: 13, color: "var(--muted-foreground)", padding: "8px 2px" }}>
                Ningún paciente coincide con la búsqueda.
              </div>
            )}
            {rows.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onPick(p)}
                style={{
                  display: "flex", alignItems: "center", gap: 10, textAlign: "left", cursor: "pointer",
                  padding: "10px 12px", borderRadius: "var(--radius-md)", border: "1px solid var(--border)",
                  background: "var(--card)", fontFamily: "var(--font-sans)",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--brand-deep)")}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--foreground)" }}>{p.full_name}</div>
                  <div style={{ fontSize: 11, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)" }}>
                    {p.hospital_id || "sin HC"} · {p.sex || "—"} · {p.study_count} {p.study_count === 1 ? "caso" : "casos"}
                  </div>
                </div>
                <Icon name="STEP_PLAN" size={14} color="var(--muted-foreground)" />
              </button>
            ))}
          </div>
          <div style={{ height: 14 }} />
          <Button type="button" variant="outline" onClick={onCreatePatient} leadingIcon={<Icon name="STEP_PATIENT" size={14} />}>
            + Nuevo paciente
          </Button>
        </>
      )}
    </Sheet>
  );
}
