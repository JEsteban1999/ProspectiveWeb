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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import (
    upload, segment, detect, perforators, plan, progress,
    auth, patients, treatment, clips, coils, longitudinal,
    report, session_state, mpr, phases, centerline,
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
        "name": "UniNavarra — Laboratorio de Imagen Médica",
        "email": "juesnaca99@gmail.com",
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

app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(upload.router)
app.include_router(segment.router)
app.include_router(detect.router)
app.include_router(perforators.router)
app.include_router(longitudinal.router)
app.include_router(treatment.router)
app.include_router(clips.router)
app.include_router(coils.router)
app.include_router(plan.router)
app.include_router(report.router)
app.include_router(session_state.router)
app.include_router(progress.router)
app.include_router(mpr.router)
app.include_router(phases.router)
app.include_router(centerline.router)


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
