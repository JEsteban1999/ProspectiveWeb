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
  has_photo?: boolean;
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
  has_photo: boolean;
  has_cv: boolean;
  created_at: string;
}

export interface UserAdminInfo {
  id: number;
  username: string;
  full_name: string;
  role: string;
  status: string;
  is_active: boolean;
  specialty: string;
  hospital: string;
  has_photo: boolean;
  has_cv: boolean;
  created_at: string;
}

export interface UserUpdate {
  full_name?: string;
  role?: string;
  is_active?: boolean;
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

export interface CrossSectionRequest {
  session_id: string;
  n_samples: number;
}

export interface CrossSectionResult {
  arc_positions_mm: number[];
  diameters_mm: number[];
  mean_diameter_mm: number;
  median_diameter_mm: number;
  min_diameter_mm: number;
  max_diameter_mm: number;
  mean_area_mm2: number;
  stenosis_ratio: number;
  stenosis_pct: number;
  stenosis_label: string;
  warning: string | null;
}

/* ── audit (SkullChain) ─────────────────────────────────────────────────── */
export interface AuditBlock {
  id: number;
  iso_ts: string;
  username: string;
  action: string;
  patient_hash: string;
  payload_json: string;
  block_hash: string;
  prev_hash: string;
}

export interface AuditVerifyResult {
  ok: boolean;
  total_blocks: number;
  broken: { id: number; iso_ts: string; action: string; reason: string }[];
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
  antecedentes_toxicologicos?: string;
  antecedentes_quirurgicos?: string;
  antecedentes_alergicos?: string;
  antecedentes_farmacologicos?: string;
  notes?: string;
}

export interface PatientDetail extends PatientCreate {
  id: number;
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

/** Full "Nuevo Caso" payload — creates a Patient + a Study. */
export interface CaseCreate {
  surname: string;
  given_name?: string;
  hospital_id?: string;
  dob?: string;
  sex?: string;
  institution?: string;
  ocupacion?: string;
  antecedentes_patologicos?: string;
  antecedentes_toxicologicos?: string;
  antecedentes_quirurgicos?: string;
  antecedentes_alergicos?: string;
  antecedentes_farmacologicos?: string;
  notes?: string;
  study_date?: string;
  sintomas_positivos?: string;
  dx_principal: string;
  dx_secundario?: string;
  tipo_aneurisma?: string;
  tratamiento_propuesto?: string;
  region_anatomica?: string;
  lateralidad?: string;
  angiographer?: string;
  mod_tac?: boolean;
  mod_angio?: boolean;
  mod_rm?: boolean;
  mod_pangio?: boolean;
}

/** Clinical study/case for an existing patient (sections 3-5 of Nuevo Caso). */
export interface StudyCreate {
  study_date?: string;
  sintomas_positivos?: string;
  dx_principal: string;
  dx_secundario?: string;
  tipo_aneurisma?: string;
  tratamiento_propuesto?: string;
  region_anatomica?: string;
  lateralidad?: string;
  angiographer?: string;
  mod_tac?: boolean;
  mod_angio?: boolean;
  mod_rm?: boolean;
  mod_pangio?: boolean;
}

export interface StudySummary {
  id: number;
  patient_id: number;
  dicom_path: string;
  modality: string;
  description: string;
  acquired_at: string;
  session_count: number;
  sintomas_positivos: string;
  dx_principal: string;
  dx_secundario: string;
  tipo_aneurisma: string;
  tratamiento_propuesto: string;
  region_anatomica: string;
  lateralidad: string;
  angiographer: string;
  mod_tac: boolean;
  mod_angio: boolean;
  mod_rm: boolean;
  mod_pangio: boolean;
}

export interface PatientSessionInfo {
  session_id: string;
  label: string;
  current_step: number;
  max_diameter_mm: number | null;
  rupture_risk_label: string | null;
  created_at: string;
  updated_at: string;
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
export interface SuggestedBand {
  lower: number;
  upper: number;
  vmin: number;
  vmax: number;
}

export interface PreviewRequest {
  lower: number;
  upper: number;
  cleanup?: number;
  downsample?: number;
}

export interface PreviewResult {
  mesh_url: string;
  vertices: number;
  voxel_fraction: number;
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

/* ── interactive mesh editing: ROI crop + grow-from-seeds ───────────────── */
export interface MeshCropRequest {
  mode: "box" | "sphere";
  center: Position3D;
  radius?: number;
  half_size?: Position3D | null;
  invert?: boolean;
}

export interface MeshCropResult {
  mesh_url: string;
  vertices: number;
  faces: number;
  removed_vertices: number;
}

export interface GrowRequest {
  seeds: Position3D[];
  lower?: number;
  upper?: number;
  auto_band?: boolean;
  smoothing?: number;
  cleanup?: number;
}

export interface GrowResult {
  mesh_url: string;
  vertices: number;
  faces: number;
  n_voxels: number;
  fragments_removed: number;
  seeds: number;
  band_lower: number;
  band_upper: number;
}

/* ── surgical approach trajectory ──────────────────────────────────────── */
export interface TrajectoryRequest {
  entry: Position3D;
  target: Position3D;
}

export interface TrajectoryResult {
  entry: number[];
  target: number[];
  depth_mm: number;
  angle_deg: number;
}

/* ── DICOM volume preprocessing ────────────────────────────────────────── */
export interface PreprocessRequest {
  clip_hu?: boolean;
  resample_isotropic?: boolean;
  target_spacing_mm?: number;
  smooth?: boolean;
  smooth_sigma?: number;
}

export interface PreprocessResult {
  shape_before: number[];
  shape_after: number[];
  spacing_before: number[];
  spacing_after: number[];
  note: string;
}

/* ── 3D-print preparation ──────────────────────────────────────────────── */
export interface PrintBed {
  name: string;
  x_mm: number;
  y_mm: number;
  z_mm: number;
}

export interface PrintPrepRequest {
  target_size_mm?: number;
  smooth_iterations?: number;
  smooth_relaxation?: number;
  fill_holes?: boolean;
  hole_size?: number;
  subdivide?: boolean;
  bed_x_mm?: number;
  bed_y_mm?: number;
  bed_z_mm?: number;
}

export interface PrintPrepResult {
  stl_url: string;
  scale_factor: number;
  dimensions_mm: number[];
  volume_cm3: number;
  surface_area_cm2: number;
  is_watertight: boolean;
  open_edge_count: number;
  fits_in_bed: boolean;
  warnings: string[];
}

/* ── centreline-guided stent (cl_stent) ────────────────────────────────── */
export interface ClStentRequest {
  session_id: string;
  stent_diameter_mm: number;
  start_arc_mm?: number | null;
  end_arc_mm?: number | null;
  braid?: boolean;
  braid_count?: number;
}

export interface ClStentResult {
  stent_mesh_url: string;
  length_mm: number;
  nominal_diameter_mm: number;
  mean_vessel_diameter_mm: number;
  coverage_ratio: number;
  total_arc_mm: number;
  warning: string | null;
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
  reliable: boolean;
  neck_source: "auto" | "manual";
  neck_valid: boolean;
  warning: string | null;
  centroid: Position3D | null;
  principal_axis: number[] | null;
}

/** User-defined neck plane for semi-automatic closed-sac morphometry. */
export interface NeckPlaneRequest {
  origin: Position3D;
  normal: number[];          // [x, y, z] toward the dome
  dome_seed?: Position3D | null;
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

export interface CustomClipInfo {
  clip_id: string;
  name: string;
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

export interface SessionRestoreResult {
  session_id: string;      // NEW live session id to use from now on
  current_step: number;
  label: string;
  has_segmentation: boolean;
  has_detection: boolean;
  has_morphometry: boolean;
  has_plan: boolean;
  restored_at: string;
  mesh_url: string;
  n_vertices: number;
  n_faces: number;
  modality: string;
  patient_id: number | null;
  study_id: number | null;
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

/* ── study gallery ─────────────────────────────────────────────────────── */
export interface StudyCard {
  id: number;
  patient_id: number;
  patient_name: string;
  hospital_id: string;
  description: string;
  modality: string;
  acquired_at: string;
  dx_principal: string;
  created_at: string;
  archived: boolean;
  has_thumbnail: boolean;
  n_files: number;
  n_slices: number;
  size_mb: number;
  session_count: number;
  last_step: number | null;
  max_diameter_mm: number | null;
  rupture_risk_label: string | null;
}

export interface OpenStudyResult {
  session_id: string;
  study_id: number;
  n_files: number;
}
