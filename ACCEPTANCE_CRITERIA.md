# ACCEPTANCE_CRITERIA — BIM Cloud Pipeline POC

Each criterion is testable and mapped to a verification method.

**Status legend:** ✅ live-validated · 🧪 implemented + unit-tested (mocked) ·
📝 implemented (not yet exercised against an external service).

## Functional
| # | Criterion | Verify | Status |
|---|-----------|--------|--------|
| A1 | Uploading a `.ifc` file creates a job and processes it to completion | POST /api/jobs (multipart) → status `completed` | ✅ |
| A2 | Pipeline emits `model.glb`, `model.gltf` (+ `.bin`) and `metadata.json` | download endpoints return 200 with correct content-type | ✅ |
| A3 | GLB is a valid binary glTF (viewable in Three.js GLTFLoader) | in-browser viewer renders geometry | ✅ |
| A4 | metadata.json is valid JSON with project, elements, properties, quantities, geometry stats | parse + inspect fields | ✅ |
| A5 | Elements carry GlobalId, name, category, material, property sets, quantities, containment | sample wall/slab show `Pset_*` / `Qto_*` | ✅ |
| A6 | Revit `.rvt` is recognised; without APS credentials it fails with a clear error (no sample substitution) | POST a `.rvt` → `failed` with "requires Autodesk APS credentials" | ✅ |
| A7 | Unsupported formats are rejected with a clear message | POST `.zip` → 400 | ✅ |
| A8 | One-click demo runs the bundled sample end-to-end | POST /api/demo → completed | ✅ |
| A9 | Public demo mode disables arbitrary uploads and exposes only bundled samples | `PUBLIC_DEMO_MODE=1` → `POST /api/jobs` returns 403, `/api/demo/*` works | ✅ |
| A10 | Public demo mode scopes job history to the requesting visitor | two clients (different cookies) see only their own jobs | ✅ |

## UX
| # | Criterion | Verify | Status |
|---|-----------|--------|--------|
| U1 | Dashboard shows live job list with status | poll UI | ✅ |
| U2 | Detail view shows stages, logs, downloads, API snippets | open a job | ✅ |
| U3 | 3D viewer loads the GLB and auto-frames | browser screenshot | ✅ |
| U4 | UI is responsive at 320/375/768/1280 px, no horizontal overflow | screenshot at widths | ✅ |
| U5 | Touch targets ≥ 44 px | button/dropzone styling | ✅ |
| U6 | Public demo mode shows a visible "no confidential models" warning | `PUBLIC_DEMO_MODE=1` → banner visible | ✅ |

## Non-functional
| # | Criterion | Verify | Status |
|---|-----------|--------|--------|
| N1 | No blocking console errors | browser console | ✅ |
| N2 | Pipeline is idempotent and re-runnable | run demo twice | ✅ |
| N3 | Real open-source data used (no dummy data) | samples provenance in README | ✅ |
| N4 | File-size / concurrency / rate limits enforced on job creation | exceed each limit → 413 / 429 | ✅ |
| N5 | Finished jobs/outputs are auto-expired (TTL cleanup) | `JOB_TTL_SECONDS` > 0 → old jobs removed | ✅ |

## Out of scope for POC
- **Live validation of the Autodesk APS (Model Derivative) adapter** — the
  adapter is fully implemented and unit-tested with mocks, but exercising it
  against a real APS account requires `APS_CLIENT_ID` / `APS_CLIENT_SECRET`.
- **Live validation of S3 storage** — implemented and unit-tested with mocks;
  requires live AWS credentials.
- Multi-tenant auth, billing.
- Full IFC4 geometry engines (BREP/CSG) — tessellated + extruded profiles only.
