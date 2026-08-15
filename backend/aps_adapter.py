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
AUTH_URL = f"{BASE}/authentication/v2/token"
OSS_BUCKETS_URL = f"{BASE}/oss/v2/buckets"
MD_JOB_URL = f"{BASE}/modelderivative/v2/designdata/job"

SCOPES = "data:read data:write data:create bucket:create bucket:read"


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

    def _get(self, url, token):
        req = urllib.request.Request(
            url, method="GET", headers={"Authorization": f"Bearer {token}"}
        )
        return urllib.request.urlopen(req, timeout=60)

    def _put_s3(self, url, data):
        """PUT to a pre-signed S3 URL (no APS auth header)."""
        req = urllib.request.Request(
            url,
            data=data,
            method="PUT",
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(data)),
            },
        )
        return urllib.request.urlopen(req, timeout=300)

    def _upload_object(self, bucket_key, object_name, data, token) -> str:
        """Upload via the signed S3 workflow and return the objectId.

        APS deprecated the direct PUT upload; files must now go through a
        three-step signed-S3 flow (get URLs -> PUT to S3 -> complete).
        """
        obj_path = urllib.parse.quote(object_name)
        base = f"{OSS_BUCKETS_URL}/{bucket_key}/objects/{obj_path}"

        # step 1: request signed upload URLs
        with self._get(f"{base}/signeds3upload?parts=1", token) as resp:
            su = json.loads(resp.read().decode())

        # step 2: PUT the bytes to the signed S3 URL, capture the ETag
        with self._put_s3(su["urls"][0], data) as resp:
            etag = (resp.headers.get("ETag") or resp.headers.get("Etag") or "") \
                .strip().strip('"')

        # step 3: complete the upload
        with self._post_json(f"{base}/signeds3upload", {
            "uploadKey": su["uploadKey"],
            "size": len(data),
            "contentType": "application/octet-stream",
            "eTags": [etag],
        }, token) as resp:
            result = json.loads(resp.read().decode())

        return result["objectId"]

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
        """Run the Model Derivative flow; return a local .ifc path.

        Revit files are translated to IFC (Revit's own export), which the
        native IFC parser then converts to GLB/GLTF + structured metadata.
        """
        if not self.configured:
            raise RuntimeError("APS adapter not configured (set APS_CLIENT_ID/SECRET)")

        token = self.authenticate()
        log("APS: authenticated (2-legged OAuth)")

        bucket_key = f"bimcloudpoc-{job_id}-{int(time.time())}"
        with self._post_json(OSS_BUCKETS_URL, {"bucketKey": bucket_key, "policyKey": "transient"}, token) as resp:
            log(f"APS: created transient bucket {bucket_key}")

        object_name = os.path.basename(rvt_path)
        with open(rvt_path, "rb") as fh:
            data = fh.read()
        object_id = self._upload_object(bucket_key, object_name, data, token)
        urn = self.to_urn(object_id)
        log(f"APS: uploaded {object_name} ({len(data):,} bytes)")

        with self._post_json(MD_JOB_URL, {
            "input": {"urn": urn},
            "output": {"formats": [{"type": "ifc"}]},
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
                    detail = ""
                    for d in manifest.get("derivatives", []):
                        for msg in d.get("messages", []):
                            if msg.get("type") == "error":
                                detail = msg.get("code") or str(msg.get("message"))
                    raise RuntimeError(
                        f"APS translation failed: {status}"
                        + (f" ({detail})" if detail else "")
                    )
                return manifest
            time.sleep(interval)
        raise TimeoutError("APS translation timed out")

    def _download_derivative(self, urn, manifest, token, job_id, log) -> str:
        """Download the IFC derivative and return its local path."""
        out_dir = os.path.join("data", "aps", job_id)
        os.makedirs(out_dir, exist_ok=True)

        target = None
        # prefer the "ifc" output type's resource child
        for d in manifest.get("derivatives", []):
            if d.get("outputType") != "ifc":
                continue
            for c in d.get("children", []):
                role = str(c.get("role", "")).lower()
                if c.get("type") == "resource" and ("ifc" in role or not role):
                    target = c
                    break
            if target:
                break
        # fallback: first resource child of any successful derivative
        if not target:
            for d in manifest.get("derivatives", []):
                for c in d.get("children", []):
                    if c.get("type") == "resource" and c.get("urn"):
                        target = c
                        break
                if target:
                    break

        if not target:
            raise RuntimeError("no downloadable derivative found in manifest")

        deriv_urn = target["urn"]
        dl_url = (f"{BASE}/modelderivative/v2/designdata/{urn}/manifest/"
                  f"{urllib.parse.quote(deriv_urn, safe='')}")
        with self._get(dl_url, token) as resp:
            raw = resp.read()

        ifc_path = os.path.join(out_dir, "model.ifc")
        with open(ifc_path, "wb") as fh:
            fh.write(raw)
        log(f"APS: downloaded IFC derivative ({len(raw):,} bytes)")
        return ifc_path
