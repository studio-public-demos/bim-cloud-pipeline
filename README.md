# BIM Cloud Pipeline

[![CI](https://github.com/studio-public-demos/bim-cloud-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/studio-public-demos/bim-cloud-pipeline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)

> **Turn IFC / Revit-derived BIM into optimized GLB/GLTF 3D assets and structured metadata for web, mobile, XR and digital-twin applications.**

- **[Watch Demo](#reproduce-the-demo)** · **[Interactive Showcase](https://studio-public-demos.github.io/bim-cloud-pipeline-showcase/)** · **[Quick Start](#try-it-yourself)** · **[Architecture](#architecture)** · **[API](#api)** · **[Limitations](#limitations)** · **[Built with NebulaCloud Studio](#built-with-nebulacloud-studio)**

---

## What this is

A **proof-of-concept / reference implementation** demonstrating BIM interoperability:
take BIM input, run it through a cloud-style processing pipeline, and produce
application-ready outputs — optimized **3D geometry** (GLB/GLTF) and **structured
BIM metadata** (JSON) — plus a REST API, an interactive 3D viewer, and a
side-by-side **model comparison** view.

## What this is not

It is **not**:

- a replacement for Revit or any BIM authoring tool
- an engineering-analysis or structural-simulation application
- a contractual BIM validation / clash-detection system
- a production document-management or multi-tenant SaaS platform
- a production-deployment reference (no auth, billing, durable queues, tenant storage)

The core capability being demonstrated is **not** "Revit → GLB". It is:

> **Transforming BIM geometry and semantics into application-ready 3D assets, structured data and APIs for web, mobile, XR and digital-twin workflows.**

## Canonical workflow

IFC is the primary open workflow. Revit is an optional ingestion adapter.

```text
IFC ───────────────────────────────┐
                                   │
RVT → optional Autodesk APS → IFC ─┤
                                   ▼
                         BIM Cloud Pipeline
                                   │
                    geometry + BIM semantics
                                   │
                  ┌────────────────┼────────────────┐
                  ▼                ▼                ▼
              GLB/GLTF      metadata.json       REST API
                  │                │                │
                  └────────────────┼────────────────┘
                                   ▼
                Web · Mobile · AR/VR/XR · Digital Twin
```

## Try it yourself

```bash
git clone https://github.com/studio-public-demos/bim-cloud-pipeline.git
cd bim-cloud-pipeline

python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8765 --app-dir backend
```

Then open **http://127.0.0.1:8765**.

## Reproduce the demo

The exact sample models shown in the recorded demonstration are bundled in this
repository — no downloads needed.

1. Click **▶ Run architecture sample** — the job advances through
   `Uploaded → Validated → Parsed → Geometry → Optimized → Metadata`.
2. Inspect the generated **3D model** (drag to orbit, scroll to zoom).
3. Open the **Metadata** tab and browse elements (IFC type, GlobalId, category, material).
4. Download **model.glb** / **model.gltf** / **metadata.json**.
5. Click **▶ Run structural sample**.
6. In **Compare models**, pick Architecture vs Structural and click **Compare** —
   two 3D viewers render side-by-side plus a metadata diff.

## What it does

| Step | Detail |
|------|--------|
| Upload | `.ifc` `.rvt` `.gltf` `.glb` via drag-and-drop or REST |
| Process | parse BIM geometry + semantics, build optimized triangle mesh |
| Track | live job status, stage progress, processing logs |
| Deliver | `model.glb`, `model.gltf` (+ `.bin`), `metadata.json` |

## Outputs explained

**`model.glb` / `model.gltf`** — the lightweight visual/geometry representation.
Optimized for web, mobile, Three.js, game engines, AR/VR/XR and digital-twin
visualization. Units are metres (glTF standard), with per-element material colours.

**`metadata.json`** — the structured semantic representation: GlobalId, IFC type,
category, material, spatial containment, property sets (`Pset_*`), quantities
(`Qto_*`) and geometry statistics.

> **The GLB tells an application what the building looks like. The metadata tells it what the building means.**

## Model comparison

Running two models through the pipeline enables side-by-side comparison — the
Architecture sample vs the Structural sample of the same building. The diff shows
element/category counts, and added / removed / changed elements, demonstrating
downstream workflows such as BIM coordination, design-revision intelligence,
automated QA, change detection and digital-twin synchronization.

## API

```
POST /api/jobs                     upload a file (multipart "file")
POST /api/demo                     run the bundled architecture sample
POST /api/demo/structural          run the bundled structural sample
GET  /api/jobs                     list jobs (scoped per visitor in public demo mode)
GET  /api/jobs/{id}                job detail (status, stages, logs, outputs)
GET  /api/jobs/{id}/download/model.glb      binary glTF
GET  /api/jobs/{id}/download/model.gltf     glTF (+ .bin)
GET  /api/jobs/{id}/download/metadata.json  structured BIM metadata
GET  /api/compare/{idA}/{idB}      diff two processed models
GET  /api/health                   health check
```

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
- `backend/compare.py` — metadata diff for the compare view.
- `frontend/` — mobile-first dashboard with a Three.js GLB viewer.

## Revit (.rvt) route and quota strategy

> **The Revit ingestion path is implemented as a credential-gated Autodesk Platform Services adapter. It translates RVT to an IFC derivative, after which the native BIM pipeline processes the IFC into GLB/GLTF and structured metadata. The adapter is code-complete and unit-tested/mocked, but live RVT processing depends on Autodesk APS credentials, quotas and service availability.**

```text
RVT
↓
Autodesk APS (Model Derivative)
↓
IFC derivative
↓
Native BIM Cloud Pipeline
↓
GLB/GLTF + metadata.json
```

Autodesk APS Model Derivative has limited quota and must **not** be consumed by
anonymous public visitors. Therefore:

- `ALLOW_RVT_UPLOAD=false` by default — live `.rvt` uploads are disabled with a
  clear message pointing to IFC / bundled samples / local BYOC use.
- **BYOC** (bring your own credentials) is supported for local and self-hosted
  use: set `APS_CLIENT_ID` + `APS_CLIENT_SECRET` and `ALLOW_RVT_UPLOAD=1`.
- There is **no** browser form to submit APS secrets — they are server-side only.

## Configuration (environment variables)

| Variable | Feature | Effect |
|----------|---------|--------|
| `PUBLIC_DEMO_MODE` | Public safety | `1` scopes job history per visitor + confidential-data warning (auto-on hosted) |
| `DISABLE_UPLOADS` | Public safety | `1` samples-only mode. Off by default — uploads enabled |
| `ALLOW_RVT_UPLOAD` | Revit route | `1` enables live `.rvt` uploads via APS. **Off by default** (quota) |
| `MAX_FILE_SIZE_MB` | Upload limit | Max upload size in MB (default `20`) |
| `MAX_CONCURRENT_JOBS` | Concurrency limit | Max active jobs (default `1`) |
| `MAX_JOBS_PER_MINUTE` | Rate limit | Max job creations per minute per IP (default `10`) |
| `JOB_TTL_SECONDS` | TTL cleanup | Auto-delete finished jobs/outputs after N seconds (default `3600`; `0` disables) |
| `APS_CLIENT_ID` + `APS_CLIENT_SECRET` | Real Revit conversion | Enables the APS route for `.rvt` (BYOC) |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_S3_BUCKET` | Cloud storage | Publishes outputs to S3 with presigned URLs (optional) |

## Deployment

The pipeline needs a Python backend (it cannot run on static hosting such as
GitHub Pages).

**Hugging Face Spaces (Docker)** — the recommended host for a public demo: the
free tier provides generous memory for processing. The included `Dockerfile`
listens on port 7860. Create a Space with **Docker** SDK, point it at this repo,
and set secrets under **Settings → Secrets**.

**Render** — use the included `render.yaml` blueprint. Note the free tier's
~512 MB can be tight for large models; the POC defaults (`MAX_CONCURRENT_JOBS=1`,
`MAX_FILE_SIZE_MB=20`, lazy-loaded heavy libraries) are tuned to keep memory bounded.

> The hosted demo is **supplementary** to the local run. Free tiers sleep after
> inactivity (cold start ~1 min) and use ephemeral storage.

## Capability status

| Capability | Status |
|-----------|--------|
| IFC → GLB/GLTF + metadata (native parser) | **Live-validated** — buildingSMART IFC4 samples end-to-end |
| glTF/GLB normalisation | **Live-validated** |
| Multi-model compare (metadata diff) | **Live-validated** — 4 common / 14 added / 15 removed |
| Job tracking, downloads, REST API | **Live-validated** |
| Responsive dashboard + Three.js viewer | **Live-validated** — 320/375/768/1280 px |
| Revit `.rvt` → Autodesk APS | **Implemented + unit-tested (mocked)** — external-service-dependent (credentials/quota); not live-validated |
| S3 cloud storage | **Implemented + unit-tested (mocked)** — external-service-dependent; falls back to local disk |

## Sample data

`samples/Building-Architecture.ifc` and `samples/Building-Structural.ifc` — real
IFC4 samples (single-family house, architectural + structural discipline views)
from the buildingSMART [Sample-Test-Files](https://github.com/buildingSMART/Sample-Test-Files)
repository, licensed for open use. No dummy data.

## Limitations

- **Fidelity:** illustrative / functional. Geometry covers tessellated facesets and
  extruded profiles (rectangle / arbitrary closed / circle); advanced BREP/CSG is
  out of scope.
- **Suitable for:** viewing, downstream web/AR/VR/digital-twin prototyping, API
  integration, and model comparison.
- **Not suitable for:** engineering analysis, contractual validation, or legal
  documentation.
- Auth, multi-tenancy, billing, durable queues and tenant storage are intentionally
  out of scope for this POC.

## Built with NebulaCloud Studio

This reference application was designed, built, tested and deployed with
[NebulaCloud Studio](https://nebulacloud.studio) — as one example of Studio taking
a domain engineering requirement (BIM interoperability) to a working application.

## License

[MIT](LICENSE) — fork it, run it, build on it.
