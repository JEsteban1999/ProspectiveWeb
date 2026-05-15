"""Backend services — pure Python processing modules (no Qt dependencies).

Modules
-------
sessions           — UUID-based session directory management and TTL cleanup
thresholds         — Auto-threshold computation for any DICOM modality (XA/CT/MR)
treatment          — CLIP vs ENDOVASCULAR decision engine (8-factor scoring)
clips              — Surgical clip library (42 models) + recommendation algorithm
coils              — Endovascular coil library (39 models) + sizing helpers
dicom_loader       — DICOM loading with SimpleITK + pydicom (multi-series, Enhanced XA)
segmentation       — Marching-cubes segmentation pipeline (VTK) + mesh I/O
aneurysm_detector  — Aneurysm candidate detection v6 (Gaussian curvature + shape gates)
morphometrics      — Full morphometric analysis (VTK plane slicing + ConvexHull)
perforator_risk    — Perforator vessel risk detection (vertex-valence anomaly)
database           — SQLAlchemy engine, Base, get_db(), init_db()  [Session D]
db_models          — ORM models: User, Patient, Study, PlanningSession  [Session D]
auth_service       — JWT creation/verification, password hashing, FastAPI deps  [Session D]
report_generator   — PDF report builder (reportlab) + session-data assembler  [Session E]
mesh_exporter      — STL export (VTK writer) + poly merge + scale utilities    [Session E]
"""
from .sessions import (
    create_session, session_dir, session_subdir, session_exists,
    delete_session, write_state, read_state, purge_expired_sessions,
    mesh_url, report_url, export_url,
    SESSIONS_ROOT,
)
from .thresholds import compute_auto_thresholds, strategy_hint, voxel_fraction as threshold_voxel_fraction
from .treatment  import compute_decision, LOCATIONS, LOCATION_UNKNOWN
from .clips      import (
    CLIP_CATALOGUE, recommend_clips,
    catalogue_to_api as clips_catalogue,
    recommendations_to_api,
)
from .coils      import (
    COIL_CATALOGUE, coils_for_aneurysm, estimate_coil_count,
    catalogue_to_api as coils_catalogue,
)
from .dicom_loader  import scan_series, load_series, DicomLoadResult
from .segmentation  import (
    SegmentationPipeline, SegmentationResult,
    write_vtp, write_stl, read_vtp,
    voxel_fraction as seg_voxel_fraction,
    level_to_smooth_iters, level_to_cleanup_verts,
)
from .aneurysm_detector import (
    AneurysmDetector,
    AneurysmCandidate as DetectorCandidate,
    DetectionResult,
)
from .morphometrics import (
    MorphometricAnalyzer,
    MorphometricResult,
)
from .perforator_risk import (
    compute_perforator_risk,
    neck_origin_from_morpho,
    PerforatorCandidate as PerforatorCandidateResult,
    PerforatorRiskResult,
)
from .report_generator import (
    ReportGenerator, ReportData, PatientInfo as ReportPatientInfo,
    build_report_data_from_session,
)
from .mesh_exporter import export_stl, merge_poly_datas, apply_scale
from .database import get_db, init_db, SessionLocal, Base
from .db_models import User, Patient, Study, PlanningSession
from .auth_service import (
    get_password_hash, verify_password,
    authenticate_user, create_access_token, decode_token,
    get_user_by_username, get_optional_user, get_current_user, require_user,
    seed_default_user,
)

# Ensure the sessions root directory exists at import time so that
# StaticFiles("/data") can mount it even before the first session is created.
SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)

__all__ = [
    # sessions
    "create_session", "session_dir", "session_subdir", "session_exists",
    "delete_session", "write_state", "read_state", "purge_expired_sessions",
    "mesh_url", "report_url", "export_url", "SESSIONS_ROOT",
    # thresholds
    "compute_auto_thresholds", "strategy_hint", "threshold_voxel_fraction",
    # treatment
    "compute_decision", "LOCATIONS", "LOCATION_UNKNOWN",
    # clips
    "CLIP_CATALOGUE", "recommend_clips", "clips_catalogue", "recommendations_to_api",
    # coils
    "COIL_CATALOGUE", "coils_for_aneurysm", "estimate_coil_count", "coils_catalogue",
    # dicom
    "scan_series", "load_series", "DicomLoadResult",
    # segmentation
    "SegmentationPipeline", "SegmentationResult",
    "write_vtp", "write_stl", "read_vtp", "seg_voxel_fraction",
    "level_to_smooth_iters", "level_to_cleanup_verts",
    # detection
    "AneurysmDetector", "DetectorCandidate", "DetectionResult",
    # morphometrics
    "MorphometricAnalyzer", "MorphometricResult",
    # perforators
    "compute_perforator_risk", "neck_origin_from_morpho",
    "PerforatorCandidateResult", "PerforatorRiskResult",
    # report / export (Session E)
    "ReportGenerator", "ReportData", "ReportPatientInfo",
    "build_report_data_from_session",
    "export_stl", "merge_poly_datas", "apply_scale",
    # database (Session D)
    "get_db", "init_db", "SessionLocal", "Base",
    # ORM models (Session D)
    "User", "Patient", "Study", "PlanningSession",
    # auth (Session D)
    "get_password_hash", "verify_password",
    "authenticate_user", "create_access_token", "decode_token",
    "get_user_by_username", "get_optional_user", "get_current_user", "require_user",
    "seed_default_user",
]
