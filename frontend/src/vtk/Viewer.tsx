/* Visor clínico — superficie de imagenología siempre negra.
   - Con malla segmentada: render 3D real (.vtp) con vtk.js.
   - Sin malla pero con volumen cargado: vista previa DICOM (MPR axial navegable).
   - Sin nada: placeholder honesto.
   La franja inferior muestra los tres planos MPR reales del volumen. */

import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { VolumeMeta } from "../api/types";
import { Icon } from "../components/Icon";
import { usePlanning } from "../store/planning";
import type { MeshLayer, MeshMarker, MeshLine } from "./MeshView";
import { MprView } from "./MprView";
import type { Vector3 } from "@kitware/vtk.js/types";

// vtk.js (~1 MB) is only needed once a 3D mesh is shown, so load MeshView — and
// with it the whole vtk.js runtime — lazily. The landing/login/MPR-only views
// never pull it into their bundle.
const MeshView = lazy(() => import("./MeshView").then((m) => ({ default: m.MeshView })));

const STEP_SCENE: Record<string, string> = {
  upload: "Vista previa DICOM",
  segment: "Segmentación vascular",
  detect: "Candidatos aneurismáticos",
  morpho: "Análisis morfométrico",
  treatment: "Cuello y domo",
  devices: "Dispositivo + trayectoria",
  report: "Escena final",
};

const VESSEL_COLOR: Vector3 = [0.65, 0.7, 0.76];
const DOME_COLOR: Vector3 = [0.32, 0.55, 0.75];
const DEVICE_COLOR: Vector3 = [0.92, 0.82, 0.45];     // warm gold — placed clip/coil/stent
const CENTERLINE_COLOR: Vector3 = [0.36, 0.85, 0.86]; // cyan — vessel centreline tube
const SOURCE_COLOR: Vector3 = [0.25, 0.73, 0.31];     // green — picked source endpoint
const TARGET_COLOR: Vector3 = [0.97, 0.32, 0.29];     // red — picked target endpoint
const MEASURE_COLOR: Vector3 = [0.98, 0.75, 0.18];    // amber — caliper rulers
const PENDING_COLOR: Vector3 = [0.98, 0.55, 0.10];    // orange — first measurement point

/* Load the volume meta once per session; shared by main view + MPR strip. */
function useVolumeMeta(sessionId: string | null): VolumeMeta | null {
  const [meta, setMeta] = useState<VolumeMeta | null>(null);
  useEffect(() => {
    setMeta(null);
    if (!sessionId) return;
    let cancelled = false;
    api
      .volumeMeta(sessionId)
      .then((m) => { if (!cancelled) setMeta(m); })
      .catch(() => { if (!cancelled) setMeta(null); });
    return () => { cancelled = true; };
  }, [sessionId]);
  return meta;
}

/* Placeholder shown while the lazy vtk.js chunk is being fetched. */
function ViewerLoading({ label }: { label: string }) {
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, background: "var(--viewer-bg)", color: "rgba(168,184,198,0.5)" }}>
      <Icon name="BRAIN" size={54} color="rgba(139,155,170,0.5)" />
      <div style={{ fontSize: 13 }}>{label}</div>
    </div>
  );
}

