/* PlanningContext — state shared across the 7-step workspace:
   session id, DICOM series, thresholds, segmentation, detection, morphometry… */

import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type {
  AneurysmCandidate,
  MorphometryResult,
  PatientSummary,
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
  /** URL of the last placed device mesh (clip/coil/stent), shown in the viewer. */
  deviceMesh: string | null;
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
  setDeviceMesh: (url: string | null) => void;
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
  setMprSeedMode: (v: boolean) => void;
  setCropCenter: (p: Vec3 | null) => void;
  setCropRadius: (r: number) => void;
  setCropShape: (s: "sphere" | "box") => void;
  setCropInvert: (v: boolean) => void;
  setTrajEntry: (p: Vec3 | null) => void;
  setTrajTarget: (p: Vec3 | null) => void;
  setMorphoOverlay: (v: boolean) => void;
  setCaptureViewport: (fn: (() => Promise<string | null>) | null) => void;
  reset: () => void;
  resetDownstream: () => void;
}

export type Vec3 = [number, number, number];
export type PickMode =
  | "cl_source" | "cl_target" | "measure" | "neck_origin" | "neck_dome"
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
  const [segmentation, setSegmentation] = useState<SegmentResult | null>(null);
  const [candidates, setCandidates] = useState<AneurysmCandidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState(0);
  const [morphometry, setMorphometry] = useState<MorphometryResult | null>(null);
  const [treatment, setTreatment] = useState<TreatmentDecisionResult | null>(null);
  const [deviceMesh, setDeviceMesh] = useState<string | null>(null);
  const [centerlineMesh, setCenterlineMesh] = useState<string | null>(null);
  const [centerlineArcMm, setCenterlineArcMm] = useState<number | null>(null);
  const [mprWl, setMprWl] = useState<{ wc: number; ww: number } | null>(null);
  const [mprVoxel, setMprVoxel] = useState({ x: 0, y: 0, z: 0 });
  const [pickMode, setPickMode] = useState<PickMode>(null);
  const [clSource, setClSource] = useState<Vec3 | null>(null);
  const [clTarget, setClTarget] = useState<Vec3 | null>(null);
  const [neckOrigin, setNeckOrigin] = useState<Vec3 | null>(null);
  const [neckDome, setNeckDome] = useState<Vec3 | null>(null);
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [measurePending, setMeasurePending] = useState<Vec3 | null>(null);
  const [growSeeds, setGrowSeeds] = useState<Vec3[]>([]);
  const [mprSeedMode, setMprSeedMode] = useState(false);
  const [cropCenter, setCropCenter] = useState<Vec3 | null>(null);
  const [cropRadius, setCropRadius] = useState(10);
  const [cropShape, setCropShape] = useState<"sphere" | "box">("sphere");
  const [cropInvert, setCropInvert] = useState(false);
  const [trajEntry, setTrajEntry] = useState<Vec3 | null>(null);
  const [trajTarget, setTrajTarget] = useState<Vec3 | null>(null);
  const [morphoOverlay, setMorphoOverlay] = useState(false);
  const [captureViewport, setCaptureViewport] = useState<(() => Promise<string | null>) | null>(null);

  // Clear everything downstream of the DICOM upload — used when a new series is
  // uploaded in the same workspace so stale meshes/metrics don't linger.
  const resetDownstream = () => {
    setPreviewBand(null);
    setPreviewMeshUrl(null);
    setSegmentation(null);
    setCandidates([]);
    setSelectedCandidate(0);
    setMorphometry(null);
    setTreatment(null);
    setDeviceMesh(null);
    setCenterlineMesh(null);
    setCenterlineArcMm(null);
    setPickMode(null);
    setClSource(null);
    setClTarget(null);
    setNeckOrigin(null);
    setNeckDome(null);
    setMeasurements([]);
    setMeasurePending(null);
    setGrowSeeds([]);
    setMprSeedMode(false);
    setCropCenter(null);
    setTrajEntry(null);
    setTrajTarget(null);
    setMorphoOverlay(false);
  };

  const reset = () => {
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
        selectedCandidate, morphometry, treatment, deviceMesh,
        centerlineMesh, centerlineArcMm, mprWl, mprVoxel, pickMode, clSource, clTarget, neckOrigin, neckDome,
        measurements, measurePending, growSeeds, mprSeedMode, cropCenter, cropRadius, cropShape, cropInvert, trajEntry, trajTarget, morphoOverlay, captureViewport,
        setPatient, setCase, setImagingStudyId, setSession, setSeries, setPreviewBand, setPreviewMeshUrl, setSegmentation,
        setCandidates, setSelectedCandidate, setMorphometry, setTreatment,
        setDeviceMesh, setCenterlineMesh, setCenterlineArcMm, setMprWl, setMprVoxel,
        setPickMode, setClSource, setClTarget,
        setNeckOrigin, setNeckDome,
        setMeasurements, setMeasurePending, setGrowSeeds, setMprSeedMode, setCropCenter, setCropRadius, setCropShape, setCropInvert, setTrajEntry, setTrajTarget, setMorphoOverlay,
        setCaptureViewport,
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
