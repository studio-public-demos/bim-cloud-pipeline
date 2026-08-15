"""Autodesk Platform Services (APS) adapter — real Revit (.rvt) conversion.

Implements the APS Model Derivative flow for Revit files:

    authenticate (2-legged OAuth)
      -> create transient bucket
      -> upload the .rvt
      -> POST translate job (svf2 + gltf outputs)
      -> poll the manifest until success
      -> download the glTF derivative (obj fallback -> glb)

Requires APS_CLIENT_ID and APS_CLIENT_SECRET. When they are absent the
pipeline falls back to a bundled representative model (see pipeline.py).

NOTE: this path is production-shaped but cannot be exercised without a live
APS account. All HTTP calls are factored into small methods so they can be
unit-tested with mocks.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
import urllib.parse

BASE = "https://developer.api.autodesk.com"
AUTH_URL = f"{BASE}/authentication/v1/authenticate"
OSS_BUCKETS_URL = f"{BASE}/oss/v2/buckets"
MD_JOB_URL = f"{BASE}/modelderivative/v2/designdata/job"

SCOPES = "data:read data:write bucket:create bucket:read"


class APSAdapter:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self.client_id = client_id or os.environ.get("APS_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("APS_CLIENT_SECRET")

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # -- HTTP helpers (mockable) ------------------------------------------- #
    def _post_form(self, url, data, headers=None):
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers=headers or {})
        return urllib.request.urlopen(req, timeout=60)

    def _post_json(self, url, payload, token):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        return urllib.request.urlopen(req, timeout=60)

    def _put(self, url, data, token):
        req = urllib.request.Request(
            url,
            data=data,
            method="PUT",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(data)),
            },
        )
        return urllib.request.urlopen(req, timeout=300)

    def _get(self, url, token):
        req = urllib.request.Request(
            url, method="GET", headers={"Authorization": f"Bearer {token}"}
        )
        return urllib.request.urlopen(req, timeout=60)

    # -- APS flow ---------------------------------------------------------- #
    def authenticate(self) -> str:
        with self._post_form(AUTH_URL, {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": SCOPES,
        }) as resp:
            token = json.loads(resp.read().decode())["access_token"]
        return token

    @staticmethod
    def to_urn(object_id: str) -> str:
        return base64.urlsafe_b64encode(object_id.encode()).decode().rstrip("=")

    def convert(self, rvt_path: str, job_id: str, log) -> str:
        """Run the full Model Derivative flow; return a local .gltf path."""
        if not self.configured:
            raise RuntimeError("APS adapter not configured (set APS_CLIENT_ID/SECRET)")

        token = self.authenticate()
        log("APS: authenticated (2-legged OAuth)")

        bucket_key = f"bimcloudpoc-{job_id}-{int(time.time())}"
        with self._post_json(OSS_BUCKETS_URL, {"bucketKey": bucket_key, "policyKey": "transient"}, token) as resp:
            log(f"APS: created transient bucket {bucket_key}")

        object_name = os.path.basename(rvt_path)
        obj_url = f"{OSS_BUCKETS_URL}/{bucket_key}/objects/{urllib.parse.quote(object_name)}"
        with open(rvt_path, "rb") as fh:
            data = fh.read()
        with self._put(obj_url, data, token) as resp:
            upload = json.loads(resp.read().decode())
        object_id = upload["objectId"]
        urn = self.to_urn(object_id)
        log(f"APS: uploaded {object_name} ({len(data):,} bytes)")

        with self._post_json(MD_JOB_URL, {
            "input": {"urn": urn},
            "output": {"formats": [
                {"type": "svf2", "views": ["3d"]},
                {"type": "gltf"},
                {"type": "obj"},
            ]},
        }, token) as resp:
            job = json.loads(resp.read().decode())
        log(f"APS: translate job submitted (result={job.get('result')})")

        manifest = self._poll_manifest(urn, token, log)
        return self._download_derivative(urn, manifest, token, job_id, log)

    def _poll_manifest(self, urn: str, token: str, log, timeout: int = 900, interval: int = 8):
        manifest_url = f"{MD_JOB_URL.replace('/job', '')}/{urn}/manifest"
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._get(manifest_url, token) as resp:
                manifest = json.loads(resp.read().decode())
            status = manifest.get("status")
            progress = manifest.get("progress")
            log(f"APS: manifest status={status} progress={progress}")
            if status in ("success", "failed", "timeout"):
                if status != "success":
                    raise RuntimeError(f"APS translation failed: {status}")
                return manifest
            time.sleep(interval)
        raise TimeoutError("APS translation timed out")

    def _download_derivative(self, urn, manifest, token, job_id, log) -> str:
        derivatives = manifest.get("derivatives", [])
        # prefer gltf, else obj
        candidates = []
        for d in derivatives:
            role = str(d.get("role", ""))
            if "gltf" in role or "glb" in role:
                candidates.insert(0, d)
            elif "obj" in role or "graphics" in role:
                candidates.append(d)
        if not candidates:
            raise RuntimeError("no downloadable derivative in manifest")

        deriv = candidates[0]
        deriv_urn = deriv.get("urn")
        role = deriv.get("role", "")
        dl_url = f"{MD_JOB_URL.replace('/job', '')}/{urn}/manifest/{urllib.parse.quote(deriv_urn, safe='')}"

        out_dir = os.path.join("data", "aps", job_id)
        os.makedirs(out_dir, exist_ok=True)

        with self._get(dl_url, token) as resp:
            raw = resp.read()

        if "obj" in role:
            obj_path = os.path.join(out_dir, "model.obj")
            with open(obj_path, "wb") as fh:
                fh.write(raw)
            log("APS: downloaded OBJ derivative, converting to glb")
            import trimesh
            mesh = trimesh.load(obj_path, force="mesh")
            glb_path = os.path.join(out_dir, "model.glb")
            mesh.export(glb_path, file_type="glb")
            return glb_path

        gltf_path = os.path.join(out_dir, "model.gltf")
        with open(gltf_path, "wb") as fh:
            fh.write(raw)
        log("APS: downloaded glTF derivative")
        return gltf_path
