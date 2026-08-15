# BIM Cloud Pipeline

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

## Quick start

```bash
# 1. (optional) create a venv and install
pip install -r requirements.txt

# 2. run the API + dashboard
python -m uvicorn main:app --host 127.0.0.1 --port 8765 --app-dir backend

# 3. open http://127.0.0.1:8765
```

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
  adapter** (`backend/aps_adapter.py`): authenticate → upload to a transient
  bucket → translate to SVF2 + glTF → download the glTF derivative;
- otherwise → **demo fallback**: processes a bundled representative IFC and
  flags it clearly in the logs and summary.

## Cloud storage (S3)

Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_S3_BUCKET`
(optional `AWS_REGION`) to publish each job's outputs to Amazon S3 and expose
**presigned download URLs** on the job (`outputs.cloud`) and in the dashboard.
Without these, outputs stay on local disk (`backend/storage.py`).

## Configuration (environment variables)

| Variable | Feature | Effect |
|----------|---------|--------|
| `APS_CLIENT_ID` + `APS_CLIENT_SECRET` | Real Revit conversion | Enables the APS Model Derivative route for `.rvt` |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_S3_BUCKET` | Cloud storage | Publishes outputs to S3 with presigned URLs |
| `AWS_REGION` (optional) | Cloud storage | S3 region (default `us-east-1`) |

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
