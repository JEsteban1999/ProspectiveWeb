"""Tests for the tamper-evident audit trail (Feature 5)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="prospective_audit_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-key-do-not-use-in-production")

from fastapi.testclient import TestClient

from main import app
from services.database import Base, engine
from services.audit import SkullChain

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)


class TestSkullChainUnit:
    def _chain(self) -> SkullChain:
        path = Path(tempfile.mkdtemp(prefix="chain_")) / "chain.db"
        return SkullChain(db_path=path)

    def test_genesis_and_append(self):
        c = self._chain()
        blocks = c.get_all_blocks()
        assert len(blocks) == 1 and blocks[0]["action"] == "GENESIS"
        h = c.append("LOGIN", {"role": "admin"}, username="admin")
        assert len(h) == 64
        assert len(c.get_all_blocks()) == 2

    def test_verify_ok(self):
        c = self._chain()
        for i in range(5):
            c.append("SEGMENTATION_COMPLETE", {"i": i}, username="u")
        ok, broken = c.verify_integrity()
        assert ok is True and broken == []

    def test_tamper_detected(self):
        c = self._chain()
        for i in range(3):
            c.append("REPORT_GENERATED", {"i": i}, username="u")
        # Tamper directly in the DB: change a payload without fixing the hash chain.
        conn = sqlite3.connect(str(c._path))
        conn.execute("UPDATE blocks SET payload_json='{\"i\": 999}' WHERE id = 3")
        conn.commit()
        conn.close()
        c2 = SkullChain(db_path=c._path)
        ok, broken = c2.verify_integrity()
        assert ok is False
        assert any(b["id"] == 3 for b in broken)


class TestAuditEndpoints:
    def test_append_and_list(self):
        r = client.post("/api/audit", json={"action": "DEVICE_PLACED", "payload": {"clip": "Yasargil"}, "username": "admin"})
        assert r.status_code == 200
        assert len(r.json()["block_hash"]) == 64
        blocks = client.get("/api/audit/blocks").json()
        assert len(blocks) >= 2
        assert any(b["action"] == "DEVICE_PLACED" for b in blocks)

    def test_verify_endpoint(self):
        d = client.get("/api/audit/verify").json()
        assert d["ok"] is True
        assert d["total_blocks"] >= 1

    def test_export_txt(self):
        r = client.get("/api/audit/export")
        assert r.status_code == 200
        assert "SkullChain Audit Trail" in r.text
