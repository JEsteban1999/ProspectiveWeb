"""Global, persistent clip library — the institution's own clips and templates.

The clips imported from `POST /api/clips/custom/{session}` live inside one
session and carry no dimensions: they are geometry the viewer can draw and
nothing the selector can reason about. A hospital's clip inventory is not a
property of one planning session, so this store is global and outside `data/`,
alongside `study_files/` and `user_files/`.

Three kinds of entry
--------------------
- `stock`         — a clip the institution actually holds. It joins the built-in
                    catalogue when the selector scores a case, so «what fits this
                    aneurysm» is answered against what is really on the shelf.
- `made_to_order` — a real design manufactured for the case (the NAVARRO™ family).
                    It competes exactly like stock, because it is going to be
                    made; it is labelled so nobody expects it on a shelf today.
- `template`      — a design not yet manufacturable. Never competes; it is the
                    starting geometry for the "have one made" path.

What is derived and what must be declared
-----------------------------------------
An STL is a triangle soup. From it this module measures the **oriented bounding
box** and the volume — real, reproducible numbers. Everything else is declared
by the person importing the clip, and the reason is worth stating because it
looks like it should be automatic:

- **Closing force** is a property of the spring and the alloy. No geometry
  carries it.
- **Shape class and fenestration** could in principle be inferred (blade axis
  curvature, surface genus), but a CAD export is rarely a clean closed manifold
  and the inference fails quietly on exactly the irregular meshes where it
  matters. `suggest_shape` below offers a hint to pre-fill the form; it is
  labelled a suggestion and never overrides what the operator states.
- **Blade width and height** cannot be separated from the jaw opening by a
  bounding box: the envelope across the jaw axis is two blades plus the gap.
  The stored figures are envelope dimensions and are named as such.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Private store: clip geometry is institutional property, not public static.
LIBRARY_ROOT = Path(
    os.environ.get("CLIP_LIBRARY_ROOT", "")
    or (Path(__file__).resolve().parents[1] / "clip_library")
)
_MANIFEST = "manifest.json"
MAX_CLIP_BYTES = 16 * 1024 * 1024
SUPPORTED_EXT = ("stl", "obj", "vtp")

#: "made_to_order" is a real design manufactured per case — it competes in the
#: recommendation like stock does, but is labelled so nobody reaches for a
#: part that is not on a shelf yet.
VALID_KINDS = ("stock", "made_to_order", "template")
VALID_SHAPES = ("STRAIGHT", "CURVED", "ANGLED", "ANGLED_45", "BAYONET", "FENESTRATED")


@dataclass
class LibraryClip:
    """One clip in the institutional library."""
    id: str
    name: str
    kind: str                      # stock | made_to_order | template
    manufacturer: str = ""
    shape: str = "STRAIGHT"        # declared, one of VALID_SHAPES
    closing_force_g: float = 0.0   # declared — geometry cannot carry it
    fenestration_mm: float = 0.0   # declared inner window diameter
    notes: str = ""
    # ── Derived from the mesh ──
    blade_length_mm: float = 0.0   # longest oriented-bounding-box axis
    envelope_width_mm: float = 0.0  # blades + jaw gap, NOT one blade's width
    envelope_height_mm: float = 0.0
    volume_mm3: float = 0.0
    mesh_file: str = ""
    source_filename: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def is_stock(self) -> bool:
        return self.kind == "stock"


# ── Store ──────────────────────────────────────────────────────────────────── #

def _manifest_path() -> Path:
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    return LIBRARY_ROOT / _MANIFEST


def _read_manifest() -> list[dict]:
    p = _manifest_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Clip library manifest unreadable (%s); treating as empty", exc)
        return []


def _write_manifest(entries: list[dict]) -> None:
    _manifest_path().write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_clips(kind: str | None = None) -> list[LibraryClip]:
    """Every clip in the library, newest first, optionally filtered by kind."""
    out = [LibraryClip(**e) for e in _read_manifest() if isinstance(e, dict)]
    if kind:
        out = [c for c in out if c.kind == kind]
    return sorted(out, key=lambda c: -c.created_at)


def get_clip(clip_id: str) -> LibraryClip | None:
    return next((c for c in list_clips() if c.id == clip_id), None)


def mesh_path(clip: LibraryClip) -> Path:
    return LIBRARY_ROOT / clip.mesh_file


# ── Mesh measurement ───────────────────────────────────────────────────────── #

def measure_mesh(path: Path) -> tuple[float, float, float, float]:
    """Oriented-bounding-box extents (long, mid, short) in mm, plus volume mm³.

    An oriented box rather than the axis-aligned bounds: a clip exported at an
    arbitrary orientation would otherwise measure its diagonal as its length.
    """
    import vtk

    ext = path.suffix.lower().lstrip(".")
    if ext == "stl":
        reader = vtk.vtkSTLReader()
    elif ext == "obj":
        reader = vtk.vtkOBJReader()
    else:
        reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    poly = reader.GetOutput()
    if poly is None or poly.GetNumberOfPoints() == 0:
        raise ValueError("La malla del clip está vacía o no se pudo leer.")

    corner = [0.0] * 3
    max_a = [0.0] * 3
    mid_a = [0.0] * 3
    min_a = [0.0] * 3
    sizes = [0.0] * 3
    vtk.vtkOBBTree.ComputeOBB(poly.GetPoints(), corner, max_a, mid_a, min_a, sizes)

    def _norm(v: list[float]) -> float:
        return float((v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5)

    extents = sorted((_norm(max_a), _norm(mid_a), _norm(min_a)), reverse=True)

    mass = vtk.vtkMassProperties()
    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(poly)
    tri.Update()
    mass.SetInputData(tri.GetOutput())
    try:
        volume = float(mass.GetVolume())
    except Exception:  # noqa: BLE001 — an open surface has no meaningful volume
        volume = 0.0

    return extents[0], extents[1], extents[2], max(0.0, volume)


def suggest_shape(long_mm: float, mid_mm: float, short_mm: float) -> tuple[str, str]:
    """A hint for the import form — never a substitute for what the operator states.

    Returns (shape, why). Only the crudest distinction is attempted, because
    anything finer is guesswork dressed as measurement: a clip whose envelope is
    deep relative to its length has its blade bent out of line.
    """
    if long_mm <= 0:
        return "STRAIGHT", "Sin medidas utilizables; se asume recto."
    depth_ratio = short_mm / long_mm
    if depth_ratio >= 0.45:
        return "ANGLED", (
            f"El envolvente es profundo respecto a su longitud "
            f"(×{depth_ratio:.2f}), lo que sugiere una hoja acodada."
        )
    if depth_ratio >= 0.22:
        return "CURVED", (
            f"Profundidad intermedia (×{depth_ratio:.2f}): compatible con hoja "
            f"curva o bayoneta."
        )
    return "STRAIGHT", f"Envolvente plano (×{depth_ratio:.2f}): compatible con hoja recta."


# ── Import / delete ────────────────────────────────────────────────────────── #

def add_clip(
    raw: bytes,
    source_filename: str,
    name: str,
    kind: str,
    closing_force_g: float,
    shape: str = "STRAIGHT",
    manufacturer: str = "",
    fenestration_mm: float = 0.0,
    notes: str = "",
    blade_length_mm: float | None = None,
) -> LibraryClip:
    """Store one clip mesh and its declared specification.

    `blade_length_mm` overrides the measured envelope, and on many real clips it
    must: the envelope is the whole part, while the blade is only the jaw that
    has to span the neck. A NAVARRO™ clip with a 7 mm jaw measures 21.30 mm
    overall — recording that as the blade makes the selector reject, as
    "oversized ×5.3", the very clip that fits.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"Tipo de clip no válido: {kind!r}. Usa 'stock' o 'template'.")
    if shape not in VALID_SHAPES:
        raise ValueError(f"Forma no válida: {shape!r}.")
    if len(raw) > MAX_CLIP_BYTES:
        raise ValueError(f"El archivo supera el límite de {MAX_CLIP_BYTES // (1024 * 1024)} MB.")
    ext = source_filename.rsplit(".", 1)[-1].lower() if "." in source_filename else ""
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"Formato no soportado ({ext or 'sin extensión'}). Usa STL, OBJ o VTP.")
    # A stock clip that cannot state its closing force cannot be scored against a
    # neck, and a clip in the list that never gets recommended is just confusing.
    if kind in ("stock", "made_to_order") and closing_force_g <= 0:
        raise ValueError(
            "Un clip de inventario necesita su fuerza de cierre en gramos: es lo que "
            "decide si aguanta el cuello, y no se puede deducir de la geometría."
        )

    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    clip_id = uuid.uuid4().hex[:12]
    mesh_file = f"{clip_id}.{ext}"
    target = LIBRARY_ROOT / mesh_file
    target.write_bytes(raw)

    try:
        long_mm, mid_mm, short_mm, volume = measure_mesh(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    if blade_length_mm is not None and blade_length_mm > 0:
        long_mm = float(blade_length_mm)

    clip = LibraryClip(
        id=clip_id,
        name=name.strip() or Path(source_filename).stem,
        kind=kind,
        manufacturer=manufacturer.strip(),
        shape=shape,
        closing_force_g=float(closing_force_g),
        fenestration_mm=float(fenestration_mm),
        notes=notes.strip(),
        blade_length_mm=round(long_mm, 2),
        envelope_width_mm=round(mid_mm, 2),
        envelope_height_mm=round(short_mm, 2),
        volume_mm3=round(volume, 2),
        mesh_file=mesh_file,
        source_filename=source_filename,
    )
    entries = _read_manifest()
    entries.append(asdict(clip))
    _write_manifest(entries)
    logger.info("Clip library import — id=%s kind=%s name=%s", clip_id, kind, clip.name)
    return clip


def delete_clip(clip_id: str) -> bool:
    entries = _read_manifest()
    keep = [e for e in entries if e.get("id") != clip_id]
    if len(keep) == len(entries):
        return False
    gone = next(e for e in entries if e.get("id") == clip_id)
    try:
        (LIBRARY_ROOT / gone.get("mesh_file", "")).unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001 — the catalogue entry is already going
        logger.warning("Could not remove clip mesh %s: %s", clip_id, exc)
    _write_manifest(keep)
    logger.info("Clip library delete — id=%s", clip_id)
    return True


def clear_library() -> None:
    """Remove every entry. Used by tests; never wired to a route."""
    if LIBRARY_ROOT.exists():
        shutil.rmtree(LIBRARY_ROOT, ignore_errors=True)


# ── Feeding the selector ───────────────────────────────────────────────────── #

def to_spec(clip: LibraryClip):
    """Convert a library entry into a `ClipSpec` the selector can score.

    Blade width and height fall back to the catalogue's median proportions when
    the envelope cannot give them — the envelope across the jaw is two blades
    plus the gap, so using it directly would report a blade three times too wide.
    """
    from services.clips import ClipShape, ClipSpec

    length = clip.blade_length_mm or 1.0
    # Proportions observed across the real catalogue (see clip_selection).
    width = round(length * 0.13, 2)
    height = round(length * 0.11, 2)
    return ClipSpec(
        name=clip.name,
        shape=ClipShape[clip.shape],
        blade_length_mm=length,
        blade_width_mm=width,
        blade_height_mm=height,
        spring_length_mm=round(length * 0.9, 2),
        closing_force_g=clip.closing_force_g,
        manufacturer=clip.manufacturer or "Biblioteca",
        fenestration_mm=clip.fenestration_mm,
    )


def catalogue_with_library() -> list:
    """Everything the selector may recommend, from every source.

    Three sources, in order: the built-in catalogue, the institution's own
    uploads (`stock` and `made_to_order`), and the NAVARRO™ family read straight
    off disk. NAVARRO™ needs no import step on purpose — dropping the curved and
    fenestrated series into the folder is enough to make them selectable, which
    is how the family is going to grow.

    `template` is excluded: a design that cannot yet be manufactured is not
    something to plan an operation around.
    """
    from services.clips import CLIP_CATALOGUE

    extra = [to_spec(c) for c in list_clips() if c.kind in ("stock", "made_to_order")]
    navarro: list = []
    try:
        from services.navarro import family_specs
        navarro = family_specs()
    except Exception as exc:  # noqa: BLE001 — a missing library must not break selection
        logger.warning("NAVARRO family unavailable: %s", exc)
    return list(CLIP_CATALOGUE) + extra + navarro
