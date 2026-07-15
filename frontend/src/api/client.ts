/* Thin typed client for the ProspectiveWeb FastAPI backend.
   All routes are same-origin in dev thanks to the Vite proxy. */

import type {
  AneurysmDetectionResult,
  AutoThresholdResult,
  CenterlineRequest,
  CenterlineResult,
  CrossSectionRequest,
  CrossSectionResult,
  ClipLibraryItem,
  ClipPlanRequest,
  ClipPlanResult,
  ClipRecommendation,
  CoilLibraryItem,
  CoilPlacement,
  CoilPlanResult,
  ExportRequest,
  LoginResponse,
  LongitudinalResult,
  MorphometryResult,
  PendingUser,
  PhasesRequest,
  PhasesResult,
  SignupRequest,
  SignupResponse,
  PatientCreate,
  PatientSummary,
  PerforatorsResult,
  ReportRequest,
  ReportResult,
  SegmentRequest,
  SegmentResult,
  SessionSaveRequest,
  SessionSaveResult,
  StentLibraryItem,
  StentParams,
  StentPlanResult,
  TreatmentDecisionRequest,
  TreatmentDecisionResult,
  UploadResult,
  UserInfo,
  VolumeMeta,
} from "./types";

const TOKEN_KEY = "prospective.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    body: body instanceof FormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });

export const api = {
  /* auth */
  login: (username: string, password: string) =>
    post<LoginResponse>("/api/auth/login", { username, password }),
  me: () => get<UserInfo>("/api/auth/me"),
  signup: (req: SignupRequest) => post<SignupResponse>("/api/auth/signup", req),
  listPending: () => get<PendingUser[]>("/api/auth/pending"),
  approvePending: (id: number) => post<{ status: string }>(`/api/auth/pending/${id}/approve`),
  rejectPending: (id: number) => post<{ status: string }>(`/api/auth/pending/${id}/reject`),

  /* patients */
  listPatients: () => get<PatientSummary[]>("/api/patients"),
  createPatient: (p: PatientCreate) => post<PatientSummary>("/api/patients", p),

  /* dicom pipeline */
  upload: (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    return post<UploadResult>("/api/upload", form);
  },
  thresholds: (sessionId: string) =>
    get<AutoThresholdResult>(`/api/thresholds/${sessionId}`),
  segment: (req: SegmentRequest) => post<SegmentResult>("/api/segment", req),
  detect: (sessionId: string) =>
    post<AneurysmDetectionResult>(`/api/detect/${sessionId}`),
  morphometry: (sessionId: string) =>
    get<MorphometryResult>(`/api/morphometry/${sessionId}`),
  perforators: (sessionId: string) =>
    get<PerforatorsResult>(`/api/perforators/${sessionId}`),
  longitudinal: (sessionId: string) =>
    get<LongitudinalResult>(`/api/longitudinal/${sessionId}`),
  phases: (req: PhasesRequest) => post<PhasesResult>("/api/phases", req),
  centerline: (sessionId: string, req: CenterlineRequest) =>
    post<CenterlineResult>(`/api/centerline/${sessionId}`, req),
  crossSection: (sessionId: string, req: CrossSectionRequest) =>
    post<CrossSectionResult>(`/api/cross-section/${sessionId}`, req),

  /* MPR / DICOM slice preview */
  volumeMeta: (sessionId: string) => get<VolumeMeta>(`/api/volume/${sessionId}/meta`),
  sliceUrl: (sessionId: string, plane: string, index: number, wc?: number, ww?: number) => {
    const q = new URLSearchParams();
    if (wc !== undefined) q.set("wc", String(Math.round(wc)));
    if (ww !== undefined) q.set("ww", String(Math.round(ww)));
    const qs = q.toString();
    return `/api/slice/${sessionId}/${plane}/${index}${qs ? `?${qs}` : ""}`;
  },

  /* treatment planning */
  treatmentDecision: (req: TreatmentDecisionRequest) =>
    post<TreatmentDecisionResult>("/api/treatment-decision", req),
  listClips: () => get<ClipLibraryItem[]>("/api/clips"),
  clipRecommendations: (sessionId: string) =>
    get<ClipRecommendation[]>(`/api/clips/recommendations/${sessionId}`),
  planClips: (req: ClipPlanRequest) => post<ClipPlanResult>("/api/clips/plan", req),
  listCoils: () => get<CoilLibraryItem[]>("/api/coils"),
  planCoils: (sessionId: string, placements: CoilPlacement[]) =>
    post<CoilPlanResult>("/api/coils/plan", { session_id: sessionId, placements }),
  listStents: () => get<StentLibraryItem[]>("/api/stents"),
  planStent: (sessionId: string, stent: StentParams) =>
    post<StentPlanResult>("/api/plan", { session_id: sessionId, stent }),

  /* report & export */
  report: (req: ReportRequest) => post<ReportResult>("/api/report", req),
  dicomSr: (req: ReportRequest) => post<ReportResult>("/api/report/dicom-sr", req),
  exportStl: (req: ExportRequest) => post<ReportResult>("/api/export/stl", req),

  /* sessions */
  saveSession: (req: SessionSaveRequest) =>
    post<SessionSaveResult>("/api/sessions/save", req),
};
