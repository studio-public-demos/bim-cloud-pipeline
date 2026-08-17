# Using the BIM Cloud Pipeline POC

Step-by-step guide for running the POC and using it two ways: through the
**web dashboard** (drag & drop) and through the **REST API** (for integration
into your own products).

---

## 1. Prerequisites

- **Python 3.10+** (verified on 3.14).
- Internet access (the 3D viewer loads Three.js from a CDN at runtime).
- **No BIM desktop software required** — no Revit, no Autodesk account, no IFC
  library. The POC ships a dependency-free IFC parser.

The only Python dependencies are `fastapi`, `uvicorn`, `trimesh`, `numpy`.

## 2. Install & run

```bash
# from the bim-cloud-poc folder

# (recommended) create an isolated environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# install dependencies
pip install -r requirements.txt

# start the API + dashboard
python -m uvicorn main:app --host 127.0.0.1 --port 8765 --app-dir backend
```

Then open **http://127.0.0.1:8765** in a browser.

> To listen on all interfaces (e.g. for a phone/headset on your LAN), use
> `--host 0.0.0.0` and open `http://<your-ip>:8765`.

## 3. Using the web dashboard

### 3.1 Run the bundled sample (fastest)

1. Click **“Run bundled sample IFC”**.
2. A job appears under **Processing jobs** and moves through stages:
   `Uploaded → Validated → Parsed → Geometry → Optimised → Metadata`.
3. The detail panel opens automatically showing the live **Logs**, and when the
   job completes, the **3D viewer** renders the building (drag to orbit, scroll
   to zoom, right-drag to pan).

### 3.2 Upload your own file

1. Drag a `.ifc`, `.rvt`, `.gltf`, or `.glb` file onto the dropzone, or click it
   to browse.
2. Watch the stages and logs update live.
3. When **Ready**, use the three download buttons:
   - **model.glb** — self-contained binary glTF (use this for web/AR/VR).
   - **model.gltf** — text glTF (+ a `.bin` buffer) when you need to inspect
     or diff the scene graph.
   - **metadata.json** — the structured BIM data.

### 3.3 Explore the tabs

- **Logs** — processing stages + timestamped log lines.
- **Metadata** — full `metadata.json` pretty-printed.
- **API** — ready-to-paste `curl` snippets for this exact job.

### 3.4 Compare two models

1. Run (or upload) at least two jobs — e.g. the **architecture** and
   **structural** samples.
2. In the **Compare models** card, pick model A and model B from the dropdowns
   and click **Compare**.
3. Two 3D viewers load side-by-side, and a **metadata diff** shows:
   - summary stats (elements / triangles) for each model,
   - category counts with deltas (e.g. `beam +6`, `slab −3`),
   - element-level **added / removed / changed** with material changes.

The same diff is available via the API: `GET /api/compare/{idA}/{idB}`.

## 4. Using the REST API

Base URL: `http://127.0.0.1:8765`

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/jobs` | Upload a file (`multipart/form-data`, field `file`) |
| `POST` | `/api/demo` | Run the bundled sample IFC |
| `GET`  | `/api/jobs` | List all jobs |
| `GET`  | `/api/jobs/{id}` | Job detail (status, stages, logs, outputs) |
| `GET`  | `/api/jobs/{id}/download/model.glb` | Download binary glTF |
| `GET`  | `/api/jobs/{id}/download/model.gltf` | Download glTF |
| `GET`  | `/api/jobs/{id}/download/model.bin` | Download glTF buffer |
| `GET`  | `/api/jobs/{id}/download/metadata.json` | Download structured metadata |
| `GET`  | `/api/health` | Health check |

### 4.1 Upload and poll

```bash
# upload
curl -X POST http://127.0.0.1:8765/api/jobs -F "file=@MyModel.ifc"
# -> {"id": "a1b2c3d4e5f6", "filename": "MyModel.ifc", "format": "ifc", "status": "queued", ...}

