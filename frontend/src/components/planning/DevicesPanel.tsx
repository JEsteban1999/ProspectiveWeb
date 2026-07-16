/* Paso 6 — Planificación de dispositivos.
   Clips: GET /api/clips/recommendations · POST /api/clips/plan
   Coils: GET /api/coils · POST /api/coils/plan
   Stents: GET /api/stents · POST /api/plan */

import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  ClipPlanResult,
  ClipRecommendation,
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

const TABS = ["Clips", "Coils", "Stents"] as const;
const ORIGIN: Position3D = { x: 0, y: 0, z: 0 };

/** Approximate neck placement from morphometry: neck ≈ centroid − axis·(dome/2),
    with the principal axis as the neck-plane normal. Puts a clip/stent across
    the neck (not inside the dome, which would always collide). */
function neckPlacement(m: MorphometryResult | null): { position: Position3D; normal: number[] } {
  const c = m?.centroid;
  const ax = m?.principal_axis;
  const dh = m?.dome_height_mm ?? 0;
  if (c && ax && ax.length === 3) {
    return {
      position: { x: c.x - (ax[0] * dh) / 2, y: c.y - (ax[1] * dh) / 2, z: c.z - (ax[2] * dh) / 2 },
      normal: ax,
    };
  }
  return { position: ORIGIN, normal: [0, 0, 1] };
}

/* ── Clips ─────────────────────────────────────────────────────────────── */
function ClipsTab() {
  const { sessionId, morphometry, setDeviceMesh } = usePlanning();
  const [recs, setRecs] = useState<ClipRecommendation[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [plan, setPlan] = useState<ClipPlanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    api
      .clipRecommendations(sessionId)
      .then((r) => {
        setRecs(r);
        if (r.length > 0) setSel(r[0].clip_id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error cargando recomendaciones"));
  }, [sessionId]);

  const place = async () => {
    if (!sessionId || !sel) return;
    setBusy(true);
    setError(null);
    try {
      const { position, normal } = neckPlacement(morphometry);
      const res = await api.planClips({
        session_id: sessionId,
        placements: [{ clip_id: sel, position, normal, rotation_deg: 0 }],
      });
      setPlan(res);
      setDeviceMesh(res.clips_mesh_url || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al colocar el clip");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 12 }}>
      <SectionLabel>Recomendaciones (ranking del catálogo)</SectionLabel>
      {recs.length === 0 && !error && (
        <div style={{ fontSize: 12, color: "var(--muted-foreground)", padding: "10px 0" }}>
          Sin recomendaciones — ejecuta primero la morfometría (cuello y AR).
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {recs.map((c) => {
          const on = sel === c.clip_id;
          return (
            <div
              key={c.clip_id}
              onClick={() => setSel(c.clip_id)}
              style={{
                cursor: "pointer",
                border: `1px solid ${on ? "var(--primary)" : "var(--border)"}`,
                background: on ? "var(--brand-subtle)" : "var(--card)",
                borderRadius: "var(--radius-lg)",
                padding: "11px 13px",
                transition: "all var(--dur-fast) var(--ease-out)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontWeight: 700, color: "var(--foreground)", fontSize: 13 }}>{c.clip_name}</span>
                <div style={{ flex: 1 }} />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-deep)", fontWeight: 700 }}>
                  {(c.score * 100).toFixed(0)}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "var(--foreground)", marginTop: 4, fontStyle: "italic" }}>{c.reason}</div>
            </div>
          );
        })}
      </div>

      {plan && (
        <Card style={{ marginTop: 14 }}>
          <Metric
            label="Cobertura de cuello"
            value={plan.neck_coverage_pct.toFixed(1)}
            unit=" %"
            badge={plan.neck_coverage_pct >= 95 ? ["Óptimo", "success"] : ["Parcial", "warning"]}
          />
          <Metric
            label="Colisión clip–vaso"
            value={plan.collision_detected ? "Sí" : "No"}
            badge={plan.collision_detected ? ["Colisión", "destructive"] : ["OK", "success"]}
          />
          {plan.warning && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--warning)" }}>{plan.warning}</div>
          )}
        </Card>
      )}
      <ErrorNote>{error}</ErrorNote>

      <Button
        style={{ marginTop: 14, width: "100%" }}
        onClick={() => void place()}
        disabled={busy || !sel}
        leadingIcon={<Icon name="CLIP_PLACE" />}
      >
        {busy ? "Verificando…" : "Colocar y verificar"}
      </Button>
    </div>
  );
}

/* ── Coils ─────────────────────────────────────────────────────────────── */
function CoilsTab() {
  const { sessionId, morphometry, setDeviceMesh } = usePlanning();
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
      setDeviceMesh(res.coils_mesh_url || null);
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
    </div>
  );
}

/* ── Stents ────────────────────────────────────────────────────────────── */
function StentsTab() {
  const { sessionId, morphometry, setDeviceMesh } = usePlanning();
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
      setDeviceMesh(res.stent_mesh_url || null);
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
    </div>
  );
}

/* ── Panel ─────────────────────────────────────────────────────────────── */
export function DevicesPanel({ onNext }: { onNext: () => void }) {
  const [tab, setTab] = useState<string>("Clips");
  return (
    <div className="fade-rise">
      <PanelHead title="Planificación de dispositivos" desc="Elige clip, coils o stent del catálogo y verifica su colocación." />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === "Clips" && <ClipsTab />}
      {tab === "Coils" && <CoilsTab />}
      {tab === "Stents" && <StentsTab />}
      <Button variant="outline" style={{ marginTop: 18, width: "100%" }} onClick={onNext} trailingIcon={<Icon name="STEP_EXPORT" />}>
        Continuar al informe
      </Button>
    </div>
  );
}
