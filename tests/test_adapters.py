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

IFC_SAMPLE = b"ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


class _FakeResp:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

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


def test_aps_flow_ifc():
    adapter = aps_adapter.APSAdapter(client_id="id", client_secret="secret")
    assert adapter.configured

    def fake_post_form(url, data, headers=None):
        assert "token" in url
        return _FakeResp(json.dumps({"access_token": "tok"}).encode())

    def fake_post_json(url, payload, token):
        if url.endswith("oss/v2/buckets"):
            return _FakeResp(b"{}")
        if url.endswith("/signeds3upload"):  # complete upload
            return _FakeResp(json.dumps({
                "objectId": "urn:adsk.objects:os.object:bk/model.rvt",
                "bucketKey": "bk",
            }).encode())
        if "designdata/job" in url:  # translate job
            return _FakeResp(json.dumps({"result": "success"}).encode())
        raise AssertionError(url)

    def fake_get(url, token):
        if "/signeds3upload" in url:  # request signed upload URL
            return _FakeResp(json.dumps({
                "uploadKey": "upkey", "urls": ["https://s3.example/x"],
                "uploadExpiration": "2099-01-01T00:00:00Z",
            }).encode())
        if url.endswith("/manifest"):  # manifest poll
            return _FakeResp(json.dumps({
                "status": "success", "progress": "complete",
                "derivatives": [{"outputType": "ifc", "status": "success", "children": [
                    {"type": "resource", "role": "ifc", "urn": "urn:adsk.viewing:fs.file:x/output/IFC/model.ifc"}
                ]}],
            }).encode())
        # derivative download
        return _FakeResp(IFC_SAMPLE)

    def fake_put_s3(url, data):
        assert url.startswith("https://s3.example")
        return _FakeResp(b"", headers={"ETag": '"abc123"'})

    with mock.patch.object(adapter, "_post_form", fake_post_form), \
         mock.patch.object(adapter, "_post_json", fake_post_json), \
         mock.patch.object(adapter, "_get", fake_get), \
         mock.patch.object(adapter, "_put_s3", fake_put_s3):
        with tempfile.TemporaryDirectory() as td:
            rvt = os.path.join(td, "model.rvt")
            with open(rvt, "wb") as fh:
                fh.write(b"rvt")
            logs = []
            out = adapter.convert(rvt, "job1", logs.append)
            assert out.endswith("model.ifc")
            with open(out, "rb") as fh:
                assert fh.read() == IFC_SAMPLE
            assert any("IFC derivative" in l for l in logs)

    print("ok aps flow (ifc)")


def test_aps_unconfigured():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("APS_CLIENT_ID", None)
        os.environ.pop("APS_CLIENT_SECRET", None)
        adapter = aps_adapter.APSAdapter()
        assert not adapter.configured
    print("ok aps unconfigured")


def test_rvt_route_requires_aps_no_sample_substitution():
    import pipeline
    fake_aps = mock.Mock()
    fake_aps.configured = False
    logs = []
    with mock.patch.object(pipeline.aps_adapter, "APSAdapter", return_value=fake_aps):
        try:
            pipeline._process_rvt("job1", "uploaded.rvt", None, logs.append, lambda *a: None)
            raise AssertionError("expected ValueError for .rvt without APS credentials")
        except ValueError as exc:
            assert "Autodesk APS credentials" in str(exc)
    print("ok rvt route requires aps (no sample substitution)")


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
    test_aps_flow_ifc()
    test_aps_unconfigured()
    test_rvt_route_requires_aps_no_sample_substitution()
    test_storage_local_fallback()
    test_s3_publish_mocked()
    print("\nALL ADAPTER TESTS PASSED")
