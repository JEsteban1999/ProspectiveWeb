"""The two PDFs that accompany a clip order.

Both are built from the same dimensioned specification, and they differ in
exactly one respect that matters: the external copy carries no patient data.

A third-party workshop needs dimensions, tolerances, material and the checks it
must perform on the finished part. It does not need a name, a hospital number or
a diagnosis, and sending those would place identifiable clinical data outside
anything the institution audits. The part number is the only thread between the
two documents, and it means nothing to anyone who does not hold the internal
copy.

The internal copy is the opposite: it exists to make the order re-derivable a
year later. It records which case it came from, which measurements produced
these dimensions, how the neck was measured, and every assumption still standing
when the order went out.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_INK = "#1f3a5f"
_ACCENT = "#388bfd"
_WARN = "#d97706"
_MUTED = "#6b7280"
_RULE = "#d1d5db"
_BAND = "#f3f4f6"


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=15, leading=19,
                                textColor=colors.HexColor(_INK), spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=8.5, leading=12,
                              textColor=colors.HexColor(_MUTED), spaceAfter=10),
        "h": ParagraphStyle("h", parent=base["Heading2"], fontSize=10.5, leading=13,
                            textColor=colors.HexColor(_INK), spaceBefore=12, spaceAfter=5),
        "p": ParagraphStyle("p", parent=base["Normal"], fontSize=8.5, leading=12.5),
        "warn": ParagraphStyle("w", parent=base["Normal"], fontSize=8.5, leading=12.5,
                               textColor=colors.HexColor(_WARN)),
        "foot": ParagraphStyle("f", parent=base["Normal"], fontSize=7, leading=9,
                               textColor=colors.HexColor(_MUTED)),
    }


def _table(rows, widths, head=True):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    t = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor(_RULE)),
    ]
    if head:
        style += [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(_INK)),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_BAND)),
        ]
    t.setStyle(TableStyle(style))
    return t


def _bullets(items, style):
    from reportlab.platypus import ListFlowable, ListItem, Paragraph

    return ListFlowable(
        [ListItem(Paragraph(x, style), leftIndent=10) for x in items],
        bulletType="bullet", start="•", leftIndent=12, bulletFontSize=7,
    )


def render_dossier(dossier: dict, output_path: str | Path) -> Path:
    """Write one dossier to PDF. The dict decides which of the two this is."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    st = _styles()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=dossier.get("title", "Clip"), author="PROSPECTIVE · SkullApp",
    )

    is_external = dossier.get("kind") == "external"
    story: list = [
        Paragraph(dossier["title"], st["title"]),
        Paragraph(f"Pieza <b>{dossier['part_no']}</b> · {dossier['label']}", st["sub"]),
    ]

    if not is_external:
        ident = [["Campo", "Valor"]]
        for k, v in (("Paciente", dossier.get("patient") or "—"),
                     ("Caso", dossier.get("case_label") or "—"),
                     ("Sesión", dossier.get("session_id") or "—")):
            ident.append([k, v])
        story += [Paragraph("Identificación del caso", st["h"]),
                  _table(ident, [45 * mm, 115 * mm])]

    story += [Paragraph("Especificación dimensional", st["h"]),
              _table([["Dimensión", "Valor", "Tolerancia"]] + [list(r) for r in dossier["dimensions"]],
                     [70 * mm, 45 * mm, 45 * mm])]

    if not is_external and dossier.get("derived_from"):
        story += [Paragraph("Medidas de las que se deriva", st["h"]),
                  _table([["Medida", "Valor"]] + [list(r) for r in dossier["derived_from"]],
                         [70 * mm, 90 * mm])]

    if not is_external and dossier.get("why_not_stock"):
        story += [Paragraph("Por qué no sirve el inventario", st["h"]),
                  _bullets(dossier["why_not_stock"], st["p"])]

    # The verification block is the point of the external copy: what has to be
    # measured on the finished part before anyone calls it done.
    story += [Paragraph("Verificación obligatoria sobre la pieza terminada", st["h"]),
              _bullets(dossier["verification"], st["warn"])]

    extra = dossier.get("assumptions") if not is_external else dossier.get("notes")
    if extra:
        story += [Paragraph("Supuestos y notas", st["h"]), _bullets(extra, st["p"])]

    if dossier.get("fallback_reason") and not is_external:
        story += [Paragraph("Origen de la pieza", st["h"]),
                  Paragraph(dossier["fallback_reason"], st["p"])]

    if is_external:
        story += [Spacer(1, 8 * mm),
                  Paragraph(dossier.get("confidentiality", ""), st["foot"])]
    else:
        story += [Spacer(1, 8 * mm),
                  Paragraph(
                      "Documento generado por PROSPECTIVE a partir de las medidas del "
                      "estudio. La fuerza de cierre es un objetivo, no una propiedad "
                      "del modelo: se confirma midiendo la pieza fabricada.", st["foot"])]

    doc.build(story)
    logger.info("Clip dossier written — %s (%s)", out.name, dossier.get("kind"))
    return out
