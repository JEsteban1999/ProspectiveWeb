/* Thin typed client for the ProspectiveWeb FastAPI backend.
   All routes are same-origin in dev thanks to the Vite proxy. */

import type {
  AneurysmDetectionResult,
  AuditBlock,
  AuditVerifyResult,
  CenterlineRequest,
  CenterlineResult,
  CrossSectionRequest,
  CrossSectionResult,
  ClStentRequest,
  ClStentResult,
  ClipLibraryItem,
  ClipPlanRequest,
  ClipPlanResult,
  ClipRecommendation,
  CustomClipInfo,
  CoilLibraryItem,
  CoilPlacement,
  CoilPlanResult,
  ExportRequest,
  GrowRequest,
  GrowResult,
  LoginResponse,
  LongitudinalResult,
  MeshCropRequest,
  MeshCropResult,
  MorphometryResult,
  NeckPlaneRequest,
  PendingUser,
  PhasesRequest,
  PhasesResult,
  PreprocessRequest,
  PreprocessResult,
  PrintBed,
  PrintPrepRequest,
  PrintPrepResult,
  SignupRequest,
  SignupResponse,
  CaseCreate,
  PatientCreate,
  PatientDetail,
  PatientSessionInfo,
  PatientSummary,
  StudyCreate,
  StudySummary,
  PerforatorsResult,
  ReportRequest,
  ReportResult,
  SegmentRequest,
  SegmentResult,
  SuggestedBand,
  PreviewRequest,
  PreviewResult,
  SessionSaveRequest,
  SessionSaveResult,
  SessionRestoreResult,
  StentLibraryItem,
  StentParams,
  StentPlanResult,
  TrajectoryRequest,
  TrajectoryResult,
  TreatmentDecisionRequest,
  TreatmentDecisionResult,
  UploadResult,
  SeriesInfo,
  UserAdminInfo,
  UserInfo,
  UserUpdate,
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
  // 204 No Content (e.g. DELETE) has no body to parse.
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

/** Authenticated fetch returning the raw Blob (for images / documents that an
 *  <img src> or download link can't carry the JWT header for). */
async function getBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { headers });
  if (!res.ok) throw new ApiError(res.status, `Error ${res.status}`);
  return res.blob();
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
  myPhotoObjectUrl: async () =>
    URL.createObjectURL(await getBlob("/api/auth/me/photo")),
  signup: (req: SignupRequest, photo?: File | null, cv?: File | null) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(req)) fd.append(k, v ?? "");
    if (photo) fd.append("photo", photo, photo.name);
    if (cv) fd.append("cv", cv, cv.name);
    return post<SignupResponse>("/api/auth/signup", fd);
  },
  listPending: () => get<PendingUser[]>("/api/auth/pending"),
  pendingPhotoObjectUrl: async (id: number) =>
    URL.createObjectURL(await getBlob(`/api/auth/pending/${id}/photo`)),
  downloadPendingCv: async (id: number, username: string) => {
    const url = URL.createObjectURL(await getBlob(`/api/auth/pending/${id}/cv`));
    const a = document.createElement("a");
    a.href = url; a.download = `CV_${username}`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  },
  approvePending: (id: number) => post<{ status: string }>(`/api/auth/pending/${id}/approve`),
  rejectPending: (id: number) => post<{ status: string }>(`/api/auth/pending/${id}/reject`),
  listUsers: () => get<UserAdminInfo[]>("/api/auth/users"),
  createUser: (fields: Record<string, string>, photo?: File | null, cv?: File | null) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) fd.append(k, v ?? "");
    if (photo) fd.append("photo", photo, photo.name);
    if (cv) fd.append("cv", cv, cv.name);
    return post<UserAdminInfo>("/api/auth/users", fd);
  },
  updateUser: (id: number, u: UserUpdate) =>
    request<UserAdminInfo>(`/api/auth/users/${id}`, { method: "PUT", body: JSON.stringify(u), headers: { "Content-Type": "application/json" } }),
  deleteUser: (id: number) =>
    request<void>(`/api/auth/users/${id}`, { method: "DELETE" }),

  /* patients */
  listPatients: () => get<PatientSummary[]>("/api/patients"),
  createPatient: (p: PatientCreate) => post<PatientSummary>("/api/patients", p),
  createCase: (c: CaseCreate) => post<PatientSummary>("/api/patients/case", c),
  patientStudies: (id: number) => get<StudySummary[]>(`/api/patients/${id}/studies`),
  createStudy: (patientId: number, s: StudyCreate) =>
    post<StudySummary>(`/api/patients/${patientId}/studies`, s),
  updateStudy: (patientId: number, studyId: number, s: StudyCreate) =>
    request<StudySummary>(`/api/patients/${patientId}/studies/${studyId}`, { method: "PUT", body: JSON.stringify(s), headers: { "Content-Type": "application/json" } }),
  deleteStudy: (patientId: number, studyId: number) =>
    request<void>(`/api/patients/${patientId}/studies/${studyId}`, { method: "DELETE" }),
  getPatient: (id: number) => get<PatientDetail>(`/api/patients/${id}`),
  updatePatient: (id: number, p: PatientCreate) =>
    request<PatientSummary>(`/api/patients/${id}`, { method: "PUT", body: JSON.stringify(p), headers: { "Content-Type": "application/json" } }),
  deletePatient: (id: number) =>
    request<void>(`/api/patients/${id}`, { method: "DELETE" }),
  patientSessions: (id: number) =>
    get<PatientSessionInfo[]>(`/api/patients/${id}/sessions`),

  /* dicom pipeline */
  upload: (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    return post<UploadResult>("/api/upload", form);
  },
  segment: (req: SegmentRequest) => post<SegmentResult>("/api/segment", req),
  suggestedBand: (sessionId: string) =>
    get<SuggestedBand>(`/api/segment/suggested-band/${sessionId}`),
  segmentPreview: (sessionId: string, req: PreviewRequest) =>
    post<PreviewResult>(`/api/segment/preview/${sessionId}`, req),
  segmentGrow: (sessionId: string, req: GrowRequest) =>
    post<GrowResult>(`/api/segment/grow/${sessionId}`, req),
  meshCrop: (sessionId: string, req: MeshCropRequest) =>
    post<MeshCropResult>(`/api/mesh-crop/${sessionId}`, req),
  detect: (sessionId: string) =>
    post<AneurysmDetectionResult>(`/api/detect/${sessionId}`),
  morphometry: (sessionId: string) =>
    get<MorphometryResult>(`/api/morphometry/${sessionId}`),
  morphometryNeckPlane: (sessionId: string, req: NeckPlaneRequest) =>
    post<MorphometryResult>(`/api/morphometry/${sessionId}/neck-plane`, req),
  perforators: (sessionId: string) =>
    get<PerforatorsResult>(`/api/perforators/${sessionId}`),
  longitudinal: (sessionId: string) =>
    get<LongitudinalResult>(`/api/longitudinal/${sessionId}`),
  phases: (req: PhasesRequest) => post<PhasesResult>("/api/phases", req),
  centerline: (sessionId: string, req: CenterlineRequest) =>
    post<CenterlineResult>(`/api/centerline/${sessionId}`, req),
  crossSection: (sessionId: string, req: CrossSectionRequest) =>
    post<CrossSectionResult>(`/api/cross-section/${sessionId}`, req),
  deployClStent: (sessionId: string, req: ClStentRequest) =>
    post<ClStentResult>(`/api/cl-stent/${sessionId}`, req),
  setTrajectory: (sessionId: string, req: TrajectoryRequest) =>
    post<TrajectoryResult>(`/api/trajectory/${sessionId}`, req),
  clearTrajectory: (sessionId: string) =>
    request<void>(`/api/trajectory/${sessionId}`, { method: "DELETE" }),
  preprocess: (sessionId: string, req: PreprocessRequest) =>
    post<PreprocessResult>(`/api/preprocess/${sessionId}`, req),
  printBeds: () => get<PrintBed[]>("/api/print-prep/beds"),
  printPrep: (sessionId: string, req: PrintPrepRequest) =>
    post<PrintPrepResult>(`/api/print-prep/${sessionId}`, req),

  /* MPR / DICOM slice preview */
  volumeMeta: (sessionId: string) => get<VolumeMeta>(`/api/volume/${sessionId}/meta`),
  volumeRawUrl: (sessionId: string) => `/api/volume/${sessionId}/raw`,
  sliceObliqueUrl: (sessionId: string, tilt: number, pos: number, axis: string, wc?: number, ww?: number) => {
    const q = new URLSearchParams({ tilt: String(tilt), pos: String(pos), axis });
    if (wc !== undefined) q.set("wc", String(Math.round(wc)));
    if (ww !== undefined) q.set("ww", String(Math.round(ww)));
    return `/api/slice-oblique/${sessionId}?${q.toString()}`;
  },
  sliceUrl: (sessionId: string, plane: string, index: number, wc?: number, ww?: number, band?: [number, number] | null) => {
    const q = new URLSearchParams();
    if (wc !== undefined) q.set("wc", String(Math.round(wc)));
    if (ww !== undefined) q.set("ww", String(Math.round(ww)));
    if (band) { q.set("lower", String(Math.round(band[0]))); q.set("upper", String(Math.round(band[1]))); }
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
  uploadCustomClip: (sessionId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return post<CustomClipInfo>(`/api/clips/custom/${sessionId}`, fd);
  },
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
  restoreSession: (sessionId: string) =>
    post<SessionRestoreResult>(`/api/sessions/${sessionId}/restore`),
  /** Switch which DICOM series of the study the session works on. */
  setActiveSeries: (sessionId: string, seriesId: string) =>
    post<SeriesInfo>(`/api/upload/${sessionId}/series/${encodeURIComponent(seriesId)}`),

  /* audit (SkullChain) */
  auditBlocks: () => get<AuditBlock[]>("/api/audit/blocks"),
  auditVerify: () => get<AuditVerifyResult>("/api/audit/verify"),
};
