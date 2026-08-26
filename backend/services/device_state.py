"""Persist placed devices (clips / coils / stent) in session state so they
appear in the PDF report, the DICOM SR and restored sessions.

Stored as compact JSON under the `devices.*` state keys. Kept dependency-free
(only touches services.sessions) so report_generator can import it safely.
"""
from __future__ import annotations

import json
import logging

from services.sessions import read_state, write_state

logger = logging.getLogger(__name__)

_CLIPS_KEY = "devices.clips"
_COILS_KEY = "devices.coils"
_STENT_KEY = "devices.stent"


def _dump(session_id: str, key: str, value) -> None:
    try:
        write_state(session_id, key, json.dumps(value))
    except Exception as exc:  # noqa: BLE001 — persistence must never break planning
        logger.warning("Could not persist %s for %s: %s", key, session_id, exc)


def _load(session_id: str, key: str, default):
    raw = read_state(session_id, key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def save_clips(session_id: str, clips: list[dict]) -> None:
    """clips: [{index, name, position:[x,y,z], orientation:[x,y,z], is_custom}]"""
    _dump(session_id, _CLIPS_KEY, clips)


def save_coils(session_id: str, coils: list[dict]) -> None:
    """coils: [{index, name, position, coil_type, diameter_mm, length_cm, manufacturer}]"""
    _dump(session_id, _COILS_KEY, coils)


def save_stent(session_id: str, stent: dict | None) -> None:
    """stent: {name, diameter_mm, length_mm, coverage_pct, kind} or None to clear."""
    _dump(session_id, _STENT_KEY, stent or {})


def read_clips(session_id: str) -> list[dict]:
    v = _load(session_id, _CLIPS_KEY, [])
    return v if isinstance(v, list) else []


def read_coils(session_id: str) -> list[dict]:
    v = _load(session_id, _COILS_KEY, [])
    return v if isinstance(v, list) else []


def read_stent(session_id: str) -> dict:
    v = _load(session_id, _STENT_KEY, {})
    return v if isinstance(v, dict) else {}


def clear_devices(session_id: str) -> None:
    for k in (_CLIPS_KEY, _COILS_KEY, _STENT_KEY):
        write_state(session_id, k, "")


#: Device kind → (state key, mesh files written by its planner). The meshes are
#: deleted alongside the state so a cleared device also leaves the 3D viewer and
#: the STL export, not just the PDF.
DEVICE_KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "clips":  (_CLIPS_KEY, ("clips_placed.vtp",)),
    "coils":  (_COILS_KEY, ("coils_placed.vtp",)),
    # Both stent planners share one state slot, so clearing either clears both
    # meshes — otherwise the report would describe a stent whose geometry is gone.
    "stent":  (_STENT_KEY, ("stent_deployed.vtp", "cl_stent.vtp")),
}


def clear_device(session_id: str, kind: str) -> None:
    """Forget one placed device kind ('clips' | 'coils' | 'stent')."""
    entry = DEVICE_KINDS.get(kind)
    if entry is None:
        raise ValueError(f"Unknown device kind: {kind!r}")
    write_state(session_id, entry[0], "")
