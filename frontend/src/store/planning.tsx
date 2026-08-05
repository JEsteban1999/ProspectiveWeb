/* PlanningContext — state shared across the 7-step workspace:
   session id, DICOM series, thresholds, segmentation, detection, morphometry… */

import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type {
  AneurysmCandidate,
  AutoThresholdResult,
  MorphometryResult,
  PatientSummary,
  SegmentResult,
  SeriesInfo,
  TreatmentDecisionResult,
} from "../api/types";

interface PlanningState {
  patient: PatientSummary | null;
  sessionId: string | null;
  series: SeriesInfo | null;
  thresholds: AutoThresholdResult | null;
  /** True while the auto-threshold is being fetched after upload (the volume
   *  load is slow on the first call), so the segmentation step can wait for the
   *  real band instead of showing the default slider values. */
  thresholdsLoading: boolean;
  /** Live threshold-preview band [lower, upper] HU set from the segmentation
   *  sliders; the MPR views tint the captured voxels in near-real-time. */
  previewBand: [number, number] | null;
  segmentation: SegmentResult | null;
  candidates: AneurysmCandidate[];
  selectedCandidate: number;
  morphometry: MorphometryResult | null;
  treatment: TreatmentDecisionResult | null;
  /** URL of the last placed device mesh (clip/coil/stent), shown in the viewer. */
  deviceMesh: string | null;
  /** URL of the extracted vessel centreline tube mesh, shown in the viewer. */
  centerlineMesh: string | null;
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
  /** Picked centre of the mesh-crop ROI (box/sphere). */
  cropCenter: Vec3 | null;

  setPatient: (p: PatientSummary | null) => void;
  setSession: (id: string | null) => void;
  setSeries: (s: SeriesInfo | null) => void;
  setThresholds: (t: AutoThresholdResult | null) => void;
  setThresholdsLoading: (v: boolean) => void;
  setPreviewBand: (b: [number, number] | null) => void;
  setSegmentation: (s: SegmentResult | null) => void;
  setCandidates: (c: AneurysmCandidate[]) => void;
  setSelectedCandidate: (i: number) => void;
  setMorphometry: (m: MorphometryResult | null) => void;
  setTreatment: (t: TreatmentDecisionResult | null) => void;
  setDeviceMesh: (url: string | null) => void;
  setCenterlineMesh: (url: string | null) => void;
  setPickMode: (m: PickMode) => void;
  setClSource: (p: Vec3 | null) => void;
  setClTarget: (p: Vec3 | null) => void;
  setNeckOrigin: (p: Vec3 | null) => void;
  setNeckDome: (p: Vec3 | null) => void;
  setMeasurements: (m: Measurement[]) => void;
  setMeasurePending: (p: Vec3 | null) => void;
  setGrowSeeds: (s: Vec3[]) => void;
  setCropCenter: (p: Vec3 | null) => void;
  reset: () => void;
  resetDownstream: () => void;
}

export type Vec3 = [number, number, number];
export type PickMode =
  | "cl_source" | "cl_target" | "measure" | "neck_origin" | "neck_dome"
  | "grow_seed" | "crop_center" | null;

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
  const [sessionId, setSession] = useState<string | null>(null);
  const [series, setSeries] = useState<SeriesInfo | null>(null);
  const [thresholds, setThresholds] = useState<AutoThresholdResult | null>(null);
  const [thresholdsLoading, setThresholdsLoading] = useState(false);
  const [previewBand, setPreviewBand] = useState<[number, number] | null>(null);
  const [segmentation, setSegmentation] = useState<SegmentResult | null>(null);
  const [candidates, setCandidates] = useState<AneurysmCandidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState(0);
  const [morphometry, setMorphometry] = useState<MorphometryResult | null>(null);
  const [treatment, setTreatment] = useState<TreatmentDecisionResult | null>(null);
  const [deviceMesh, setDeviceMesh] = useState<string | null>(null);
  const [centerlineMesh, setCenterlineMesh] = useState<string | null>(null);
  const [pickMode, setPickMode] = useState<PickMode>(null);
  const [clSource, setClSource] = useState<Vec3 | null>(null);
  const [clTarget, setClTarget] = useState<Vec3 | null>(null);
  const [neckOrigin, setNeckOrigin] = useState<Vec3 | null>(null);
  const [neckDome, setNeckDome] = useState<Vec3 | null>(null);
  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [measurePending, setMeasurePending] = useState<Vec3 | null>(null);
  const [growSeeds, setGrowSeeds] = useState<Vec3[]>([]);
  const [cropCenter, setCropCenter] = useState<Vec3 | null>(null);

  // Clear everything downstream of the DICOM upload — used when a new series is
  // uploaded in the same workspace so stale meshes/metrics don't linger.
  const resetDownstream = () => {
    setThresholds(null);
    setThresholdsLoading(false);
    setPreviewBand(null);
    setSegmentation(null);
    setCandidates([]);
    setSelectedCandidate(0);
    setMorphometry(null);
    setTreatment(null);
    setDeviceMesh(null);
    setCenterlineMesh(null);
    setPickMode(null);
    setClSource(null);
    setClTarget(null);
    setNeckOrigin(null);
    setNeckDome(null);
    setMeasurements([]);
    setMeasurePending(null);
    setGrowSeeds([]);
    setCropCenter(null);
  };

  const reset = () => {
    setSession(null);
    setSeries(null);
    resetDownstream();
  };

  return (
    <PlanningContext.Provider
      value={{
        patient, sessionId, series, thresholds, thresholdsLoading, previewBand, segmentation, candidates,
        selectedCandidate, morphometry, treatment, deviceMesh,
        centerlineMesh, pickMode, clSource, clTarget, neckOrigin, neckDome,
        measurements, measurePending, growSeeds, cropCenter,
        setPatient, setSession, setSeries, setThresholds, setThresholdsLoading, setPreviewBand, setSegmentation,
        setCandidates, setSelectedCandidate, setMorphometry, setTreatment,
        setDeviceMesh, setCenterlineMesh, setPickMode, setClSource, setClTarget,
        setNeckOrigin, setNeckDome,
        setMeasurements, setMeasurePending, setGrowSeeds, setCropCenter,
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
