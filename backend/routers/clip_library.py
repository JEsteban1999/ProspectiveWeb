"""Global clip library — the institution's clips and manufacturing templates.

Separate from `clips.py` on purpose: that router plans clips inside one session,
this one curates a store shared by every session and every user. Writes are
admin-only, because a clip added here changes what the selector recommends for
every future case.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services import clip_library
from services.auth_service import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["clip-library"])


class LibraryClipOut(BaseModel):
    """One clip in the institutional library, as the UI lists it."""

    id: str
    name: str
    kind: str = Field(..., description="'stock' = held in inventory · 'template' = manufacturing design")
    manufacturer: str = ""
    shape: str = Field(..., description="STRAIGHT | CURVED | ANGLED | ANGLED_45 | BAYONET | FENESTRATED")
    closing_force_g: float = Field(0.0, description="Declared — no geometry carries this")
    fenestration_mm: float = Field(0.0, description="Declared inner window diameter (mm)")
    notes: str = ""
    blade_length_mm: float = Field(0.0, description="Longest oriented-bounding-box axis, measured")
    envelope_width_mm: float = Field(
        0.0, description="Envelope across the jaw: two blades plus the gap, NOT one blade"
    )
    envelope_height_mm: float = 0.0
    volume_mm3: float = 0.0
    source_filename: str = ""
    created_at: float = 0.0
    mesh_url: str = ""


class ShapeSuggestion(BaseModel):
    """Geometry's opinion on the shape — a form pre-fill, never a fact."""

    shape: str
    why: str
    blade_length_mm: float
    envelope_width_mm: float
    envelope_height_mm: float
    volume_mm3: float


def _out(c: clip_library.LibraryClip) -> LibraryClipOut:
    return LibraryClipOut(
        id=c.id, name=c.name, kind=c.kind, manufacturer=c.manufacturer, shape=c.shape,
        closing_force_g=c.closing_force_g, fenestration_mm=c.fenestration_mm,
        notes=c.notes, blade_length_mm=c.blade_length_mm,
        envelope_width_mm=c.envelope_width_mm, envelope_height_mm=c.envelope_height_mm,
        volume_mm3=c.volume_mm3, source_filename=c.source_filename,
        created_at=c.created_at, mesh_url=f"/api/clip-library/{c.id}/mesh",
    )


@router.get(
    "/clip-library",
    response_model=list[LibraryClipOut],
    summary="Every clip and template the institution holds",
    description=(
        "`kind=stock` are clips actually in inventory — these join the built-in "
        "catalogue when a case is scored. `kind=template` are parametric "
        "manufacturing designs and never compete as stock: a design that has not "
        "been made is not something anyone can pick up in theatre."
    ),
)
async def list_library(kind: str | None = None) -> list[LibraryClipOut]:
    if kind and kind not in clip_library.VALID_KINDS:
        raise HTTPException(status_code=422, detail=f"Tipo no válido: {kind!r}")
    return [_out(c) for c in clip_library.list_clips(kind)]


@router.post(
    "/clip-library",
    response_model=LibraryClipOut,
    status_code=201,
    dependencies=[Depends(require_admin)],
    summary="Add a clip or a manufacturing template to the library (admin)",
    description=(
        "Upload an STL, OBJ or VTP together with the specification the geometry "
        "cannot supply.\n\n"
        "**Closing force is required for `stock` clips** — it is a property of the "
        "spring and the alloy, so no mesh carries it, and without it the selector "
        "cannot judge whether the clip holds the neck. Shape and fenestration "
        "diameter are declared for the same reason: inferring them from an "
        "arbitrary CAD export fails quietly on exactly the irregular meshes where "
        "it would matter.\n\n"
        "Blade length is measured from the mesh's oriented bounding box. The width "
        "and height stored are ENVELOPE dimensions — across the jaw axis that is "
        "two blades plus the opening, not one blade."
    ),
)
async def add_library_clip(
    file: UploadFile = File(...),
    name: str = Form(""),
    kind: str = Form("stock"),
    shape: str = Form("STRAIGHT"),
    closing_force_g: float = Form(0.0),
    fenestration_mm: float = Form(0.0),
    manufacturer: str = Form(""),
    notes: str = Form(""),
) -> LibraryClipOut:
    raw = await file.read()
    try:
        clip = clip_library.add_clip(
            raw=raw,
            source_filename=file.filename or "clip.stl",
            name=name,
            kind=kind,
            closing_force_g=closing_force_g,
            shape=shape,
            manufacturer=manufacturer,
            fenestration_mm=fenestration_mm,
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Clip library import failed")
        raise HTTPException(status_code=422, detail=f"No se pudo importar el clip: {exc}")
    return _out(clip)


@router.post(
    "/clip-library/measure",
    response_model=ShapeSuggestion,
    dependencies=[Depends(require_admin)],
    summary="Measure a mesh before importing it, to pre-fill the form (admin)",
    description=(
        "Measures the oriented bounding box and volume and offers a shape guess. "
        "The guess only separates flat from bent envelopes — anything finer would "
        "be guesswork presented as measurement, so the operator still states the "
        "shape."
    ),
)
async def measure_before_import(file: UploadFile = File(...)) -> ShapeSuggestion:
    import tempfile
    from pathlib import Path as _Path

    raw = await file.read()
    if len(raw) > clip_library.MAX_CLIP_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el límite de tamaño.")
    ext = (file.filename or "clip.stl").rsplit(".", 1)[-1].lower()
    if ext not in clip_library.SUPPORTED_EXT:
        raise HTTPException(status_code=422, detail="Formato no soportado. Usa STL, OBJ o VTP.")

    tmp = _Path(tempfile.mkdtemp(prefix="clip_measure_")) / f"probe.{ext}"
    try:
        tmp.write_bytes(raw)
        long_mm, mid_mm, short_mm, volume = clip_library.measure_mesh(tmp)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"No se pudo medir la malla: {exc}")
    finally:
        tmp.unlink(missing_ok=True)

    shape, why = clip_library.suggest_shape(long_mm, mid_mm, short_mm)
    return ShapeSuggestion(
        shape=shape, why=why,
        blade_length_mm=round(long_mm, 2),
        envelope_width_mm=round(mid_mm, 2),
        envelope_height_mm=round(short_mm, 2),
        volume_mm3=round(volume, 2),
    )


@router.get(
    "/clip-library/{clip_id}/mesh",
    summary="Download one library clip's geometry",
    description="Served through the API, not the public static mount: the library is private.",
)
async def library_clip_mesh(clip_id: str):
    clip = clip_library.get_clip(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail=f"Clip '{clip_id}' no está en la biblioteca")
    path = clip_library.mesh_path(clip)
    if not path.exists():
        raise HTTPException(status_code=404, detail="La geometría de este clip ya no está en disco")
    return FileResponse(path, filename=clip.source_filename or path.name)


@router.delete(
    "/clip-library/{clip_id}",
    dependencies=[Depends(require_admin)],
    summary="Remove a clip from the library (admin)",
)
async def delete_library_clip(clip_id: str) -> dict:
    if not clip_library.delete_clip(clip_id):
        raise HTTPException(status_code=404, detail=f"Clip '{clip_id}' no está en la biblioteca")
    return {"deleted": clip_id}
