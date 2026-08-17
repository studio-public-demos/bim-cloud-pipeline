"""FastAPI backend for the BIM Cloud Pipeline POC.

Routes:
  POST /api/jobs                     upload a .ifc/.rvt/.gltf/.glb and start processing
  POST /api/demo                     run the bundled architecture sample
  POST /api/demo/{sample}            run a bundled sample (architecture | structural)
  GET  /api/jobs                     list jobs (scoped to the visitor in public demo mode)
  GET  /api/jobs/{id}                job detail (status, stages, logs, outputs)
  GET  /api/jobs/{id}/download/{f}   download a derivative (model.glb/.gltf/metadata.json)
  GET  /api/compare/{idA}/{idB}      diff two processed models
  GET  /api/health                   health check (incl. public-demo-mode + limits)
  GET  /                             dashboard (single-page UI)

Public safety (see config.py):

  - PUBLIC_DEMO_MODE disables arbitrary upload and exposes only bundled samples.
  - Job history is scoped to a per-visitor cookie so unrelated visitors cannot
    see each other's jobs.
  - File-size, concurrency, and rate limits are enforced on job creation.
  - A background thread expires old jobs/outputs (TTL cleanup).
"""
from __future__ import annotations

import os
import json
import time
import tempfile
import threading
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import compare
import pipeline
import aps_adapter
import storage
import config
from store import JobStore

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
SAMPLES_DIR = PROJECT_ROOT / "samples"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DOCS_DIR = PROJECT_ROOT / "docs"

CLIENT_COOKIE = "bim_client"
CLIENT_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _resolve_data_dir() -> Path:
    """Pick a writable directory for runtime data (jobs/outputs/uploads).

    Prefers BIM_DATA_DIR, then the repo's data/ dir, falling back to the
    system temp dir when the filesystem is read-only (e.g. cloud hosts).
    """
    env = os.environ.get("BIM_DATA_DIR")
    if env:
        return Path(env)
    candidates = [PROJECT_ROOT / "data", Path(tempfile.gettempdir()) / "bim-cloud-pipeline"]
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write_probe"
            probe.write_text("ok")
            probe.unlink()
            return cand
        except OSError:
            continue
    return candidates[-1]


DATA_DIR = _resolve_data_dir()
UPLOADS_DIR = DATA_DIR / "uploads"


def _load_env_file(path: Path):
    """Load KEY=VALUE pairs from a .env file into the environment (gitignored)."""
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file(PROJECT_ROOT / ".env")

os.makedirs(UPLOADS_DIR, exist_ok=True)

store = JobStore(str(DATA_DIR))

app = FastAPI(title="BIM Cloud Pipeline", version="0.1.0")

ALLOWED = {".ifc", ".rvt", ".gltf", ".glb"}

# --------------------------------------------------------------------------- #
# Per-visitor identity + simple in-memory rate limiting
# --------------------------------------------------------------------------- #

_rate_windows: dict[str, deque] = defaultdict(deque)


def _client_id(request: Request) -> str | None:
    return request.cookies.get(CLIENT_COOKIE)


def _set_client(response: Response, client_id: str):
    response.set_cookie(
        CLIENT_COOKIE,
        client_id,
        httponly=True,
        samesite="lax",
        max_age=CLIENT_COOKIE_MAX_AGE,
    )


def _ensure_client(request: Request, response: Response) -> str:
    cid = _client_id(request)
    if not cid:
        cid = uuid.uuid4().hex
        _set_client(response, cid)
    return cid


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request):
    """Sliding-window rate limit on job creation per client IP."""
    now = time.time()
    window = _rate_windows[_client_ip(request)]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= config.MAX_JOBS_PER_MINUTE:
        raise HTTPException(429, "Rate limit exceeded. Please wait a minute and try again.")
    window.append(now)


def _check_concurrency():
    active = sum(
        1 for j in store.list() if j["status"] in ("queued", "processing")
    )
    if active >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            429, f"Too many concurrent jobs (limit {config.MAX_CONCURRENT_JOBS}). Try again shortly."
        )


def _owns(job: dict | None, request: Request) -> bool:
    if not job:
        return False
    if not config.PUBLIC_DEMO_MODE:
        return True
    return job.get("clientId") == _client_id(request)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "bim-cloud-pipeline",
        "publicDemoMode": config.PUBLIC_DEMO_MODE,
        "limits": {
            "maxFileSizeMB": config.MAX_FILE_SIZE_MB,
            "maxConcurrentJobs": config.MAX_CONCURRENT_JOBS,
            "maxJobsPerMinute": config.MAX_JOBS_PER_MINUTE,
            "jobTtlSeconds": config.JOB_TTL_SECONDS,
        },
        "integrations": {
            "aps": aps_adapter.APSAdapter().configured,
            "s3": storage.S3Storage().configured,
        },
    }


