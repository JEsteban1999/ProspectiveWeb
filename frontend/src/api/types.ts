/* TypeScript mirror of the backend Pydantic models (backend/models/*.py).
   Field names match the JSON contract exactly — see openapi.json. */

/* ── auth ──────────────────────────────────────────────────────────────── */
export interface UserInfo {
  id: number;
  username: string;
  full_name: string;
  role: string;
  institution: string;
  avatar_initials: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserInfo;
}

export interface SignupRequest {
  username: string;
  password: string;
  full_name: string;
  national_id?: string;
  professional_id?: string;
  specialty?: string;
  university?: string;
  hospital?: string;
  position?: string;
  orcid?: string;
}

export interface SignupResponse {
  status: string;
  message: string;
}

export interface PendingUser {
  id: number;
  username: string;
  full_name: string;
  national_id: string;
  professional_id: string;
  specialty: string;
  university: string;
  hospital: string;
  position: string;
  orcid: string;
  created_at: string;
}

/* ── PHASES score ──────────────────────────────────────────────────────── */
export type PhasesPopulation = "other" | "japan" | "finland";
export type PhasesSite = "ica" | "mca" | "aca_pcom_posterior";

export interface PhasesRequest {
  population: PhasesPopulation;
  hypertension: boolean;
  age_years: number;
  size_mm: number;
  earlier_sah: boolean;
  site: PhasesSite;
}

export interface PhasesResult {
  population_pts: number;
  hypertension_pts: number;
  age_pts: number;
  size_pts: number;
  sah_pts: number;
  site_pts: number;
  total_score: number;
  risk_5yr_pct: number;
  risk_band: "low" | "moderate" | "high";
}

/* ── centerline ────────────────────────────────────────────────────────── */
export interface CenterlineRequest {
  session_id: string;
  source: { x: number; y: number; z: number };
  target: { x: number; y: number; z: number };
  voxel_size_mm: number;
}

export interface CenterlineResult {
  centerline_mesh_url: string;
  n_points: number;
  arc_length_mm: number;
  chord_length_mm: number;
  tortuosity: number;
  tortuosity_index_pct: number;
  mean_diameter_mm: number;
  min_diameter_mm: number;
  max_diameter_mm: number;
  warning: string | null;
}

/* ── patients ──────────────────────────────────────────────────────────── */
export interface PatientCreate {
  surname: string;
  given_name?: string;
  hospital_id?: string;
  dob?: string;
  sex?: string;
  institution?: string;
  ocupacion?: string;
  antecedentes_patologicos?: string;
  antecedentes_farmacologicos?: string;
  notes?: string;
}

export interface PatientSummary {
  id: number;
  full_name: string;
  hospital_id: string;
  dob: string;
  sex: string;
  institution: string;
  study_count: number;
  created_at: string;
}

/* ── dicom / upload ────────────────────────────────────────────────────── */
export interface SpacingXYZ {
  x: number;
  y: number;
  z: number;
}

export interface SeriesInfo {
  session_id: string;
  series_id: string;
  description: string;
  modality: string;
  slices: number;
  spacing: SpacingXYZ;
  window_center: number;
  window_width: number;
  is_projection: boolean;
  projection_warning: string | null;
  size_mb: number;
}

export interface UploadResult {
  session_id: string;
  series: SeriesInfo[];
  total_files: number;
}

/* ── MPR / volume ──────────────────────────────────────────────────────── */
export interface VolumeMeta {
  /** [z, y, x] */
  shape: [number, number, number];
  /** [sz, sy, sx] mm */
  spacing: [number, number, number];
  wc: number;
  ww: number;
  modality: string;
}

/* ── segmentation ──────────────────────────────────────────────────────── */
export interface AutoThresholdResult {
  lower: number;
  upper: number;
  strategy: string;
  is_dsa: boolean;
  hint: string;
  voxel_fraction: number | null;
}

export interface SegmentRequest {
  session_id: string;
  series_id: string;
  lower: number;
  upper: number;
  smoothing: number;
  cleanup: number;
}

export interface SegmentResult {
  mesh_url: string;
  voxel_fraction: number | null;
  strategy: string;
  is_dsa: boolean;
  vertices: number;
  faces: number;
}

/* ── detection / morphometry ───────────────────────────────────────────── */
export interface Position3D {
  x: number;
  y: number;
  z: number;
}

export interface AneurysmCandidate {
  id: string;
  center_mm: Position3D;
  max_diameter_mm: number;
  confidence: number;
  dome_mesh_url: string;
  selected: boolean;
}

export interface AneurysmDetectionResult {
  found: boolean;
  candidates: AneurysmCandidate[];
}

export type RiskLabel = "Alto" | "Moderado" | "Bajo";

export interface MorphometryResult {
  volume_mm3: number;
  surface_area_mm2: number;
  eq_sphere_diam_mm: number;
  max_diameter_mm: number;
  bbox_w_mm: number;
  bbox_h_mm: number;
  neck_mm: number;
  dome_height_mm: number;
  dnr: number;
  ar: number;
  bf: number;
  compactness: number;
  ui: number;
  ei: number;
  nsi: number;
  sr: number;
  rupture_risk_label: RiskLabel;
  neck_valid: boolean;
  warning: string | null;
  centroid: Position3D | null;
  principal_axis: number[] | null;
}

/* ── perforators ───────────────────────────────────────────────────────── */
export interface PerforatorCandidate {
  id: string;
  position_mm: Position3D;
  radius_mm: number;
  distance_to_neck_mm: number;
  risk_level: 1 | 2 | 3;
  risk_label: string;
  risk_color: string;
}

