# PROSPECTIVE Web

> Computer-assisted planning for cerebral aneurysm surgery, in the browser.
> FastAPI backend (VTK · SimpleITK · pydicom) + React/TypeScript frontend with
> real-time 3D and MPR viewers — the web port of the PROSPECTIVE desktop app.

---

## Table of Contents

- [Overview](#overview)
- [Status](#status)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Running the App](#running-the-app)
- [Environment Variables](#environment-variables)
- [Data Model](#data-model)
- [Session Lifecycle](#session-lifecycle)
- [API Reference](#api-reference)
- [Running Tests](#running-tests)
- [Development Scripts](#development-scripts)
- [Relationship to the Desktop App](#relationship-to-the-desktop-app)
- [Known Limitations](#known-limitations)
- [Privacy & Security Notes](#privacy--security-notes)
- [License](#license)

---

## Overview

PROSPECTIVE Web is a clinical decision-support system for neurosurgical planning
of cerebral aneurysms. A clinician uploads a DICOM study and walks a seven-step
pipeline, with every step rendered live in 3D:

```
1 DICOM upload  →  2 Segmentation  →  3 Detection  →  4 Morphometry
      →  5 Treatment decision  →  6 Devices  →  7 Report
```

All medical image processing runs on the server (VTK + SimpleITK); the browser
renders meshes with vtk.js and 2D slices as server-rendered PNGs.

Beyond the pipeline the platform covers the surrounding clinical workflow:
patient registry, clinical cases, a durable archive of imaging studies with a
searchable preview gallery, resumable planning sessions, user signup with admin
approval, and a tamper-evident audit chain.

---

## Status

| | |
|---|---|
| Backend tests | **335 passing** (`pytest`, 26 files) |
| Frontend | `tsc -b` clean · production build clean |
| REST endpoints | **77** operations across 69 paths (21 routers), all authenticated except login/signup/logout |
| Feature parity with desktop | **Complete** |

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.110+ with Uvicorn |
| Medical imaging | SimpleITK 2.3, VTK 9.3, pydicom 2.4, scipy 1.12, Pillow 10 |
| Mesh processing | VTK (Marching Cubes, smoothing, decimation, STL export) |
| Auth | python-jose (JWT HS256), passlib + bcrypt 4.x |
| Database | SQLAlchemy 2.0 + SQLite (WAL mode) |
| Report generation | reportlab 4.x (PDF), pydicom (DICOM SR) |
| Study archive | pluggable local filesystem or AWS S3 (boto3, optional) |
| Frontend | React 19 + TypeScript 5.8 + Vite 7 |
| 3D / 2D viewers | @kitware/vtk.js 36 (meshes, volume rendering) + server-rendered MPR PNGs |
| Routing | react-router-dom 7 |
| Python | 3.11+ (developed on 3.13) · Node 20+ |

---

## Project Structure

```
ProspectiveWeb/
├── openapi.json            # OpenAPI 3.1 spec (regenerate: make openapi:export)
├── Makefile                # Dev shortcuts
├── start-all.bat           # Windows: launches backend + frontend in two windows
│
├── backend/
│   ├── main.py             # FastAPI app: lifespan, CORS, static mounts, guarded routers
│   ├── requirements.txt
│   ├── models/    (20)     # Pydantic request/response schemas
│   ├── routers/   (21)     # Route handlers, one file per domain
│   ├── services/  (32)     # Qt-free business logic, shared with the desktop app
│   ├── test_*.py  (26)     # pytest suites
│   ├── data/               # PUBLIC static mount — sessions, meshes, reports
│   ├── study_files/        # PRIVATE archive: DICOM of archived studies (gitignored)
│   ├── user_files/         # PRIVATE: signup photos and CVs (gitignored)
│   └── secrets/            # PRIVATE: JWT signing key (gitignored)
│
└── frontend/
    ├── src/
    │   ├── pages/          # Landing · Login · Signup · Patients · NuevoCaso
    │   │                   # Studies · Workspace · PendingRequests · UsersAdmin · AuditTrail
    │   ├── components/     # Design-system primitives + one panel per pipeline step
    │   ├── vtk/            # MeshView · VolumeView · MprView · ObliqueMprView · Viewer
    │   ├── store/          # planning · auth · nav · theme contexts
    │   └── styles/tokens/  # Design tokens (light/dark via [data-theme])
    └── public/media/       # Intro / loading / landing videos
```

Key backend services (all ported from the desktop `prospective/processing`):

| Service | Purpose |
|---|---|
| `dicom_loader.py` | SimpleITK series loading, multi-series scan, Enhanced XA multiframe |
| `thresholds.py` | Auto HU/intensity band per modality (CT · MR · XA · DSA strategies) |
| `preprocess.py` | HU clipping, isotropic resampling, Gaussian smoothing, bone subtraction |
| `segmentation.py` | Marching Cubes → component filter → smoothing → decimation |
| `grow.py` / `mesh_crop.py` | Region-grow from seeds · box/sphere ROI clipping |
| `aneurysm_detector.py` | Curvature + shape-gate candidate detection |
| `morphometrics.py` | Neck / dome / AR / DNR / BF / UI / EI / NSI with reliability guards |
| `sac_isolation.py` | Semi-automatic watertight sac isolation from two clicks |
| `parent_artery.py` | Parent-vessel diameter → size ratio |
| `centerline.py` / `cross_section.py` | Medial-axis extraction · diameter profile · stenosis |
| `perforator_risk.py` | Vertex-valence anomaly → perforator candidates |
| `treatment.py` | 8-factor CLIP vs ENDOVASCULAR scoring with literature citations |
| `clips.py` / `coils.py` / `devices.py` | Device catalogues, recommendations, real VTK collision |
| `stent_deployment.py` | Centerline-guided braided stent along real vessel curvature |
| `phases.py` | PHASES 5-year rupture risk (Greving 2014) |
| `mesh_prep.py` | 3D-print preparation + printer-bed presets |
| `report_generator.py` / `dicom_sr.py` / `mesh_exporter.py` | PDF · DICOM SR · STL |
| `audit.py` | SkullChain SHA-256 tamper-evident event chain |
| `storage.py` / `study_archive.py` | Durable study archive (local or S3) + previews |
| `sessions.py` | Session dirs, TTL purge, durable snapshot / rehydrate |

---

## Prerequisites

- **Python 3.11+** and **Node.js 20+**
- Windows / macOS / Linux (VTK and SimpleITK are cross-platform)

---

## Installation

```bash
git clone https://github.com/JEsteban1999/ProspectiveWeb.git
cd ProspectiveWeb

# Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt        # macOS / Linux

# Frontend
cd ../frontend
npm install
```

Or, on Windows, with the Makefile from the repo root:

```bash
make install:backend
make install:frontend
```

---

## Running the App

Double-click **`start-all.bat`** (Windows) to launch both servers, or run them
separately:

```bash
# Backend — http://127.0.0.1:8000
cd backend && .venv\Scripts\uvicorn main:app --reload --host 127.0.0.1 --port 8000

# Frontend — http://localhost:5173
cd frontend && npm run dev
```

| URL | Description |
|---|---|
| `http://localhost:5173/` | Public landing page |
| `http://localhost:5173/app` | The application (login → patients → workspace) |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/redoc` | ReDoc |
| `http://127.0.0.1:8000/health` | Health check |

Default account seeded on first run: **`admin` / `admin123`**. There is no
password-change endpoint yet, so treat this as a development credential and set
up a proper account flow before any real deployment.

> **Note on `--reload`**: uvicorn's reloader does not reliably pick up *new*
> modules, and a stale process on :8000 will silently serve old code. Restart the
> backend for real when verifying a change end to end.

---

## Environment Variables

The server runs out of the box with sensible defaults.

| Variable | Default | Description |
|---|---|---|
| `PROSPECTIVE_DB_URL` | `sqlite:///backend/data/prospective.db` | SQLAlchemy connection string |
| `JWT_SECRET` | auto-generated into `backend/secrets/jwt_secret.txt` | HS256 signing key |
| `SESSION_TTL_HOURS` | `24` | Age at which an idle working session is purged |
| `STUDY_FILES_ROOT` | `backend/study_files` | Root of the durable study archive |
| `STORAGE_BACKEND` | `local` | `local` (filesystem) or `s3` |
| `STORAGE_S3_BUCKET` | — | Required when `STORAGE_BACKEND=s3`; bucket must be private |
| `STORAGE_S3_PREFIX` | — | Optional key prefix inside the bucket |
| `COOKIE_SECURE` | off | Mark the auth cookie `Secure` (set it when serving over HTTPS) |
| `BACKEND_URL` | `http://127.0.0.1:8000` | Where the Vite dev server proxies `/api`, `/data`, `/static` |

Token lifetime is currently a constant (`ACCESS_TOKEN_EXPIRE_MIN`, 24 h) in
`services/auth_service.py`, not an environment variable.

For production, always set `JWT_SECRET` from the deployment environment and never
commit it.

---

## Data Model

The clinical hierarchy is deliberately four levels deep, so one episode of care
can carry several acquisitions without duplicating records:

```
Patient  ──<  Study (clinical case)  ──<  ImagingStudy (one acquisition)
                      │                            │
                      └──────<  PlanningSession  >─┘
```

- **Patient** — demographics, history, institution.
- **Study** — the *clinical case*: diagnosis, aneurysm type, region, laterality,
  proposed treatment. Created via "Nuevo caso" against an existing patient.
- **ImagingStudy** — one archived acquisition (CT, angiography, follow-up) with
  its DICOM in durable storage plus a rendered preview. A case may hold several.
- **PlanningSession** — a saved run of the pipeline, linked to both the case and
  the acquisition it analysed, resumable from the step it was saved at.

The **Studies gallery** (the "Estudios" tab, and inside each patient sheet) lists
archived imaging studies as preview cards, filterable by patient name, hospital ID
or diagnosis. Clicking one restores its DICOM into a fresh working session and
opens the pipeline.

---

## Session Lifecycle

Every pipeline interaction is scoped to a **session** — a UUID directory:

```
backend/data/sessions/{uuid}/
├── .created_at          # ISO timestamp used for TTL cleanup
├── state.txt            # Key-value store (dicom.*, seg.*, morpho.*, treatment.*)
├── dicom/               # Uploaded DICOM files
├── meshes/              # Meshes (.vtp) + cached volume (_volume.npy)
├── reports/             # Generated PDFs
└── exports/             # Exported STL files
```

Sessions are working scratch and are purged after `SESSION_TTL_HOURS`. Two
mechanisms make work survive that sweep:

- **Archiving a study** copies its DICOM into `study_files/` (or S3) and creates
  an `ImagingStudy`. This is what puts it in the gallery.
- **Saving progress** snapshots the session directory into
  `data/session_saves/{uuid}`. The DICOM is hard-linked rather than copied
  (studies are ~1 GB and copying them filled the disk); meshes and the volume
  cache are copied, because re-running a step rewrites them in place and a
  snapshot must stay a point-in-time image.

Typical flow:

```
POST /api/upload                       → session_id + detected series
GET  /api/segment/suggested-band/{id}  → auto HU band for this modality
POST /api/segment                      → vessel_tree.vtp
POST /api/detect/{id}                  → aneurysm candidates
GET  /api/morphometry/{id}             → neck/dome measurements
POST /api/treatment-decision           → CLIP vs ENDO recommendation
POST /api/report                       → PDF assembled from session state
POST /api/studies/cases/{case}/archive → DICOM into durable storage
POST /api/sessions/save                → resumable snapshot + DB link
```

Session files are served statically under `/data/sessions/` so vtk.js can fetch
mesh URLs directly — behind a middleware that requires the same token as the API,
since those directories also hold the uploaded DICOM.

---

## API Reference

77 operations under `/api`. Full spec in `openapi.json` or at `/docs`.

**Everything except `POST /api/auth/login`, `/signup` and `/logout` requires a
token.** It travels as `Authorization: Bearer …` or as the `prospective_token`
cookie that login also sets — the browser cannot attach a header to an `<img
src>` or to the requests vtk.js makes for `.vtp` meshes, and those URLs serve
patient imaging.

### Authentication & users

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Obtain JWT (username + password) |
| `GET` | `/api/auth/me` · `/api/auth/me/photo` | Current user + avatar |
| `POST` | `/api/auth/logout` | Clear the session cookie |
| `POST` | `/api/auth/change-password` | Change your own (current password required) |
| `POST` | `/api/auth/users/{id}/reset-password` | Reset someone else's (admin) |
| `POST` | `/api/auth/signup` | Public signup (multipart: photo + CV) → *pending* |
| `GET` | `/api/auth/pending` | Pending signup requests (admin) |
| `POST` | `/api/auth/pending/{id}/approve` · `/reject` | Approve or reject (admin) |
| `GET` | `/api/auth/pending/{id}/photo` · `/cv` | Download applicant documents (admin) |
| `GET` `POST` | `/api/auth/users` | List / create users (admin) |
| `PUT` `DELETE` | `/api/auth/users/{id}` | Edit / delete, with anti-lockout guards (admin) |

### Patients, cases & imaging studies

| Method | Endpoint | Description |
|---|---|---|
| `GET` `POST` | `/api/patients` | List / create patients |
| `GET` `PUT` `DELETE` | `/api/patients/{id}` | Full record, edit, delete (cascades) |
| `POST` | `/api/patients/case` | Create patient + clinical case in one step |
| `GET` `POST` | `/api/patients/{id}/studies` | List / add clinical cases |
| `PUT` `DELETE` | `/api/patients/{id}/studies/{sid}` | Edit / delete a case |
| `GET` | `/api/patients/{id}/sessions` | Saved planning sessions of a patient |
| `GET` | `/api/studies` | Gallery: archived imaging studies (`q`, `patient_id`, `case_id`) |
| `GET` | `/api/studies/{id}/thumbnail` | Rendered preview PNG |
| `POST` | `/api/studies/cases/{case_id}/archive` | Archive a session's DICOM under a case |
| `POST` | `/api/studies/{id}/open` | Restore an archived study into a new session |

### DICOM, viewers & sessions

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/upload` | Upload DICOM files/folder → session + series list |
| `POST` | `/api/upload/{sid}/series/{series_id}` | Switch the active series |
| `GET` | `/api/volume/{sid}/meta` · `/raw` | Volume metadata · raw uint8 volume |
| `GET` | `/api/slice/{sid}/{plane}/{index}` | MPR slice PNG (`wc`, `ww`, optional `lower`/`upper` tint) |
| `GET` | `/api/slice-oblique/{sid}` | Oblique reslice PNG |
| `POST` | `/api/sessions/save` · `/{sid}/restore` | Durable snapshot · rehydrate |
| `GET` | `/api/sessions` | List saved sessions |

### Processing pipeline

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/segment/suggested-band/{sid}` | Auto HU band + strategy used |
| `POST` | `/api/segment/preview/{sid}` | Coarse live preview mesh while tuning sliders |
| `POST` | `/api/segment` | Full Marching Cubes segmentation |
| `POST` | `/api/segment/grow/{sid}` | Region-grow from picked seeds |
| `POST` | `/api/mesh-crop/{sid}` | Box / sphere ROI crop of the mesh |
| `POST` | `/api/preprocess/{sid}` | Resample · smooth · bone subtraction |
| `POST` | `/api/detect/{sid}` | Aneurysm candidate detection |
| `GET` | `/api/morphometry/{sid}` | Morphometric indices with reliability flags |
| `POST` | `/api/morphometry/{sid}/neck-plane` | Two-click sac isolation → reliable metrics |
| `GET` | `/api/perforators/{sid}` | Perforator risk candidates |
| `POST` | `/api/centerline/{sid}` · `/api/cross-section/{sid}` | Medial axis · diameter profile |
| `GET` | `/api/longitudinal/{sid}` | Growth history + alert if Δ > 1 mm/year |

### Treatment planning

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/treatment-decision` | 8-factor CLIP vs ENDOVASCULAR scoring |
| `POST` | `/api/phases` | PHASES 5-year rupture risk |
| `GET` | `/api/clips` · `/api/coils` · `/api/stents` | Device catalogues |
| `GET` | `/api/clips/recommendations/{sid}` | Ranked clip recommendations |
| `POST` | `/api/clips/plan` · `/api/clips/custom/{sid}` | Placement + real VTK collision |
| `POST` | `/api/coils/plan` · `/api/plan` | Coil packing · stent deployment |
| `POST` | `/api/cl-stent/{sid}` | Centerline-guided stent along vessel curvature |
| `POST` `DELETE` | `/api/trajectory/{sid}` | Surgical trajectory |

### Report, export & audit

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/report` | PDF surgical planning report |
| `POST` | `/api/report/dicom-sr` | DICOM Structured Report (TID 1500) |
| `POST` | `/api/export/stl` | Binary STL export |
| `GET` `POST` | `/api/print-prep/beds` · `/api/print-prep/{sid}` | 3D-print preparation |
| `POST` `GET` | `/api/audit` · `/blocks` · `/verify` · `/export` | SkullChain audit trail |

---

## Running Tests

```bash
cd backend
.venv\Scripts\python -m pytest -q                        # all 335 tests
.venv\Scripts\python -m pytest test_session_abc.py -v    # one suite
```

Expected: **335 passed, 0 failed** (~1–2 min; VTK and SimpleITK do real work).

Frontend checks:

```bash
cd frontend
npx tsc -b --noEmit     # type check
npm run build           # production build
```

Test isolation notes:

- Suites that touch the database point `PROSPECTIVE_DB_URL` at a temp SQLite file.
- Suites that touch the study archive **must** set `STUDY_FILES_ROOT` to a temp
  directory. The archive root is resolved per call precisely so this works; a
  frozen module constant once let the suite overwrite a real patient's DICOM.
  `test_study_gallery.py` asserts the isolation holds for the live app too.

---

## Development Scripts

```bash
make install:backend     # create .venv + pip install
make install:frontend    # npm install
make dev:backend         # uvicorn --reload on :8000
make dev:frontend        # vite on :5173
make openapi:export      # curl /openapi.json → openapi.json (server must be up)
```

---

## Relationship to the Desktop App

The **Prospective** desktop application (PyQt5/VTK) and this web app share the
same algorithms: every module under `prospective/processing`, `prospective/io`,
`prospective/dicom`, `prospective/audit` and `prospective/auth` has a Qt-free
counterpart under `backend/services`, and every desktop panel has a web panel.

| | Desktop (Prospective) | Web (ProspectiveWeb) |
|---|---|---|
| UI | PyQt5 widgets | React 19 + vtk.js in the browser |
| Processing | `processing/` (Qt-coupled) | `services/` (Qt-free, same algorithms) |
| Auth | local SQLite + signup approval | JWT + SQLite, same approval flow |
| Password change / reset | yes | yes (self-service + admin reset, audited) |
| Session persistence | `.prospective` file on disk | DB record + durable server-side snapshot |
| Study archive & gallery | no | local or S3, with preview thumbnails |
| Case ↔ imaging separation | one study per case | several acquisitions per clinical case |
| Live HU threshold preview | no | tinted MPR overlay while dragging sliders |
| Series selector | no | picks among all series in a study |
| Public landing page | no | yes |
| Access | local machine | browser / any HTTP client |

---

## Known Limitations

An honest list of what is *not* done, so nobody discovers it in front of a
clinician.

**Functional**

- **`GET /api/thresholds/{sid}` is not used by the bundled frontend.** It returns
  the strategy key and a clinical hint; the UI reads the slider range from
  `GET /api/segment/suggested-band/{sid}` instead. Both share the same
  `compute_auto_thresholds` core, so they cannot drift apart.
- **No progress streaming.** Long operations show an indeterminate bar. A
  WebSocket route used to exist but emitted a canned sequence unrelated to real
  work and no client connected to it, so it was removed rather than left to look
  like a feature.
- **CSRF relies on `SameSite=Lax`.** The auth cookie is not sent on cross-site
  requests, and the API only accepts JSON, but there is no anti-CSRF token. Add
  one before serving the app from a domain that also hosts untrusted content.

**Clinical accuracy** (needs annotated ground truth, not a patch)

- Fully automatic aneurysm isolation is not viable on dense vascular trees; the
  reliable path is the two-click neck plane, which the UI guides you through.
- Bone and contrast overlap in HU, so no global threshold separates them on some
  studies. That is why the live threshold preview, seeded region-grow and ROI crop
  exist.
- The detector is unstable on sparse meshes and CT can saturate the candidate list
  with bone false positives; candidates are ranked and labelled with confidence so
  a low-confidence pick is visible.

---

## Privacy & Security Notes

This software handles identifiable patient data.

**How access control works**

- Every route requires a valid token except `POST /api/auth/login`, `/signup` and
  `/logout`. This is enforced at `include_router` time in `main.py` rather than
  per endpoint, so a router added without a guard is closed by default.
  `test_auth_coverage.py` walks the real route table and fails if anything
  outside an explicit allowlist answers anonymously.
- Beware `get_current_user`: it is an alias of `get_optional_user` and returns
  `None` instead of raising. Only `require_user` / `require_admin` authenticate.
- Login issues the token twice: as a bearer token for the API client and as an
  HttpOnly `SameSite=Lax` cookie, because `<img src>` (MPR slices) and vtk.js
  mesh requests cannot carry a header. Logging out clears the cookie server-side.
- `backend/data/` is a StaticFiles mount, so router dependencies do not apply to
  it. A middleware guards `/data/` with the same token check — session DICOM used
  to be downloadable by anyone who knew a session UUID.

**Before deploying**

- **Set `JWT_SECRET` from the environment.** Otherwise it is generated into
  `backend/secrets/jwt_secret.txt`. Never place it under `data/`: it lived there
  once and `GET /data/jwt_secret.txt` returned the signing key, which is enough to
  mint an admin token.
- **Change the seeded `admin` password** from the user menu ("Cambiar contraseña").
- Serve over HTTPS and set `COOKIE_SECURE=1` so the auth cookie is marked secure.
- Private material belongs in `study_files/` (archived DICOM), `user_files/`
  (signup photos and CVs) and `secrets/` — all outside `data/` and gitignored.
- **Never run `git add -A` in this repository.** Real DICOM files have no extension
  (`IM_0001`, bare UIDs); the ignore rules cover the known folders, but stage
  explicit paths and check `git diff --cached --name-only` first.
- **S3 archive**: the bucket must be private and encrypted at rest; objects are
  handed out only as short-lived presigned URLs. Get legal sign-off before
  uploading identifiable patient imaging to a cloud provider.

---

## License

Proprietary — SkullApp, Fundación Universitaria Navarra (UNINAVARRA),
Laboratorio de Imagen Médica.
