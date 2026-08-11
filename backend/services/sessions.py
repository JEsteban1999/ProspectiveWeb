"""Session management — UUID-based temporary folders per processing session.

Each API session gets an isolated directory under SESSIONS_ROOT where
all intermediate files (DICOM uploads, meshes, reports) are stored.
Sessions are cleaned up automatically after SESSION_TTL_HOURS hours.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────── #

SESSIONS_ROOT = Path(__file__).resolve().parents[1] / "data" / "sessions"

# Durable store for SAVED sessions. Unlike SESSIONS_ROOT this is never purged by
# the TTL sweep, so a saved study (volume + meshes + state) survives indefinitely
# and can be rehydrated into a fresh live session on resume.
SAVES_ROOT = Path(__file__).resolve().parents[1] / "data" / "session_saves"

# Sessions older than this are purged. Configurable via SESSION_TTL_HOURS
# (defaults to 24 h, matching the documented env var in the README).
try:
    _TTL_HOURS = float(os.environ.get("SESSION_TTL_HOURS", "24"))
except ValueError:
    _TTL_HOURS = 24.0
SESSION_TTL_SEC = int(_TTL_HOURS * 3600)

# Sub-directories created inside each session folder
_SUBDIRS = ["dicom", "meshes", "reports", "exports", "screenshots"]


# ── Session lifecycle ──────────────────────────────────────────────────────── #

def create_session() -> str:
    """Create a new session directory and return its UUID."""
    session_id = str(uuid.uuid4())
    session_dir = SESSIONS_ROOT / session_id
    for sub in _SUBDIRS:
        (session_dir / sub).mkdir(parents=True, exist_ok=True)
    # Write creation timestamp for TTL tracking
    (session_dir / ".created_at").write_text(str(time.time()))
    return session_id


def session_dir(session_id: str) -> Path:
    """Return the root Path for a session. Does NOT validate existence."""
    return SESSIONS_ROOT / session_id


def session_subdir(session_id: str, sub: str) -> Path:
    """Return a specific sub-directory path, creating it if needed."""
    p = SESSIONS_ROOT / session_id / sub
    p.mkdir(parents=True, exist_ok=True)
    return p


def session_exists(session_id: str) -> bool:
    return (SESSIONS_ROOT / session_id).is_dir()


def delete_session(session_id: str) -> None:
    """Permanently delete a session and all its files."""
    d = SESSIONS_ROOT / session_id
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


# ── Durable save / resume ──────────────────────────────────────────────────── #

def snapshot_session(session_id: str) -> float:
    """Copy the live session dir into the durable saves store (overwrite).

    Returns the snapshot size in KB. This is what makes a saved session survive
    the TTL purge: the copy lives under SAVES_ROOT, which the sweep never touches.
    """
    src = SESSIONS_ROOT / session_id
    if not src.is_dir():
        raise FileNotFoundError(f"Session '{session_id}' has no live directory to save")
    dst = SAVES_ROOT / session_id
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    total = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    return round(total / 1024, 1)


def has_saved_session(session_id: str) -> bool:
    return (SAVES_ROOT / session_id).is_dir()


def rehydrate_session(saved_session_id: str) -> str:
    """Copy a durable saved session into a fresh live session; return its new id.

    The mesh/volume files and the full state.txt are copied verbatim, so the
    restored session is functionally identical to the saved one — segmentation,
    detection and morphometry re-read/re-derive from the same inputs.
    """
    src = SAVES_ROOT / saved_session_id
    if not src.is_dir():
        raise FileNotFoundError(f"No saved session '{saved_session_id}' found")
    new_sid = create_session()  # creates the sub-dirs + .created_at
    dst = SESSIONS_ROOT / new_sid
    for item in src.iterdir():
        s, d = src / item.name, dst / item.name
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    return new_sid


def delete_saved_session(session_id: str) -> None:
    """Remove a session's durable snapshot (does not touch any live session)."""
    d = SAVES_ROOT / session_id
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


# ── State helpers ──────────────────────────────────────────────────────────── #

def write_state(session_id: str, key: str, value: str) -> None:
    """Persist a simple key=value string in the session state file."""
    state_file = SESSIONS_ROOT / session_id / "state.txt"
    lines: dict[str, str] = {}
    if state_file.exists():
        for line in state_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                lines[k.strip()] = v.strip()
    lines[key] = value
    state_file.write_text("\n".join(f"{k}={v}" for k, v in lines.items()))


def read_state(session_id: str, key: str, default: str = "") -> str:
    """Read a value from the session state file."""
    state_file = SESSIONS_ROOT / session_id / "state.txt"
    if not state_file.exists():
        return default
    for line in state_file.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return default


# ── Static file URL helpers ────────────────────────────────────────────────── #

def mesh_url(session_id: str, filename: str) -> str:
    """Return the public URL for a mesh file served by FastAPI StaticFiles."""
    return f"/data/sessions/{session_id}/meshes/{filename}"


def report_url(session_id: str, filename: str) -> str:
    return f"/data/sessions/{session_id}/reports/{filename}"


def export_url(session_id: str, filename: str) -> str:
    return f"/data/sessions/{session_id}/exports/{filename}"


# ── Cleanup ────────────────────────────────────────────────────────────────── #

def purge_expired_sessions() -> int:
    """Delete all sessions older than SESSION_TTL_SEC. Returns count deleted.

    A session with no readable `.created_at` timestamp is treated as expired so
    stray/partial directories do not accumulate.
    """
    if not SESSIONS_ROOT.exists():
        return 0
    deleted = 0
    now = time.time()
    for d in SESSIONS_ROOT.iterdir():
        if not d.is_dir():
            continue
        ts_file = d / ".created_at"
        try:
            created = float(ts_file.read_text()) if ts_file.exists() else 0.0
        except (ValueError, OSError):
            created = 0.0
        if now - created > SESSION_TTL_SEC:
            shutil.rmtree(d, ignore_errors=True)
            deleted += 1
    if deleted:
        logger.info("Purged %d expired session(s) (TTL %.0f h)", deleted, SESSION_TTL_SEC / 3600)
    return deleted
