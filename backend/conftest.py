"""Pytest bootstrap — isolate the test database from the dev database.

Previously every test module called ``Base.metadata.create_all(bind=engine)`` on
the shared ``data/prospective.db``, so running the suite wrote hundreds of test
patients/sessions into the real dev database. Here we point the ORM at a throwaway
SQLite file *before* ``services.database`` is imported, then create the schema and
seed the default admin the tests rely on.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Must be set before anything imports services.database (it reads the env at
# import time to build the engine). conftest.py is imported by pytest first.
_TEST_DB = Path(tempfile.gettempdir()) / "prospective_test.db"
for _suffix in ("", "-wal", "-shm"):
    _p = Path(str(_TEST_DB) + _suffix)
    if _p.exists():
        try:
            _p.unlink()
        except OSError:
            pass
os.environ["PROSPECTIVE_DB_URL"] = f"sqlite:///{_TEST_DB}"

# Create tables + seed the default admin (admin/admin123) on the fresh test DB,
# mirroring the app's startup lifespan which TestClient does not run at import.
from services.database import SessionLocal, init_db  # noqa: E402
from services.auth_service import seed_default_user   # noqa: E402

init_db()
_db = SessionLocal()
try:
    seed_default_user(_db)
finally:
    _db.close()

# ── Authenticated by default ──────────────────────────────────────────────── #
#
# Patient data endpoints now require a token (they used to answer anonymously,
# which is what made the whole registry readable without logging in). Every test
# module builds its own ``TestClient(app)`` at import time, so instead of
# threading a header through ~300 call sites the client is given one by default.
# The header is a REAL token verified by the real dependency, so the tests still
# exercise authentication rather than bypassing it.
#
# For tests that must be anonymous, use ``anonymous_client(app)`` below.
from starlette.testclient import TestClient as _TestClient  # noqa: E402
from services.auth_service import create_access_token       # noqa: E402

_TEST_TOKEN = create_access_token(subject="admin")

_orig_testclient_init = _TestClient.__init__


def _testclient_init(self, *args, **kwargs):
    _orig_testclient_init(self, *args, **kwargs)
    self.headers.setdefault("Authorization", f"Bearer {_TEST_TOKEN}")


_TestClient.__init__ = _testclient_init


def anonymous_client(app):
    """A TestClient with no credentials, for asserting endpoints reject anons."""
    c = _TestClient(app)
    c.headers.pop("Authorization", None)
    c.cookies.clear()
    return c
