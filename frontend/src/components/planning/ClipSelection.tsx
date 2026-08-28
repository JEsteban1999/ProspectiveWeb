/* Selección de clip — qué sirve para este caso, por qué, o qué hay que fabricar.

   La lista anterior mostraba nombre + un número (0–100). Un número no se puede
   defender delante de un cirujano, así que aquí cada candidato lleva la matriz
   de criterios con la medida que produjo cada veredicto, y los descartados
   llevan la única razón por la que quedaron fuera: saber por qué NO entró un
   clip es lo que hace creíble a los que sí.

   Cuando el inventario no da, el panel no se queda vacío: muestra la ficha de
   fabricación con medidas, forma y fuerza, y deja descargar el STL. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type {
  ClipCandidateOut,
  ClipCriterion,
  ClipSelectionResult,
  ClipVerdict,
  CustomJawOut,
  ManufactureSpecOut,
} from "../../api/types";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { Card, Collapsible, ErrorNote, SectionLabel } from "../PanelHead";
import { Slider } from "../Slider";

const VERDICT_MARK: Record<ClipVerdict, string> = { ok: "✓", warn: "!", fail: "✕" };
const VERDICT_COLOR: Record<ClipVerdict, string> = {
  ok: "var(--success)",
  warn: "var(--warning)",
  fail: "var(--destructive)",
};

/** One criterion as a chip: the mark, the label, and the number behind it. */
function CriterionChip({ c }: { c: ClipCriterion }) {
  return (
    <div
      title={c.detail}
      style={{
        display: "flex", alignItems: "flex-start", gap: 6, fontSize: 11,
        lineHeight: 1.45, padding: "3px 0",
      }}
    >
      <span
        aria-hidden
        style={{
          flex: "0 0 auto", width: 14, height: 14, borderRadius: 4, marginTop: 1,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 10, fontWeight: 800, color: "#fff",
          background: VERDICT_COLOR[c.verdict],
        }}
      >
        {VERDICT_MARK[c.verdict]}
      </span>
      <span style={{ color: "var(--muted-foreground)", minWidth: 0 }}>
        <b style={{ color: "var(--foreground)", fontWeight: 700 }}>{c.label}:</b>{" "}
        {c.detail}
      </span>
    </div>
  );
}

