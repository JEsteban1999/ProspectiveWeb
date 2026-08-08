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
import { ObliqueMprView } from "./ObliqueMprView";
import type { Vector3 } from "@kitware/vtk.js/types";

// vtk.js (~1 MB) is only needed once a 3D mesh is shown, so load MeshView — and
// with it the whole vtk.js runtime — lazily. The landing/login/MPR-only views
// never pull it into their bundle.
const MeshView = lazy(() => import("./MeshView").then((m) => ({ default: m.MeshView })));
const VolumeView = lazy(() => import("./VolumeView").then((m) => ({ default: m.VolumeView })));

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
const NECK_ORIGIN_COLOR: Vector3 = [0.85, 0.35, 0.85]; // magenta — neck-plane point
const NECK_DOME_COLOR: Vector3 = [0.36, 0.85, 0.86];   // cyan — dome apex
const GROW_SEED_COLOR: Vector3 = [0.55, 0.95, 0.35];   // lime — grow-from-seeds seeds
const CROP_CENTER_COLOR: Vector3 = [0.98, 0.60, 0.20]; // orange — crop ROI centre
const TRAJ_ENTRY_COLOR: Vector3 = [0.40, 0.80, 1.00];  // sky blue — approach entry
const TRAJ_TARGET_COLOR: Vector3 = [0.97, 0.32, 0.29]; // red — approach target
const TRAJ_LINE_COLOR: Vector3 = [0.55, 0.85, 1.00];   // light blue — approach corridor
const MO_NECK_COLOR: Vector3 = [0.20, 0.75, 1.00];     // sky blue — neck ring/marker
const MO_DOME_COLOR: Vector3 = [1.00, 0.55, 0.10];     // orange — dome-height line/apex
const MO_MAXD_COLOR: Vector3 = [0.85, 0.20, 0.20];     // red — max-diameter span

/* Small 3-vector helpers for the morphometric overlay geometry. */
type V3 = [number, number, number];
const vadd = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const vsub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const vscale = (a: V3, s: number): V3 => [a[0] * s, a[1] * s, a[2] * s];
const vcross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const vnorm = (a: V3): V3 => { const m = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / m, a[1] / m, a[2] / m]; };
function perpBasis(axis: V3): [V3, V3] {
  const ref: V3 = Math.abs(axis[2]) > 0.9 ? [0, 1, 0] : [0, 0, 1];
  const u = vnorm(vcross(axis, ref));
  const v = vnorm(vcross(axis, u));
  return [u, v];
}

/* Standard CT window/level presets (port of utils/window_presets.py):
   name → [window_center, window_width] in HU. */
