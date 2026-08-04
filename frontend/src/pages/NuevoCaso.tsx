/* Nuevo Caso — full clinical-case form (patient + study), porting the desktop
   nuevo_caso_dialog.py: 5 sections. Creates both records via POST /patients/case.
   DICOM is uploaded later in the pipeline (section 5 records which modalities). */

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import type { CaseCreate, PatientSummary } from "../api/types";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { Select } from "../components/Select";
import { Sheet } from "../components/Sheet";
import { ErrorNote } from "../components/PanelHead";

const SEX_OPTS = ["—", "Masculino", "Femenino", "Otro"];
const SEX_VAL: Record<string, string> = { "—": "", Masculino: "M", Femenino: "F", Otro: "O" };
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
const ANTECEDENTES: [string, string][] = [
  ["patologicos", "Patológicos"], ["toxicologicos", "Toxicológicos"], ["quirurgicos", "Quirúrgicos"],
  ["alergicos", "Alérgicos"], ["farmacologicos", "Farmacológicos"],
];
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

export function NuevoCasoSheet({
  open, onClose, onCreated,
}: { open: boolean; onClose: () => void; onCreated: (p: PatientSummary) => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({
    given_name: "", surname: "", hospital_id: "", dob: "", sex: "—", ocupacion: "", institution: "",
    study_date: today, sintomas_positivos: "", dx_principal: "", dx_secundario: "",
    tipo_aneurisma: "", region_anatomica: "", lateralidad: "", angio_marca: "", angio_tipo: "",
  });
  const [ant, setAnt] = useState<Record<string, { on: boolean; text: string }>>(
    Object.fromEntries(ANTECEDENTES.map(([k]) => [k, { on: false, text: "" }])),
  );
  const [trat, setTrat] = useState<Record<string, boolean>>(
    Object.fromEntries(TRATAMIENTOS.map((t) => [t, false])),
  );
  const [mods, setMods] = useState<Mods>({ tac: false, angio: false, rm: false, pangio: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  const edad = useMemo(() => {
    if (!f.dob) return "—";
    const d = new Date(f.dob);
    if (isNaN(d.getTime())) return "—";
    const now = new Date();
    let a = now.getFullYear() - d.getFullYear();
    const m = now.getMonth() - d.getMonth();
    if (m < 0 || (m === 0 && now.getDate() < d.getDate())) a -= 1;
    return a >= 0 && a < 150 ? `${a} años` : "—";
  }, [f.dob]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!f.given_name.trim() && !f.surname.trim()) return setError("El nombre del paciente es obligatorio.");
    if (!f.hospital_id.trim()) return setError("La cédula / NHC es obligatoria.");
    if (!f.dx_principal.trim()) return setError("El diagnóstico principal es obligatorio.");

    const payload: CaseCreate = {
      surname: f.surname.trim(), given_name: f.given_name.trim(), hospital_id: f.hospital_id.trim(),
      dob: f.dob, sex: SEX_VAL[f.sex] ?? "", institution: f.institution.trim(), ocupacion: f.ocupacion.trim(),
      antecedentes_patologicos: ant.patologicos.on ? ant.patologicos.text.trim() : "",
      antecedentes_toxicologicos: ant.toxicologicos.on ? ant.toxicologicos.text.trim() : "",
      antecedentes_quirurgicos: ant.quirurgicos.on ? ant.quirurgicos.text.trim() : "",
      antecedentes_alergicos: ant.alergicos.on ? ant.alergicos.text.trim() : "",
      antecedentes_farmacologicos: ant.farmacologicos.on ? ant.farmacologicos.text.trim() : "",
      study_date: f.study_date,
      sintomas_positivos: f.sintomas_positivos.trim(),
      dx_principal: f.dx_principal.trim(), dx_secundario: f.dx_secundario.trim(),
      tipo_aneurisma: f.tipo_aneurisma, region_anatomica: f.region_anatomica, lateralidad: f.lateralidad,
      tratamiento_propuesto: TRATAMIENTOS.filter((t) => trat[t]).join(", "),
      angiographer: [f.angio_marca.trim(), f.angio_tipo].filter(Boolean).join(" | "),
      mod_tac: mods.tac, mod_angio: mods.angio, mod_rm: mods.rm, mod_pangio: mods.pangio,
    };
    setBusy(true);
    try {
      const created = await api.createCase(payload);
      onCreated(created);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear el caso");
    } finally {
      setBusy(false);
    }
  };

  const checkRow = (label: string, checked: boolean, onToggle: (v: boolean) => void, extra?: React.ReactNode) => (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--foreground)", cursor: "pointer" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onToggle(e.target.checked)} />
      <span style={{ minWidth: 150 }}>{label}</span>
      {extra}
    </label>
  );

  return (
    <Sheet open={open} onClose={onClose} title="Nuevo caso" width={560}>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {/* 1. Datos del paciente */}
        <div style={SECTION}>1. Datos del paciente</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Nombres *" value={f.given_name} onChange={set("given_name")} placeholder="María" />
          <Input label="Apellidos *" value={f.surname} onChange={set("surname")} placeholder="Restrepo" />
        </div>
        <div style={{ height: 12 }} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Cédula / NHC *" value={f.hospital_id} onChange={set("hospital_id")} placeholder="HC-00000" />
          <Select label="Sexo" options={SEX_OPTS} value={f.sex} onChange={set("sex")} />
        </div>
        <div style={{ height: 12 }} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 12, alignItems: "end" }}>
          <Input label="Fecha de nacimiento" type="date" value={f.dob} onChange={set("dob")} />
          <div style={{ fontSize: 12, color: "var(--muted-foreground)", paddingBottom: 10 }}>Edad: <b style={{ color: "var(--foreground)" }}>{edad}</b></div>
          <Input label="Fecha del caso" type="date" value={f.study_date} onChange={set("study_date")} />
        </div>
        <div style={{ height: 12 }} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Input label="Ocupación" value={f.ocupacion} onChange={set("ocupacion")} placeholder="Profesión u ocupación" />
          <Input label="Hospital" value={f.institution} onChange={set("institution")} placeholder="Hospital o institución" />
        </div>

        {/* 2. Antecedentes */}
        <div style={SECTION}>2. Antecedentes personales</div>
        <div style={SUBTLE}>Marque la categoría y describa brevemente los antecedentes relevantes.</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {ANTECEDENTES.map(([k, label]) => (
            <div key={k} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {checkRow(label, ant[k].on, (on) => setAnt((s) => ({ ...s, [k]: { ...s[k], on } })))}
              {ant[k].on && textarea(ant[k].text, (text) => setAnt((s) => ({ ...s, [k]: { ...s[k], text } })), `Detalle los antecedentes ${label.toLowerCase()}…`)}
            </div>
          ))}
        </div>

        {/* 3. Datos clínicos */}
        <div style={SECTION}>3. Datos clínicos</div>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Síntomas positivos</div>
        {textarea(f.sintomas_positivos, (v) => setF((s) => ({ ...s, sintomas_positivos: v })), "Síntomas actuales, cefalea, déficit neurológico…", false, 3)}
        <div style={{ height: 12 }} />
        <Input label="Diagnóstico principal *" value={f.dx_principal} onChange={set("dx_principal")} placeholder="Diagnóstico principal" />
        <div style={{ height: 12 }} />
        <Input label="Diagnóstico secundario" value={f.dx_secundario} onChange={set("dx_secundario")} placeholder="Diagnóstico secundario (opcional)" />

        {/* 4. Caracterización aneurismática */}
        <div style={SECTION}>4. Caracterización aneurismática</div>
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

        {/* 5. Imágenes diagnósticas */}
        <div style={SECTION}>5. Imágenes diagnósticas</div>
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
          <Button type="submit" style={{ flex: 1 }} disabled={busy}>
            {busy ? "Creando caso…" : "Crear caso"}
          </Button>
          <Button type="button" variant="outline" onClick={onClose}>Cancelar</Button>
        </div>
      </form>
    </Sheet>
  );
}
