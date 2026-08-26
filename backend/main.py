"""PROSPECTIVE Web — FastAPI backend entry point.

Run with:
    uvicorn main:app --reload --host 127.0.0.1 --port 8000

Interactive API docs:
    http://127.0.0.1:8000/docs        ← Swagger UI
    http://127.0.0.1:8000/redoc       ← ReDoc
    http://127.0.0.1:8000/openapi.json ← Raw OpenAPI spec (for Claude Design)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from services.auth_service import require_user, user_for_token

from routers import (
    upload, segment, detect, perforators, plan,
    auth, patients, treatment, clips, coils, longitudinal,
    report, session_state, mpr, phases, centerline, audit,
    mesh_edit, print_prep, preprocess, studies, devices,
)

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────── #

async def _purge_loop(interval_sec: int = 3600) -> None:
    """Background task: purge expired session directories every `interval_sec`."""
    from services.sessions import purge_expired_sessions
    while True:
        try:
            await asyncio.sleep(interval_sec)
            await asyncio.to_thread(purge_expired_sessions)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # never let the loop die on a transient error
            logger.warning("Session purge loop error: %s", exc)


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ARG001
    """Initialise DB, seed admin, purge stale sessions, start the purge loop."""
    from services.database import init_db, SessionLocal
    from services.auth_service import seed_default_user
    from services.sessions import purge_expired_sessions
    init_db()
    db = SessionLocal()
    try:
        seed_default_user(db)
    finally:
        db.close()

    # Reclaim disk from sessions left over past their TTL, then keep purging.
    freed = await asyncio.to_thread(purge_expired_sessions)
    logger.info("Startup complete — database ready (purged %d stale session(s))", freed)

    purge_task = asyncio.create_task(_purge_loop())
    try:
        yield
    finally:
        purge_task.cancel()
        try:
            await purge_task
        except asyncio.CancelledError:
            pass


# ── App ───────────────────────────────────────────────────────────────────── #

app = FastAPI(
    lifespan=_lifespan,
    title="PROSPECTIVE Web API",
    description=(
        "REST + WebSocket API for cerebral aneurysm segmentation, detection, "
        "morphometry, perforator risk assessment and stent planning.\n\n"
        "All linear dimensions are in **millimetres (mm)**. "
        "All HU values follow the standard Hounsfield scale."
    ),
    version="0.1.0",
    contact={
        "name": "SkullApp — Laboratorio de Imagen Médica",
        "email": "ingprospective@skullapp.tech",
    },
    license_info={"name": "Proprietary"},
)

# ── CORS — allow React dev server (Vite default port) ─────────────────────── #

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server
        "http://127.0.0.1:5173",
        "http://localhost:3000",   # CRA / alternative
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Private static files ──────────────────────────────────────────────────── #
#
# StaticFiles is mounted below and bypasses router dependencies entirely, so the
# guard has to live in middleware. Session directories hold uploaded DICOM,
# whose headers carry patient name, national ID and date of birth: reachable by
# anyone who knew (or guessed) a session UUID before this existed.
#
# /static is bundled sample geometry with no patient data and stays public.

_PROTECTED_STATIC_PREFIXES = ("/data/",)


@app.middleware("http")
async def guard_private_static(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in _PROTECTED_STATIC_PREFIXES):
        from services.database import SessionLocal
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else request.cookies.get("prospective_token")
        db = SessionLocal()
        try:
            if user_for_token(db, token) is None:
                return JSONResponse(
                    {"detail": "Authentication required — patient data"},
                    status_code=401,
                )
        finally:
            db.close()
    return await call_next(request)


# ── Static files ──────────────────────────────────────────────────────────── #
# /static — bundled sample meshes (development only; production: S3/CloudFront)
# /data   — session-scoped files: DICOM uploads, meshes, reports, exports
#            served directly so vtk.js can fetch .vtp mesh URLs from the browser
Path("data").mkdir(exist_ok=True)     # ensure root exists for StaticFiles mount
Path("static").mkdir(exist_ok=True)   # same for static

app.mount(
    "/static",
    StaticFiles(directory="static", html=False),
    name="static",
)
app.mount(
    "/data",
    StaticFiles(directory="data", html=False),
    name="data",
)


# ── Routers ───────────────────────────────────────────────────────────────── #
#
# Everything except `auth` is patient data, so it is gated here rather than
# endpoint by endpoint — a router added without a guard would otherwise be
# public by default. `auth` keeps its own rules (login and signup are public,
# the rest already require a user or an admin).
#
# NOTE: `get_current_user` does NOT authenticate; it is an alias of
# `get_optional_user` and returns None when no token is present. Only
# `require_user` / `require_admin` reject anonymous callers.

_private = [Depends(require_user)]

app.include_router(auth.router)
app.include_router(patients.router,      dependencies=_private)
app.include_router(studies.router,       dependencies=_private)
app.include_router(upload.router,        dependencies=_private)
app.include_router(segment.router,       dependencies=_private)
app.include_router(detect.router,        dependencies=_private)
app.include_router(perforators.router,   dependencies=_private)
app.include_router(longitudinal.router,  dependencies=_private)
app.include_router(treatment.router,     dependencies=_private)
app.include_router(clips.router,         dependencies=_private)
app.include_router(coils.router,         dependencies=_private)
app.include_router(plan.router,          dependencies=_private)
app.include_router(report.router,        dependencies=_private)
app.include_router(session_state.router, dependencies=_private)
app.include_router(mpr.router,           dependencies=_private)
app.include_router(phases.router,        dependencies=_private)
app.include_router(centerline.router,    dependencies=_private)
app.include_router(audit.router,         dependencies=_private)
app.include_router(mesh_edit.router,     dependencies=_private)
app.include_router(print_prep.router,    dependencies=_private)
app.include_router(preprocess.router,    dependencies=_private)
app.include_router(devices.router,        dependencies=_private)


# ── Health check ──────────────────────────────────────────────────────────── #

@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict:
    return {"status": "ok", "version": app.version}


# ── API summary (useful during development) ───────────────────────────────── #

@app.get("/", tags=["system"], include_in_schema=False)
async def root() -> dict:
    return {
        "message": "PROSPECTIVE Web API",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }
