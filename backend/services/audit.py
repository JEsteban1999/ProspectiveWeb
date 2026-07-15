"""SkullChain — tamper-evident local audit trail (port of audit/skull_chain.py).

Each block is a SHA-256 hash of (iso_ts | username | patient_hash | action |
payload_hash | prev_hash). Altering any block breaks every subsequent hash, so
tampering is detectable. Backed by a dedicated SQLite DB under the data dir.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64

# Action constants
ACT_LOGIN              = "LOGIN"
ACT_SEGMENTATION       = "SEGMENTATION_COMPLETE"
ACT_TREATMENT_DECISION = "TREATMENT_DECISION"
ACT_DEVICE_PLACED      = "DEVICE_PLACED"
ACT_REPORT_GENERATED   = "REPORT_GENERATED"
ACT_SR_GENERATED       = "DICOM_SR_GENERATED"
ACT_INTEGRITY_CHECK    = "INTEGRITY_CHECK"

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "audit" / "chain.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS blocks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    iso_ts       TEXT    NOT NULL,
    username     TEXT    NOT NULL DEFAULT '',
    patient_hash TEXT    NOT NULL DEFAULT '',
    action       TEXT    NOT NULL,
    payload_json TEXT    NOT NULL DEFAULT '{}',
    payload_hash TEXT    NOT NULL,
    prev_hash    TEXT    NOT NULL,
    block_hash   TEXT    NOT NULL
)
"""


class SkullChain:
    """Singleton tamper-evident audit trail backed by a local SQLite DB."""

    _instance: "SkullChain | None" = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()
        if self._conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0:
            self._write_genesis()

    @classmethod
    def instance(cls) -> "SkullChain":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── hashing ──────────────────────────────────────────────────────── #

    @staticmethod
    def _compute_block_hash(iso_ts, username, patient_hash, action, payload_hash, prev_hash) -> str:
        raw = "|".join([iso_ts, username, patient_hash, action, payload_hash, prev_hash])
        return sha256(raw.encode("utf-8")).hexdigest()

    def _last_hash(self) -> str:
        row = self._conn.execute("SELECT block_hash FROM blocks ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS_HASH

    def _write_genesis(self) -> None:
        iso_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
        payload_json = "{}"
        payload_hash = sha256(payload_json.encode()).hexdigest()
        block_hash = self._compute_block_hash(iso_ts, "", "", "GENESIS", payload_hash, GENESIS_HASH)
        self._conn.execute(
            "INSERT INTO blocks (iso_ts, username, patient_hash, action, payload_json, payload_hash, prev_hash, block_hash)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (iso_ts, "", "", "GENESIS", payload_json, payload_hash, GENESIS_HASH, block_hash),
        )
        self._conn.commit()

    # ── public API ───────────────────────────────────────────────────── #

    def append(self, action: str, payload: dict, username: str = "",
               patient_id: str = "", patient_dob: str = "") -> str:
        patient_hash = (
            sha256((patient_id + patient_dob).encode("utf-8")).hexdigest()
            if (patient_id or patient_dob) else ""
        )
        now = datetime.now(timezone.utc)
        iso_ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload_hash = sha256(payload_json.encode("utf-8")).hexdigest()
        with self._lock:
            prev_hash = self._last_hash()
            block_hash = self._compute_block_hash(iso_ts, username, patient_hash, action, payload_hash, prev_hash)
            self._conn.execute(
                "INSERT INTO blocks (iso_ts, username, patient_hash, action, payload_json, payload_hash, prev_hash, block_hash)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (iso_ts, username, patient_hash, action, payload_json, payload_hash, prev_hash, block_hash),
            )
            self._conn.commit()
        logger.debug("SkullChain: appended block %s action=%s", block_hash[:12], action)
        return block_hash

    def verify_integrity(self) -> tuple[bool, list[dict]]:
        rows = self._conn.execute(
            "SELECT id, iso_ts, username, patient_hash, action, payload_json, payload_hash, prev_hash, block_hash"
            " FROM blocks ORDER BY id ASC"
        ).fetchall()
        broken: list[dict] = []
        prev_block_hash: str | None = None
        for row in rows:
            if prev_block_hash is None:
                if row["prev_hash"] != GENESIS_HASH:
                    broken.append({"id": row["id"], "iso_ts": row["iso_ts"], "action": row["action"],
                                   "reason": f"prev_hash mismatch on genesis (got {row['prev_hash'][:12]}…)"})
            elif row["prev_hash"] != prev_block_hash:
                broken.append({"id": row["id"], "iso_ts": row["iso_ts"], "action": row["action"],
                               "reason": f"prev_hash mismatch: expected {prev_block_hash[:12]}… got {row['prev_hash'][:12]}…"})
            # Payload integrity: the stored payload_hash must match the JSON
            # (closes a gap in the desktop original where editing payload_json
            # alone went undetected).
            expected_pl = sha256(row["payload_json"].encode("utf-8")).hexdigest()
            if expected_pl != row["payload_hash"]:
                broken.append({"id": row["id"], "iso_ts": row["iso_ts"], "action": row["action"],
                               "reason": "payload_hash mismatch — payload tampered"})

            expected = self._compute_block_hash(
                row["iso_ts"], row["username"], row["patient_hash"], row["action"], row["payload_hash"], row["prev_hash"]
            )
            if expected != row["block_hash"]:
                broken.append({"id": row["id"], "iso_ts": row["iso_ts"], "action": row["action"],
                               "reason": f"block_hash corrupted: expected {expected[:12]}… stored {row['block_hash'][:12]}…"})
            prev_block_hash = row["block_hash"]
        return (len(broken) == 0), broken

    def get_all_blocks(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, iso_ts, username, patient_hash, action, payload_json, payload_hash, prev_hash, block_hash"
            " FROM blocks ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def export_txt(self) -> str:
        blocks = self.get_all_blocks()
        all_ok, broken = self.verify_integrity()
        lines = [
            "=" * 100,
            "  PROSPECTIVE — SkullChain Audit Trail Export",
            f"  Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z",
            "=" * 100, "",
            f"{'#':>4}  {'Fecha/Hora':<26} {'Usuario':<14} {'Acción':<24} {'Hash bloque':<16}",
            "-" * 100,
        ]
        for b in blocks:
            lines.append(f"{b['id']:>4}  {b['iso_ts']:<26} {(b['username'] or '—'):<14} {b['action']:<24} {b['block_hash'][:12]}…")
        lines += ["-" * 100, "", f"Total blocks: {len(blocks)}"]
        if all_ok:
            lines.append(f"Integrity: OK — all {len(blocks)} blocks verified.")
        else:
            lines.append(f"Integrity: WARNING — {len(broken)} corrupted block(s)!")
            for b in broken:
                lines.append(f"  Block #{b['id']} ({b['iso_ts']}) {b['action']}: {b['reason']}")
        lines.append("=" * 100)
        return "\n".join(lines) + "\n"


def audit_append(action: str, payload: dict, username: str = "",
                 patient_id: str = "", patient_dob: str = "") -> None:
    """Fire-and-forget append that never raises into the caller's flow."""
    try:
        SkullChain.instance().append(action, payload, username, patient_id, patient_dob)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Audit append failed (%s): %s", action, exc)
