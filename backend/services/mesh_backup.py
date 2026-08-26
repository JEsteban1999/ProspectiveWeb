"""Edit history for the working vessel mesh (`vessel_tree.vtp`).

Segmentation, the ROI crop and grow-from-seeds all overwrite the working mesh in
place, so until this existed the only way back from a bad edit was a full
re-segmentation — minutes of compute that also threw away every earlier
refinement, and no way back at all from the re-segmentation itself.

Every operation that rewrites the mesh snapshots it first. The snapshots form an
undo stack; undoing moves the current mesh onto a redo stack, so stepping back
one step too far costs one click rather than the whole edit. A manifest next to
the files records what each step was, which is what lets the panel show a real
history («recorte», «segmentación») instead of a bare count.

History travels inside the session directory, so a saved and resumed session
keeps it.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from services.sessions import session_subdir

logger = logging.getLogger(__name__)

#: Keep the stack bounded — a vessel mesh is a few MB and an operator tuning a
#: crop can fire dozens of edits in a session.
MAX_SNAPSHOTS = 12

#: What produced each state, in the user's language.
STEP_LABELS = {
    "segment": "Segmentación",
    "crop": "Recorte de malla",
    "grow": "Crecimiento desde semillas",
    "edit": "Edición de malla",
}

_MESH_NAME = "vessel_tree.vtp"
_UNDO_DIR = "_undo"
_REDO_DIR = "_redo"
_MANIFEST = "index.json"


@dataclass(frozen=True)
class Step:
    """One recoverable mesh state."""

    label: str          # raw key ("crop", "grow", "segment")
    title: str          # human-readable, for the panel
    vertices: int
    at: float           # unix timestamp


def _meshes(session_id: str) -> Path:
    return session_subdir(session_id, "meshes")


def _dir(session_id: str, which: str) -> Path:
    d = _meshes(session_id) / which
    d.mkdir(parents=True, exist_ok=True)
    return d


def _files(session_id: str, which: str) -> list[Path]:
    """Snapshot files, oldest first (the numeric name prefix orders them)."""
    d = _meshes(session_id) / which
    if not d.is_dir():
        return []
    return sorted(d.glob("*.vtp"), key=lambda p: p.name)


def _read_manifest(session_id: str, which: str) -> list[dict]:
    path = _meshes(session_id) / which / _MANIFEST
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_manifest(session_id: str, which: str, entries: list[dict]) -> None:
    try:
        (_dir(session_id, which) / _MANIFEST).write_text(
            json.dumps(entries), encoding="utf-8"
        )
    except OSError as exc:  # noqa: BLE001 — history is a convenience, not the work
        logger.warning("Could not write %s manifest for %s: %s", which, session_id, exc)


def _push(session_id: str, which: str, label: str, vertices: int) -> bool:
    """Copy the working mesh onto one of the stacks. False when there is none."""
    src = _meshes(session_id) / _MESH_NAME
    if not src.exists():
        return False

    files = _files(session_id, which)
    entries = _read_manifest(session_id, which)
    # Past the cap, drop the oldest — but never the first entry on the undo
    # stack: that is the state «Restaurar malla original» comes back to.
    while len(files) >= MAX_SNAPSHOTS:
        victim_idx = 1 if (which == _UNDO_DIR and len(files) > 1) else 0
        files.pop(victim_idx).unlink(missing_ok=True)
        if victim_idx < len(entries):
            entries.pop(victim_idx)

    idx = 0 if not files else int(files[-1].name.split("_", 1)[0]) + 1
    safe = "".join(ch if ch.isalnum() else "_" for ch in label)[:24] or "edit"
    try:
        shutil.copy2(src, _dir(session_id, which) / f"{idx:03d}_{safe}.vtp")
    except OSError as exc:  # noqa: BLE001 — a failed backup must not block the edit
        logger.warning("Could not snapshot mesh for %s: %s", session_id, exc)
        return False

    entries.append({
        "label": label,
        "title": STEP_LABELS.get(label, STEP_LABELS["edit"]),
        "vertices": int(vertices),
        "at": time.time(),
    })
    _write_manifest(session_id, which, entries)
    return True


def _pop(session_id: str, which: str) -> bool:
    """Restore the newest snapshot from a stack over the working mesh."""
    files = _files(session_id, which)
    if not files:
        return False
    newest = files[-1]
    try:
        shutil.copy2(newest, _meshes(session_id) / _MESH_NAME)
    except OSError as exc:  # noqa: BLE001
        logger.warning("Could not restore mesh for %s: %s", session_id, exc)
        return False
    newest.unlink(missing_ok=True)
    entries = _read_manifest(session_id, which)
    if entries:
        entries.pop()
    _write_manifest(session_id, which, entries)
    return True


def _current_vertices(session_id: str) -> int:
    """Vertex count of the working mesh, for the history entry. 0 if unreadable."""
    path = _meshes(session_id) / _MESH_NAME
    if not path.exists():
        return 0
    try:
        from services.segmentation import read_vtp
        return int(read_vtp(path).GetNumberOfPoints())
    except Exception:  # noqa: BLE001 — the count is a label, never the work
        return 0


# ── Public API ─────────────────────────────────────────────────────────────── #

def snapshot(session_id: str, label: str = "edit") -> int:
    """Record the current mesh before an edit replaces it. Returns undo depth.

    A new edit invalidates the redo stack: those states belong to a branch the
    user has just left.
    """
    pushed = _push(session_id, _UNDO_DIR, label, _current_vertices(session_id))
    if pushed:
        _drop(session_id, _REDO_DIR)
    return depth(session_id)


def depth(session_id: str) -> int:
    """How many edits can be undone."""
    return len(_files(session_id, _UNDO_DIR))


def redo_depth(session_id: str) -> int:
    """How many undone edits can be replayed."""
    return len(_files(session_id, _REDO_DIR))


def undo(session_id: str) -> bool:
    """Step back one edit, keeping the state left behind on the redo stack."""
    if not _files(session_id, _UNDO_DIR):
        return False
    _push(session_id, _REDO_DIR, "edit", _current_vertices(session_id))
    return _pop(session_id, _UNDO_DIR)


def redo(session_id: str) -> bool:
    """Replay the most recently undone edit."""
    if not _files(session_id, _REDO_DIR):
        return False
    _push(session_id, _UNDO_DIR, "edit", _current_vertices(session_id))
    return _pop(session_id, _REDO_DIR)


def restore_baseline(session_id: str) -> bool:
    """Go back to the oldest state still kept — the first segmentation's output.

    Implemented as repeated undo so every intermediate state lands on the redo
    stack: restoring the original is itself reversible.
    """
    if not _files(session_id, _UNDO_DIR):
        return False
    while _files(session_id, _UNDO_DIR):
        if not undo(session_id):
            return False
    return True


def history(session_id: str) -> list[Step]:
    """The undo stack, oldest first — what the panel lists."""
    entries = _read_manifest(session_id, _UNDO_DIR)
    return [
        Step(
            label=e.get("label", "edit"),
            title=e.get("title") or STEP_LABELS["edit"],
            vertices=int(e.get("vertices", 0) or 0),
            at=float(e.get("at", 0) or 0),
        )
        for e in entries
    ]


def _drop(session_id: str, which: str) -> None:
    d = _meshes(session_id) / which
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


def clear(session_id: str) -> None:
    """Drop the whole history — used when a session's mesh lineage restarts."""
    _drop(session_id, _UNDO_DIR)
    _drop(session_id, _REDO_DIR)


def prune_for_snapshot(meshes_dir: Path, keep: int = 2) -> None:
    """Trim the history inside a DURABLE snapshot of a session.

    A saved session used to carry every undo state — up to twelve copies of the
    vessel mesh — which is a lot of disk for a project whose save path already
    had to hard-link the DICOM to stop filling the volume. Keeping the newest
    couple of steps preserves a useful «deshacer» after resuming; the redo stack
    is dropped entirely, since saving is an explicit commitment to a state.
    """
    redo = meshes_dir / _REDO_DIR
    if redo.is_dir():
        shutil.rmtree(redo, ignore_errors=True)

    undo = meshes_dir / _UNDO_DIR
    if not undo.is_dir():
        return
    files = sorted(undo.glob("*.vtp"), key=lambda p: p.name)
    excess = len(files) - max(keep, 0)
    if excess <= 0:
        return
    for f in files[:excess]:
        f.unlink(missing_ok=True)

    manifest = undo / _MANIFEST
    if manifest.is_file():
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(entries, list):
                manifest.write_text(json.dumps(entries[excess:]), encoding="utf-8")
        except (OSError, ValueError):
            manifest.unlink(missing_ok=True)
