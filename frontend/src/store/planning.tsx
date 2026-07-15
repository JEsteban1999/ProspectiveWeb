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
  segmentation: SegmentResult | null;
  candidates: AneurysmCandidate[];
  selectedCandidate: number;
  morphometry: MorphometryResult | null;
  treatment: TreatmentDecisionResult | null;
  /** URL of the last placed device mesh (clip/coil/stent), shown in the viewer. */
  deviceMesh: string | null;

  setPatient: (p: PatientSummary | null) => void;
  setSession: (id: string | null) => void;
  setSeries: (s: SeriesInfo | null) => void;
  setThresholds: (t: AutoThresholdResult | null) => void;
  setSegmentation: (s: SegmentResult | null) => void;
  setCandidates: (c: AneurysmCandidate[]) => void;
  setSelectedCandidate: (i: number) => void;
  setMorphometry: (m: MorphometryResult | null) => void;
  setTreatment: (t: TreatmentDecisionResult | null) => void;
  setDeviceMesh: (url: string | null) => void;
  reset: () => void;
  resetDownstream: () => void;
}

const PlanningContext = createContext<PlanningState | null>(null);

export function PlanningProvider({ children }: { children: ReactNode }) {
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [sessionId, setSession] = useState<string | null>(null);
  const [series, setSeries] = useState<SeriesInfo | null>(null);
  const [thresholds, setThresholds] = useState<AutoThresholdResult | null>(null);
  const [segmentation, setSegmentation] = useState<SegmentResult | null>(null);
  const [candidates, setCandidates] = useState<AneurysmCandidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState(0);
  const [morphometry, setMorphometry] = useState<MorphometryResult | null>(null);
  const [treatment, setTreatment] = useState<TreatmentDecisionResult | null>(null);
  const [deviceMesh, setDeviceMesh] = useState<string | null>(null);

  // Clear everything downstream of the DICOM upload — used when a new series is
  // uploaded in the same workspace so stale meshes/metrics don't linger.
  const resetDownstream = () => {
    setThresholds(null);
    setSegmentation(null);
    setCandidates([]);
    setSelectedCandidate(0);
    setMorphometry(null);
    setTreatment(null);
    setDeviceMesh(null);
  };

  const reset = () => {
    setSession(null);
    setSeries(null);
    resetDownstream();
  };

  return (
    <PlanningContext.Provider
      value={{
        patient, sessionId, series, thresholds, segmentation, candidates,
        selectedCandidate, morphometry, treatment, deviceMesh,
        setPatient, setSession, setSeries, setThresholds, setSegmentation,
        setCandidates, setSelectedCandidate, setMorphometry, setTreatment,
        setDeviceMesh, reset, resetDownstream,
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
