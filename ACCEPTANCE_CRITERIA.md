# ACCEPTANCE_CRITERIA — BIM Cloud Pipeline POC

Each criterion is testable and mapped to a verification method.

## Functional
| # | Criterion | Verify |
|---|-----------|--------|
| A1 | Uploading a `.ifc` file creates a job and processes it to completion | POST /api/jobs (multipart) → status `completed` |
| A2 | Pipeline emits `model.glb`, `model.gltf` (+ `.bin`) and `metadata.json` | download endpoints return 200 with correct content-type |
| A3 | GLB is a valid binary glTF (viewable in Three.js GLTFLoader) | in-browser viewer renders geometry |
| A4 | metadata.json is valid JSON with project, elements, properties, quantities, geometry stats | parse + inspect fields |
| A5 | Elements carry GlobalId, name, category, material, property sets, quantities, containment | sample wall/slab show `Pset_*` / `Qto_*` |
| A6 | Revit `.rvt` is recognised; without APS credentials it uses the documented demo fallback | POST a `.rvt` → completed with fallback note |
| A7 | Unsupported formats are rejected with a clear message | POST `.zip` → 400 |
| A8 | One-click demo runs the bundled sample end-to-end | POST /api/demo → completed |

## UX
| # | Criterion | Verify |
|---|-----------|--------|
| U1 | Dashboard shows live job list with status | poll UI |
| U2 | Detail view shows stages, logs, downloads, API snippets | open a job |
| U3 | 3D viewer loads the GLB and auto-frames | browser screenshot |
| U4 | UI is responsive at 320/375/768/1280 px, no horizontal overflow | screenshot at widths |
| U5 | Touch targets ≥ 44 px | button/dropzone styling |

## Non-functional
| # | Criterion | Verify |
|---|-----------|--------|
| N1 | No blocking console errors | browser console |
| N2 | Pipeline is idempotent and re-runnable | run demo twice |
| N3 | Real open-source data used (no dummy data) | samples provenance in README |

## Out of scope for POC
- Live Autodesk APS (Forge/Model Derivative) integration — stubbed, requires
  `APS_CLIENT_ID` / `APS_CLIENT_SECRET`.
- Multi-tenant auth, billing, cloud storage (S3/GCS).
- Full IFC4 geometry engines (BREP/CSG) — tessellated + extruded profiles only.
