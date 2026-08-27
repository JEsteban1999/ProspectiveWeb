/* PlanningContext — state shared across the 7-step workspace:
   session id, DICOM series, thresholds, segmentation, detection, morphometry… */

import { createContext, useCallback, useContext, useState } from "react";
import type { ReactNode } from "react";
import type {
  AneurysmCandidate,
  DeviceKind,
  MorphometryResult,
  PatientSummary,
  PerforatorCandidate,
  SegmentResult,
  SeriesInfo,
  TreatmentDecisionResult,
} from "../api/types";

interface PlanningState {
  patient: PatientSummary | null;
  /** Clinical case being planned (Study row). Known when the pipeline is
   *  entered from a case, so the upload panel no longer has to ask. */
  caseId: number | null;
  caseLabel: string;
  /** Imaging study (acquisition) loaded in this session, once archived. */
  imagingStudyId: number | null;
  sessionId: string | null;
  series: SeriesInfo | null;
  /** Live threshold-preview band [lower, upper] HU set from the segmentation
   *  sliders; the MPR views tint the captured voxels in near-real-time. */
  previewBand: [number, number] | null;
  /** URL of the coarse 3D preview mesh shown while tuning the thresholds. */
  previewMeshUrl: string | null;
  segmentation: SegmentResult | null;
  candidates: AneurysmCandidate[];
  selectedCandidate: number;
  morphometry: MorphometryResult | null;
  treatment: TreatmentDecisionResult | null;
  /** Placed device meshes by family, shown together in the viewer. One slot per
   *  family because that is how the backend records them: planning a stent after
   *  a clip leaves BOTH in the report, so the viewer has to show both — and each
   *  needs its own «Limpiar» to take one off without touching the other.
   *  The two stent planners (straight and centreline-guided) share the `stent`
   *  slot, mirroring the single stent record the backend keeps. */
  deviceMeshes: Record<DeviceKind, string | null>;
  /** URL of the extracted vessel centreline tube mesh, shown in the viewer. */
  centerlineMesh: string | null;
  /** Total arc length (mm) of the extracted centreline — feeds the cl-stent range sliders. */
  centerlineArcMm: number | null;
  /** Window/level shared by every MPR view (strip, main preview and oblique).
      Null until the volume metadata arrives, then seeded from the DICOM. */
  mprWl: { wc: number; ww: number } | null;
  /** Crosshair voxel shared by every MPR view, so navigating in one moves all. */
  mprVoxel: { x: number; y: number; z: number };
  /** Active 3D-pick mode: centreline endpoints, a measurement, or the neck plane. */
  pickMode: PickMode;
  clSource: Vec3 | null;
  clTarget: Vec3 | null;
  /** Semi-automatic neck plane: a point on the neck and the dome apex (click on the mesh). */
  neckOrigin: Vec3 | null;
  neckDome: Vec3 | null;
  /** 3D caliper measurements (distance between two picked points). */
  measurements: Measurement[];
  /** First endpoint of an in-progress measurement (waiting for the second click). */
  measurePending: Vec3 | null;
  /** Seed points placed on the volume for grow-from-seeds segmentation. */
  growSeeds: Vec3[];
  /** Points marked around the neck rim. With three or more the neck plane is
   *  fitted to them instead of assuming it is perpendicular to the dome axis. */
  neckRim: Vec3[];
  /** Perforator candidates from GET /perforators, kept in the store so the 3D
   *  viewer can mark where each one is — the panel used to list distances with
   *  no way to see which vessel any row referred to. */
  perforators: PerforatorCandidate[];
  /** Id of the perforator the user selected in the list, highlighted in 3D. */
  selectedPerforator: string | null;
  /** Outer radius of each risk zone [high, medium, low] in mm, as reported by
   *  the backend, so the viewer legend states the bands really used. */
  perforatorZones: [number, number, number] | null;
  /** When true, clicking an MPR slice adds a grow-from-seeds seed (place seeds on
   *  a vessel where it's clearly separable from bone — the clean path for CTA). */
  mprSeedMode: boolean;
  /** Picked centre of the mesh-crop ROI (box/sphere). */
  cropCenter: Vec3 | null;
  /** Mesh-crop ROI shape/size/mode — shared with the viewer so it can draw a
   *  translucent preview of exactly what the crop will keep/remove. */
  cropRadius: number;
  cropShape: "sphere" | "box";
  cropInvert: boolean;
  /** Surgical approach trajectory: entry point and aneurysm target (mm). */
  trajEntry: Vec3 | null;
  trajTarget: Vec3 | null;
  /** Show the 3D morphometric overlay (neck disc, dome/max-diameter lines, labels). */
  morphoOverlay: boolean;
  /** Capture the live 3D viewport as a PNG data URL (set by MeshView while mounted). */
  captureViewport: (() => Promise<string | null>) | null;
  /** True when results exist that have not been written to a saved session.
   *  Saving is a manual action, so without this a click on the logo threw away
   *  an afternoon's analysis with no warning at all. */
  dirty: boolean;

