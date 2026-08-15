"""Unit tests for the credential-gated adapters (APS + S3), run with mocks.

    python tests/test_adapters.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import aps_adapter
import storage


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def test_to_urn():
    urn = aps_adapter.APSAdapter.to_urn("urn:adsk.objects:os.object:b/test.rvt")
    assert urn and "=" not in urn
    print("ok to_urn")


def test_aps_flow_gltf():
    adapter = aps_adapter.APSAdapter(client_id="id", client_secret="secret")
    assert adapter.configured

    def fake_post_form(url, data, headers=None):
        assert "authenticate" in url
        return _FakeResp(json.dumps({"access_token": "tok"}).encode())

    def fake_post_json(url, payload, token):
        if "buckets" in url and not url.endswith("/objects"):
            return _FakeResp(b"{}")
        if "designdata/job" in url:
            return _FakeResp(json.dumps({"result": "created"}).encode())
        raise AssertionError(url)

    def fake_put(url, data, token):
        return _FakeResp(json.dumps({
            "objectId": "urn:adsk.objects:os.object:bk/model.rvt",
            "bucketKey": "bk",
        }).encode())

    manifest = {"status": "success", "derivatives": [
        {"urn": "urn:adsk.viewing:fs.file:dXJu/gltf", "role": "autodesk.gltf"},
    ]}

    def fake_get(url, token):
        if url.endswith("/manifest"):
            return _FakeResp(json.dumps(manifest).encode())
        return _FakeResp(b"gltf-bytes")

    with mock.patch.object(adapter, "_post_form", fake_post_form), \
         mock.patch.object(adapter, "_post_json", fake_post_json), \
         mock.patch.object(adapter, "_put", fake_put), \
         mock.patch.object(adapter, "_get", fake_get):
        with tempfile.TemporaryDirectory() as td:
            rvt = os.path.join(td, "model.rvt")
            with open(rvt, "wb") as fh:
                fh.write(b"rvt")
            logs = []
            out = adapter.convert(rvt, "job1", logs.append)
            assert out.endswith("model.gltf")
            assert any("glTF derivative" in l for l in logs)

    print("ok aps flow (gltf)")


def test_aps_unconfigured():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("APS_CLIENT_ID", None)
        os.environ.pop("APS_CLIENT_SECRET", None)
        adapter = aps_adapter.APSAdapter()
        assert not adapter.configured
    print("ok aps unconfigured")


def test_storage_local_fallback():
    os.environ.pop("AWS_S3_BUCKET", None)
    os.environ.pop("AWS_ACCESS_KEY_ID", None)
    os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
    backend = storage.get_storage()
    assert isinstance(backend, storage.LocalStorage)
    assert backend.publish("j", "dir", ["x"]) == {}
    print("ok storage local fallback")


def test_s3_publish_mocked():
    with mock.patch.dict(os.environ, {
        "AWS_ACCESS_KEY_ID": "k", "AWS_SECRET_ACCESS_KEY": "s", "AWS_S3_BUCKET": "b"
    }):
        s3 = storage.S3Storage()
        assert s3.configured

        fake_client = mock.MagicMock()
        fake_client.generate_presigned_url.return_value = "https://presigned/x"

        with mock.patch.object(s3, "_client", return_value=fake_client):
            with tempfile.TemporaryDirectory() as td:
                open(os.path.join(td, "model.glb"), "wb").write(b"data")
                urls = s3.publish("job1", td, ["model.glb", "missing.bin"])
            assert urls["model.glb"].startswith("https://presigned")
            assert "missing.bin" not in urls
            fake_client.upload_file.assert_called_once()
    print("ok s3 publish (mocked)")


if __name__ == "__main__":
    test_to_urn()
    test_aps_flow_gltf()
    test_aps_unconfigured()
    test_storage_local_fallback()
    test_s3_publish_mocked()
    print("\nALL ADAPTER TESTS PASSED")
