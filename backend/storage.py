"""Cloud storage abstraction for pipeline outputs.

Two backends:
  - LocalStorage  (default) — outputs stay on disk; no cloud URLs.
  - S3Storage     — uploads outputs to Amazon S3 and returns presigned URLs.

Configure S3 via environment variables:
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET  (+ optional AWS_REGION)

When S3 is not configured, get_storage() returns LocalStorage and the pipeline
behaves exactly as before (local downloads).
"""
from __future__ import annotations

import os


class StorageBackend:
    configured = False

    def publish(self, job_id: str, local_dir: str, files: list[str]) -> dict:
        """Upload outputs and return {filename: url}. {} means no cloud copy."""
        return {}


class LocalStorage(StorageBackend):
    pass


class S3Storage(StorageBackend):
    def __init__(self, bucket: str | None = None, region: str | None = None):
        self.bucket = bucket or os.environ.get("AWS_S3_BUCKET")
        self.region = region or os.environ.get("AWS_REGION") or "us-east-1"
        self.configured = bool(
            self.bucket
            and os.environ.get("AWS_ACCESS_KEY_ID")
            and os.environ.get("AWS_SECRET_ACCESS_KEY")
        )

    def _client(self):
        import boto3  # imported lazily so local mode needs no boto3
        return boto3.client("s3", region_name=self.region)

    def publish(self, job_id: str, local_dir: str, files: list[str]) -> dict:
        if not self.configured:
            return {}
        s3 = self._client()
        out = {}
        for name in files:
            local = os.path.join(local_dir, name)
            if not os.path.isfile(local):
                continue
            key = f"jobs/{job_id}/{name}"
            s3.upload_file(local, self.bucket, key)
            out[name] = self.presign(key)
        return out

    def presign(self, key: str, expires: int = 3600) -> str:
        s3 = self._client()
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )


def get_storage() -> StorageBackend:
    s3 = S3Storage()
    if s3.configured:
        return s3
    return LocalStorage()
