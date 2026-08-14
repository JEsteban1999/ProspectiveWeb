"""Report generation and STL export router — Session E.

POST /api/report      — generate PDF surgical plan (reportlab)
POST /api/export/stl  — export merged VTP meshes as STL (VTK)
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import ReportRequest, ReportResult, ExportRequest
from models.trajectory import TrajectoryRequest, TrajectoryResult
from services.database import get_db
from services.sessions import (
    session_exists, session_subdir, read_state, write_state,
)
from services.report_generator import (
    ReportGenerator, build_report_data_from_session, read_trajectory_state,
)
from services.dicom_sr import DicomSRGenerator
from services.mesh_exporter import export_stl, merge_poly_datas, apply_scale
from services.segmentation import read_vtp

logger  = logging.getLogger(__name__)
router  = APIRouter(prefix="/api", tags=["report"])

# All CPU-bound reportlab / VTK work runs off the event loop
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="report-worker")


# ── POST /report ───────────────────────────────────────────────────────────── #

@router.post(
    "/report",
    response_model=ReportResult,
    summary="Generate surgical PDF report",
    description=(
        "Assembles all session data (morphometry, treatment decision, patient info) "
        "and generates a structured PDF using ReportLab.\n\n"
        "**Prerequisite:** the session must have completed at least the morphometry step "
        "(Step 3) for the report to contain clinical data.\n\n"
        "An optional `screenshot_png_b64` field (base64-encoded PNG) can be sent "
        "to embed the 3D viewer capture in the report.\n\n"
        "Returns a `/data/…` download URL pointing to the generated PDF."
    ),
)
async def generate_report(
    req: ReportRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ReportResult:
    if not session_exists(req.session_id):
        raise HTTPException(
            status_code=404,
            detail=f"Session '{req.session_id}' not found",
        )

    loop = asyncio.get_event_loop()

    def _generate_sync() -> Path:
        data = build_report_data_from_session(
            req.session_id,
            patient_name      = req.patient_name,
            patient_dob       = req.patient_dob,
            patient_sex       = req.patient_sex,
            hospital_id       = req.hospital_id,
            surgeon_name      = req.surgeon_name,
            institution       = req.institution,
            clinical_notes    = req.clinical_notes,
            screenshot_png_b64= req.screenshot_png_b64 if req.include_3d_screenshot else None,
            db                = db,
        )
        out_dir = session_subdir(req.session_id, "reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{req.session_id}_report.pdf"
        gen = ReportGenerator(data)
        return gen.generate(out_path)

    try:
        pdf_path: Path = await loop.run_in_executor(_executor, _generate_sync)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Report generation failed for session %s", req.session_id)
        raise HTTPException(status_code=500, detail=f"Report generation error: {exc}") from exc

    # Build the page count from the file (reportlab writes it as part of the PDF)
    # We can get an approximate page count by reading the PDF trailer — simpler:
    page_count = _pdf_page_count(pdf_path)

    pdf_url = f"/data/sessions/{req.session_id}/reports/{req.session_id}_report.pdf"

    from services.audit import audit_append, ACT_REPORT_GENERATED
    audit_append(ACT_REPORT_GENERATED, {"session_id": req.session_id, "pages": page_count},
                 username=req.surgeon_name or "", patient_id=req.hospital_id or "")

    logger.info(
        "Report generated — session=%s  pages=%s  size=%.1f KB",
        req.session_id, page_count, pdf_path.stat().st_size / 1024,
    )

    return ReportResult(
        pdf_url      = pdf_url,
        dicom_sr_url = None,    # DICOM SR not yet implemented in web backend
        stl_url      = None,
        generated_at = datetime.now(timezone.utc).isoformat(),
        page_count   = page_count,
    )


def _pdf_page_count(path: Path) -> int | None:
    """Best-effort page count from PDF trailer (/Count value)."""
    try:
        data = path.read_bytes()
        # Find last occurrence of /Count integer in the PDF
        import re
        matches = re.findall(rb"/Count\s+(\d+)", data)
        if matches:
            return int(matches[-1])
    except Exception:
        pass
    return None


# ── POST /report/dicom-sr ────────────────────────────────────────────────────── #

@router.post(
    "/report/dicom-sr",
    response_model=ReportResult,
    summary="Generate a DICOM Structured Report (SR)",
    description=(
        "Builds a DICOM Comprehensive SR (TID 1500) from the session's morphometry "
        "and risk assessment — an interoperable, PACS-storable record of the "
        "measurements. **Prerequisite:** the morphometry step must be complete.\n\n"
        "Returns a `/data/…` download URL pointing to the generated `.dcm` file."
    ),
)
async def generate_dicom_sr(
    req: ReportRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ReportResult:
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail=f"Session '{req.session_id}' not found")

    loop = asyncio.get_event_loop()

    def _generate_sync() -> Path:
        data = build_report_data_from_session(
            req.session_id,
            patient_name = req.patient_name,
            patient_dob  = req.patient_dob,
            patient_sex  = req.patient_sex,
            hospital_id  = req.hospital_id,
            surgeon_name = req.surgeon_name,
            institution  = req.institution,
            db           = db,
        )
        if not any(float(v or 0) for v in data.morphometrics.values()):
            raise ValueError(
                "No hay datos de morfometría en la sesión. Ejecuta la morfometría primero."
            )
        series_meta = {
            "patient_name":      data.patient.name,
            "patient_id":        data.patient.id,
            "study_date":        data.patient.study_date,
            "study_description": "PROSPECTIVE Surgical Plan",
        }
        # The SR builder already models clip/coil/stent containers, but nothing
        # was feeding them — the planned devices only existed in the PDF.
        stent = data.stent
        gen = DicomSRGenerator(
            series_meta   = series_meta,
            morphometrics = data.morphometrics,
            risk_label    = data.risk_label,
            trajectory    = data.trajectory or None,
            clips = [
                {"name": c.name, "is_custom": c.is_custom, "position_mm": c.position_mm}
                for c in data.clips
            ] or None,
            coils = [
                {"name": c.name, "coil_type": c.coil_type, "diameter_mm": c.diameter_mm}
                for c in data.coils
            ] or None,
            phases = data.phases or None,
            stents = [{
                "name":        stent.name,
                "stent_type":  "Guiado por línea central" if stent.kind == "centerline"
                               else "Recto / catálogo",
                "diameter_mm": stent.diameter_mm,
                "length_mm":   stent.length_mm,
            }] if stent is not None else None,
        )
        out_dir = session_subdir(req.session_id, "reports")
        return gen.generate(out_dir / f"{req.session_id}_sr.dcm")

    try:
        sr_path: Path = await loop.run_in_executor(_executor, _generate_sync)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("DICOM SR generation failed for session %s", req.session_id)
        raise HTTPException(status_code=500, detail=f"DICOM SR error: {exc}") from exc

    sr_url = f"/data/sessions/{req.session_id}/reports/{req.session_id}_sr.dcm"

    from services.audit import audit_append, ACT_SR_GENERATED
    audit_append(ACT_SR_GENERATED, {"session_id": req.session_id},
                 username=req.surgeon_name or "", patient_id=req.hospital_id or "")

    logger.info("DICOM SR generated — session=%s  size=%.1f KB",
                req.session_id, sr_path.stat().st_size / 1024)

    return ReportResult(
        pdf_url      = None,
        dicom_sr_url = sr_url,
        stl_url      = None,
        generated_at = datetime.now(timezone.utc).isoformat(),
        page_count   = None,
    )


# ── POST /export/stl ───────────────────────────────────────────────────────── #

@router.post(
    "/export/stl",
    response_model=ReportResult,
    summary="Export mesh as STL for 3D printing",
    description=(
        "Merges the selected session meshes (vessel tree and/or aneurysm dome) "
        "into a single STL file suitable for 3D printing.\n\n"
        "**Prerequisite:** the session must have completed the segmentation step "
        "(Step 2) so that `vessel_tree.vtp` exists.\n\n"
        "Use `scale_factor` to adjust physical dimensions (1.0 = real size in mm).\n\n"
        "Returns a `/data/…` download URL pointing to the generated `.stl` file."
    ),
)
async def export_stl_endpoint(
    req: ExportRequest,
) -> ReportResult:
    if not session_exists(req.session_id):
        raise HTTPException(
            status_code=404,
            detail=f"Session '{req.session_id}' not found",
        )

    meshes_dir = session_subdir(req.session_id, "meshes")
    vessel_vtp  = meshes_dir / "vessel_tree.vtp"

    # At least one mesh must be available
    if not vessel_vtp.exists() and req.include_vessel_tree:
        raise HTTPException(
            status_code=422,
            detail=(
                "vessel_tree.vtp not found in session. "
                "Run the segmentation step (POST /api/segment) first."
            ),
        )

    loop = asyncio.get_event_loop()

    def _export_sync() -> Path:
        parts = []

        if req.include_vessel_tree and vessel_vtp.exists():
            pd = read_vtp(vessel_vtp)
            if pd is not None:
                parts.append(pd)

        if req.include_aneurysm_dome:
            # Use the best candidate VTP stored in session state
            best_name = read_state(req.session_id, "detect.best_vtp_name", "")
            if best_name:
                cand_vtp = meshes_dir / best_name
                if cand_vtp.exists():
                    pd = read_vtp(cand_vtp)
                    if pd is not None:
                        parts.append(pd)

        if not parts:
            raise ValueError(
                "No mesh data available to export. "
                "Complete segmentation (and optionally detection) first."
            )

        merged  = merge_poly_datas(parts)
        scaled  = apply_scale(merged, req.scale_factor)

        out_dir = session_subdir(req.session_id, "exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{req.session_id}_export.stl"
        return export_stl(scaled, out_path, binary=True)

    try:
        stl_path: Path = await loop.run_in_executor(_executor, _export_sync)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("STL export failed for session %s", req.session_id)
        raise HTTPException(status_code=500, detail=f"STL export error: {exc}") from exc

    stl_url = f"/data/sessions/{req.session_id}/exports/{req.session_id}_export.stl"

    logger.info(
        "STL exported — session=%s  size=%.1f KB  scale=%.2f",
        req.session_id, stl_path.stat().st_size / 1024, req.scale_factor,
    )

    return ReportResult(
        pdf_url      = None,
        dicom_sr_url = None,
        stl_url      = stl_url,
        generated_at = datetime.now(timezone.utc).isoformat(),
        page_count   = None,
    )


# ── Surgical approach trajectory ────────────────────────────────────────────── #

@router.post(
    "/trajectory/{session_id}",
    response_model=TrajectoryResult,
    summary="Save the surgical approach trajectory",
    description=(
        "Persists the entry → target approach corridor in session state so it is "
        "included in the PDF report and the DICOM SR. Returns the stored points "
        "plus the approach depth and incidence angle."
    ),
)
async def set_trajectory(session_id: str, req: TrajectoryRequest) -> TrajectoryResult:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    write_state(session_id, "trajectory.entry_x", str(req.entry.x))
    write_state(session_id, "trajectory.entry_y", str(req.entry.y))
    write_state(session_id, "trajectory.entry_z", str(req.entry.z))
    write_state(session_id, "trajectory.target_x", str(req.target.x))
    write_state(session_id, "trajectory.target_y", str(req.target.y))
    write_state(session_id, "trajectory.target_z", str(req.target.z))
    tr = read_trajectory_state(session_id)
    return TrajectoryResult(
        entry=tr["entry"], target=tr["target"],
        depth_mm=tr["depth_mm"], angle_deg=tr["angle_deg"],
    )


@router.delete(
    "/trajectory/{session_id}",
    status_code=204,
    summary="Clear the surgical approach trajectory",
)
async def clear_trajectory(session_id: str) -> None:
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    for k in ("entry_x", "entry_y", "entry_z", "target_x", "target_y", "target_z"):
        write_state(session_id, f"trajectory.{k}", "")
