# PROSPECTIVE Web

> REST API backend for computer-assisted cerebral aneurysm surgical planning.
> Wraps the full PROSPECTIVE processing pipeline (VTK · SimpleITK · pydicom) in a
> FastAPI service ready to be consumed by any web frontend.

---

## Table of Contents

- [PROSPECTIVE Web](#prospective-web)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Tech Stack](#tech-stack)
  - [Project Structure](#project-structure)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Running the Server](#running-the-server)
  - [Environment Variables](#environment-variables)
  - [API Reference](#api-reference)
    - [Authentication](#authentication)
    - [Patients \& Studies](#patients--studies)
    - [DICOM \& Session](#dicom--session)
    - [Image Processing Pipeline](#image-processing-pipeline)
    - [Treatment Planning](#treatment-planning)
    - [Report \& Export](#report--export)
    - [Longitudinal Follow-up](#longitudinal-follow-up)
  - [Session Lifecycle](#session-lifecycle)
  - [Running Tests](#running-tests)
  - [Development Scripts](#development-scripts)
  - [Relationship to the Desktop App](#relationship-to-the-desktop-app)
  - [License](#license)

---

## Overview

PROSPECTIVE Web is the server-side component of the PROSPECTIVE platform — a clinical
decision-support system for neurosurgical planning of cerebral aneurysms.

The backend exposes **26 REST endpoints** that cover the entire planning workflow:

```
DICOM upload → auto-threshold → segmentation → aneurysm detection
  → morphometry → perforator risk → treatment decision
    → clip / coil / stent planning → PDF report → STL export
```

Patient data, studies and planning sessions are persisted in an **SQLite database**
with JWT-based authentication. All medical image processing runs on the server
(VTK + SimpleITK) so the browser only needs to render mesh URLs.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.110+ with Uvicorn |
| Medical imaging | SimpleITK 2.3, VTK 9.3, pydicom 2.4, scipy 1.12 |
| Mesh processing | VTK (Marching Cubes, smoothing, decimation, STL export) |
| Auth | python-jose (JWT HS256), passlib + bcrypt 4.x |
| Database | SQLAlchemy 2.0 + SQLite (WAL mode) |
| Report generation | reportlab 4.x (PDF) |
| Validation | Pydantic v2 |
| Testing | pytest 8, httpx, pytest-asyncio |
| Python | 3.11+ |

---

## Project Structure

```
ProspectiveWeb/
├── openapi.json                  # Full OpenAPI 3.1 spec (auto-exported from /openapi.json)
├── Makefile                      # Dev shortcuts (install, run, export openapi)
├── .gitignore
├── .gitattributes
│
└── backend/
    ├── main.py                   # FastAPI app, lifespan, CORS, static mounts, routers
    ├── requirements.txt
    ├── start.bat                 # Windows one-click launcher
    │
    ├── models/                   # Pydantic request/response schemas
    │   ├── auth.py               # LoginRequest, UserInfo, TokenResponse
    │   ├── clips.py              # ClipLibraryItem, ClipPlacement, ClipPlanRequest/Result
    │   ├── coils.py              # CoilLibraryItem, CoilPlacement, CoilPlanRequest/Result
    │   ├── detection.py          # AneurysmCandidate, DetectionResult, Position3D
    │   ├── dicom.py              # SeriesInfo, UploadResponse, ThresholdResponse
    │   ├── longitudinal.py       # LongitudinalEntry, LongitudinalResponse
    │   ├── patient.py            # PatientCreate, PatientSummary, StudySummary
    │   ├── perforators.py        # PerforatorCandidate, PerforatorRiskResponse
    │   ├── plan.py               # StentSpec, StentPlanRequest/Result
    │   ├── progress.py           # ProgressEvent (WebSocket)
    │   ├── report.py             # ReportRequest, ReportResponse
    │   ├── segmentation.py       # SegmentRequest, SegmentResponse
    │   ├── session_state.py      # SessionSaveRequest, SessionRestoreResponse
    │   └── treatment.py          # TreatmentRequest, TreatmentResponse, Factor
    │
    ├── routers/                  # FastAPI route handlers (one file per domain)
    │   ├── auth.py               # POST /api/auth/login  GET /api/auth/me
    │   ├── clips.py              # GET /api/clips  GET /api/clips/recommendations/{sid}
    │   │                         # POST /api/clips/plan
    │   ├── coils.py              # GET /api/coils  POST /api/coils/plan
    │   ├── detect.py             # POST /api/detect/{session_id}
    │   ├── longitudinal.py       # GET /api/longitudinal/{session_id}
    │   ├── patients.py           # GET/POST /api/patients
    │   │                         # GET /api/patients/{patient_id}/studies
    │   ├── perforators.py        # GET /api/perforators/{session_id}
    │   ├── plan.py               # POST /api/plan  GET /api/stents
    │   ├── progress.py           # WebSocket /ws/progress/{session_id}
    │   ├── report.py             # POST /api/report  POST /api/export/stl
    │   ├── segment.py            # POST /api/segment
    │   ├── session_state.py      # POST /api/sessions/save
    │   │                         # GET  /api/sessions
    │   │                         # POST /api/sessions/{session_id}/restore
    │   ├── treatment.py          # POST /api/treatment-decision
    │   └── upload.py             # POST /api/upload
    │
    ├── services/                 # Pure Python business logic (no Qt dependencies)
    │   ├── sessions.py           # UUID session dirs, TTL cleanup, state key/value store
    │   ├── thresholds.py         # Auto-threshold (CT/MR/XA) + voxel fraction
    │   ├── treatment.py          # 8-factor CLIP vs ENDOVASCULAR scoring engine
    │   ├── clips.py              # 42-model clip catalogue + recommendation algorithm
    │   ├── coils.py              # 39-model coil catalogue + sizing helpers
    │   ├── dicom_loader.py       # SimpleITK DICOM loading, multi-series, Enhanced XA
    │   ├── segmentation.py       # Marching Cubes pipeline, mesh I/O (.vtp / .stl)
    │   ├── aneurysm_detector.py  # Detection v6: Gaussian curvature + shape gates
    │   ├── morphometrics.py      # VTK plane slicing + ConvexHull → neck/dome/AR/bf/ui
    │   ├── perforator_risk.py    # Vertex-valence anomaly → perforator vessel candidates
    │   ├── report_generator.py   # reportlab PDF builder + session-data assembler
    │   ├── mesh_exporter.py      # STL export, poly merge, scale (VTK)
    │   ├── database.py           # SQLAlchemy engine, Base, get_db(), init_db()
    │   ├── db_models.py          # ORM: User, Patient, Study, PlanningSession
    │   └── auth_service.py       # JWT create/decode, password hash, FastAPI deps
    │
    └── tests
        ├── test_session_abc.py   # 76 tests — Sessions A-C (full pipeline, no DB)
        ├── test_session_d.py     # 39 tests — Auth, patients, longitudinal
        └── test_session_e.py     # 29 tests — PDF report, STL export
```

---

## Prerequisites

- **Python 3.11+**
- **pip** (or the included `.venv` setup via Makefile)
- Windows / macOS / Linux (VTK and SimpleITK are cross-platform)
- *(Frontend — future)* Node.js 20+ and npm 10+

---

## Installation

```bash
# 1 — Clone the repo
git clone https://github.com/juesnaca99/ProspectiveWeb.git
cd ProspectiveWeb

# 2 — Create virtual environment and install dependencies
cd backend
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt

# macOS / Linux
.venv/bin/pip install -r requirements.txt
```

Or with the Makefile (Windows):

```bash
make install:backend
```

---

## Running the Server

```bash
# From the backend/ directory
.venv\Scripts\uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Or double-click **`backend/start.bat`** on Windows, or use the Makefile:

```bash
make dev:backend
```

Once running:

| URL | Description |
|---|---|
| `http://127.0.0.1:8000/docs` | Swagger UI — interactive API explorer |
| `http://127.0.0.1:8000/redoc` | ReDoc — clean reference docs |
| `http://127.0.0.1:8000/openapi.json` | Raw OpenAPI 3.1 spec |
| `http://127.0.0.1:8000/health` | Health check `{"status":"ok"}` |

---

## Environment Variables

The server works out of the box with sensible defaults. Optional overrides:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/prospective.db` | SQLAlchemy connection string |
| `JWT_SECRET` | auto-generated, saved to `data/jwt_secret.txt` | HS256 signing secret |
| `JWT_EXPIRE_MINUTES` | `480` | Token lifetime (8 hours) |
| `SESSIONS_ROOT` | `data/sessions/` | Root directory for session files |
| `SESSION_TTL_HOURS` | `24` | Inactive session expiry |

No `.env` file is required for local development. For production, set `JWT_SECRET`
via your deployment environment (never commit it).

---

## API Reference

All endpoints are prefixed with `/api`. Full spec available at `/openapi.json`.

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Obtain JWT token (username + password) |
| `GET` | `/api/auth/me` | Current user info (requires Bearer token) |

Default dev account: **`admin` / `prospective2024`** (seeded on first startup).

### Patients & Studies

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/patients` | Create patient record |
| `GET` | `/api/patients` | List all patients |
| `GET` | `/api/patients/{patient_id}/studies` | List studies for a patient |

### DICOM & Session

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/upload` | Upload DICOM file(s); returns `session_id` |
| `GET` | `/api/thresholds/{session_id}` | Auto-computed HU/intensity thresholds |
| `POST` | `/api/sessions/save` | Persist session state to DB (link to patient/study) |
| `GET` | `/api/sessions` | List saved sessions |
| `POST` | `/api/sessions/{session_id}/restore` | Restore a saved session |

### Image Processing Pipeline

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/segment` | Run Marching Cubes segmentation → `.vtp` mesh |
| `POST` | `/api/detect/{session_id}` | Detect aneurysm candidates (curvature analysis) |
| `GET` | `/api/morphometry/{session_id}` | Full morphometric analysis (neck, dome, AR, bf, ui…) |
| `GET` | `/api/perforators/{session_id}` | Perforator vessel risk assessment |

### Treatment Planning

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/treatment-decision` | 8-factor CLIP vs ENDOVASCULAR scoring |
| `GET` | `/api/clips` | Surgical clip device library (42 models) |
| `GET` | `/api/clips/recommendations/{session_id}` | Top-8 ranked clip recommendations |
| `POST` | `/api/clips/plan` | Compute clip placement plan + neck coverage |
| `GET` | `/api/coils` | Endovascular coil library (39 models) |
| `POST` | `/api/coils/plan` | Coil sizing + packing density estimate |
| `GET` | `/api/stents` | Stent / flow-diverter catalogue |
| `POST` | `/api/plan` | Stent deployment planning |

### Report & Export

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/report` | Generate PDF surgical planning report |
| `POST` | `/api/export/stl` | Export combined mesh as binary STL |

### Longitudinal Follow-up

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/longitudinal/{session_id}` | Growth history + alert if Δmax_mm > 1 mm/year |

---

## Session Lifecycle

Every interaction is scoped to a **session** — a UUID directory under `data/sessions/`:

```
data/sessions/{uuid}/
├── .created_at          # ISO timestamp used for TTL cleanup
├── state.txt            # Key-value store (morpho.*, treatment.*, detect.*)
├── dicom/               # Uploaded DICOM files
├── meshes/              # Segmentation outputs (.vtp)
├── reports/             # Generated PDFs
└── exports/             # Exported STL files
```

Typical flow:

```
POST /api/upload          → session_id created
GET  /api/thresholds/{id} → auto HU thresholds
POST /api/segment         → vessel_tree.vtp generated
POST /api/detect/{id}     → aneurysm candidates detected
GET  /api/morphometry/{id}→ neck/dome measurements stored in state
POST /api/treatment-decision → recommendation + factors stored in state
POST /api/report          → PDF assembled from session state
POST /api/sessions/save   → session linked to Patient + Study in DB
```

Session files are served statically under `/data/sessions/` so the frontend
can load mesh URLs directly (e.g. `/data/sessions/{id}/meshes/vessel_tree.vtp`).

---

## Running Tests

```bash
cd backend

# All 144 tests
python -m pytest test_session_abc.py test_session_d.py test_session_e.py -v

# By suite
python -m pytest test_session_abc.py -v   # 76 tests — pipeline (A-C)
python -m pytest test_session_d.py    -v  # 39 tests — auth & DB (D)
python -m pytest test_session_e.py    -v  # 29 tests — report & export (E)
```

Each test file is fully isolated:
- `test_session_abc.py` — in-memory session state, no database
- `test_session_d.py` — temporary SQLite via `DATABASE_URL` env override + `dependency_overrides`
- `test_session_e.py` — temporary SQLite, real `reportlab`/VTK calls

Expected result: **144 passed, 0 failed**.

---

## Development Scripts

```bash
# Makefile (from repo root — Windows)
make install:backend     # create .venv + pip install
make dev:backend         # uvicorn --reload on :8000
make install:frontend    # npm install (when frontend exists)
make dev:frontend        # npm run dev (Vite on :5173)
make openapi:export      # curl /openapi.json → openapi.json
```

---

## Relationship to the Desktop App

The **Prospective** desktop application (PyQt5/VTK) shares the same processing
services with this web backend. The difference is architectural:

| | Desktop (Prospective) | Web (ProspectiveWeb) |
|---|---|---|
| UI | PyQt5 widgets | React frontend *(planned)* |
| Processing | `services/` (Qt-coupled) | `services/` (Qt-free, same algorithms) |
| Auth & persistence | none | JWT + SQLite via SQLAlchemy |
| Longitudinal tracking | none | ✅ growth-alert engine |
| Access | local machine | browser / any HTTP client |

The `openapi.json` at the repo root is the single source of truth for the
frontend contract — use it with Claude Design or any OpenAPI code generator
to scaffold the React frontend.

---

## License

Proprietary — SkullApp, Laboratorio de Imagen Médica.