export function Viewer({ step }: { step: string }) {
  const {
    sessionId, segmentation, candidates, selectedCandidate, series, deviceMesh,
    centerlineMesh, pickMode, clSource, clTarget, setPickMode, setClSource, setClTarget,
    measurements, measurePending, setMeasurements, setMeasurePending,
  } = usePlanning();
  // mesh_url carries a generation token (?v=…) from the backend, so it changes
  // on every re-segmentation and vtk.js refetches instead of serving the cache.
  const meshUrl = segmentation?.mesh_url ?? null;
  const candidate = candidates[selectedCandidate];
  const meta = useVolumeMeta(sessionId);
  // Only show a placed device mesh once its URL points at a real session file.
  const showDevice = step === "devices" && !!deviceMesh && deviceMesh.startsWith("/data/");
  const showCenterline = !!centerlineMesh && centerlineMesh.startsWith("/data/");

  const layers = useMemo<MeshLayer[]>(() => {
    if (!meshUrl) return [];
    const vesselDim = step === "detect" || step === "morpho" || showDevice || pickMode !== null || showCenterline;
    const out: MeshLayer[] = [{ url: meshUrl, color: VESSEL_COLOR, opacity: vesselDim ? 0.45 : 1 }];
    if (candidate?.dome_mesh_url && step !== "segment" && step !== "upload") {
      out.push({ url: candidate.dome_mesh_url, color: DOME_COLOR, opacity: showDevice ? 0.5 : 1 });
    }
    if (showDevice && deviceMesh) {
      out.push({ url: deviceMesh, color: DEVICE_COLOR, opacity: 1 });
    }
    if (showCenterline && centerlineMesh) {
      out.push({ url: centerlineMesh, color: CENTERLINE_COLOR, opacity: 1 });
    }
    return out;
  }, [meshUrl, candidate?.dome_mesh_url, step, showDevice, deviceMesh, showCenterline, centerlineMesh, pickMode]);

  const markers = useMemo<MeshMarker[]>(() => {
    const out: MeshMarker[] = [];
    if (clSource) out.push({ pos: clSource, color: SOURCE_COLOR });
    if (clTarget) out.push({ pos: clTarget, color: TARGET_COLOR });
    if (measurePending) out.push({ pos: measurePending, color: PENDING_COLOR });
    return out;
  }, [clSource, clTarget, measurePending]);

  const lines = useMemo<MeshLine[]>(
    () => measurements.filter((m) => m.visible).map((m) => ({ a: m.a, b: m.b, color: MEASURE_COLOR })),
    [measurements],
  );

  const onPick = useCallback(
    (xyz: [number, number, number]) => {
      if (pickMode === "cl_source") { setClSource(xyz); setPickMode(null); }
      else if (pickMode === "cl_target") { setClTarget(xyz); setPickMode(null); }
      else if (pickMode === "measure") {
        if (!measurePending) {
          setMeasurePending(xyz);           // first click — wait for the second
        } else {
          const d = Math.hypot(xyz[0] - measurePending[0], xyz[1] - measurePending[1], xyz[2] - measurePending[2]);
          const nextId = (measurements.reduce((mx, m) => Math.max(mx, m.id), 0)) + 1;
          setMeasurements([...measurements, { id: nextId, a: measurePending, b: xyz, distance: d, label: `M${nextId}`, visible: true }]);
          setMeasurePending(null);
          setPickMode(null);
        }
      }
    },
    [pickMode, measurePending, measurements, setClSource, setClTarget, setPickMode, setMeasurePending, setMeasurements],
  );

  return (
    <div style={{ flex: 1, position: "relative", background: "var(--viewer-bg)", overflow: "hidden", minHeight: 0 }}>
      {meshUrl ? (
        <Suspense fallback={<ViewerLoading label="Cargando visor 3D…" />}>
          <MeshView layers={layers} markers={markers} lines={lines} pickMode={pickMode !== null} onPick={onPick} />
        </Suspense>
      ) : sessionId && meta ? (
        <MprView sessionId={sessionId} meta={meta} plane="axial" showSlider />
      ) : (
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "radial-gradient(60% 60% at 52% 46%, rgba(78,102,120,0.30), transparent 70%), linear-gradient(rgba(139,155,170,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(139,155,170,0.05) 1px, transparent 1px)",
            backgroundSize: "100% 100%, 34px 34px, 34px 34px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            color: "rgba(168,184,198,0.5)",
          }}
        >
          <Icon name="BRAIN" size={54} color="rgba(139,155,170,0.5)" />
          <div style={{ fontSize: 13 }}>
            {series ? "Cargando vista previa del volumen…" : "Carga una serie DICOM para comenzar"}
          </div>
        </div>
      )}

      {/* Scene label */}
      <div style={{ position: "absolute", top: 14, left: 16, fontSize: 11, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.75)", pointerEvents: "none" }}>
        {STEP_SCENE[step]} · {meshUrl ? "vtk.js" : "MPR"}
        {step === "detect" && candidate && <span style={{ marginLeft: 10, color: "#A8B8C6" }}>· {candidate.id}</span>}
      </div>

      {/* Pick-mode banner */}
      {pickMode && meshUrl && (
        <div style={{ position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)", background: pickMode === "cl_source" ? "rgba(63,186,80,0.92)" : pickMode === "cl_target" ? "rgba(248,81,73,0.92)" : "rgba(234,179,8,0.94)", color: pickMode === "measure" ? "#1a1a1a" : "#fff", fontSize: 12, fontWeight: 600, padding: "6px 14px", borderRadius: 999, pointerEvents: "none", boxShadow: "0 2px 8px rgba(0,0,0,0.35)" }}>
          {pickMode === "cl_source" && "Clic sobre el vaso para marcar el origen"}
          {pickMode === "cl_target" && "Clic sobre el vaso para marcar el destino"}
          {pickMode === "measure" && (measurePending ? "Clic en el segundo punto" : "Clic en el primer punto")}
        </div>
      )}

      {(step === "morpho" || step === "treatment" || step === "devices") && (
        <div style={{ position: "absolute", bottom: 14, right: 16, display: "flex", gap: 12, fontSize: 10, color: "rgba(235,235,235,0.7)", pointerEvents: "none" }}>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: "#ef4444" }} />perforante &lt;3mm</span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: "#eab308" }} />3–6mm</span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: "#22c55e" }} />&gt;6mm</span>
        </div>
      )}

      {meshUrl && (
        <div style={{ position: "absolute", bottom: 14, left: 16, fontSize: 10, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.55)", pointerEvents: "none" }}>
          arrastra para rotar · rueda para zoom
        </div>
      )}
    </div>
  );
}

