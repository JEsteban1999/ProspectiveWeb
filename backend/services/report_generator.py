"""PDF surgical plan report generator — Session E.

Adapted from prospective/io/report_generator.py — no Qt dependencies.
Added: build_report_data_from_session() to pull data from session state + DB.
"""
from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── reportlab imports ─────────────────────────────────────────────────────── #
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        HRFlowable,
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    _REPORTLAB_OK = True
except ImportError:
    _REPORTLAB_OK = False
    logger.warning("reportlab not installed — PDF reports disabled. Run: pip install reportlab")


# ──────────────────────────────────────────────────────────────────────────── #
# Data model                                                                   #
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class PatientInfo:
    name: str = "Anónimo"
    id: str = ""
    dob: str = ""
    study_date: str = ""
    study_id: str = ""
    institution: str = "SkullApp"
    surgeon: str = ""
    notes: str = ""


@dataclass
class ClipEntry:
    index: int
    name: str
    position_mm: tuple[float, float, float]
    orientation_deg: tuple[float, float, float]
    is_custom: bool = False


@dataclass
class CoilEntry:
    index: int
    name: str
    position_mm: tuple[float, float, float]
    coil_type: str = ""
    diameter_mm: float = 0.0
    length_cm: float = 0.0
    manufacturer: str = ""
    is_custom: bool = False


@dataclass
class ReportData:
    patient: PatientInfo = field(default_factory=PatientInfo)
    morphometrics: dict[str, Any] = field(default_factory=dict)
    clips: list[ClipEntry] = field(default_factory=list)
    coils: list[CoilEntry] = field(default_factory=list)
    trajectory: dict[str, Any] = field(default_factory=dict)
    screenshot_png: bytes | None = None
    risk_label: str = ""
    treatment: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────── #
# Session state → ReportData builder                                           #
# ──────────────────────────────────────────────────────────────────────────── #

