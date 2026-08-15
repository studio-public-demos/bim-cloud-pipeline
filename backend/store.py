"""Job store with JSON persistence for the BIM Cloud Pipeline POC."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

STAGES = [
    "uploaded",
    "validated",
    "parsed",
    "geometry",
    "optimized",
    "metadata",
]


class JobStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.jobs_dir = os.path.join(base_dir, "jobs")
        self.outputs_dir = os.path.join(base_dir, "outputs")
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.outputs_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs = {}
        self._load_existing()

    def _load_existing(self):
        for name in os.listdir(self.jobs_dir):
            path = os.path.join(self.jobs_dir, name, "job.json")
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as fh:
                        job = json.load(fh)
                    self._jobs[job["id"]] = job
                except Exception:
                    pass

    def create(self, filename: str, size_bytes: int, file_format: str) -> dict:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        job = {
            "id": job_id,
            "filename": filename,
            "format": file_format,
            "sizeBytes": size_bytes,
            "status": "queued",
            "progress": 0,
            "createdAt": now,
            "updatedAt": now,
            "logs": [],
            "stages": [],
            "outputs": {},
            "summary": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._persist(job)
        return job

    def get(self, job_id: str):
        return self._jobs.get(job_id)

    def list(self):
        jobs = sorted(self._jobs.values(), key=lambda j: -j["createdAt"])
        return jobs

    def log(self, job_id: str, message: str):
        with self._lock:
            job = self._jobs[job_id]
            job["logs"].append(f"[{time.strftime('%H:%M:%S')}] {message}")
            job["updatedAt"] = time.time()
            self._persist(job)

    def stage(self, job_id: str, name: str, status: str, message: str = ""):
        with self._lock:
            job = self._jobs[job_id]
            job["stages"] = [s for s in job["stages"] if s["name"] != name]
            job["stages"].append({"name": name, "status": status, "message": message})
            job["updatedAt"] = time.time()
            self._persist(job)

    def update(self, job_id: str, **fields):
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)
            job["updatedAt"] = time.time()
            self._persist(job)

    def output_dir(self, job_id: str) -> str:
        d = os.path.join(self.outputs_dir, job_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _persist(self, job: dict):
        d = os.path.join(self.jobs_dir, job["id"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "job.json"), "w", encoding="utf-8") as fh:
            json.dump(job, fh, ensure_ascii=False, indent=2)
