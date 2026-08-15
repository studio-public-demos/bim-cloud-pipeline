"""FastAPI backend for the BIM Cloud Pipeline POC.

Routes:
  POST /api/jobs                     upload a .ifc/.rvt/.gltf/.glb and start processing
  POST /api/demo                     run the bundled sample IFC through the pipeline
  GET  /api/jobs                     list all jobs
  GET  /api/jobs/{id}                job detail (status, stages, logs, outputs)
  GET  /api/jobs/{id}/download/{f}   download a derivative (model.glb/.gltf/metadata.json)
  GET  /api/health                   health check
  GET  /                             dashboard (single-page UI)
"""
from __future__ import annotations

import os
import json
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import compare
import pipeline
from store import JobStore

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
SAMPLES_DIR = PROJECT_ROOT / "samples"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DOCS_DIR = PROJECT_ROOT / "docs"


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


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "bim-cloud-pipeline"}


@app.get("/api/jobs")
def list_jobs():
    return store.list()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.post("/api/jobs")
def upload_job(file: UploadFile = File(...)):
    name = file.filename or "upload.bin"
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: .ifc .rvt .gltf .glb")

    job = store.create(name, 0, ext.lstrip('.'))
    dest = UPLOADS_DIR / f"{job['id']}{ext}"
    content = file.file.read()
    with open(dest, "wb") as fh:
        fh.write(content)
    store.update(job["id"], sizeBytes=len(content))

    threading.Thread(
        target=pipeline.run_pipeline,
        args=(job["id"], str(dest), store, str(SAMPLES_DIR)),
        daemon=True,
    ).start()
    return job


@app.post("/api/demo")
def demo_job():
    return _demo("architecture")


@app.post("/api/demo/{sample}")
def demo_job_named(sample: str):
    if sample not in ("architecture", "structural"):
        raise HTTPException(404, f"unknown sample '{sample}'")
    return _demo(sample)


def _demo(sample: str):
    name = {"architecture": "Building-Architecture.ifc",
            "structural": "Building-Structural.ifc"}[sample]
    path = SAMPLES_DIR / name
    if not path.exists():
        raise HTTPException(500, f"bundled sample {name} not found")
    job = store.create(path.name, path.stat().st_size, "ifc")
    threading.Thread(
        target=pipeline.run_pipeline,
        args=(job["id"], str(path), store, str(SAMPLES_DIR)),
        daemon=True,
    ).start()
    return job


@app.get("/api/jobs/{job_id}/download/{filename}")
def download(job_id: str, filename: str):
    job = store.get(job_id)
    if not job:
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


def _load_metadata(job_id: str):
    job = store.get(job_id)
    if not job:
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
def compare_jobs(id_a: str, id_b: str):
    meta_a = _load_metadata(id_a)
    meta_b = _load_metadata(id_b)
    return compare.compare_models(meta_a, meta_b)


if DOCS_DIR.exists():
    app.mount("/guide", StaticFiles(directory=str(DOCS_DIR), html=True), name="docs")

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