# poll until "status" is "completed" or "failed"
curl http://127.0.0.1:8765/api/jobs/a1b2c3d4e5f6
```

### 4.2 Download derivatives

```bash
JOB=a1b2c3d4e5f6
curl -o model.glb      http://127.0.0.1:8765/api/jobs/$JOB/download/model.glb
curl -o model.gltf     http://127.0.0.1:8765/api/jobs/$JOB/download/model.gltf
curl -o metadata.json  http://127.0.0.1:8765/api/jobs/$JOB/download/metadata.json
```

### 4.3 Full Python client example

```python
import json, time, urllib.request

BASE = "http://127.0.0.1:8765"

def upload(path):
    boundary = "----bim"
    with open(path, "rb") as f:
        data = f.read()
    body = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.split("/")[-1]}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/api/jobs", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req))

def wait(job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = json.load(urllib.request.urlopen(f"{BASE}/api/jobs/{job_id}"))
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.5)
    raise TimeoutError("job did not finish")

job = upload("MyModel.ifc")
done = wait(job["id"])
print(done["status"], done["summary"])
for name, url in done["outputs"].items():
    urllib.request.urlretrieve(BASE + url, f"{job['id']}_{name}")
```

## 5. Understanding the outputs

### 5.1 `model.glb` / `model.gltf`

- Units are **metres** (converted from IFC millimetres — correct for glTF and
  AR/VR).
- Each element keeps a **vertex colour** taken from its IFC material style, so
  the model is readable without textures.
- Analytical volumes (spaces/zones) and georeference helper proxies are excluded
  from the visual mesh but remain in the metadata.
- Load in any glTF viewer: Three.js, Babylon.js, `<model-viewer>`, Blender,
  Unity/Unreal, AR Quick Look, etc.

### 5.2 `metadata.json` — schema

```jsonc
{
  "schema": "bim-metadata",
  "version": "1.0",
  "project": { "globalId": "...", "name": "...", "units": { "LENGTHUNIT": "MILLI.METRE" } },
  "spatialStructure": { "sites": [], "buildings": [], "storeys": [], "spaces": [], "zones": [] },
  "elements": [
    {
      "globalId": "0OfZwWc8j9QP5uX8xPTxDH",
      "ifcType": "IFCWALL",
      "category": "wall",
      "name": "house - outer wall - house left",
      "objectType": "solidwall",
      "typeName": "IFCWALLTYPE",
      "material": "stone_sand-lime",
      "classification": null,
      "containedIn": "00 groundfloor",
      "isVirtual": false,
      "properties": {
        "Pset_WallCommon": { "IsExternal": true, "LoadBearing": false },
        "Qto_WallBaseQuantities": { "Length": 6000.0, "Area": 20.3 }
      },
      "geometry": { "vertexCount": 24, "triangleCount": 12, "bbox": null }
    }
  ],
  "stats": { "totalElements": 19, "byCategory": { "wall": 4 }, "totalTriangles": 270 }
}
```

Notes:

- `properties` maps IFC **property sets** (`Pset_*`) and **quantities**
  (`Qto_*`) to key/value pairs.
- `containedIn` resolves the element's spatial container (storey/building/space).
- `isVirtual` marks helper entities (origin/geo-reference proxies) you should
  ignore for visualisation.
- `geometry.vertices` / `triangles` are embedded for element-level access; the
  full mesh is delivered as GLB/GLTF.

## 6. Supported formats & the Revit route

| Extension | Behaviour |
|-----------|-----------|
| `.ifc` | Fully parsed: real geometry + real metadata (live-validated). |
| `.gltf` / `.glb` | Validated, normalised and re-exported through the same derivative pipeline. |
| `.rvt` | Recognised. Real conversion uses Autodesk APS (Model Derivative) — see below. |

**Revit `.rvt`:**

The canonical `.rvt` workflow is:

```
.rvt ──► Autodesk APS Model Derivative ──► IFC derivative ──► native IFC pipeline ──► GLB/GLTF + metadata.json
```

- **With credentials** — set `APS_CLIENT_ID` and `APS_CLIENT_SECRET` and the
  pipeline runs the real APS adapter (`backend/aps_adapter.py`): authenticate
  (2-legged OAuth) → create a transient bucket → upload the RVT → translate to
  an **IFC derivative** (Revit's own IFC export) → download the IFC and
  normalise it through the same native IFC pipeline.
- **Without credentials** — **demo fallback**: processes a bundled
  representative IFC and flags it clearly in the job logs and summary.

> Status note: the APS adapter is a complete implementation that is
> **unit-tested with mocks** but has **not been live-validated** — exercising
> it requires a live Autodesk APS account. See `README.md` → *Capability status*.

## 7. Cloud storage & configuration

### Environment variables

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

When the pipeline is reachable by arbitrary visitors on the internet (Render,
Hugging Face Spaces, etc.), public demo mode is **on by default**. Force it on
with `PUBLIC_DEMO_MODE=1`, or off with `PUBLIC_DEMO_MODE=0`. This:

1. **Disables arbitrary uploads** — `POST /api/jobs` returns `403`; only the
   bundled Architecture / Structural samples can be run.
2. **Scopes job history** — each visitor sees only the jobs they created (a
   per-session cookie), so unrelated visitors cannot browse the global job list,
   open others' jobs, download their outputs, or compare their models.
3. **Enforces limits** — file-size, concurrency, and rate limits.
4. **Auto-expires** jobs and outputs (TTL cleanup).
5. Shows a **visible warning** in the dashboard: never upload confidential or
   proprietary models.

### S3 cloud copies

Set the AWS variables above and every completed job additionally uploads
`model.glb`, `model.gltf`, `model.bin` and `metadata.json` to S3 under
`jobs/<id>/...`. Presigned URLs appear:

- in the dashboard's download buttons (`☁ model.glb`, etc.), and
- in the API response as `outputs.cloud`.

Without the variables, outputs remain on local disk and the pipeline behaves
identically (local download endpoints).

### Example (PowerShell)

```powershell
$env:APS_CLIENT_ID = "your-id"
$env:APS_CLIENT_SECRET = "your-secret"
$env:AWS_ACCESS_KEY_ID = "AKIA..."
$env:AWS_SECRET_ACCESS_KEY = "secret"
$env:AWS_S3_BUCKET = "my-bim-bucket"
python -m uvicorn main:app --port 8765 --app-dir backend
```

## 8. Integrating into your own product

The dashboard is just one client. Build on the API:

```js
// create a job
const fd = new FormData();
fd.append("file", fileInput.files[0]);
const job = await fetch("/api/jobs", { method: "POST", body: fd }).then(r => r.json());

