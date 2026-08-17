# PRODUCT_BRIEF — BIM Cloud Pipeline

## Objective
A proof-of-concept (POC) for a cloud BIM conversion pipeline that lets BIM/VDC
teams upload **Revit (`.rvt`)** and **IFC (`.ifc`)** files, run cloud processing
jobs, and download **optimised GLB/GLTF 3D models** plus **structured BIM metadata
JSON** — making BIM data consumable on web, mobile, AR/VR, XR and digital-twin
applications where direct Revit/IFC support is heavy or unavailable.

## Problem
BIM models are locked inside heavyweight, desktop-bound formats. Downstream
consumers (web viewers, AR/VR headsets, digital twins, real-time AEC apps)
need lightweight, runtime-friendly 3D assets plus queryable metadata. There is
no single, simple pipeline that delivers both.

## Solution
A single REST pipeline that:
1. **Upload** — accepts `.ifc`, `.rvt`, `.gltf`, `.glb` via dashboard or API.
2. **Process** — parses BIM geometry + semantics and builds derivatives.
3. **Track** — live job status, stage progress, and processing logs.
4. **Deliver** — `model.glb` (self-contained binary), `model.gltf` + `.bin`,
   and `metadata.json` (structured BIM data) with download endpoints.

## Target users & roles
- **BIM / VDC teams** — publish models for review and downstream use.
- **Construction-technology developers** — build web/mobile BIM apps on APIs.
- **AR/VR / XR teams** — get lightweight glTF assets for headsets & mobile.
- **Digital-twin teams** — feed geometry + metadata into twin platforms.

## Primary journeys
1. Upload an IFC file → watch stages progress → download GLB + metadata JSON.
2. Run the bundled sample (one click) → inspect the 3D viewer + structured JSON.
3. Call the REST API to integrate the pipeline into a custom product.

## Data (sample, open-source)
- `samples/Building-Architecture.ifc` — real IFC4 sample from the
  buildingSMART `Sample-Test-Files` repository (PCERT sample scene), a
  single-family house with walls, slabs, roof, furniture, spaces, property
  sets, quantities, materials and classification.

## Acceptance criteria (summary — see ACCEPTANCE_CRITERIA.md)
- Upload + process `.ifc` → real GLB + GLTF + metadata JSON.
- Job status, stage progress and logs are live.
- 3D model is viewable in-browser; metadata is structured and queryable.
- Revit `.rvt` route is clearly handled: real Autodesk APS adapter
  (implemented, unit-tested with mocks, not yet live-validated); without APS
  credentials the job fails with a clear error (an uploaded file is never
  replaced by a bundled sample).
- Responsive UI; no blocking console errors.

## Capability status

| Capability | Status |
|-----------|--------|
| IFC → GLB/GLTF + metadata | **Live-validated** (real buildingSMART samples) |
| glTF/GLB normalisation | **Live-validated** |
| Multi-model compare | **Live-validated** (4 common / 14 added / 15 removed) |
| Dashboard + viewer | **Live-validated** |
| Revit `.rvt` → APS | **Implemented + unit-tested (mocked)** — not live-validated (needs live APS account) |
| S3 storage | **Implemented + unit-tested (mocked)** — not live-validated (needs live AWS credentials) |