function CandidateCard({
  cand, selected, onSelect,
}: {
  cand: ClipCandidateOut;
  selected: boolean;
  onSelect?: () => void;
}) {
  const fit = cand.fit;
  return (
    <Card
      style={{
        borderColor: selected ? "var(--brand-deep)" : undefined,
        background: selected ? "var(--brand-subtle)" : undefined,
        padding: "12px 14px",
        cursor: onSelect ? "pointer" : "default",
      }}
      onClick={onSelect}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)", flex: 1, minWidth: 0 }}>
          {cand.clip_name}
        </div>
        {/* Que un clip se fabrique para el caso no lo hace peor, pero sí cambia
            la planificación: hay que contar con el plazo. Va junto al nombre,
            no escondido en los criterios. */}
        {cand.availability === "made_to_order" && (
          <Badge variant="subtle">bajo pedido</Badge>
        )}
        <Badge variant={cand.verdict === "ok" ? "success" : cand.verdict === "warn" ? "warning" : "destructive"}>
          {cand.verdict === "ok" ? "Cumple" : cand.verdict === "warn" ? "Con reservas" : "Descartado"}
        </Badge>
      </div>

      <div style={{ fontSize: 11, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", marginTop: 2 }}>
        {cand.shape}
        {cand.bend_angle_deg > 0 && cand.bend_angle_deg !== 45 && cand.bend_angle_deg !== 90
          ? ` ${cand.bend_angle_deg.toFixed(0)}°` : ""}
        {" · mordaza "}{cand.blade_length_mm.toFixed(1)} mm ·{" "}
        {/* Una banda es una banda: quedarse con el punto medio inventaría una
            precisión que la pieza todavía no tiene. */}
        {cand.closing_force_max_g > cand.closing_force_min_g
          ? `${cand.closing_force_min_g.toFixed(0)}–${cand.closing_force_max_g.toFixed(0)} g`
          : `${cand.closing_force_g.toFixed(0)} g`}
        {cand.force_provisional ? " (sin caracterizar)" : ""}
        {cand.manufacturer ? ` · ${cand.manufacturer}` : ""}
      </div>

      {/* Los criterios, cada uno con su medida. Sustituyen a la barra de score:
          «cubre el cuello con 1,8 mm de margen» dice algo; «92,6» no. */}
      <div style={{ marginTop: 8, borderTop: "1px solid var(--border)", paddingTop: 6 }}>
        {cand.criteria.map((c) => <CriterionChip key={c.key} c={c} />)}
      </div>

      {/* Cuántas orientaciones de aplicación libran los vasos vecinos. Un clip
          limpio en 1 de 6 es utilizable, pero exige una precisión que el que
          está limpio en 6 de 6 no pide — y eso no se ve en un score. */}
      {fit && fit.n_rolls > 0 && (
        <div style={{ marginTop: 6, fontSize: 11, color: "var(--muted-foreground)" }}>
          Comprobado sobre la malla del paciente:{" "}
          <b style={{ color: fit.clean_rolls === 0 ? "var(--destructive)" : "var(--foreground)" }}>
            {fit.clean_rolls}/{fit.n_rolls}
          </b>{" "}
          orientaciones sin tocar vasos vecinos · cubre {fit.neck_coverage_pct.toFixed(0)}% del cuello
        </div>
      )}
    </Card>
  );
}

function ManufactureSheet({
  spec, sessionId, caseId,
}: {
  spec: ManufactureSpecOut;
  sessionId: string;
  caseId?: number | null;
}) {
  const [built, setBuilt] = useState<ManufactureSpecOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shown = built ?? spec;

  const rows: [string, string][] = [
    ["Forma", `${shown.shape}${shown.angle_deg ? ` · ${shown.angle_deg.toFixed(0)}°` : ""}`],
    ["Longitud de hoja", `${shown.blade_length_mm.toFixed(1)} mm`],
    ["Anchura de hoja", `${shown.blade_width_mm.toFixed(2)} mm`],
    ["Altura de hoja", `${shown.blade_height_mm.toFixed(2)} mm`],
    ["Longitud de muelle", `${shown.spring_length_mm.toFixed(1)} mm`],
    ["Fuerza de cierre", `${shown.closing_force_g.toFixed(0)} g`],
    ...(shown.fenestration_mm > 0
      ? ([["Ventana (interior)", `${shown.fenestration_mm.toFixed(1)} mm`]] as [string, string][])
      : []),
    ["Cuello medido", `${shown.neck_mm.toFixed(2)} mm`],
  ];

  const generate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setBuilt(await api.clipManufacture(sessionId, caseId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo generar el STL");
    } finally {
      setBusy(false);
    }
  }, [sessionId, caseId]);

  const copy = () => {
    const text = [
      `Clip a medida — ${shown.label}`,
      ...rows.map(([k, v]) => `${k}: ${v}`),
      "",
      "Motivo:",
      ...shown.reasons.map((r) => `- ${r}`),
      "",
      "A confirmar antes de fabricar:",
      ...shown.confidence_notes.map((n) => `- ${n}`),
    ].join("\n");
    void navigator.clipboard?.writeText(text);
  };

  return (
    <Card>
      <div style={{ fontSize: 13, fontWeight: 800, color: "var(--foreground)" }}>
        Clip a medida · {shown.label}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "2px 12px", marginTop: 10 }}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <div style={{ fontSize: 11, color: "var(--muted-foreground)" }}>{k}</div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--foreground)", fontFamily: "var(--font-mono)" }}>
              {v}
            </div>
          </div>
        ))}
      </div>

      {shown.reasons.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <SectionLabel>Por qué no sirve el inventario</SectionLabel>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 11, color: "var(--muted-foreground)", lineHeight: 1.5 }}>
            {shown.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Lo que la ficha NO sabe. Una especificación que esconde sus supuestos
          es peor que una que los declara: aquí es lo que un taller tiene que
          confirmar antes de mecanizar nada. */}
      {shown.confidence_notes.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <SectionLabel>A confirmar antes de fabricar</SectionLabel>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 11, color: "var(--warning)", lineHeight: 1.5 }}>
            {shown.confidence_notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </div>
      )}

      <ErrorNote>{error}</ErrorNote>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <Button size="sm" onClick={() => void generate()} disabled={busy}>
          {busy ? "Generando…" : shown.stl_url ? "Regenerar STL" : "Generar STL"}
        </Button>
        {shown.stl_url && (
          <Button size="sm" variant="ghost" onClick={() => window.open(shown.stl_url!, "_blank")}>
            Descargar STL
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={copy}>Copiar especificación</Button>
      </div>
    </Card>
  );
}