def build_report_data_from_session(
    session_id: str,
    *,
    # Fields from the API request (can override / supplement DB values)
    patient_name: str = "",
    patient_dob: str = "",
    patient_sex: str = "",
    hospital_id: str = "",
    surgeon_name: str = "",
    institution: str = "",
    clinical_notes: str = "",
    screenshot_png_b64: str | None = None,
    # Optional DB session: pass a SQLAlchemy Session to enrich with patient data
    db=None,
) -> ReportData:
    """Build a ReportData from session state keys + optional DB lookup.

    Priority: request params > DB patient row > session state defaults.
    """
    from services.sessions import read_state
    from services.db_models import PlanningSession, Patient

    def _rf(key: str, default: float = 0.0) -> float:
        raw = read_state(session_id, key, "")
        try:
            return float(raw) if raw else default
        except ValueError:
            return default

    def _rs(key: str, default: str = "") -> str:
        return read_state(session_id, key, default) or default

    # ── 1. Morphometrics from session state ───────────────────────────── #
    morpho = {
        "volume_mm3":         _rf("morpho.volume_mm3"),
        "surface_area_mm2":   _rf("morpho.surface_area_mm2"),
        "max_diameter_mm":    _rf("morpho.max_diameter_mm"),
        "neck_diameter_mm":   _rf("morpho.neck_mm"),
        "dome_height_mm":     _rf("morpho.dome_height_mm"),
        "dome_to_neck_ratio": _rf("morpho.dnr"),
        "aspect_ratio":       _rf("morpho.ar"),
        "compactness":        _rf("morpho.compactness", 0.0),
        "bottleneck_factor":  _rf("morpho.bf"),
        "undulation_index":   _rf("morpho.ui"),
    }
    risk_label = _rs("morpho.rupture_risk", "")

    # ── 2. Treatment decision from session state ───────────────────────── #
    treatment: dict[str, Any] = {}
    if _rs("treatment.recommendation_key"):
        treatment = {
            "recommendation":     _rs("treatment.recommendation"),
            "recommendation_key": _rs("treatment.recommendation_key"),
            "confidence":         _rs("treatment.confidence"),
            "clip_pct":           int(_rf("treatment.clip_pct")),
            "endo_pct":           int(_rf("treatment.endo_pct")),
            "factors":            [],   # serialised separately if needed
            "notes":              [],
        }
        # Deserialise factors (stored as JSON string)
        import json
        factors_raw = _rs("treatment.factors_json", "")
        if factors_raw:
            try:
                treatment["factors"] = json.loads(factors_raw)
            except Exception:
                pass

    # ── 3. Patient info — request params > DB > defaults ─────────────── #
    db_patient_name  = ""
    db_hospital_id   = ""
    db_dob           = ""
    db_institution   = ""

    if db is not None:
        ps = db.query(PlanningSession).filter_by(session_id=session_id).first()
        if ps is not None and ps.patient_id is not None:
            pt = db.get(Patient, ps.patient_id)
            if pt is not None:
                db_patient_name = pt.full_name
                db_hospital_id  = pt.hospital_id or ""
                db_dob          = pt.dob.isoformat() if pt.dob else ""
                db_institution  = pt.institution or ""

    patient = PatientInfo(
        name        = patient_name  or db_patient_name  or "Anónimo",
        id          = hospital_id   or db_hospital_id   or "",
        dob         = patient_dob   or db_dob           or "",
        study_date  = datetime.now().strftime("%Y-%m-%d"),
        institution = institution   or db_institution   or "SkullApp",
        surgeon     = surgeon_name,
        notes       = clinical_notes,
    )

    # ── 4. Screenshot ─────────────────────────────────────────────────── #
    screenshot_bytes: bytes | None = None
    if screenshot_png_b64:
        try:
            screenshot_bytes = base64.b64decode(screenshot_png_b64)
        except Exception:
            logger.warning("Could not decode screenshot_png_b64 — skipping image")

    # ── 5. Surgical approach trajectory (persisted in session state) ──── #
    trajectory = read_trajectory_state(session_id)

    # ── 6. Placed devices (persisted by the clip/coil/stent planners) ─── #
    from services.device_state import read_clips, read_coils

    def _pos(v, n=3):
        v = list(v or [])
        return tuple((v + [0.0] * n)[:n])

    clips = [
        ClipEntry(
            index=int(c.get("index", i)),
            name=str(c.get("name", "Clip")),
            position_mm=_pos(c.get("position")),
            orientation_deg=_pos(c.get("orientation")),
            is_custom=bool(c.get("is_custom", False)),
        )
        for i, c in enumerate(read_clips(session_id))
    ]
    coils = [
        CoilEntry(
            index=int(c.get("index", i + 1)),
            name=str(c.get("name", "Coil")),
            position_mm=_pos(c.get("position")),
            coil_type=str(c.get("coil_type", "")),
            diameter_mm=float(c.get("diameter_mm", 0.0) or 0.0),
            length_cm=float(c.get("length_cm", 0.0) or 0.0),
            manufacturer=str(c.get("manufacturer", "")),
        )
        for i, c in enumerate(read_coils(session_id))
    ]

    return ReportData(
        patient      = patient,
        morphometrics= morpho,
        clips        = clips,
        coils        = coils,
        trajectory   = trajectory,
        screenshot_png = screenshot_bytes,
        risk_label   = risk_label,
        treatment    = treatment,
    )


