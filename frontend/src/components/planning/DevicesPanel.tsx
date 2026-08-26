/* Paso 6 — Planificación de dispositivos.
   Clips: GET /api/clips/recommendations · POST /api/clips/plan
   Coils: GET /api/coils · POST /api/coils/plan
   Stents: GET /api/stents · POST /api/plan */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type {
  ClipPlanResult,
  CustomClipInfo,
  DeviceKind,
  ClipRecommendation,
  ClStentResult,
  CoilLibraryItem,
  CoilPlanResult,
  MorphometryResult,
  Position3D,
  StentLibraryItem,
  StentPlanResult,
} from "../../api/types";
import { Button } from "../Button";
import { Icon } from "../Icon";
import { Metric } from "../Metric";
import { PanelHead, SectionLabel, ErrorNote, Card } from "../PanelHead";
import { Select } from "../Select";
import { Slider } from "../Slider";
import { Tabs } from "../Tabs";
import { usePlanning } from "../../store/planning";

const TABS = ["Clips", "Coils", "Stents", "Stent CL"] as const;
const ORIGIN: Position3D = { x: 0, y: 0, z: 0 };

/** Take a placed device family off the plan: its mesh AND the record the report
    reads. Clearing only one of the two leaves a plan that contradicts itself —
    a device drawn but not reported, or reported but not drawn. */
function useClearDevice(kind: DeviceKind) {
  const { sessionId, deviceMeshes, clearDeviceMeshes } = usePlanning();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const placed = !!deviceMeshes[kind];

  const clear = async (after?: () => void) => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      await api.clearDevices(sessionId, kind);
      clearDeviceMeshes(kind);
      after?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo limpiar el dispositivo");
    } finally {
      setBusy(false);
    }
  };
  return { placed, busy, error, clear };
}

/** Uniform «Limpiar» control for the device tabs. */
function ClearDeviceButton({
  label, disabled, busy, onClick,
}: { label: string; disabled: boolean; busy: boolean; onClick: () => void }) {
  return (
    <Button
      variant="outline"
      style={{ marginTop: 8, width: "100%" }}
      disabled={disabled || busy}
      onClick={onClick}
      leadingIcon={<Icon name="CLEAR" size={14} />}
    >
      {busy ? "Limpiando…" : label}
    </Button>
  );
}

/** Where to place a clip/stent: the neck centre the backend measured, with the
    principal axis as the neck-plane normal.

    The backend already knows this point exactly (it is the same one the
    perforator analysis uses). Approximating it here as centroid − axis·(dome/2)
    landed on the parent vessel instead — 0 % neck coverage — and collapsed onto
    the centroid, inside the dome, whenever the dome height was not measured.
    The approximation survives only as a fallback for older sessions whose
    morphometry predates `neck_origin`. */
function neckPlacement(m: MorphometryResult | null): { position: Position3D; normal: number[] } {
  const ax = m?.principal_axis;
  const normal = ax && ax.length === 3 ? ax : [0, 0, 1];

  if (m?.neck_origin) return { position: { ...m.neck_origin }, normal };

  const c = m?.centroid;
  const dh = m?.dome_height_mm ?? 0;
  if (c && ax && ax.length === 3) {
    return {
      position: { x: c.x - (ax[0] * dh) / 2, y: c.y - (ax[1] * dh) / 2, z: c.z - (ax[2] * dh) / 2 },
      normal,
    };
  }
  return { position: ORIGIN, normal };
}

/* ── Clips ─────────────────────────────────────────────────────────────── */
interface PlacedClip {
  key: number;
  clip_id: string;
  name: string;
  position: Position3D;
  rotation_deg: number;
}

/** Compact numeric field for live clip repositioning. */
function NumField({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1, minWidth: 0 }}>
      <span style={{ fontSize: 10, color: "var(--muted-foreground)", textTransform: "uppercase", letterSpacing: ".04em" }}>{label}</span>
      <input
        type="number" value={Number.isFinite(value) ? value : 0} step={step}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        style={{ width: "100%", fontSize: 12, fontFamily: "var(--font-mono)", padding: "4px 6px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--card)", color: "var(--foreground)" }}
      />
    </label>
  );
}

