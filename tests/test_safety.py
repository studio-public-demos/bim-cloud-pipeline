"""Tests for public-safety features (config, job scoping, TTL cleanup).

    python tests/test_safety.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import config
from store import JobStore


def test_config_defaults():
    with mock.patch.dict(os.environ, {}, clear=True):
        import importlib
        importlib.reload(config)
        assert config.PUBLIC_DEMO_MODE is False
        assert config.MAX_FILE_SIZE_MB == 50
        assert config.MAX_CONCURRENT_JOBS == 4
        assert config.MAX_JOBS_PER_MINUTE == 10
        assert config.JOB_TTL_SECONDS == 3600
    print("ok config defaults")


def test_config_public_demo_on():
    with mock.patch.dict(os.environ, {"PUBLIC_DEMO_MODE": "1"}, clear=True):
        import importlib
        importlib.reload(config)
        assert config.PUBLIC_DEMO_MODE is True
    importlib.reload(config)
    print("ok config public demo on")


def test_config_hosted_default_on():
    # On a hosted platform (e.g. Render), public demo mode defaults to ON.
    with mock.patch.dict(os.environ, {"RENDER": "true"}, clear=True):
        import importlib
        importlib.reload(config)
        assert config.PUBLIC_DEMO_MODE is True
    # Explicit override still wins.
    with mock.patch.dict(os.environ, {"RENDER": "true", "PUBLIC_DEMO_MODE": "0"}, clear=True):
        importlib.reload(config)
        assert config.PUBLIC_DEMO_MODE is False
    importlib.reload(config)
    print("ok config hosted default on")


def test_store_client_scoping():
    with tempfile.TemporaryDirectory() as td:
        store = JobStore(td)
        store.create("a.ifc", 1, "ifc", client_id="visitor-1")
        store.create("b.ifc", 1, "ifc", client_id="visitor-2")
        store.create("c.ifc", 1, "ifc", client_id=None)
        assert len(store.list()) == 3
        assert len(store.list_for_client("visitor-1")) == 1
        assert store.list_for_client("visitor-1")[0]["filename"] == "a.ifc"
        assert len(store.list_for_client("visitor-2")) == 1
    print("ok store client scoping")


def test_store_ttl_cleanup():
    with tempfile.TemporaryDirectory() as td:
        store = JobStore(td)
        j = store.create("old.ifc", 1, "ifc", client_id="x")
        # backdate the job beyond the TTL
        with store._lock:
            store._jobs[j["id"]]["createdAt"] = time.time() - 9999
            store._persist(store._jobs[j["id"]])
        store.create("new.ifc", 1, "ifc", client_id="x")
        removed = store.cleanup(max_age_seconds=3600)
        assert removed == 1, f"expected 1 removed, got {removed}"
        assert store.get(j["id"]) is None
        assert len(store.list()) == 1
    print("ok store ttl cleanup")


if __name__ == "__main__":
    test_config_defaults()
    test_config_public_demo_on()
    test_config_hosted_default_on()
    test_store_client_scoping()
    test_store_ttl_cleanup()
    print("\nALL SAFETY TESTS PASSED")
