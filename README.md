# BIM Cloud Pipeline

[![CI](https://github.com/studio-public-demos/bim-cloud-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/studio-public-demos/bim-cloud-pipeline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)

Upload **Revit / IFC** files, process them in the cloud, and download
**GLB / GLTF** 3D models + **structured metadata JSON** for web, mobile,
AR/VR and digital-twin applications.

> The value is not just "convert BIM to 3D". It is making BIM data *usable*
> where direct Revit/IFC support is heavy or unavailable.

This is a full-stack reference implementation — a working FastAPI backend with a
dependency-free IFC parser, a mobile-first dashboard, a Three.js 3D viewer, a
multi-model compare view, and credential-gated adapters for real Revit
conversion (Autodesk APS) and S3 cloud storage. It ships with **real IFC sample
data** (buildingSMART) and an automated test suite.

**Documentation:**
- [USAGE.md](USAGE.md) — full how-to guide: install, dashboard walkthrough,
  REST API, output schema, integration examples, troubleshooting.
- **Browsable docs:** [studio-public-demos.github.io/bim-cloud-pipeline](https://studio-public-demos.github.io/bim-cloud-pipeline/) —
  usage guide, architecture (with diagrams), product brief, and acceptance
  criteria, deployed to GitHub Pages.

## Quick start

```bash
# 1. (optional) create a venv and install
pip install -r requirements.txt

# 2. run the API + dashboard
python -m uvicorn main:app --host 127.0.0.1 --port 8765 --app-dir backend

# 3. open http://127.0.0.1:8765
```

## Deployment (live demo)

The pipeline needs a Python backend (it cannot run on static hosting such as
GitHub Pages). Two easy options:

**Hugging Face Spaces (Docker)** — free, instant public URL, secrets as env vars:

1. On [huggingface.co](https://huggingface.co/new-space), create a new **Space**
   with **Docker** as the SDK.
2. Point it at this repo (or upload the files) — the included `Dockerfile`
   listens on port 7860, which HF Spaces requires.
3. In **Settings → Secrets**, add:
   - `PUBLIC_DEMO_MODE=1` (required for any public deployment — disables uploads, scopes job history per visitor)
   - `APS_CLIENT_ID` and `APS_CLIENT_SECRET` (for real Revit conversion)
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET` (optional, S3)
4. The Space builds and serves the app at `https://<user>-<space>.hf.space`.

**Render** — alternative Python host. Use the included `render.yaml` blueprint
(or `Deploy to Render`), then set the same environment variables in the
dashboard.

> Note: free tiers sleep after inactivity (cold start ~1 min) and use ephemeral
> storage, so jobs/outputs don't survive restarts — fine for a demo. Keep the
> APS **secret** as a server-side env var; never commit it or put it in the
> frontend.

## What it does

| Step | Detail |
|------|--------|
| Upload | `.ifc` `.rvt` `.gltf` `.glb` via drag-and-drop or REST |
| Process | parse BIM geometry + semantics, build optimised triangle mesh |
| Track | live job status, stage progress, processing logs |
| Deliver | `model.glb`, `model.gltf` + `.bin`, `metadata.json` |

## API

```
POST /api/jobs                     upload a file (multipart "file")
POST /api/demo                     run the bundled architecture sample
POST /api/demo/structural          run the bundled structural sample
GET  /api/jobs                     list jobs
GET  /api/jobs/{id}                job detail (status, stages, logs, outputs)
GET  /api/jobs/{id}/download/model.glb      binary glTF
GET  /api/jobs/{id}/download/model.gltf     glTF (+ .bin)
GET  /api/jobs/{id}/download/metadata.json  structured BIM metadata
GET  /api/compare/{idA}/{idB}      diff two processed models
GET  /api/health                   health check
```

Example:

```bash
curl -X POST http://127.0.0.1:8765/api/jobs -F "file=@model.ifc"
curl http://127.0.0.1:8765/api/jobs/<id>
curl -o model.glb http://127.0.0.1:8765/api/jobs/<id>/download/model.glb
curl http://127.0.0.1:8765/api/compare/<idA>/<idB>
```

## Architecture

```
frontend (dashboard) ──► FastAPI (/api/jobs ...)
                              │
                              ▼
                     pipeline.run_pipeline()
                       ├─ ifc_parser  (STEP tokenizer → entities → semantics)
                       ├─ glb_builder (trimesh → model.glb / model.gltf)
                       └─ metadata.json (project, elements, propsets, quantities)
```

- `backend/ifc_parser.py` — dependency-free IFC (ISO-10303-21) parser extracting
  spatial structure, elements, property sets, quantities, materials,
  classification, and tessellated/extruded geometry with placements.
- `backend/glb_builder.py` — converts the extracted model (mm → m) into GLB/GLTF
  with per-element vertex colours.
- `backend/pipeline.py` — staged, logged processing with format routing.
- `backend/store.py` — JSON-backed job store.
- `frontend/` — mobile-first dashboard with a Three.js GLB viewer.

## Revit (.rvt) route

Native `.rvt` parsing requires Autodesk APS (Model Derivative). The pipeline
detects `.rvt` and:

- if `APS_CLIENT_ID` / `APS_CLIENT_SECRET` are set → runs the **real APS
  adapter** (`backend/aps_adapter.py`): authenticate (2-legged OAuth) → upload
  to a transient bucket → translate to an **IFC derivative** (Revit's own IFC
  export) → download the IFC → feed it through the **native IFC pipeline**
  (`ifc_parser` + `glb_builder`) to produce GLB/GLTF + metadata;
- otherwise → **demo fallback**: processes a bundled representative IFC and
  flags it clearly in the logs and summary.

Canonical `.rvt` workflow:

```
.rvt ──► Autodesk APS Model Derivative ──► IFC derivative ──► native IFC pipeline ──► GLB/GLTF + metadata.json
```

## Cloud storage (S3)

Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_S3_BUCKET`
(optional `AWS_REGION`) to publish each job's outputs to Amazon S3 and expose
**presigned download URLs** on the job (`outputs.cloud`) and in the dashboard.
Without these, outputs stay on local disk (`backend/storage.py`).

## Configuration (environment variables)

| Variable | Feature | Effect |
|----------|---------|--------|
| `PUBLIC_DEMO_MODE` | Public safety | `1` disables uploads, exposes only bundled samples, scopes job history per visitor |
| `MAX_FILE_SIZE_MB` | Upload limit | Max upload size in MB (default `50`) |
| `MAX_CONCURRENT_JOBS` | Concurrency limit | Max active jobs (default `4`) |
| `MAX_JOBS_PER_MINUTE` | Rate limit | Max job creations per minute per IP (default `10`) |
| `JOB_TTL_SECONDS` | TTL cleanup | Auto-delete finished jobs/outputs after N seconds (default `3600`; `0` disables) |
| `APS_CLIENT_ID` + `APS_CLIENT_SECRET` | Real Revit conversion | Enables the APS Model Derivative route for `.rvt` |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_S3_BUCKET` | Cloud storage | Publishes outputs to S3 with presigned URLs |
| `AWS_REGION` (optional) | Cloud storage | S3 region (default `us-east-1`) |

### Public demo mode

Public demo mode is **on by default on hosted platforms** (Render, Hugging Face
Spaces, etc.) and **off by default locally**. Set `PUBLIC_DEMO_MODE=1` to force
it on, or `PUBLIC_DEMO_MODE=0` to force it off. It:

1. **Disables arbitrary uploads** (`POST /api/jobs` → 403). Only the bundled
   Architecture and Structural samples can be run.
2. **Scopes job history** to the requesting visitor (per-session cookie), so
   unrelated visitors cannot see each other's jobs, downloads, or comparisons.
3. **Enforces limits** (file size, concurrency, rate) and **TTL cleanup**
   (finished jobs/outputs are deleted automatically).
4. Shows a **visible warning** in the dashboard to never upload confidential
   models.

Always keep `APS_CLIENT_ID` / `APS_CLIENT_SECRET` and AWS credentials as
server-side secrets; never commit them or expose them in the frontend.

## Capability status

This section distinguishes what is *implemented* vs *mocked/unit-tested* vs
*live-validated*, so the claim "it works" is precise.

| Capability | Status |
|-----------|--------|
| IFC → GLB/GLTF + metadata (native parser) | **Live-validated** — real buildingSMART IFC4 samples processed end-to-end (Architecture: 19 elements → 270-triangle GLB, ~17 KB; Structural: 18 elements → 712-triangle GLB, ~43 KB) |
| glTF/GLB normalisation | **Live-validated** — validated and re-exported through the derivative pipeline |
| Multi-model compare (metadata diff) | **Live-validated** — Architecture vs Structural: 4 common / 14 added / 15 removed |
| Job tracking, downloads, REST API | **Live-validated** — exercised via the dashboard and `curl` |
| Responsive dashboard + Three.js viewer | **Live-validated** — 320/375/768/1280 px, WebGL renders both samples |
| Revit `.rvt` → APS Model Derivative | **Implemented + unit-tested (mocked)** — real adapter code, verified with mocks; *not live-validated* (requires a live APS account) |
| Revit `.rvt` demo fallback (no credentials) | **Implemented** — deterministic substitute of a bundled representative IFC, clearly flagged |
| S3 cloud storage (presigned URLs) | **Implemented + unit-tested (mocked)** — *not live-validated* (requires live AWS credentials); falls back to local disk |

## Sample data

`samples/Building-Architecture.ifc` and `samples/Building-Structural.ifc` — real
IFC4 samples (single-family house, architectural + structural discipline views)
from the buildingSMART [Sample-Test-Files](https://github.com/buildingSMART/Sample-Test-Files)
repository, licensed for open use. No dummy data.

## Notes / limitations

- Fidelity: illustrative / functional. Geometry covers tessellated facesets and
  extruded profiles (rectangle / arbitrary closed / circle); advanced BREP/CSG
  is out of scope.
- Suitable for: viewing, downstream web/AR/VR/twin prototyping, API integration.
- Not suitable for: engineering analysis or legal documentation.