  setPatient: (p: PatientSummary | null) => void;
  setCase: (id: number | null, label?: string) => void;
  setImagingStudyId: (id: number | null) => void;
  setSession: (id: string | null) => void;
  setSeries: (s: SeriesInfo | null) => void;
  setPreviewBand: (b: [number, number] | null) => void;
  setPreviewMeshUrl: (u: string | null) => void;
  setSegmentation: (s: SegmentResult | null) => void;
  setCandidates: (c: AneurysmCandidate[]) => void;
  setSelectedCandidate: (i: number) => void;
  setMorphometry: (m: MorphometryResult | null) => void;
  setTreatment: (t: TreatmentDecisionResult | null) => void;
  setDeviceMesh: (kind: DeviceKind, url: string | null) => void;
  /** Forget placed devices locally (the API call is the panel's job). */
  clearDeviceMeshes: (kind?: DeviceKind) => void;
  setCenterlineMesh: (url: string | null) => void;
  setCenterlineArcMm: (v: number | null) => void;
  setMprWl: (w: { wc: number; ww: number } | null) => void;
  setMprVoxel: (v: { x: number; y: number; z: number }) => void;
  setPickMode: (m: PickMode) => void;
  setClSource: (p: Vec3 | null) => void;
  setClTarget: (p: Vec3 | null) => void;
  setNeckOrigin: (p: Vec3 | null) => void;
  setNeckDome: (p: Vec3 | null) => void;
  setMeasurements: (m: Measurement[]) => void;
  setMeasurePending: (p: Vec3 | null) => void;
  setGrowSeeds: (s: Vec3[]) => void;
  setNeckRim: (s: Vec3[]) => void;
  setPerforators: (p: PerforatorCandidate[], zones?: [number, number, number] | null) => void;
  setSelectedPerforator: (id: string | null) => void;
  setMprSeedMode: (v: boolean) => void;
  setCropCenter: (p: Vec3 | null) => void;
  setCropRadius: (r: number) => void;
  setCropShape: (s: "sphere" | "box") => void;
  setCropInvert: (v: boolean) => void;
  setTrajEntry: (p: Vec3 | null) => void;
  setTrajTarget: (p: Vec3 | null) => void;
  setMorphoOverlay: (v: boolean) => void;
  setCaptureViewport: (fn: (() => Promise<string | null>) | null) => void;
  /** Called after a successful save — the session on disk now matches the store. */
  markSaved: () => void;
  reset: () => void;
  resetDownstream: () => void;
}

export type Vec3 = [number, number, number];
export type PickMode =
  | "cl_source" | "cl_target" | "measure" | "neck_origin" | "neck_dome"
  | "neck_rim"
  | "grow_seed" | "crop_center" | "traj_entry" | "traj_target" | null;

export interface Measurement {
  id: number;
  a: Vec3;
  b: Vec3;
  distance: number; // mm
  label: string;
  visible: boolean;
}

const PlanningContext = createContext<PlanningState | null>(null);