function ClipsTab() {
  const { sessionId, morphometry, setDeviceMesh } = usePlanning();
  const clearer = useClearDevice("clips");
  const [recs, setRecs] = useState<ClipRecommendation[]>([]);
  const [customs, setCustoms] = useState<CustomClipInfo[]>([]);
  const [sel, setSel] = useState<string>("");
  const [placed, setPlaced] = useState<PlacedClip[]>([]);
  const [plan, setPlan] = useState<ClipPlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const nextKey = useRef(1);

  useEffect(() => {
    if (!sessionId) return;
    api.clipRecommendations(sessionId)
      .then((r) => { setRecs(r); if (r.length > 0 && !sel) setSel(r[0].clip_id); })
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando recomendaciones"));
    // Imported clips live in the session directory, but the browser forgets them
    // on resume — the dropdown lost geometry that was still on disk.
    api.listCustomClips(sessionId).then(setCustoms).catch(() => { /* none imported */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const removeCustom = async (clipId: string) => {
    if (!sessionId) return;
    setError(null);
    try {
      const rest = await api.deleteCustomClip(sessionId, clipId);
      setCustoms(rest);
      if (sel === clipId) setSel(recs[0]?.clip_id ?? rest[0]?.clip_id ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo quitar el clip importado");
    }
  };

  const options = useMemo(() => [
    ...recs.map((r) => ({ value: r.clip_id, label: `${r.clip_name} · ${(r.score * 100).toFixed(0)}` })),
    ...customs.map((c) => ({ value: c.clip_id, label: `★ ${c.name} (personalizado)` })),
  ], [recs, customs]);

  const nameFor = (clipId: string) =>
    recs.find((r) => r.clip_id === clipId)?.clip_name
    ?? customs.find((c) => c.clip_id === clipId)?.name
    ?? clipId;

  const addClip = () => {
    if (!sel) return;
    const { position } = neckPlacement(morphometry);
    setPlaced((p) => [...p, { key: nextKey.current++, clip_id: sel, name: nameFor(sel), position: { ...position }, rotation_deg: 0 }]);
  };

  const updateClip = (key: number, patch: Partial<PlacedClip>) =>
    setPlaced((p) => p.map((c) => (c.key === key ? { ...c, ...patch } : c)));
  const removeClip = (key: number) => setPlaced((p) => p.filter((c) => c.key !== key));

  const importClip = async (file: File) => {
    if (!sessionId) return;
    setUploading(true);
    setError(null);
    try {
      const info = await api.uploadCustomClip(sessionId, file);
      setCustoms((c) => [...c, info]);
      setSel(info.clip_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error importando el clip");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const place = async () => {
    if (!sessionId || placed.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const { normal } = neckPlacement(morphometry);
      const res = await api.planClips({
        session_id: sessionId,
        placements: placed.map((c) => ({ clip_id: c.clip_id, position: c.position, normal, rotation_deg: c.rotation_deg })),
      });
      setPlan(res);
      setDeviceMesh("clips", res.clips_mesh_url || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al colocar los clips");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 12 }}>
      <SectionLabel>Modelo de clip</SectionLabel>
      {recs.length === 0 && customs.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", padding: "8px 0" }}>
          {morphometry?.reliable
            ? "Sin recomendación automática de clip para esta geometría. Elige un modelo del catálogo o importa un clip."
            : "Marca el plano de cuello en Morfometría (para obtener cuello y AR) o importa un clip."}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Select label={`Catálogo + personalizados (${options.length})`} options={options} value={sel} onChange={(e) => setSel(e.target.value)} />
        </div>
        <Button size="sm" onClick={addClip} disabled={!sel} leadingIcon={<Icon name="CLIP_PLACE" size={14} />}>Añadir</Button>
      </div>
      <input ref={fileRef} type="file" accept=".stl,.obj" style={{ display: "none" }} onChange={(e) => { const f = e.target.files?.[0]; if (f) void importClip(f); }} />
      <button
        onClick={() => fileRef.current?.click()} disabled={uploading}
        style={{ width: "100%", padding: "7px 10px", fontSize: 12, fontWeight: 600, cursor: uploading ? "wait" : "pointer", borderRadius: "var(--radius-md)", border: "1px dashed var(--border)", background: "transparent", color: "var(--brand-deep)", marginBottom: customs.length ? 8 : 12 }}
      >
        {uploading ? "Importando…" : "＋ Importar clip personalizado (STL/OBJ)"}
      </button>
      {/* Without a way out, importing the wrong file left it in the dropdown for
          the rest of the session. */}
      {customs.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
          {customs.map((c) => (
            <div key={c.clip_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: "var(--radius-md)", border: "1px solid var(--border)", background: "var(--card)" }}>
              <Icon name="CLIPS" size={12} color="var(--muted-foreground)" />
              <span className="truncate" style={{ flex: 1, fontSize: 12, color: "var(--foreground)" }}>{c.name}</span>
              <button
                onClick={() => void removeCustom(c.clip_id)}
                title="Quitar del catálogo"
                style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--muted-foreground)", fontSize: 13, lineHeight: 1, padding: 2 }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {placed.length > 0 && (
        <>
          <SectionLabel>Clips colocados ({placed.length})</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
            {placed.map((c, i) => (
              <Card key={c.key} style={{ padding: "10px 12px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "var(--foreground)", flex: 1 }}>#{i + 1} · {c.name}</span>
                  <button onClick={() => removeClip(c.key)} title="Quitar" style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--destructive, #ef4444)", fontSize: 14 }}>✕</button>
                </div>
                <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                  <NumField label="X" value={c.position.x} onChange={(v) => updateClip(c.key, { position: { ...c.position, x: v } })} />
                  <NumField label="Y" value={c.position.y} onChange={(v) => updateClip(c.key, { position: { ...c.position, y: v } })} />
                  <NumField label="Z" value={c.position.z} onChange={(v) => updateClip(c.key, { position: { ...c.position, z: v } })} />
                  <NumField label="Rot°" value={c.rotation_deg} onChange={(v) => updateClip(c.key, { rotation_deg: v })} step={5} />
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {plan && (
        <Card style={{ marginTop: 14 }}>
          <Metric label="Cobertura de cuello" value={plan.neck_coverage_pct.toFixed(1)} unit=" %" badge={plan.neck_coverage_pct >= 95 ? ["Óptimo", "success"] : ["Parcial", "warning"]} />
          <Metric label="Colisión clip–vaso" value={plan.collision_detected ? "Sí" : "No"} badge={plan.collision_detected ? ["Colisión", "destructive"] : ["OK", "success"]} />
          {plan.warning && <div style={{ marginTop: 8, fontSize: 12, color: "var(--warning)" }}>{plan.warning}</div>}
        </Card>
      )}
      <ErrorNote>{error}</ErrorNote>

      <Button style={{ marginTop: 14, width: "100%" }} onClick={() => void place()} disabled={busy || placed.length === 0} leadingIcon={<Icon name="CLIP_PLACE" />}>
        {busy ? "Verificando…" : `Colocar ${placed.length || ""} y verificar`}
      </Button>
      {/* Removing a clip from the list above only changes what the NEXT «Colocar»
          will send; the clips already placed stay in the scene and in the report
          until they are cleared here. */}
      <ClearDeviceButton
        label="Limpiar clips colocados"
        disabled={!clearer.placed && !plan}
        busy={clearer.busy}
        onClick={() => void clearer.clear(() => { setPlan(null); setPlaced([]); })}
      />
      <ErrorNote>{clearer.error}</ErrorNote>
    </div>
  );
}

/* ── Coils ─────────────────────────────────────────────────────────────── */
function CoilsTab() {
  const { sessionId, morphometry, setDeviceMesh } = usePlanning();
  const clearer = useClearDevice("coils");
  const [coils, setCoils] = useState<CoilLibraryItem[]>([]);
  const [sel, setSel] = useState("");
  const [count, setCount] = useState(3);
  const [plan, setPlan] = useState<CoilPlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCoils()
      .then((c) => {
        setCoils(c);
        if (c.length > 0) setSel(c[0].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando catálogo de coils"));
  }, []);

  const options = useMemo(
    () =>
      coils.map((c) => ({
        value: c.id,
        label: `${c.name} — ${c.diameter_mm} mm × ${c.length_cm} cm (${c.coil_type})`,
      })),
    [coils]
  );

  const run = async () => {
    if (!sessionId || !sel) return;
    setBusy(true);
    setError(null);
    try {
      const position = morphometry?.centroid ?? ORIGIN;
      const placements = Array.from({ length: count }, () => ({
        coil_id: sel,
        position,
        packing_density: 0,
      }));
      const res = await api.planCoils(sessionId, placements);
      setPlan(res);
      setDeviceMesh("coils", res.coils_mesh_url || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en el plan de coils");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 12 }}>
      <Select label={`Catálogo (${coils.length} modelos)`} options={options} value={sel} onChange={(e) => setSel(e.target.value)} />
      <div style={{ height: 14 }} />
      <Slider label="Número de coils" min={1} max={8} value={count} onChange={setCount} />

      {plan && (
        <Card style={{ marginTop: 14 }}>
          <Metric
            label="Densidad de empaque"
            value={(plan.total_packing_density * 100).toFixed(1)}
            unit=" %"
            badge={plan.total_packing_density >= 0.2 ? ["Óptimo", "success"] : ["Insuficiente", "warning"]}
          />
          <Metric label="Oclusión estimada" value={plan.estimated_occlusion_pct.toFixed(0)} unit=" %" />
          {plan.warning && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--warning)" }}>{plan.warning}</div>
          )}
        </Card>
      )}
      <ErrorNote>{error}</ErrorNote>

      <Button style={{ marginTop: 14, width: "100%" }} onClick={() => void run()} disabled={busy || !sel} leadingIcon={<Icon name="COIL" />}>
        {busy ? "Calculando…" : "Calcular empaque"}
      </Button>
      <ClearDeviceButton
        label="Limpiar coils"
        disabled={!clearer.placed && !plan}
        busy={clearer.busy}
        onClick={() => void clearer.clear(() => setPlan(null))}
      />
      <ErrorNote>{clearer.error}</ErrorNote>
    </div>
  );
}

/* ── Stents ────────────────────────────────────────────────────────────── */
function StentsTab() {
  const { sessionId, morphometry, setDeviceMesh } = usePlanning();
  const clearer = useClearDevice("stent");
  const [stents, setStents] = useState<StentLibraryItem[]>([]);
  const [sel, setSel] = useState("");
  const [diameter, setDiameter] = useState(4);
  const [length, setLength] = useState(20);
  const [plan, setPlan] = useState<StentPlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listStents()
      .then((s) => {
        setStents(s);
        if (s.length > 0) setSel(s[0].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando catálogo de stents"));
  }, []);

  const current = stents.find((s) => s.id === sel);

  const run = async () => {
    if (!sessionId || !current) return;
    setBusy(true);
    setError(null);
    try {
      const { position } = neckPlacement(morphometry);
      const res = await api.planStent(sessionId, {
        stent_id: current.id,
        diameter_mm: diameter,
        length_mm: length,
        position,
        rotation_deg: 0,
      });
      setPlan(res);
      setDeviceMesh("stent", res.stent_mesh_url || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en el despliegue del stent");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 12 }}>
      <Select
        label={`Stent / desviador de flujo (${stents.length} modelos)`}
        options={stents.map((s) => ({ value: s.id, label: `${s.name} — ${s.manufacturer} (${s.type})` }))}
        value={sel}
        onChange={(e) => {
          setSel(e.target.value);
          const st = stents.find((x) => x.id === e.target.value);
          if (st) {
            setDiameter(Math.min(Math.max(diameter, st.min_diameter_mm), st.max_diameter_mm));
            if (!st.available_lengths_mm.includes(length)) setLength(st.available_lengths_mm[0]);
          }
        }}
      />
      {current && (
        <>
          <div style={{ height: 14 }} />
          <Slider
            label="Diámetro nominal"
            min={current.min_diameter_mm}
            max={current.max_diameter_mm}
            step={0.25}
            value={diameter}
            onChange={setDiameter}
            unit=" mm"
          />
          <div style={{ height: 14 }} />
          <Select
            label="Longitud"
            options={current.available_lengths_mm.map((l) => ({ value: String(l), label: `${l} mm` }))}
            value={String(length)}
            onChange={(e) => setLength(Number(e.target.value))}
          />
        </>
      )}

      {plan && (
        <Card style={{ marginTop: 14 }}>
          <Metric
            label="Cobertura de cuello"
            value={plan.coverage_pct.toFixed(1)}
            unit=" %"
            badge={plan.coverage_pct >= 30 ? ["Óptimo", "success"] : ["Baja", "warning"]}
          />
          <Metric label="Cuello cubierto" value={plan.neck_diameter_covered_mm.toFixed(1)} unit=" mm" />
          <Metric
            label="Despliegue"
            value={plan.deployed ? "OK" : "Incompatible"}
            badge={plan.deployed ? ["OK", "success"] : ["Revisar", "destructive"]}
          />
          {plan.warning && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--warning)" }}>{plan.warning}</div>
          )}
        </Card>
      )}
      <ErrorNote>{error}</ErrorNote>

      <Button style={{ marginTop: 14, width: "100%" }} onClick={() => void run()} disabled={busy || !current} leadingIcon={<Icon name="STENT" />}>
        {busy ? "Desplegando…" : "Desplegar y evaluar"}
      </Button>
      {/* One stent record per session: this also clears a centreline-guided stent. */}
      <ClearDeviceButton
        label="Retirar stent"
        disabled={!clearer.placed && !plan}
        busy={clearer.busy}
        onClick={() => void clearer.clear(() => setPlan(null))}
      />
      <ErrorNote>{clearer.error}</ErrorNote>
    </div>
  );
}

/* ── Stent guiado por centerline ───────────────────────────────────────── */
function ClStentTab() {
  const { sessionId, centerlineMesh, centerlineArcMm, setDeviceMesh } = usePlanning();
  const clearer = useClearDevice("stent");
  const [diameter, setDiameter] = useState(4);
  const [startArc, setStartArc] = useState(0);
  const [endArc, setEndArc] = useState(0);
  const [braid, setBraid] = useState(true);
  const [plan, setPlan] = useState<ClStentResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const total = centerlineArcMm ?? 0;
  const hasCenterline = !!centerlineMesh && total > 0;

  // Default the range to the full centreline once it's known.
  useEffect(() => {
    if (total > 0) { setStartArc(0); setEndArc(Math.round(total)); }
  }, [total]);

  const run = async () => {
    if (!sessionId || !hasCenterline) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.deployClStent(sessionId, {
        session_id: sessionId,
        stent_diameter_mm: diameter,
        start_arc_mm: startArc,
        end_arc_mm: endArc,
        braid,
        braid_count: 6,
      });
      setPlan(res);
      setDeviceMesh("stent", res.stent_mesh_url || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desplegando el stent");
    } finally {
      setBusy(false);
    }
  };

  if (!hasCenterline) {
    return (
      <div style={{ marginTop: 12, fontSize: 12, color: "var(--muted-foreground)", lineHeight: 1.6 }}>
        Extrae primero la <b style={{ color: "var(--foreground)" }}>línea central</b> del vaso
        (paso Morfometría → Línea central). El stent se desplegará siguiendo su curvatura,
        a diferencia del stent recto de la pestaña «Stents».
      </div>
    );
  }

  return (
    <div style={{ marginTop: 12 }}>
      <SectionLabel>Segmento de la línea central</SectionLabel>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", margin: "6px 0 12px" }}>
        Arco total: <b style={{ color: "var(--foreground)", fontFamily: "var(--font-mono)" }}>{total.toFixed(1)} mm</b>.
        Ajusta el tramo a cubrir.
      </div>
      <Slider label="Inicio del tramo" min={0} max={Math.round(total)} value={startArc} onChange={(v) => setStartArc(Math.min(v, endArc - 1))} unit=" mm" />
      <div style={{ height: 14 }} />
      <Slider label="Fin del tramo" min={0} max={Math.round(total)} value={endArc} onChange={(v) => setEndArc(Math.max(v, startArc + 1))} unit=" mm" />
      <div style={{ height: 14 }} />
      <Slider label="Diámetro nominal" min={1.5} max={6} step={0.25} value={diameter} onChange={setDiameter} unit=" mm" />
      <div style={{ height: 12 }} />
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--foreground)", cursor: "pointer" }}>
        <input type="checkbox" checked={braid} onChange={(e) => setBraid(e.target.checked)} />
        Trenzado helicoidal (aspecto de desviador de flujo)
      </label>

      {plan && (
        <Card style={{ marginTop: 14 }}>
          <Metric label="Longitud desplegada" value={plan.length_mm.toFixed(1)} unit=" mm" />
          <Metric label="Ø stent" value={plan.nominal_diameter_mm.toFixed(2)} unit=" mm" />
          <Metric label="Ø vaso medio" value={plan.mean_vessel_diameter_mm.toFixed(2)} unit=" mm" />
          <Metric
            label="Cobertura (stent/vaso)"
            value={plan.coverage_ratio.toFixed(2)}
            badge={plan.coverage_ratio >= 0.9 && plan.coverage_ratio <= 1.15 ? ["Buen ajuste", "success"] : ["Revisar", "warning"]}
          />
          {plan.warning && <div style={{ marginTop: 8, fontSize: 12, color: "var(--warning)" }}>{plan.warning}</div>}
        </Card>
      )}
      <ErrorNote>{error}</ErrorNote>

      <Button style={{ marginTop: 14, width: "100%" }} onClick={() => void run()} disabled={busy} leadingIcon={<Icon name="STENT" />}>
        {busy ? "Desplegando…" : "Desplegar sobre la línea central"}
      </Button>
      <ClearDeviceButton
        label="Retirar stent"
        disabled={!clearer.placed && !plan}
        busy={clearer.busy}
        onClick={() => void clearer.clear(() => setPlan(null))}
      />
      <ErrorNote>{clearer.error}</ErrorNote>
    </div>
  );
}

/* ── Trayectoria de abordaje quirúrgico ────────────────────────────────── */
function TrajectoryTool() {
  const {
    sessionId, segmentation, pickMode, setPickMode,
    trajEntry, trajTarget, setTrajEntry, setTrajTarget,
  } = usePlanning();
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<{ depth: number; angle: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const hasMesh = !!segmentation?.mesh_url;
  const depth = trajEntry && trajTarget
    ? Math.hypot(trajTarget[0] - trajEntry[0], trajTarget[1] - trajEntry[1], trajTarget[2] - trajEntry[2])
    : null;

  const save = async () => {
    if (!sessionId || !trajEntry || !trajTarget) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.setTrajectory(sessionId, {
        entry: { x: trajEntry[0], y: trajEntry[1], z: trajEntry[2] },
        target: { x: trajTarget[0], y: trajTarget[1], z: trajTarget[2] },
      });
      setSaved({ depth: res.depth_mm, angle: res.angle_deg });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar la trayectoria");
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setTrajEntry(null);
    setTrajTarget(null);
    setSaved(null);
    setPickMode(null);
    if (sessionId) { try { await api.clearTrajectory(sessionId); } catch { /* ignore */ } }
  };

  const pickBtn = (which: "traj_entry" | "traj_target", label: string, done: boolean) => {
    const active = pickMode === which;
    return (
      <Button
        variant={active ? "default" : "outline"} size="sm" style={{ flex: 1 }}
        disabled={!hasMesh}
        onClick={() => setPickMode(active ? null : which)}
        leadingIcon={<Icon name={done ? "STATUS_OK" : "TRAJECTORY"} size={14} />}
      >
        {active ? "Clic en el visor…" : label}
      </Button>
    );
  };

  return (
    <Card style={{ marginBottom: 16, padding: "14px 16px" }}>
      <SectionLabel>Trayectoria de abordaje</SectionLabel>
      <div style={{ fontSize: 12, color: "var(--muted-foreground)", margin: "6px 0 10px" }}>
        Marca el punto de entrada y el aneurisma; el corredor se muestra en el visor y se
        incluye en el informe.
      </div>
      {!hasMesh && (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", marginBottom: 8 }}>
          Segmenta el vaso primero para marcar puntos sobre él.
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        {pickBtn("traj_entry", "Entrada", !!trajEntry)}
        {pickBtn("traj_target", "Diana", !!trajTarget)}
      </div>
      {depth !== null && (
        <div style={{ fontSize: 12, color: "var(--foreground)", marginBottom: 10 }}>
          Profundidad de abordaje: <b style={{ fontFamily: "var(--font-mono)" }}>{depth.toFixed(1)} mm</b>
          {saved && <> · Ángulo: <b style={{ fontFamily: "var(--font-mono)" }}>{saved.angle.toFixed(1)}°</b></>}
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>
      <div style={{ display: "flex", gap: 8 }}>
        <Button size="sm" style={{ flex: 1 }} disabled={busy || !trajEntry || !trajTarget} onClick={() => void save()} leadingIcon={<Icon name="SAVE" size={14} />}>
          {busy ? "Guardando…" : saved ? "Guardada ✓" : "Guardar trayectoria"}
        </Button>
        <Button size="sm" variant="outline" disabled={!trajEntry && !trajTarget} onClick={() => void clear()}>
          Limpiar
        </Button>
      </div>
    </Card>
  );
}

/* ── Dispositivos en el plan ───────────────────────────────────────────── */

const KIND_LABEL: Record<DeviceKind, string> = {
  clips: "Clips", coils: "Coils", stent: "Stent",
};

/** What the PDF report and the DICOM SR will actually list, above the tabs.
 *
 *  Each tab only knows about its own device, so a plan holding a clip AND a
 *  stent looked like whichever tab was open. This is the one place that says
 *  what the plan really contains — and lets it be emptied in one action. */
function PlacedDevicesBar() {
  const { sessionId, deviceMeshes, setDeviceMesh, clearDeviceMeshes } = usePlanning();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A resumed session rebuilds the store from scratch, so ask the backend what
  // it still has on record — otherwise the devices are in the report but not in
  // the viewer, and there is nothing to clear.
  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    api.placedDevices(sessionId)
      .then((r) => {
        if (!alive) return;
        for (const kind of r.remaining) {
          const url = r.mesh_urls[kind];
          if (url) setDeviceMesh(kind, url);
        }
      })
      .catch(() => { /* nothing placed, or the session is gone */ });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const placed = (Object.keys(KIND_LABEL) as DeviceKind[]).filter((k) => !!deviceMeshes[k]);

  const clearAll = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      await api.clearDevices(sessionId);
      clearDeviceMeshes();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron limpiar los dispositivos");
    } finally {
      setBusy(false);
    }
  };

  if (placed.length === 0) return null;

  return (
    <Card style={{ marginBottom: 14, padding: "12px 14px" }}>
      <SectionLabel style={{ marginBottom: 8 }}>En el plan ({placed.length})</SectionLabel>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {placed.map((k) => (
          <span
            key={k}
            style={{
              fontSize: 11, fontWeight: 700, padding: "3px 9px", borderRadius: 999,
              background: "var(--brand-subtle)", color: "var(--brand-subtle-foreground)",
            }}
          >
            {KIND_LABEL[k]}
          </span>
        ))}
      </div>
      <div style={{ fontSize: 11, color: "var(--muted-foreground)", marginBottom: 10, lineHeight: 1.5 }}>
        Estos dispositivos se dibujan en el visor y aparecen en el informe. Límpialos
        para probar otra estrategia sin que se acumulen.
      </div>
      <Button
        variant="outline" size="sm" style={{ width: "100%" }}
        disabled={busy} onClick={() => void clearAll()}
        leadingIcon={<Icon name="CLEAR" size={14} />}
      >
        {busy ? "Limpiando…" : "Limpiar todos los dispositivos"}
      </Button>
      <ErrorNote>{error}</ErrorNote>
    </Card>
  );
}

/* ── Panel ─────────────────────────────────────────────────────────────── */
export function DevicesPanel({ onNext }: { onNext: () => void }) {
  const [tab, setTab] = useState<string>("Clips");
  return (
    <div className="fade-rise">
      <PanelHead title="Planificación de dispositivos" desc="Elige clip, coils o stent del catálogo y verifica su colocación." />
      <TrajectoryTool />
      <PlacedDevicesBar />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === "Clips" && <ClipsTab />}
      {tab === "Coils" && <CoilsTab />}
      {tab === "Stents" && <StentsTab />}
      {tab === "Stent CL" && <ClStentTab />}
      <Button variant="outline" style={{ marginTop: 18, width: "100%" }} onClick={onNext} trailingIcon={<Icon name="STEP_EXPORT" />}>
        Continuar al informe
      </Button>
    </div>
  );
}
