"""Report generation models.

Matches prospective/io/report_generator.py and prospective/ui/widgets/report_panel.py.
Step 6 — Exportar › Informe PDF + Impresión 3D.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    """All data needed to generate the surgical PDF report."""

    session_id: str

    # Patient / surgeon information (filled in the report panel form)
    patient_name: str = Field("", description="Full patient name for the report header")
    patient_dob: str = Field("", description="Date of birth YYYY-MM-DD")
    patient_sex: str = Field("", description="M / F / O")
    hospital_id: str = Field("", description="Hospital / HIS identifier")
    surgeon_name: str = Field("", description="Lead surgeon name")
    institution: str = Field("", description="Hospital or institution name")
    report_date: str = Field("", description="Report date YYYY-MM-DD (defaults to today)")
    clinical_notes: str = Field("", description="Free-text clinical observations")
    include_3d_screenshot: bool = Field(
        True,
        description="Include a screenshot of the current 3D view in the report"
    )

    # Optional: 3D screenshot from the browser VTK viewer (base64-encoded PNG)
    screenshot_png_b64: str | None = Field(
        None,
        description=(
            "Base64-encoded PNG screenshot of the 3D viewer. "
            "When provided it is embedded in the report as the aneurysm image."
        ),
    )

    # Optional: override morphometry values shown in the report
    force_morphometry_note: str | None = Field(
        None,
        description="If set, shown as a red note under morphometry (e.g. 'Cuello no detectado')"
    )


class ReportResult(BaseModel):
    """URLs and metadata of the generated export files."""

    pdf_url: str | None = Field(
        None, description="Download URL of the generated PDF report"
    )
    dicom_sr_url: str | None = Field(
        None, description="Download URL of the DICOM Structured Report (.dcm)"
    )
    stl_url: str | None = Field(
        None, description="Download URL of the exported STL mesh for 3D printing"
    )
    generated_at: str = Field(..., description="ISO-8601 timestamp of generation")
    page_count: int | None = Field(
        None, description="Number of pages in the generated PDF"
    )


class ExportRequest(BaseModel):
    """Request for mesh export (STL for 3D printing)."""

    session_id: str
    include_vessel_tree: bool = Field(
        True, description="Include the full vascular tree mesh"
    )
    include_aneurysm_dome: bool = Field(
        True, description="Include the isolated aneurysm dome mesh"
    )
    include_skull: bool = Field(
        False, description="Include the skull surface mesh (adds volume)"
    )
    scale_factor: float = Field(
        1.0, gt=0.0,
        description="Uniform scale factor applied before STL export (1.0 = real size)"
    )