@app.get("/api/jobs")
def list_jobs(request: Request):
    if config.PUBLIC_DEMO_MODE:
        return store.list_for_client(_client_id(request))
    return store.list()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    job = store.get(job_id)
    if not _owns(job, request):
        raise HTTPException(404, "job not found")
    return job


@app.post("/api/jobs")
def upload_job(request: Request, response: Response, file: UploadFile | None = File(None)):
    if config.PUBLIC_DEMO_MODE:
        raise HTTPException(
            403,
            "Uploads are disabled in public demo mode. Run the bundled Architecture "
            "or Structural sample instead.",
        )
    if file is None:
        raise HTTPException(400, "No file provided. Upload a .ifc/.rvt/.gltf/.glb file.")

    name = file.filename or "upload.bin"
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: .ifc .rvt .gltf .glb")

    _check_rate_limit(request)
    _check_concurrency()

    content = file.file.read()
    if len(content) > config.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            413,
            f"File too large ({len(content)} bytes). Limit is {config.MAX_FILE_SIZE_MB} MB.",
        )

    client_id = _ensure_client(request, response)
    job = store.create(name, len(content), ext.lstrip('.'), client_id=client_id)
    dest = UPLOADS_DIR / f"{job['id']}{ext}"
    with open(dest, "wb") as fh:
        fh.write(content)

    threading.Thread(
        target=pipeline.run_pipeline,
        args=(job["id"], str(dest), store, str(SAMPLES_DIR)),
        daemon=True,
    ).start()
    return job


@app.post("/api/demo")
def demo_job(request: Request, response: Response):
    return _demo("architecture", request, response)


@app.post("/api/demo/{sample}")
def demo_job_named(sample: str, request: Request, response: Response):
    if sample not in ("architecture", "structural"):
        raise HTTPException(404, f"unknown sample '{sample}'")
    return _demo(sample, request, response)


def _demo(sample: str, request: Request, response: Response):
    _check_rate_limit(request)
    _check_concurrency()
    name = {"architecture": "Building-Architecture.ifc",
            "structural": "Building-Structural.ifc"}[sample]
    path = SAMPLES_DIR / name
    if not path.exists():
        raise HTTPException(500, f"bundled sample {name} not found")
    client_id = _ensure_client(request, response)
    job = store.create(path.name, path.stat().st_size, "ifc", client_id=client_id)
    threading.Thread(
        target=pipeline.run_pipeline,
        args=(job["id"], str(path), store, str(SAMPLES_DIR)),
        daemon=True,
    ).start()
    return job


@app.get("/api/jobs/{job_id}/download/{filename}")
def download(job_id: str, filename: str, request: Request):
    job = store.get(job_id)
    if not _owns(job, request):
        raise HTTPException(404, "job not found")
    safe = {
        "model.glb", "model.gltf", "model.bin", "metadata.json",
    }
    if filename not in safe:
        raise HTTPException(400, "unknown derivative")
    path = Path(store.output_dir(job_id)) / filename
    if not path.exists():
        raise HTTPException(404, "derivative not available")
    return FileResponse(str(path), filename=filename)


def _load_metadata(job_id: str, request: Request):
    job = store.get(job_id)
    if not _owns(job, request):
        raise HTTPException(404, f"job {job_id} not found")
    path = Path(store.output_dir(job_id)) / "metadata.json"
    if not path.exists():
        raise HTTPException(404, "metadata not available for this job")
    with open(path, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["_jobId"] = job["id"]
    meta["_filename"] = job["filename"]
    return meta


@app.get("/api/compare/{id_a}/{id_b}")
def compare_jobs(id_a: str, id_b: str, request: Request):
    meta_a = _load_metadata(id_a, request)
    meta_b = _load_metadata(id_b, request)
    return compare.compare_models(meta_a, meta_b)


# --------------------------------------------------------------------------- #
# TTL cleanup (background)
# --------------------------------------------------------------------------- #

def _cleanup_loop():
    while True:
        time.sleep(config.CLEANUP_INTERVAL_SECONDS)
        try:
            removed = store.cleanup(config.JOB_TTL_SECONDS)
            if removed:
                print(f"[cleanup] expired {removed} job(s)", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[cleanup] error: {exc}", flush=True)


threading.Thread(target=_cleanup_loop, daemon=True).start()


if DOCS_DIR.exists():
    app.mount("/guide", StaticFiles(directory=str(DOCS_DIR), html=True), name="docs")

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