export interface PerforatorsResult {
  candidates: PerforatorCandidate[];
  high_count: number;
  medium_count: number;
  low_count: number;
  search_radius_mm: number;
}

/* ── treatment decision ────────────────────────────────────────────────── */
export const ANEURYSM_LOCATIONS = [
  "Desconocida / No especificada",
  "ACM — Arteria Cerebral Media",
  "ACA / ACoA — Arteria Comunicante Anterior",
  "ACI proximal (segm. cavernoso / clinoideo)",
  "ACI distal (PCOM / oftálmica)",
  "ACoP — Arteria Comunicante Posterior",
  "Basilar (punta, tronco o AICA)",
  "PICA / Vertebral",
  "Otra localización",
] as const;

export type AneurysmLocation = (typeof ANEURYSM_LOCATIONS)[number];

export interface DecisionFactor {
  name: string;
  detail: string;
  direction: "clip" | "endo" | "neutral";
  points: number;
}

export interface TreatmentDecisionRequest {
  session_id: string;
  location: AneurysmLocation;
  is_ruptured: boolean;
  patient_age: number | null;
  has_comorbidities: boolean;
}

export interface TreatmentDecisionResult {
  clip_pct: number;
  endo_pct: number;
  balance: number;
  recommendation: string;
  recommendation_key: "clip" | "endo" | "mdt" | "surveillance";
  confidence: "Alta" | "Moderada" | "Baja";
  factors: DecisionFactor[];
  clip_factors: string[];
  endo_factors: string[];
}

/* ── devices: clips ────────────────────────────────────────────────────── */
export interface ClipLibraryItem {
  id: string;
  name: string;
  manufacturer: string;
  length_mm: number;
  angle_deg: number;
  is_fenestrated: boolean;
  closing_force_g: number;
  compatible_applier: string;
}

export interface ClipPlacement {
  clip_id: string;
  position: Position3D;
  normal: number[];
  rotation_deg: number;
}

export interface ClipRecommendation {
  clip_id: string;
  clip_name: string;
  score: number;
  reason: string;
  suggested_placement: ClipPlacement | null;
}

export interface ClipPlanRequest {
  session_id: string;
  placements: ClipPlacement[];
  trajectory_entry?: Position3D | null;
  trajectory_target?: Position3D | null;
}

export interface ClipPlanResult {
  clips_mesh_url: string;
  trajectory_mesh_url: string | null;
  neck_coverage_pct: number;
  collision_detected: boolean;
  warning: string | null;
}

/* ── devices: coils ────────────────────────────────────────────────────── */
export interface CoilLibraryItem {
  id: string;
  name: string;
  manufacturer: string;
  diameter_mm: number;
  length_cm: number;
  coil_type: string;
  is_detachable: boolean;
}

export interface CoilPlacement {
  coil_id: string;
  position: Position3D;
  packing_density: number;
}

export interface CoilPlanResult {
  coils_mesh_url: string;
  total_packing_density: number;
  estimated_occlusion_pct: number;
  warning: string | null;
}

/* ── devices: stents ───────────────────────────────────────────────────── */
export interface StentLibraryItem {
  id: string;
  name: string;
  manufacturer: string;
  min_diameter_mm: number;
  max_diameter_mm: number;
  available_lengths_mm: number[];
  type: string;
}

export interface StentParams {
  stent_id: string;
  diameter_mm: number;
  length_mm: number;
  position: Position3D;
  rotation_deg: number;
}

export interface StentPlanResult {
  stent_mesh_url: string;
  coverage_pct: number;
  neck_diameter_covered_mm: number;
  deployed: boolean;
  warning: string | null;
}

/* ── report / export ───────────────────────────────────────────────────── */
export interface ReportRequest {
  session_id: string;
  patient_name?: string;
  patient_dob?: string;
  patient_sex?: string;
  hospital_id?: string;
  surgeon_name?: string;
  institution?: string;
  report_date?: string;
  clinical_notes?: string;
  include_3d_screenshot?: boolean;
  screenshot_png_b64?: string | null;
}

export interface ReportResult {
  pdf_url: string | null;
  dicom_sr_url: string | null;
  stl_url: string | null;
  generated_at: string;
  page_count: number | null;
}

export interface ExportRequest {
  session_id: string;
  include_vessel_tree?: boolean;
  include_aneurysm_dome?: boolean;
  include_skull?: boolean;
  scale_factor?: number;
}

/* ── sessions ──────────────────────────────────────────────────────────── */
export interface SessionSaveRequest {
  session_id: string;
  label?: string;
  patient_id?: number | null;
  study_id?: number | null;
  current_step?: number;
}

export interface SessionSaveResult {
  file_path: string;
  download_url: string;
  saved_at: string;
}

/* ── longitudinal ──────────────────────────────────────────────────────── */
export interface LongitudinalEntry {
  session_date: string;
  session_label: string;
  max_diameter_mm: number;
  neck_mm: number;
  volume_mm3: number;
  ar: number;
  dnr: number;
  rupture_risk_label: string;
}

export interface LongitudinalDelta {
  metric: string;
  label: string;
  value_current: number;
  value_previous: number;
  delta: number;
  delta_pct: number;
  trend: string;
  is_concerning: boolean;
}

export interface LongitudinalResult {
  patient_id: number | null;
  entries: LongitudinalEntry[];
  deltas: LongitudinalDelta[];
  growth_alert: boolean;
  growth_alert_message: string | null;
}