/** A made-to-order clip sized to this case, with a slider to override the jaw.

    These designs are manufactured per case, so the jaw is not restricted to the
    six drawn sizes: an exact one is a real order, not a wish. The system offers
    the size the neck asks for; the surgeon can still dial it by hand, which is
    why the slider exists next to the suggestion rather than instead of it. */
function CustomJawSheet({
  suggestion, sessionId,
}: {
  suggestion: CustomJawOut;
  sessionId: string;
}) {
  const [jaw, setJaw] = useState(suggestion.jaw_mm);
  const [built, setBuilt] = useState<CustomJawOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const build = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setBuilt(await api.buildNavarroClip(sessionId, jaw, suggestion.angle_deg));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo generar el clip");
    } finally {
      setBusy(false);
    }
  }, [sessionId, jaw, suggestion.angle_deg]);

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: "var(--foreground)", flex: 1 }}>
          {suggestion.label}
        </div>
        <Badge variant="subtle">bajo pedido</Badge>
      </div>
      <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 4, lineHeight: 1.5 }}>
        {suggestion.reason}
      </div>

      {/* El Slider del sistema de diseño, no un <input range> suelto: la lectura
          numérica en monoespaciada y el tratamiento del control son los mismos
          que en umbralización y suavizado. */}
      <div style={{ marginTop: 12 }}>
        <Slider
          label="Mordaza (longitud útil de agarre)"
          min={2} max={30} step={0.5} value={jaw} unit=" mm"
          onChange={(v) => { setJaw(v); setBuilt(null); }}
        />
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 4 }}>
          Talla dibujada más cercana: {suggestion.nearest_drawn_mm.toFixed(0)} mm
        </div>
      </div>

      <ErrorNote>{error}</ErrorNote>

      {built && (
        <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginTop: 8, lineHeight: 1.5 }}>
          {built.reason}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <Button size="sm" onClick={() => void build()} disabled={busy}>
          {busy ? "Generando…" : built ? "Regenerar" : "Generar clip"}
        </Button>
        {built?.stl_url && (
          <Button size="sm" variant="ghost" onClick={() => window.open(built.stl_url!, "_blank")}>
            Descargar STL
          </Button>
        )}
      </div>
    </Card>
  );
}

const OUTCOME_STYLE: Record<string, { variant: "success" | "warning" | "destructive" | "subtle"; label: string }> = {
  stock:       { variant: "success",     label: "Hay clip en inventario" },
  marginal:    { variant: "warning",     label: "Utilizable con reservas" },
  manufacture: { variant: "destructive", label: "Requiere fabricación" },
  unmeasured:  { variant: "subtle",      label: "Falta medir el cuello" },
};