// poll
while (job.status === "queued" || job.status === "processing") {
  await new Promise(r => setTimeout(r, 800));
  Object.assign(job, await fetch(`/api/jobs/${job.id}`).then(r => r.json()));
}

// feed a web/AR/VR viewer
const modelUrl = job.outputs.modelGlb;      // -> <model-viewer src=...>
const meta = await fetch(job.outputs.metadata).then(r => r.json());
```

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt`. |
| 3D viewer stays blank / "Waiting for GLB" | Job hasn't finished; check **Logs**. Requires internet for the Three.js CDN. |
| `Unsupported format '.zip'` (HTTP 400) | Only `.ifc`, `.rvt`, `.gltf`, `.glb` are accepted. |
| `.rvt` job says "demo fallback" | Expected without `APS_CLIENT_ID`/`APS_CLIENT_SECRET`. |
| Port already in use | Run with a different `--port` (e.g. `--port 9000`). |

## 10. Limitations (POC scope)

- Geometry: tessellated facesets + extruded profiles (rectangle / arbitrary
  closed / circle). Advanced BREP/CSG is out of scope.
- Suitable for: viewing, downstream web/AR/VR/digital-twin prototyping, and API
  integration.
- Not suitable for: engineering analysis or legal documentation.
- No auth/multi-tenancy/billing — that's production work, intentionally left out.