/* MprStrip — franja inferior con los tres planos reales, crosshairs
   sincronizados y window/level por arrastre compartido. */
export function MprStrip() {
  const { sessionId, series } = usePlanning();
  const meta = useVolumeMeta(sessionId);

  // Shared crosshair voxel {x,y,z} and window/level across the three planes.
  const [nz, ny, nx] = meta?.shape ?? [1, 1, 1];
  const [vox, setVox] = useState<{ x: number; y: number; z: number }>({ x: 0, y: 0, z: 0 });
  const [wl, setWl] = useState<{ wc: number; ww: number } | null>(null);

  useEffect(() => {
    if (meta) {
      setVox({ x: Math.floor(nx / 2), y: Math.floor(ny / 2), z: Math.floor(nz / 2) });
      setWl({ wc: meta.wc, ww: meta.ww });
    }
  }, [meta, nx, ny, nz]);

  // Per-plane wiring: controlled index, crosshair {u,v}, click→voxel.
  const cfg = (plane: "axial" | "coronal" | "sagital") => {
    const f = (n: number, i: number) => (n > 1 ? i / (n - 1) : 0.5);
    const clamp = (n: number, u: number) => Math.max(0, Math.min(n - 1, Math.round(u * (n - 1))));
    if (plane === "axial")
      return {
        index: vox.z,
        crosshair: { u: f(nx, vox.x), v: f(ny, vox.y) },
        onIndexChange: (i: number) => setVox((p) => ({ ...p, z: i })),
        onPlaneClick: (u: number, v: number) => setVox((p) => ({ ...p, x: clamp(nx, u), y: clamp(ny, v) })),
      };
    if (plane === "coronal")
      return {
        index: vox.y,
        crosshair: { u: f(nx, vox.x), v: f(nz, vox.z) },
        onIndexChange: (i: number) => setVox((p) => ({ ...p, y: i })),
        onPlaneClick: (u: number, v: number) => setVox((p) => ({ ...p, x: clamp(nx, u), z: clamp(nz, v) })),
      };
    return {
      index: vox.x,
      crosshair: { u: f(ny, vox.y), v: f(nz, vox.z) },
      onIndexChange: (i: number) => setVox((p) => ({ ...p, x: i })),
      onPlaneClick: (u: number, v: number) => setVox((p) => ({ ...p, y: clamp(ny, u), z: clamp(nz, v) })),
    };
  };

  return (
    <div style={{ height: 132, flexShrink: 0, display: "flex", gap: 1, background: "var(--border)", borderTop: "1px solid var(--border)" }}>
      {(["axial", "coronal", "sagital"] as const).map((plane) => {
        const c = cfg(plane);
        return (
        <div key={plane} style={{ flex: 1, position: "relative", minWidth: 0 }}>
          {sessionId && meta ? (
            <MprView
              sessionId={sessionId} meta={meta} plane={plane} compact
              wc={wl?.wc} ww={wl?.ww}
              index={c.index}
              onIndexChange={c.onIndexChange}
              crosshair={c.crosshair}
              onPlaneClick={c.onPlaneClick}
              onWindowLevel={(wc, ww) => setWl({ wc, ww })}
            />
          ) : (
            <div style={{ width: "100%", height: "100%", background: "var(--viewer-bg)", position: "relative" }}>
              <span style={{ position: "absolute", top: 8, left: 10, fontSize: 10, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.7)" }}>
                {plane === "axial" ? "Axial" : plane === "coronal" ? "Coronal" : "Sagital"}
              </span>
              <span style={{ position: "absolute", bottom: 8, right: 10, fontSize: 9, fontFamily: "var(--font-mono)", color: "rgba(168,184,198,0.4)" }}>
                {series ? "cargando…" : "sin volumen"}
              </span>
            </div>
          )}
        </div>
        );
      })}
    </div>
  );
}