def read_trajectory_state(session_id: str) -> dict:
    """Read the surgical approach trajectory from session state.

    Returns {} when no trajectory was defined, else a dict with entry/target
    (mm), the approach depth (distance) and the incidence angle vs the aneurysm
    principal axis (falls back to the SI/z axis when no axis is stored).
    """
    import math
    from services.sessions import read_state

    def _f(key: str) -> float | None:
        raw = read_state(session_id, key, "")
        try:
            return float(raw) if raw != "" else None
        except ValueError:
            return None

    ex, ey, ez = _f("trajectory.entry_x"), _f("trajectory.entry_y"), _f("trajectory.entry_z")
    tx, ty, tz = _f("trajectory.target_x"), _f("trajectory.target_y"), _f("trajectory.target_z")
    if None in (ex, ey, ez, tx, ty, tz):
        return {}

    entry = [ex, ey, ez]
    target = [tx, ty, tz]
    vx, vy, vz = tx - ex, ty - ey, tz - ez
    depth = math.sqrt(vx * vx + vy * vy + vz * vz)

    # Incidence angle vs the aneurysm principal axis (if stored), else z-axis.
    ax = _f("morpho.axis_x")
    ay = _f("morpho.axis_y")
    az = _f("morpho.axis_z")
    if None in (ax, ay, az) or (ax == 0 and ay == 0 and az == 0):
        ax, ay, az = 0.0, 0.0, 1.0
    an = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    if depth > 1e-6:
        dot = (vx * ax + vy * ay + vz * az) / (depth * an)
        dot = max(-1.0, min(1.0, dot))
        angle = math.degrees(math.acos(abs(dot)))  # 0..90, direction-agnostic
    else:
        angle = 0.0

    return {"entry": entry, "target": target, "depth_mm": round(depth, 1), "angle_deg": round(angle, 1)}


# ──────────────────────────────────────────────────────────────────────────── #
# Generator                                                                     #
# ──────────────────────────────────────────────────────────────────────────── #