export function ClipSelectionPanel({
  sessionId,
  caseId,
  selectedClipId,
  onPick,
}: {
  sessionId: string;
  caseId?: number | null;
  selectedClipId?: string;
  /** Called when the surgeon picks a candidate, so the placement list can use it. */
  onPick?: (clipId: string, clipName: string) => void;
}) {
  const [sel, setSel] = useState<ClipSelectionResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api.clipSelection(sessionId, caseId)
      .then(setSel)
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando la selección de clip"))
      .finally(() => setLoading(false));
  }, [sessionId, caseId]);

  useEffect(load, [load]);

  if (loading) {
    return <div style={{ fontSize: 12, color: "var(--muted-foreground)", padding: "8px 0" }}>Evaluando el catálogo…</div>;
  }
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!sel) return null;

  const style = OUTCOME_STYLE[sel.outcome] ?? OUTCOME_STYLE.unmeasured;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Veredicto primero: lo que hay que saber antes de leer ninguna lista. */}
      <Card style={{ background: "var(--muted)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Badge variant={style.variant}>{style.label}</Badge>
          <Button size="sm" variant="ghost" onClick={load} style={{ marginLeft: "auto" }}>
            Recalcular
          </Button>
        </div>
        <div style={{ fontSize: 12, color: "var(--foreground)", marginTop: 6, lineHeight: 1.5 }}>
          {sel.summary}
        </div>
        {sel.case.neck_mm > 0 && (
          <div style={{ fontSize: 11, color: "var(--muted-foreground)", fontFamily: "var(--font-mono)", marginTop: 4 }}>
            cuello {sel.case.neck_mm.toFixed(2)} mm · AR {sel.case.ar.toFixed(2)}
            {sel.case.parent_artery_mm > 0 && ` · vaso padre ${sel.case.parent_artery_mm.toFixed(2)} mm`}
            {sel.case.region && ` · ${sel.case.region}`}
          </div>
        )}
      </Card>

      {sel.recommended.length > 0 && (
        <div>
          <SectionLabel>Clips recomendados ({sel.recommended.length})</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
            {sel.recommended.map((c) => (
              <CandidateCard
                key={c.clip_id}
                cand={c}
                selected={selectedClipId === c.clip_id}
                onSelect={onPick ? () => onPick(c.clip_id, c.clip_name) : undefined}
              />
            ))}
          </div>
        </div>
      )}

      {/* La opción a medida va ANTES de la ficha genérica de fabricación: es un
          diseño real de la casa, no una especificación desde cero. */}
      {sel.custom_jaw && (
        <div>
          <SectionLabel>Clip a medida sobre un diseño propio</SectionLabel>
          <div style={{ marginTop: 6 }}>
            <CustomJawSheet suggestion={sel.custom_jaw} sessionId={sessionId} />
          </div>
        </div>
      )}

      {sel.manufacture && (
        <div>
          <SectionLabel>
            {sel.outcome === "manufacture" ? "Especificación de fabricación" : "Alternativa a medida"}
          </SectionLabel>
          <div style={{ marginTop: 6 }}>
            <ManufactureSheet spec={sel.manufacture} sessionId={sessionId} caseId={caseId} />
          </div>
        </div>
      )}

      {/* Los que se quedaron cerca. Sin esto la lista de arriba es una caja
          negra: no se puede saber si el catálogo se consideró entero. */}
      {sel.rejected.length > 0 && (
        <Collapsible
          title="Por qué se descartaron otros"
          subtitle={`${sel.rejected.length} clips cercanos, con el motivo de cada uno`}
          storageKey={`clipsel.rejected.${sessionId}`}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sel.rejected.map((c) => <CandidateCard key={c.clip_id} cand={c} selected={false} />)}
          </div>
        </Collapsible>
      )}

      {sel.caveats.length > 0 && (
        <Collapsible
          title="Qué limita esta recomendación"
          subtitle={`${sel.caveats.length} advertencias`}
          storageKey={`clipsel.caveats.${sessionId}`}
          defaultOpen={sel.outcome === "unmeasured"}
        >
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11, color: "var(--muted-foreground)", lineHeight: 1.6 }}>
            {sel.caveats.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </Collapsible>
      )}
    </div>
  );
}