const WL_PRESETS: { name: string; wc: number; ww: number }[] = [
  { name: "Cerebro", wc: 40, ww: 80 },
  { name: "Hemorragia", wc: 55, ww: 100 },
  { name: "Subdural", wc: 75, ww: 215 },
  { name: "CTA", wc: 170, ww: 600 },
  { name: "Hueso", wc: 400, ww: 1000 },
  { name: "Pulmón", wc: -600, ww: 1500 },
  { name: "Mediastino", wc: 50, ww: 350 },
  { name: "Abdomen", wc: 40, ww: 350 },
  { name: "Hígado", wc: 70, ww: 170 },
];

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
    neckOrigin, neckDome, setNeckOrigin, setNeckDome,
    measurements, measurePending, setMeasurements, setMeasurePending, previewBand, previewMeshUrl,
    growSeeds, setGrowSeeds, cropCenter, setCropCenter,
    trajEntry, trajTarget, setTrajEntry, setTrajTarget,
    morphometry, morphoOverlay, setCaptureViewport,
  } = usePlanning();

  // 3D morphometric overlay: neck ring + dome-height & max-diameter spans + apex.
  const overlay = useMemo<{ markers: MeshMarker[]; lines: MeshLine[] } | null>(() => {
    if (!morphoOverlay || !morphometry) return null;
    const c = morphometry.centroid;
    const ax = morphometry.principal_axis;
    if (!c || !ax || ax.length !== 3) return null;
    const centroid: V3 = [c.x, c.y, c.z];
    const axis = vnorm([ax[0], ax[1], ax[2]] as V3);
    const dome = morphometry.dome_height_mm || 0;
    const neckR = (morphometry.neck_mm || 0) / 2;
    const maxR = (morphometry.max_diameter_mm || 0) / 2;
    const neckC = vsub(centroid, vscale(axis, dome / 2));
    const apex = vadd(centroid, vscale(axis, dome / 2));
    const [u, v] = perpBasis(axis);

    const markers: MeshMarker[] = [
      { pos: neckC, color: MO_NECK_COLOR },
      { pos: apex, color: MO_DOME_COLOR },
    ];
    const lines: MeshLine[] = [
      { a: neckC, b: apex, color: MO_DOME_COLOR },                                   // dome height
      { a: vsub(centroid, vscale(u, maxR)), b: vadd(centroid, vscale(u, maxR)), color: MO_MAXD_COLOR }, // max Ø
    ];
    // Neck ring approximated by N segments in the plane perpendicular to the axis.
    if (neckR > 0.05) {
      const N = 28;
      const ring: V3[] = [];
      for (let k = 0; k < N; k++) {
        const t = (2 * Math.PI * k) / N;
        ring.push(vadd(neckC, vadd(vscale(u, neckR * Math.cos(t)), vscale(v, neckR * Math.sin(t)))));
      }
      for (let k = 0; k < N; k++) lines.push({ a: ring[k], b: ring[(k + 1) % N], color: MO_NECK_COLOR });
    }
    return { markers, lines };
  }, [morphoOverlay, morphometry]);
  // mesh_url carries a generation token (?v=…) from the backend, so it changes
  // on every re-segmentation and vtk.js refetches instead of serving the cache.
  const meshUrl = segmentation?.mesh_url ?? null;
  // During threshold tuning (segment step, no final mesh yet) show the coarse 3D
  // preview mesh forming in near-real-time, like the desktop app.
  const segPreview = step === "segment" && !meshUrl && !!previewMeshUrl && pickMode === null;
  const displayMeshUrl = meshUrl ?? (segPreview ? previewMeshUrl : null);
  // Fall back to the MPR slices (with the tinted band) only while no 3D preview
  // mesh is available yet — and never during a 3D pick (seed/crop needs the mesh).
  const previewActive = !!previewBand && step === "segment" && pickMode === null && !segPreview;
  // Step 1 (DICOM upload) always shows the volume preview (axial MPR + strip),
  // even after a mesh has been segmented — so navigating back to it from a later
  // step shows the study's DICOM views, not the leftover 3D mesh.
  const meshVisible = !!displayMeshUrl && step !== "upload" && !previewActive;
  const candidate = candidates[selectedCandidate];
  // Frame + highlight the selected candidate during detection and morphometry,
  // so it's obvious where the aneurysm is (and where to place the neck plane).
  const focusUrl =
    (step === "detect" || step === "morpho") && candidate?.dome_mesh_url
      ? candidate.dome_mesh_url
      : undefined;
  const meta = useVolumeMeta(sessionId);
  const [viewMode, setViewMode] = useState<"default" | "volume" | "oblique">("default");
  // Only show a placed device mesh once its URL points at a real session file.
  const showDevice = step === "devices" && !!deviceMesh && deviceMesh.startsWith("/data/");
  const showCenterline = !!centerlineMesh && centerlineMesh.startsWith("/data/");

  const layers = useMemo<MeshLayer[]>(() => {
    if (!displayMeshUrl) return [];
    const vesselDim = step === "detect" || step === "morpho" || showDevice || pickMode !== null || showCenterline;
    const out: MeshLayer[] = [{ url: displayMeshUrl, color: VESSEL_COLOR, opacity: vesselDim ? 0.45 : 1 }];
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
  }, [displayMeshUrl, candidate?.dome_mesh_url, step, showDevice, deviceMesh, showCenterline, centerlineMesh, pickMode]);

  const markers = useMemo<MeshMarker[]>(() => {
    const out: MeshMarker[] = [];
    if (clSource) out.push({ pos: clSource, color: SOURCE_COLOR });
    if (clTarget) out.push({ pos: clTarget, color: TARGET_COLOR });
    if (measurePending) out.push({ pos: measurePending, color: PENDING_COLOR });
    if (neckOrigin) out.push({ pos: neckOrigin, color: NECK_ORIGIN_COLOR });
    if (neckDome) out.push({ pos: neckDome, color: NECK_DOME_COLOR });
    for (const s of growSeeds) out.push({ pos: s, color: GROW_SEED_COLOR });
    if (cropCenter) out.push({ pos: cropCenter, color: CROP_CENTER_COLOR });
    if (trajEntry) out.push({ pos: trajEntry, color: TRAJ_ENTRY_COLOR });
    if (trajTarget) out.push({ pos: trajTarget, color: TRAJ_TARGET_COLOR });
    if (overlay) out.push(...overlay.markers);
    return out;
  }, [clSource, clTarget, measurePending, neckOrigin, neckDome, growSeeds, cropCenter, trajEntry, trajTarget, overlay]);

  const lines = useMemo<MeshLine[]>(() => {
    const out: MeshLine[] = measurements
      .filter((m) => m.visible)
      .map((m) => ({ a: m.a, b: m.b, color: MEASURE_COLOR }));
    if (trajEntry && trajTarget) out.push({ a: trajEntry, b: trajTarget, color: TRAJ_LINE_COLOR });
    if (overlay) out.push(...overlay.lines);
    return out;
  }, [measurements, trajEntry, trajTarget, overlay]);

  const onPick = useCallback(
    (xyz: [number, number, number]) => {
      if (pickMode === "cl_source") { setClSource(xyz); setPickMode(null); }
      else if (pickMode === "cl_target") { setClTarget(xyz); setPickMode(null); }
      else if (pickMode === "neck_origin") { setNeckOrigin(xyz); setPickMode(null); }
      else if (pickMode === "neck_dome") { setNeckDome(xyz); setPickMode(null); }
      else if (pickMode === "crop_center") { setCropCenter(xyz); setPickMode(null); }
      else if (pickMode === "traj_entry") { setTrajEntry(xyz); setPickMode(null); }
      else if (pickMode === "traj_target") { setTrajTarget(xyz); setPickMode(null); }
      else if (pickMode === "grow_seed") { setGrowSeeds([...growSeeds, xyz]); }  // stay armed for multiple seeds
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
    [pickMode, measurePending, measurements, growSeeds, setClSource, setClTarget, setNeckOrigin, setNeckDome, setCropCenter, setGrowSeeds, setTrajEntry, setTrajTarget, setPickMode, setMeasurePending, setMeasurements],
  );

  return (
    <div style={{ flex: 1, position: "relative", background: "var(--viewer-bg)", overflow: "hidden", minHeight: 0 }}>
      {viewMode === "volume" && sessionId && meta ? (
        <Suspense fallback={<ViewerLoading label="Cargando volumen 3D…" />}>
          <VolumeView sessionId={sessionId} />
        </Suspense>
      ) : viewMode === "oblique" && sessionId && meta ? (
        <ObliqueMprView sessionId={sessionId} wc={meta.wc} ww={meta.ww} />
      ) : meshVisible ? (
        <Suspense fallback={<ViewerLoading label="Cargando visor 3D…" />}>
          <MeshView layers={layers} markers={markers} lines={lines} pickMode={pickMode !== null} onPick={onPick} focusUrl={focusUrl} registerCapture={setCaptureViewport} preserveCamera={segPreview} />
        </Suspense>
      ) : sessionId && meta ? (
        <MprView sessionId={sessionId} meta={meta} plane="axial" showSlider band={previewActive ? previewBand : null} />
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
        {STEP_SCENE[step]} · {viewMode === "volume" ? "volumen" : viewMode === "oblique" ? "oblicuo" : meshVisible ? "vtk.js" : "MPR"}
        {step === "detect" && candidate && <span style={{ marginLeft: 10, color: "#A8B8C6" }}>· {candidate.id}</span>}
      </div>

      {/* Live threshold-preview legend (2D tint fallback). */}
      {previewActive && previewBand && (
        <div style={{ position: "absolute", top: 38, left: 16, display: "flex", alignItems: "center", gap: 8, background: "rgba(20,24,28,0.72)", border: "1px solid rgba(54,214,168,0.5)", borderRadius: 999, padding: "5px 12px", pointerEvents: "none", boxShadow: "0 2px 10px rgba(0,0,0,0.35)" }}>
          <span style={{ width: 9, height: 9, borderRadius: 2, background: "rgb(54,214,168)" }} />
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#DCE6EE" }}>
            Vista previa · captura [{Math.round(previewBand[0])}, {Math.round(previewBand[1])}]
          </span>
        </div>
      )}

      {/* Coarse 3D mesh preview chip (interactive threshold tuning). */}
      {viewMode === "default" && segPreview && (
        <div style={{ position: "absolute", top: 38, left: 16, display: "flex", alignItems: "center", gap: 8, background: "rgba(20,24,28,0.72)", border: "1px solid rgba(54,214,168,0.5)", borderRadius: 999, padding: "5px 12px", pointerEvents: "none", boxShadow: "0 2px 10px rgba(0,0,0,0.35)" }}>
          <span style={{ width: 9, height: 9, borderRadius: "50%", background: "rgb(54,214,168)" }} />
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#DCE6EE" }}>
            Vista previa 3D (malla gruesa) · pulsa «Segmentar» para la malla final
          </span>
        </div>
      )}

      {/* Candidate focus chip — the highlighted candidate's id + diameter. */}
      {viewMode === "default" && meshVisible && focusUrl && candidate && (
        <div style={{ position: "absolute", top: 38, left: 16, display: "flex", alignItems: "center", gap: 8, background: "rgba(20,24,28,0.72)", border: "1px solid rgba(82,140,180,0.5)", borderRadius: 999, padding: "5px 12px", pointerEvents: "none", boxShadow: "0 2px 10px rgba(0,0,0,0.35)" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#529CC0", boxShadow: "0 0 8px 1px rgba(82,156,192,0.9)" }} />
          <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "#DCE6EE" }}>
            {candidate.id} · Ø {candidate.max_diameter_mm.toFixed(1)} mm
          </span>
        </div>
      )}

      {/* View-mode switcher (only when a volume is available) */}
      {sessionId && meta && !pickMode && (
        <div style={{ position: "absolute", top: 12, right: 14, display: "flex", gap: 2, background: "rgba(20,24,28,0.72)", borderRadius: 999, padding: 3 }}>
          {([["default", meshVisible ? "3D" : "MPR"], ["volume", "Volumen"], ["oblique", "Oblicuo"]] as const).map(([m, lbl]) => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              style={{
                padding: "4px 12px", fontSize: 11, fontWeight: 600, borderRadius: 999, border: "none", cursor: "pointer",
                background: viewMode === m ? "var(--brand-mist, #8B9BAA)" : "transparent",
                color: viewMode === m ? "#0e1114" : "rgba(200,210,220,0.8)",
              }}
            >
              {lbl}
            </button>
          ))}
        </div>
      )}

      {/* Pick-mode banner */}
      {pickMode && meshUrl && (
        <div style={{ position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)", background: pickMode === "cl_source" ? "rgba(63,186,80,0.92)" : pickMode === "cl_target" ? "rgba(248,81,73,0.92)" : pickMode === "neck_origin" ? "rgba(217,89,217,0.92)" : pickMode === "neck_dome" ? "rgba(92,217,219,0.94)" : pickMode === "grow_seed" ? "rgba(140,224,90,0.94)" : pickMode === "crop_center" ? "rgba(240,150,50,0.94)" : pickMode === "traj_entry" ? "rgba(102,204,255,0.94)" : pickMode === "traj_target" ? "rgba(248,81,73,0.92)" : "rgba(234,179,8,0.94)", color: pickMode === "measure" || pickMode === "neck_dome" || pickMode === "grow_seed" || pickMode === "traj_entry" ? "#1a1a1a" : "#fff", fontSize: 12, fontWeight: 600, padding: "6px 14px", borderRadius: 999, pointerEvents: "none", boxShadow: "0 2px 8px rgba(0,0,0,0.35)" }}>
          {pickMode === "cl_source" && "Clic sobre el vaso para marcar el origen"}
          {pickMode === "cl_target" && "Clic sobre el vaso para marcar el destino"}
          {pickMode === "neck_origin" && "Clic sobre el cuello del aneurisma"}
          {pickMode === "neck_dome" && "Clic sobre el ápice del domo"}
          {pickMode === "grow_seed" && `Clic sobre el vaso para añadir semilla (${growSeeds.length})`}
          {pickMode === "crop_center" && "Clic sobre la malla para el centro del recorte"}
          {pickMode === "traj_entry" && "Clic para el punto de entrada del abordaje"}
          {pickMode === "traj_target" && "Clic sobre el aneurisma (punto diana)"}
          {pickMode === "measure" && (measurePending ? "Clic en el segundo punto" : "Clic en el primer punto")}
        </div>
      )}

      {/* Morphometric overlay legend — values annotated in the 3D scene. */}
      {viewMode === "default" && meshVisible && overlay && morphometry && (
        <div style={{ position: "absolute", bottom: 40, left: 16, display: "flex", flexDirection: "column", gap: 3, background: "rgba(20,24,28,0.72)", border: "1px solid rgba(120,140,160,0.4)", borderRadius: 8, padding: "8px 11px", pointerEvents: "none", fontSize: 11, fontFamily: "var(--font-mono)", color: "#DCE6EE" }}>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: "rgb(51,191,255)" }} />Ø cuello {morphometry.neck_mm.toFixed(1)} mm</span>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: "rgb(255,140,26)" }} />H domo {morphometry.dome_height_mm.toFixed(1)} mm</span>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: "rgb(217,51,51)" }} />Ø máx {morphometry.max_diameter_mm.toFixed(1)} mm</span>
          <span style={{ color: "rgba(200,210,220,0.75)" }}>AR {morphometry.ar.toFixed(2)} · DNR {morphometry.dnr.toFixed(2)}</span>
        </div>
      )}

      {/* Perforator legend — only over the mesh scene (the oblique view has its
          own control bar down there, and the volume view has no perforators). */}
      {viewMode === "default" && meshUrl && (step === "morpho" || step === "treatment" || step === "devices") && (
        <div style={{ position: "absolute", bottom: 14, right: 16, display: "flex", flexWrap: "wrap", justifyContent: "flex-end", gap: "4px 12px", maxWidth: "60%", fontSize: 10, color: "rgba(235,235,235,0.7)", pointerEvents: "none" }}>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: "#ef4444" }} />perforante &lt;3mm</span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: "#eab308" }} />3–6mm</span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: "#22c55e" }} />&gt;6mm</span>
        </div>
      )}

      {/* Rotate/zoom hint — only for the rotatable 3D scenes (mesh & volume). */}
      {((viewMode === "default" && meshUrl) || viewMode === "volume") && (
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
  const { sessionId, series, previewBand, mprSeedMode, growSeeds, setGrowSeeds } = usePlanning();
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

  // spacing = [sz, sy, sx]; mesh/world coords have origin 0 → world = voxel·spacing.
  const sp = meta?.spacing ?? [1, 1, 1];
  const worldOf = (vx: number, vy: number, vz: number): V3 => [vx * sp[2], vy * sp[1], vz * sp[0]];
  const voxelOf = (s: V3) => ({ vx: Math.round(s[0] / sp[2]), vy: Math.round(s[1] / sp[1]), vz: Math.round(s[2] / sp[0]) });
  const addSeed = (vx: number, vy: number, vz: number) => setGrowSeeds([...growSeeds, worldOf(vx, vy, vz)]);

  // Per-plane wiring: controlled index, crosshair {u,v}, click→voxel, seed dots.
  const cfg = (plane: "axial" | "coronal" | "sagital") => {
    const f = (n: number, i: number) => (n > 1 ? i / (n - 1) : 0.5);
    const clamp = (n: number, u: number) => Math.max(0, Math.min(n - 1, Math.round(u * (n - 1))));
    // Grow seeds that lie on (±1 slice of) this plane's current slice → dots.
    const dotsFor = (onSlice: (v: ReturnType<typeof voxelOf>) => boolean, uv: (v: ReturnType<typeof voxelOf>) => { u: number; v: number }) =>
      mprSeedMode ? growSeeds.map(voxelOf).filter(onSlice).map(uv) : [];
    if (plane === "axial")
      return {
        index: vox.z,
        crosshair: { u: f(nx, vox.x), v: f(ny, vox.y) },
        onIndexChange: (i: number) => setVox((p) => ({ ...p, z: i })),
        onPlaneClick: (u: number, v: number) => {
          const x = clamp(nx, u), y = clamp(ny, v);
          setVox((p) => ({ ...p, x, y }));
          if (mprSeedMode) addSeed(x, y, vox.z);
        },
        seedDots: dotsFor((s) => Math.abs(s.vz - vox.z) <= 1, (s) => ({ u: f(nx, s.vx), v: f(ny, s.vy) })),
      };
    if (plane === "coronal")
      return {
        index: vox.y,
        crosshair: { u: f(nx, vox.x), v: f(nz, vox.z) },
        onIndexChange: (i: number) => setVox((p) => ({ ...p, y: i })),
        onPlaneClick: (u: number, v: number) => {
          const x = clamp(nx, u), z = clamp(nz, v);
          setVox((p) => ({ ...p, x, z }));
          if (mprSeedMode) addSeed(x, vox.y, z);
        },
        seedDots: dotsFor((s) => Math.abs(s.vy - vox.y) <= 1, (s) => ({ u: f(nx, s.vx), v: f(nz, s.vz) })),
      };
    return {
      index: vox.x,
      crosshair: { u: f(ny, vox.y), v: f(nz, vox.z) },
      onIndexChange: (i: number) => setVox((p) => ({ ...p, x: i })),
      onPlaneClick: (u: number, v: number) => {
        const y = clamp(ny, u), z = clamp(nz, v);
        setVox((p) => ({ ...p, y, z }));
        if (mprSeedMode) addSeed(vox.x, y, z);
      },
      seedDots: dotsFor((s) => Math.abs(s.vx - vox.x) <= 1, (s) => ({ u: f(ny, s.vy), v: f(nz, s.vz) })),
    };
  };

  return (
    <div className="mpr-strip" style={{ height: "clamp(160px, 26vh, 240px)", flexShrink: 0, display: "flex", gap: 1, background: "var(--border)", borderTop: "1px solid var(--border)", position: "relative" }}>
      {/* Window/Level preset selector — sets the shared W/L for the three planes. */}
      {sessionId && meta && (
        <select
          title="Preajuste de ventana/nivel"
          value=""
          onChange={(e) => {
            const p = WL_PRESETS.find((x) => x.name === e.target.value);
            if (p) setWl({ wc: p.wc, ww: p.ww });
          }}
          style={{ position: "absolute", top: 6, left: 8, zIndex: 6, fontSize: 10, fontFamily: "var(--font-mono)", padding: "3px 6px", borderRadius: 6, border: "1px solid rgba(120,140,160,0.4)", background: "rgba(20,24,28,0.82)", color: "#DCE6EE", cursor: "pointer" }}
        >
          <option value="" disabled>Ventana…{wl ? ` (${Math.round(wl.wc)}/${Math.round(wl.ww)})` : ""}</option>
          {WL_PRESETS.map((p) => (
            <option key={p.name} value={p.name}>{p.name} · {p.wc}/{p.ww}</option>
          ))}
        </select>
      )}
      {(["axial", "coronal", "sagital"] as const).map((plane) => {
        const c = cfg(plane);
        return (
        <div key={plane} style={{ flex: 1, position: "relative", minWidth: 0, outline: mprSeedMode ? "2px solid rgba(140,224,90,0.9)" : "none", outlineOffset: -2 }}>
          {sessionId && meta ? (
            <MprView
              sessionId={sessionId} meta={meta} plane={plane} compact
              wc={wl?.wc} ww={wl?.ww}
              band={previewBand}
              index={c.index}
              onIndexChange={c.onIndexChange}
              crosshair={c.crosshair}
              onPlaneClick={c.onPlaneClick}
              onWindowLevel={(wc, ww) => setWl({ wc, ww })}
              seedDots={c.seedDots}
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