export function PlanningProvider({ children }: { children: ReactNode }) {
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [caseId, setCaseId] = useState<number | null>(null);
  const [caseLabel, setCaseLabel] = useState("");
  const [imagingStudyId, setImagingStudyId] = useState<number | null>(null);
  const setCase = (id: number | null, label = "") => { setCaseId(id); setCaseLabel(label); };
  const [sessionId, setSession] = useState<string | null>(null);
  const [series, setSeries] = useState<SeriesInfo | null>(null);
  const [previewBand, setPreviewBand] = useState<[number, number] | null>(null);
  const [previewMeshUrl, setPreviewMeshUrl] = useState<string | null>(null);
  const [segmentation, _setSegmentation] = useState<SegmentResult | null>(null);
  const [candidates, _setCandidates] = useState<AneurysmCandidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState(0);
  const [morphometry, _setMorphometry] = useState<MorphometryResult | null>(null);
  const [treatment, _setTreatment] = useState<TreatmentDecisionResult | null>(null);
  const [deviceMeshes, _setDeviceMeshes] = useState<Record<DeviceKind, string | null>>(
    { clips: null, coils: null, stent: null },
  );
  const [centerlineMesh, _setCenterlineMesh] = useState<string | null>(null);
  const [centerlineArcMm, setCenterlineArcMm] = useState<number | null>(null);
  const [mprWl, setMprWl] = useState<{ wc: number; ww: number } | null>(null);
  const [mprVoxel, setMprVoxel] = useState({ x: 0, y: 0, z: 0 });
  const [pickMode, setPickMode] = useState<PickMode>(null);
  const [clSource, setClSource] = useState<Vec3 | null>(null);
  const [clTarget, setClTarget] = useState<Vec3 | null>(null);
  const [neckOrigin, setNeckOrigin] = useState<Vec3 | null>(null);
  const [neckDome, setNeckDome] = useState<Vec3 | null>(null);
  const [measurements, _setMeasurements] = useState<Measurement[]>([]);
  const [measurePending, setMeasurePending] = useState<Vec3 | null>(null);
  const [growSeeds, setGrowSeeds] = useState<Vec3[]>([]);
  const [neckRim, setNeckRim] = useState<Vec3[]>([]);
  const [perforators, _setPerforators] = useState<PerforatorCandidate[]>([]);
  const [perforatorZones, setPerforatorZones] = useState<[number, number, number] | null>(null);
  const setPerforators = useCallback(
    (p: PerforatorCandidate[], zones?: [number, number, number] | null) => {
      _setPerforators(p);
      if (zones !== undefined) setPerforatorZones(zones);
    },
    [],
  );
  const [selectedPerforator, setSelectedPerforator] = useState<string | null>(null);
  const [mprSeedMode, setMprSeedMode] = useState(false);
  const [cropCenter, setCropCenter] = useState<Vec3 | null>(null);
  const [cropRadius, setCropRadius] = useState(10);
  const [cropShape, setCropShape] = useState<"sphere" | "box">("sphere");
  const [cropInvert, setCropInvert] = useState(false);
  const [trajEntry, setTrajEntry] = useState<Vec3 | null>(null);
  const [trajTarget, setTrajTarget] = useState<Vec3 | null>(null);
  const [morphoOverlay, setMorphoOverlay] = useState(false);
  const [captureViewport, setCaptureViewport] = useState<(() => Promise<string | null>) | null>(null);
  const [dirty, setDirty] = useState(false);
  const markSaved = () => setDirty(false);

  // Every setter that produces a result worth keeping marks the session dirty.
  // Wrapping them here rather than at each call site means a panel added later
  // cannot forget to do it.
  const touch = <T,>(set: (v: T) => void) => (v: T) => { set(v); setDirty(true); };
  const setSegmentation = touch(_setSegmentation);
  const setCandidates = touch(_setCandidates);
  const setMorphometry = touch(_setMorphometry);
  const setTreatment = touch(_setTreatment);
  const setCenterlineMesh = touch(_setCenterlineMesh);
  const setMeasurements = touch(_setMeasurements);
  const setDeviceMesh = (kind: DeviceKind, url: string | null) => {
    _setDeviceMeshes((d) => ({ ...d, [kind]: url }));
    setDirty(true);
  };
  const clearDeviceMeshes = (kind?: DeviceKind) => {
    _setDeviceMeshes((d) => (kind ? { ...d, [kind]: null } : { clips: null, coils: null, stent: null }));
    setDirty(true);
  };

  // Clear everything downstream of the DICOM upload — used when a new series is
  // uploaded in the same workspace so stale meshes/metrics don't linger.
  const resetDownstream = () => {
    setPreviewBand(null);
    setPreviewMeshUrl(null);
    _setSegmentation(null);
    _setCandidates([]);
    setSelectedCandidate(0);
    _setMorphometry(null);
    _setTreatment(null);
    _setDeviceMeshes({ clips: null, coils: null, stent: null });
    _setCenterlineMesh(null);
    setCenterlineArcMm(null);
    setPickMode(null);
    setClSource(null);
    setClTarget(null);
    setNeckOrigin(null);
    setNeckDome(null);
    setNeckRim([]);
    _setPerforators([]);
    setPerforatorZones(null);
    setSelectedPerforator(null);
    _setMeasurements([]);
    setMeasurePending(null);
    setGrowSeeds([]);
    setMprSeedMode(false);
    setCropCenter(null);
    setTrajEntry(null);
    setTrajTarget(null);
    setMorphoOverlay(false);
  };

  const reset = () => {
    setDirty(false);
    setCase(null);
    setImagingStudyId(null);
    setSession(null);
    setSeries(null);
    resetDownstream();
  };

  return (
    <PlanningContext.Provider
      value={{
        patient, caseId, caseLabel, imagingStudyId, sessionId, series, previewBand, previewMeshUrl, segmentation, candidates,
        selectedCandidate, morphometry, treatment, deviceMeshes,
        centerlineMesh, centerlineArcMm, mprWl, mprVoxel, pickMode, clSource, clTarget, neckOrigin, neckDome,
        measurements, measurePending, growSeeds, neckRim, perforators, selectedPerforator, perforatorZones, mprSeedMode, cropCenter, cropRadius, cropShape, cropInvert, trajEntry, trajTarget, morphoOverlay, captureViewport, dirty,
        setPatient, setCase, setImagingStudyId, setSession, setSeries, setPreviewBand, setPreviewMeshUrl, setSegmentation,
        setCandidates, setSelectedCandidate, setMorphometry, setTreatment,
        setDeviceMesh, clearDeviceMeshes, setCenterlineMesh, setCenterlineArcMm, setMprWl, setMprVoxel,
        setPickMode, setClSource, setClTarget, setNeckRim, setPerforators, setSelectedPerforator,
        setNeckOrigin, setNeckDome,
        setMeasurements, setMeasurePending, setGrowSeeds, setMprSeedMode, setCropCenter, setCropRadius, setCropShape, setCropInvert, setTrajEntry, setTrajTarget, setMorphoOverlay,
        setCaptureViewport, markSaved,
        reset, resetDownstream,
      }}
    >
      {children}
    </PlanningContext.Provider>
  );
}

export function usePlanning(): PlanningState {
  const ctx = useContext(PlanningContext);
  if (!ctx) throw new Error("usePlanning must be used inside PlanningProvider");
  return ctx;
}