class ReportGenerator:
    """Build a PDF surgical plan from a ReportData instance.

    Identical to the desktop version (no Qt dependencies).
    """

    _BLUE_DARK  = None   # set in __init__ after lazy check
    _BLUE_MED   = None
    _PURPLE     = None
    _RED        = None
    _YELLOW     = None
    _GREEN      = None
    _GREY_LIGHT = None
    _GREY_MED   = None
    _CLIP_HEX   = "#1e40af"
    _ENDO_HEX   = "#15803d"
    _MDT_HEX    = "#b45309"
    _SURV_HEX   = "#4b5563"

    def __init__(self, data: ReportData) -> None:
        if not _REPORTLAB_OK:
            raise RuntimeError(
                "reportlab is not installed. Run: pip install reportlab"
            )
        self._data = data
        # Colour palette
        self._BLUE_DARK  = colors.HexColor("#1f3a5f")
        self._BLUE_MED   = colors.HexColor("#388bfd")
        self._PURPLE     = colors.HexColor("#4c1d95")
        self._RED        = colors.HexColor("#dc2626")
        self._YELLOW     = colors.HexColor("#d97706")
        self._GREEN      = colors.HexColor("#15803d")
        self._GREY_LIGHT = colors.HexColor("#f3f4f6")
        self._GREY_MED   = colors.HexColor("#d1d5db")

        self._styles = getSampleStyleSheet()
        self._build_styles()

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def generate(self, output_path: str | Path) -> Path:
        """Write the PDF to *output_path* and return the resolved Path."""
        p = Path(output_path)
        if p.suffix.lower() != ".pdf":
            p = p.with_suffix(".pdf")
        p.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(p),
            pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2.5*cm, bottomMargin=2*cm,
            title="PROSPECTIVE — Plan Quirúrgico",
            author=self._data.patient.surgeon or "PROSPECTIVE",
        )

        story: list = []
        story += self._section_header()
        story += self._section_patient()
        story += self._section_screenshot()
        story += self._section_morphometrics()
        story += self._section_treatment_decision()
        story += self._section_clips()
        story += self._section_coils()
        story += self._section_trajectory()
        story += self._section_risk()
        story += self._section_notes()
        story += self._section_footer()

        doc.build(
            story,
            onFirstPage=self._page_template,
            onLaterPages=self._page_template,
        )
        logger.info("PDF report written: %s", p)
        return p

    # ------------------------------------------------------------------ #
    # Styles                                                               #
    # ------------------------------------------------------------------ #

    def _build_styles(self) -> None:
        s  = self._styles
        base = s["Normal"]

        self._style_h1 = ParagraphStyle(
            "ProspH1", parent=base,
            fontSize=18, textColor=self._BLUE_DARK,
            spaceAfter=4, spaceBefore=0,
            fontName="Helvetica-Bold",
        )
        self._style_h2 = ParagraphStyle(
            "ProspH2", parent=base,
            fontSize=12, textColor=self._BLUE_DARK,
            spaceAfter=3, spaceBefore=8,
            fontName="Helvetica-Bold",
        )
        self._style_h3 = ParagraphStyle(
            "ProspH3", parent=base,
            fontSize=10, textColor=self._BLUE_DARK,
            fontName="Helvetica-Bold",
            spaceAfter=2, spaceBefore=4,
        )
        self._style_body = ParagraphStyle(
            "ProspBody", parent=base,
            fontSize=9, leading=13, spaceAfter=2,
        )
        self._style_small = ParagraphStyle(
            "ProspSmall", parent=base,
            fontSize=7.5, textColor=colors.HexColor("#6b7280"),
            leading=11,
        )
        self._style_center = ParagraphStyle(
            "ProspCenter", parent=base,
            fontSize=9, alignment=TA_CENTER,
        )
        self._style_rec_badge = ParagraphStyle(
            "ProspRecBadge", parent=base,
            fontSize=13, fontName="Helvetica-Bold",
            alignment=TA_CENTER, spaceAfter=2,
        )
        self._style_td_bar_endo = ParagraphStyle(
            "ProspTDBarEndo", parent=base,
            fontSize=8, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_LEFT,
        )
        self._style_td_bar_clip = ParagraphStyle(
            "ProspTDBarClip", parent=base,
            fontSize=8, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_RIGHT,
        )
        self._style_td_note = ParagraphStyle(
            "ProspTDNote", parent=base,
            fontSize=8, textColor=colors.HexColor(self._MDT_HEX),
            spaceAfter=2, leading=11,
        )
        self._style_td_disclaimer = ParagraphStyle(
            "ProspTDDisclaimer", parent=base,
            fontSize=7, textColor=colors.HexColor("#9ca3af"),
            leading=10,
        )
        self._style_risk_high = ParagraphStyle(
            "ProspRiskHigh", parent=base,
            fontSize=11, textColor=self._RED,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        )
        self._style_risk_mod = ParagraphStyle(
            "ProspRiskMod", parent=base,
            fontSize=11, textColor=self._YELLOW,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        )
        self._style_risk_low = ParagraphStyle(
            "ProspRiskLow", parent=base,
            fontSize=11, textColor=self._GREEN,
            fontName="Helvetica-Bold", alignment=TA_CENTER,
        )

    # ------------------------------------------------------------------ #
    # Page template                                                        #
    # ------------------------------------------------------------------ #

    def _page_template(self, canvas, doc) -> None:
        canvas.saveState()
        w, h = A4

        canvas.setFillColor(self._BLUE_DARK)
        canvas.rect(0, h - 1.4*cm, w, 1.4*cm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(2*cm, h - 0.9*cm, "PROSPECTIVE  |  Plan Quirúrgico Preoperatorio")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(
            w - 2*cm, h - 0.9*cm,
            datetime.now().strftime("%d/%m/%Y  %H:%M"),
        )

        canvas.setFillColor(self._BLUE_DARK)
        canvas.rect(0, 0, w, 1.0*cm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(2*cm, 0.35*cm, self._data.patient.institution)
        canvas.drawCentredString(w / 2, 0.35*cm, f"Página {doc.page}")
        canvas.drawRightString(w - 2*cm, 0.35*cm, "CONFIDENCIAL — USO CLÍNICO")

        canvas.restoreState()

    # ------------------------------------------------------------------ #
    # Sections                                                             #
    # ------------------------------------------------------------------ #

    def _section_header(self) -> list:
        return [
            Spacer(1, 0.3*cm),
            Paragraph("PROSPECTIVE", self._style_h1),
            Paragraph(
                "Informe de planificación quirúrgica preoperatoria — Aneurisma Cerebral",
                self._style_body,
            ),
            HRFlowable(width="100%", thickness=1.5, color=self._BLUE_MED, spaceAfter=6),
        ]

    def _section_patient(self) -> list:
        pt = self._data.patient
        elems = [Paragraph("Datos del paciente", self._style_h2)]
        data = [
            ["Paciente",      pt.name,         "N.º historia", pt.id or "—"],
            ["F. nacimiento", pt.dob or "—",   "F. estudio",   pt.study_date or "—"],
            ["Institución",   pt.institution,  "Cirujano",     pt.surgeon or "—"],
        ]
        tbl = Table(data, colWidths=[3.2*cm, 6.5*cm, 3.2*cm, 5.0*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), self._GREY_LIGHT),
            ("BACKGROUND",    (2, 0), (2, -1), self._GREY_LIGHT),
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",      (2, 0), (2, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("GRID",          (0, 0), (-1, -1), 0.4, self._GREY_MED),
            ("ROWBACKGROUND", (0, 0), (-1, -1), [colors.white, self._GREY_LIGHT]),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elems.append(tbl)
        return elems

    def _section_screenshot(self) -> list:
        if not self._data.screenshot_png:
            return []
        elems = [
            Spacer(1, 0.2*cm),
            Paragraph("Imagen 3D del aneurisma", self._style_h2),
        ]
        img_buf = io.BytesIO(self._data.screenshot_png)
        img = Image(img_buf, width=14*cm, height=9*cm, kind="proportional")
        img.hAlign = "CENTER"
        elems.append(img)
        elems.append(Paragraph(
            "Captura de pantalla del visor 3D en el momento de la generación del informe.",
            self._style_small,
        ))
        return elems

    def _section_morphometrics(self) -> list:
        m = self._data.morphometrics
        if not any(v for v in m.values() if v):
            return []

        elems = [Paragraph("Morfometría del aneurisma", self._style_h2)]
        rows = [
            ["Parámetro", "Valor", "Referencia clínica"],
            ["Volumen",
             f"{m.get('volume_mm3', 0):.2f} mm³", "—"],
            ["Área superficial",
             f"{m.get('surface_area_mm2', 0):.2f} mm²", "—"],
            ["Diámetro máximo",
             f"{m.get('max_diameter_mm', 0):.2f} mm",
             "< 7 mm bajo riesgo"],
            ["Diámetro cuello (estimado)",
             f"{m.get('neck_diameter_mm', 0):.2f} mm",
             "Guía selección clip"],
            ["Altura del domo",
             f"{m.get('dome_height_mm', 0):.2f} mm", "—"],
            ["DNR (Dome/Neck ratio)",
             f"{m.get('dome_to_neck_ratio', 0):.2f}",
             "Riesgo ruptura si > 1.6"],
            ["Aspect Ratio (AR)",
             f"{m.get('aspect_ratio', 0):.2f}",
             "Riesgo ruptura si > 1.3"],
            ["Compacidad",
             f"{m.get('compactness', 0):.3f}",
             "1.0 = esfera perfecta"],
        ]
        col_w = [5.5*cm, 4.0*cm, 8.4*cm]
        tbl   = Table(rows, colWidths=col_w)

        ts = TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), self._BLUE_DARK),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("GRID",          (0, 0), (-1, -1), 0.4, self._GREY_MED),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
        for i in range(1, len(rows)):
            bg = colors.white if i % 2 else self._GREY_LIGHT
            ts.add("BACKGROUND", (0, i), (-1, i), bg)

        dnr    = m.get("dome_to_neck_ratio", 0)
        ar     = m.get("aspect_ratio", 0)
        dnr_row, ar_row = 6, 7
        if dnr >= 2.0:
            ts.add("TEXTCOLOR", (1, dnr_row), (1, dnr_row), self._RED)
            ts.add("FONTNAME",  (1, dnr_row), (1, dnr_row), "Helvetica-Bold")
        elif dnr >= 1.6:
            ts.add("TEXTCOLOR", (1, dnr_row), (1, dnr_row), self._YELLOW)
            ts.add("FONTNAME",  (1, dnr_row), (1, dnr_row), "Helvetica-Bold")
        if ar >= 1.6:
            ts.add("TEXTCOLOR", (1, ar_row), (1, ar_row), self._RED)
            ts.add("FONTNAME",  (1, ar_row), (1, ar_row), "Helvetica-Bold")
        elif ar >= 1.3:
            ts.add("TEXTCOLOR", (1, ar_row), (1, ar_row), self._YELLOW)
            ts.add("FONTNAME",  (1, ar_row), (1, ar_row), "Helvetica-Bold")

        tbl.setStyle(ts)
        elems.append(tbl)
        return elems

    def _section_treatment_decision(self) -> list:
        t = self._data.treatment
        if not t:
            return []

        elems = [Paragraph("Recomendación Terapéutica", self._style_h2)]

        rec_key  = t.get("recommendation_key", "mdt")
        rec_text = t.get("recommendation", "—")
        conf     = t.get("confidence", "—")
        clip_pct = t.get("clip_pct", 50)
        endo_pct = t.get("endo_pct", 50)

        rec_color_hex = {
            "clip":        self._CLIP_HEX,
            "endo":        self._ENDO_HEX,
            "mdt":         self._MDT_HEX,
            "surveillance": self._SURV_HEX,
        }.get(rec_key, self._SURV_HEX)

        elems.append(Paragraph(
            f'<font color="{rec_color_hex}"><b>{rec_text}</b></font>',
            self._style_rec_badge,
        ))
        elems.append(Paragraph(f'Confianza: <b>{conf}</b>', self._style_center))
        elems.append(Spacer(1, 0.25*cm))

        # Balance bar
        total_w = 17.0 * cm
        min_w   = 0.8  * cm
        if clip_pct == 0:
            clip_w = min_w; endo_w = total_w - min_w
        elif endo_pct == 0:
            endo_w = min_w; clip_w = total_w - min_w
        else:
            endo_w = max(min_w, total_w * endo_pct / 100)
            clip_w = total_w - endo_w

        bar_data = [[
            Paragraph(f"ENDO  {endo_pct}%", self._style_td_bar_endo),
            Paragraph(f"{clip_pct}%  CLIP", self._style_td_bar_clip),
        ]]
        bar_tbl = Table(bar_data, colWidths=[endo_w, clip_w])
        bar_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0), colors.HexColor(self._ENDO_HEX)),
            ("BACKGROUND",    (1, 0), (1, 0), colors.HexColor(self._CLIP_HEX)),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elems.append(bar_tbl)
        elems.append(Spacer(1, 0.25*cm))

        # Factors table
        factors = t.get("factors", [])
        if factors:
            elems.append(Paragraph("Factores determinantes:", self._style_h3))
            rows = [["Factor", "Estrategia", "Pts"]]
            for f in factors:
                direction = f.get("direction", "neutral")
                pts       = f.get("points", 0)
                dir_label = {"clip": "Clipping", "endo": "Endovascular"}.get(
                    direction, "Neutro"
                )
                rows.append([
                    f.get("name", ""),
                    dir_label,
                    f"+{pts}" if pts > 0 else "—",
                ])

            col_w = [10.5*cm, 4.0*cm, 2.4*cm]
            tbl   = Table(rows, colWidths=col_w)
            ts    = TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), self._BLUE_DARK),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, -1), 8),
                ("GRID",       (0, 0), (-1, -1), 0.4, self._GREY_MED),
                ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                ("ALIGN",      (2, 0), (2, -1), "CENTER"),
            ])
            for i in range(1, len(rows)):
                bg = colors.white if i % 2 else self._GREY_LIGHT
                ts.add("BACKGROUND", (0, i), (-1, i), bg)
            for i, factor in enumerate(factors, start=1):
                direction = factor.get("direction", "neutral")
                if direction == "clip":
                    ts.add("TEXTCOLOR", (1, i), (2, i), colors.HexColor(self._CLIP_HEX))
                    ts.add("FONTNAME",  (1, i), (2, i), "Helvetica-Bold")
                elif direction == "endo":
                    ts.add("TEXTCOLOR", (1, i), (2, i), colors.HexColor(self._ENDO_HEX))
                    ts.add("FONTNAME",  (1, i), (2, i), "Helvetica-Bold")
            tbl.setStyle(ts)
            elems.append(tbl)

        for note in t.get("notes", []):
            elems.append(Spacer(1, 0.1*cm))
            elems.append(Paragraph(f"<i>Nota:</i> {note}", self._style_td_note))

        elems.append(Spacer(1, 0.15*cm))
        elems.append(Paragraph(
            "(*) Recomendación generada por algoritmo de soporte de decisión basado en "
            "criterios morfométricos (ISAT 2002, Spetzler-BRAT 2013, AHA/ASA 2015). "
            "No sustituye el juicio clínico del equipo neurovascular tratante.",
            self._style_td_disclaimer,
        ))
        return elems

    def _section_clips(self) -> list:
        clips = self._data.clips
        if not clips:
            return [
                Paragraph("Clips quirúrgicos", self._style_h2),
                Paragraph(
                    "No se han colocado clips en esta sesión.", self._style_body
                ),
            ]

        elems = [Paragraph("Clips quirúrgicos planificados", self._style_h2)]
        rows  = [["#", "Nombre / Modelo", "Posición (mm)", "Orientación (°)", "Tipo"]]
        for c in clips:
            pos = f"({c.position_mm[0]:.1f}, {c.position_mm[1]:.1f}, {c.position_mm[2]:.1f})"
            ori = f"({c.orientation_deg[0]:.1f}, {c.orientation_deg[1]:.1f}, {c.orientation_deg[2]:.1f})"
            rows.append([
                str(c.index + 1), c.name, pos, ori,
                "Personalizado" if c.is_custom else "Catálogo",
            ])

        col_w = [0.7*cm, 5.5*cm, 4.0*cm, 4.0*cm, 3.0*cm]
        tbl   = Table(rows, colWidths=col_w)
        ts    = TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), self._BLUE_DARK),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("GRID",          (0, 0), (-1, -1), 0.4, self._GREY_MED),
            ("ALIGN",         (0, 0), (0, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
        for i in range(1, len(rows)):
            ts.add("BACKGROUND", (0, i), (-1, i),
                   colors.white if i % 2 else self._GREY_LIGHT)
        tbl.setStyle(ts)
        elems.append(tbl)
        return elems

    def _section_coils(self) -> list:
        coils = self._data.coils
        if not coils:
            return []

        elems = [Paragraph("Coils de embolización planificados", self._style_h2)]
        rows  = [["#", "Nombre / Modelo", "Tipo", "Ø (mm)", "Long. (cm)", "Fabricante", "Posición (mm)"]]
        for c in coils:
            pos = f"({c.position_mm[0]:.1f}, {c.position_mm[1]:.1f}, {c.position_mm[2]:.1f})"
            rows.append([
                str(c.index), c.name,
                c.coil_type if c.coil_type else ("Custom" if c.is_custom else "—"),
                f"{c.diameter_mm:.0f}" if c.diameter_mm else "—",
                f"{c.length_cm:.0f}"   if c.length_cm   else "—",
                c.manufacturer if c.manufacturer else "—",
                pos,
            ])

        col_w = [0.6*cm, 4.2*cm, 2.4*cm, 1.4*cm, 1.6*cm, 2.8*cm, 4.7*cm]
        tbl   = Table(rows, colWidths=col_w)
        ts    = TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), self._BLUE_DARK),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
            ("GRID",          (0, 0), (-1, -1), 0.4, self._GREY_MED),
            ("ALIGN",         (0, 0), (0, -1), "CENTER"),
            ("ALIGN",         (3, 1), (4, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
        for i in range(1, len(rows)):
            ts.add("BACKGROUND", (0, i), (-1, i),
                   colors.white if i % 2 else self._GREY_LIGHT)
        tbl.setStyle(ts)
        elems.append(tbl)
        return elems

    def _section_trajectory(self) -> list:
        tr = self._data.trajectory
        if not tr:
            return []

        elems = [Paragraph("Trayectoria de abordaje", self._style_h2)]
        entry  = tr.get("entry",  [0, 0, 0])
        target = tr.get("target", [0, 0, 0])
        rows   = [
            ["Punto de entrada (mm)",
             f"({entry[0]:.1f}, {entry[1]:.1f}, {entry[2]:.1f})"],
            ["Punto diana / aneurisma (mm)",
             f"({target[0]:.1f}, {target[1]:.1f}, {target[2]:.1f})"],
            ["Profundidad de abordaje", f"{tr.get('depth_mm', 0):.1f} mm"],
            ["Ángulo de incidencia",    f"{tr.get('angle_deg', 0):.1f} °"],
        ]
        tbl = Table(rows, colWidths=[7*cm, 10.9*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), self._GREY_LIGHT),
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("GRID",          (0, 0), (-1, -1), 0.4, self._GREY_MED),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elems.append(tbl)
        return elems

    def _section_risk(self) -> list:
        risk = self._data.risk_label
        if not risk:
            return []

        elems = [Paragraph("Evaluación de riesgo de ruptura", self._style_h2)]

        if "Alto" in risk:
            style  = self._style_risk_high
            detail = ("DNR ≥ 2.0 o AR ≥ 1.6 — Riesgo ALTO de ruptura espontánea. "
                      "Se recomienda tratamiento urgente.")
        elif "Moderado" in risk:
            style  = self._style_risk_mod
            detail = ("DNR ≥ 1.6 o AR ≥ 1.3 — Riesgo MODERADO. "
                      "Valorar tratamiento en función de clínica y preferencias del paciente.")
        else:
            style  = self._style_risk_low
            detail = ("Índices morfométricos dentro de rangos de bajo riesgo. "
                      "Seguimiento radiológico según protocolo.")

        elems.append(Paragraph(f"RIESGO: {risk.upper()}", style))
        elems.append(Spacer(1, 0.1*cm))
        elems.append(Paragraph(detail, self._style_body))
        return elems

    def _section_notes(self) -> list:
        notes = self._data.patient.notes.strip()
        if not notes:
            return []
        return [
            Paragraph("Notas / observaciones", self._style_h2),
            Paragraph(notes, self._style_body),
        ]

    def _section_footer(self) -> list:
        return [
            Spacer(1, 0.5*cm),
            HRFlowable(width="100%", thickness=0.5, color=self._GREY_MED),
            Spacer(1, 0.1*cm),
            Paragraph(
                "Este documento ha sido generado automáticamente por PROSPECTIVE y es de uso "
                "exclusivo para planificación quirúrgica preoperatoria. No sustituye al juicio "
                "clínico del especialista. Generado el "
                + datetime.now().strftime("%d de %B de %Y a las %H:%M") + ".",
                self._style_small,
            ),
        ]
