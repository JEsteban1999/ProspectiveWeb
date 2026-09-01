"""The clip to have made for this case, and the paperwork that goes with it.

`clip_selection.derive_manufacture_spec` says what the case needs. This module
answers the next question — can we actually build it, and out of what — and then
produces the two documents a real order needs.

Why the family cannot always serve
----------------------------------
The specification is free to ask for any shape the anatomy argues for. The
NAVARRO™ library holds what has actually been drawn: straight and angled today,
curved and fenestrated in design. Asking `build_jaw` for a fenestrated clip used
to return the nearest ANGLE — a straight clip — while the spec still said
"Fenestrado, ventana 3.7 mm". A silently wrong part is worse than no part, so
when the family cannot build the shape this module says so and falls back to a
commercial clip that can.

Why the STL comes from the family and not from a builder
--------------------------------------------------------
`devices.make_clip_shaped` assembles boxes: for a 10 mm clip that is 348
triangles with 696 boundary edges and a third of the real volume. It is a fine
stand-in for a viewer and useless as a manufacturing master — an open surface is
not a solid, and no workshop or printer can take it. The real designs are
watertight (22 958 triangles, 0 boundary edges), so anything meant to be MADE is
built from those.

Two dossiers, and why they differ
---------------------------------
The internal one is the institution's record: which patient, which case, which
measurements produced these dimensions, and every caveat attached to them.

The external one goes to a third-party workshop and carries NO patient data —
not a name, not an ID, not a diagnosis. A workshop needs dimensions, tolerances,
material and the verification it must perform; it has no need to know whose
aneurysm this is, and sending it would put identifiable clinical data in a place
nobody is auditing. They share a part number so the two can be reconciled.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from services.clip_selection import ClipCase, ManufactureSpec
from services.clips import ClipShape

logger = logging.getLogger(__name__)

#: Material of the drawn designs, from the exports' own .mtl files.
MATERIAL = "Titanio grado 5 (Ti-6Al-4V), pulido"

#: What a workshop may not be left to guess. Machining tolerance on the jaw is
#: the tight one: it is the dimension measured against the neck.
TOL_JAW_MM = 0.10
TOL_OTHER_MM = 0.20
#: The force is a target, and the only honest way to know it is to measure the
#: finished part. The band is what the designer stated for the family.
FORCE_TOLERANCE_G = 15.0


def family_shapes() -> set[ClipShape]:
    """Shapes the NAVARRO™ library can actually build, read off the disk.

    Derived rather than listed so the curved and fenestrated series become
    available by dropping their files into the folder, with no code change.
    """
    from services.navarro import list_variants

    out: set[ClipShape] = set()
    for v in list_variants():
        name = v.name.lower()
        if "fenestr" in name:
            out.add(ClipShape.FENESTRATED)
        elif "curv" in name:
            out.add(ClipShape.CURVED)
        elif v.angle_deg == 0:
            out.add(ClipShape.STRAIGHT)
        elif v.angle_deg >= 67.5:
            out.add(ClipShape.ANGLED)
        else:
            out.add(ClipShape.ANGLED_45)
    return out


@dataclass
class PerfectClip:
    """What to have made for this case, and where the geometry comes from."""

    #: "navarro"    — the family builds it, there is an STL to send out
    #: "commercial"  — the family cannot, but a catalogue clip fits
    #: "unavailable" — neither: nothing on offer would close this neck
    source: str
    spec: ManufactureSpec
    label: str
    #: Set when the family builds it: the design and jaw to machine.
    navarro_series: str = ""
    navarro_angle_deg: float = 0.0
    navarro_jaw_mm: float = 0.0
    navarro_is_drawn_size: bool = False
    #: Set when it does not: the catalogue clip to reach for instead.
    commercial_name: str = ""
    commercial_blade_mm: float = 0.0
    #: Why the family could not serve, in the user's words.
    fallback_reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def can_manufacture(self) -> bool:
        """True when this ends in an STL the workshop can be given."""
        return self.source == "navarro"


def _commercial_alternative(spec: ManufactureSpec, case: ClipCase):
    """The best stock clip of this shape that would actually WORK, or None.

    Only a viable one is returned. Handing back the closest near-miss looked
    helpful and was the opposite: for a 12 mm neck none of the six fenestrated
    clips in the catalogue reaches 13 mm of blade, and the answer offered was a
    7 mm one — a clip that cannot close the neck, presented as the alternative.
    """
    from services.clip_selection import evaluate_clip
    from services.clips import CLIP_CATALOGUE

    same_shape = [c for c in CLIP_CATALOGUE if c.shape == spec.shape]
    if not same_shape:
        return None
    scored = sorted((evaluate_clip(c, case) for c in same_shape), key=lambda c: -c.score)
    return next((c for c in scored if c.viable), None)


def resolve_perfect_clip(case: ClipCase, spec: ManufactureSpec) -> PerfectClip:
    """Turn a specification into something that can actually be obtained."""
    from services.navarro import STOCK_JAW_MM, nearest_variant

    shapes = family_shapes()
    notes: list[str] = []

    if spec.shape in shapes:
        src = nearest_variant(spec.angle_deg, spec.blade_length_mm)
        if src is not None:
            drawn = abs(src.jaw_mm - spec.blade_length_mm) < 1e-6
            if not drawn:
                notes.append(
                    f"La mordaza de {spec.blade_length_mm:.1f} mm no es una talla dibujada "
                    f"({min(STOCK_JAW_MM)}–{max(STOCK_JAW_MM)} mm en pasos de 3): se mecaniza "
                    f"a partir del diseño de {src.jaw_mm} mm, estirando SOLO la mordaza."
                )
            shape_txt = "Recto" if src.angle_deg == 0 else f"Angulado {src.angle_deg:.0f}°"
            return PerfectClip(
                source="navarro", spec=spec,
                label=f"NAVARRO™ {src.series} {shape_txt}, mordaza {spec.blade_length_mm:.1f} mm",
                navarro_series=src.series, navarro_angle_deg=float(src.angle_deg),
                navarro_jaw_mm=float(spec.blade_length_mm), navarro_is_drawn_size=drawn,
                notes=notes,
            )

    # The family cannot build this shape. Say which, and offer what can.
    alt = _commercial_alternative(spec, case)
    have = ", ".join(sorted(s.value for s in shapes)) or "ninguna"
    missing = (
        f"La familia NAVARRO™ no tiene todavía un diseño {spec.shape.value.lower()}; "
        f"las series disponibles son: {have}."
    )

    if alt is None:
        # Neither route serves. Saying so is the answer — the alternative would
        # be to name a clip that cannot close this neck.
        return PerfectClip(
            source="unavailable", spec=spec,
            label=f"{spec.shape.value} de {spec.blade_length_mm:.1f} mm — sin proveedor",
            fallback_reason=(
                f"{missing} Y ningún clip {spec.shape.value.lower()} del catálogo cubre "
                f"un cuello de {spec.neck_mm:.1f} mm: el mayor se queda corto. No hay "
                f"nada que ofrecer para este caso hasta que exista la serie."
            ),
            notes=notes + [
                "Sin pieza ni sustituto: replantear el abordaje, o esperar a la serie "
                f"{spec.shape.value.lower()} de NAVARRO™.",
            ],
        )

    notes.append(
        "Esta pieza NO se fabrica: es un clip de catálogo. Cuando la serie "
        f"{spec.shape.value.lower()} esté en la biblioteca, el sistema la ofrecerá sola."
    )
    return PerfectClip(
        source="commercial", spec=spec, label=alt.clip.name,
        commercial_name=alt.clip.name, commercial_blade_mm=alt.clip.blade_length_mm,
        fallback_reason=f"{missing} Mientras llega, este clip comercial sí cubre el caso.",
        notes=notes,
    )


def build_manufacture_mesh(perfect: PerfectClip):
    """The watertight solid to send out, built from the drawn design.

    Only for `source == "navarro"`: a commercial clip is bought, not made.
    """
    from services.navarro import build_jaw

    if not perfect.can_manufacture:
        raise ValueError(
            "Este caso se resuelve con un clip de catálogo; no hay pieza que fabricar."
        )
    mesh, src, exact = build_jaw(perfect.navarro_angle_deg, perfect.navarro_jaw_mm)
    return mesh, src, exact


# ── Dossiers ──────────────────────────────────────────────────────────────── #

def _dimension_rows(spec: ManufactureSpec, perfect: PerfectClip) -> list[tuple[str, str, str]]:
    """(dimension, value, tolerance) — the table both dossiers share."""
    rows = [
        ("Forma", spec.shape.value + (f" · {spec.angle_deg:.0f}°" if spec.angle_deg else ""), "—"),
        ("Longitud de mordaza (agarre útil)", f"{spec.blade_length_mm:.1f} mm", f"± {TOL_JAW_MM:.2f} mm"),
        ("Anchura de hoja", f"{spec.blade_width_mm:.2f} mm", f"± {TOL_OTHER_MM:.2f} mm"),
        ("Altura de hoja", f"{spec.blade_height_mm:.2f} mm", f"± {TOL_OTHER_MM:.2f} mm"),
        ("Longitud de cuerpo/muelle", f"{spec.spring_length_mm:.1f} mm", f"± {TOL_OTHER_MM:.2f} mm"),
    ]
    if spec.fenestration_mm > 0:
        rows.append(("Ventana (diámetro interior)", f"{spec.fenestration_mm:.1f} mm",
                     f"+{TOL_OTHER_MM:.2f} / −0.00 mm"))
    rows.append(("Apertura máxima de puntas", "10.0 mm", "máximo del mecanismo"))
    rows.append(("Fuerza de cierre (objetivo)", f"{spec.closing_force_g:.0f} g",
                 f"± {FORCE_TOLERANCE_G:.0f} g · VERIFICAR EN LA PIEZA"))
    rows.append(("Material", MATERIAL, "—"))
    return rows


def _verification_notes() -> list[str]:
    """What must be checked on the finished part before it goes anywhere."""
    return [
        "La fuerza de cierre NO puede darse por buena a partir del modelo: sale del "
        "muelle, la aleación y el tratamiento térmico. Medir la pieza terminada y "
        "registrar el valor obtenido.",
        "Comprobar la longitud de mordaza con la pieza cerrada: es la cota que se "
        "compara con el cuello del aneurisma.",
        "Verificar que las puntas abren hasta 10 mm sin deformación permanente.",
        "El STL adjunto es la geometría de partida derivada del diseño paramétrico; "
        "los radios de acuerdo y el acabado los fija el fabricante.",
    ]


def internal_dossier(perfect: PerfectClip, case: ClipCase, *, part_no: str,
                     patient: str = "", case_label: str = "",
                     session_id: str = "") -> dict:
    """The institution's own record: what was ordered and what it came from."""
    spec = perfect.spec
    return {
        "kind": "internal",
        "part_no": part_no,
        "title": "Solicitud de fabricación de clip — copia interna",
        "patient": patient,
        "case_label": case_label,
        "session_id": session_id,
        "source": perfect.source,
        "label": perfect.label,
        "dimensions": _dimension_rows(spec, perfect),
        # The measurements the dimensions were derived FROM: without these the
        # order cannot be re-derived or audited later.
        "derived_from": [
            ("Cuello medido", f"{case.neck_mm:.2f} mm"),
            ("Procedencia del cuello", {"rim": "borde marcado", "manual": "punto marcado",
                                        "auto": "detección automática"}.get(case.neck_source, case.neck_source)),
            ("Altura de domo", f"{case.dome_height_mm:.2f} mm"),
            ("Ø máximo del saco", f"{case.max_diameter_mm:.2f} mm"),
            ("Vaso padre", f"{case.parent_artery_mm:.2f} mm" if case.parent_artery_mm > 0 else "sin medir"),
            ("Región anatómica", case.region or "no registrada"),
        ],
        "why_not_stock": spec.reasons,
        "assumptions": spec.confidence_notes + perfect.notes,
        "verification": _verification_notes(),
        "fallback_reason": perfect.fallback_reason,
    }


def external_dossier(perfect: PerfectClip, *, part_no: str) -> dict:
    """The workshop's copy. No patient data, by construction.

    A third-party workshop needs dimensions, tolerances, material and the
    verification it must perform. It has no need to know whose aneurysm this is,
    and sending that would put identifiable clinical data somewhere nobody is
    auditing. The part number is the only link back, and it is meaningless
    outside the institution.
    """
    spec = perfect.spec
    return {
        "kind": "external",
        "part_no": part_no,
        "title": "Especificación de fabricación — clip de aneurisma",
        "label": perfect.label,
        "dimensions": _dimension_rows(spec, perfect),
        "verification": _verification_notes(),
        "notes": [n for n in perfect.notes if "paciente" not in n.lower()],
        "confidentiality": (
            "Este documento no contiene datos de paciente. Cualquier consulta se "
            "canaliza por el número de pieza."
        ),
    }
