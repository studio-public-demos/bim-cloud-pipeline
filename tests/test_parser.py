"""Integration tests for the IFC parser and pipeline against real sample data.

    python tests/test_parser.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import ifc_parser
import glb_builder

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def _load(name: str) -> dict:
    path = os.path.join(SAMPLES, name)
    with open(path, encoding="utf-8") as fh:
        return ifc_parser.extract_model(fh.read())


def test_architecture_sample():
    model = _load("Building-Architecture.ifc")
    st = model["stats"]
    assert st["totalElements"] >= 15, "expected a populated building model"
    assert st["totalTriangles"] > 0, "expected real geometry"

    cats = st["byCategory"]
    assert cats.get("wall", 0) >= 1
    assert cats.get("slab", 0) >= 1

    walls = [e for e in model["elements"] if e["category"] == "wall"]
    assert walls and walls[0]["globalId"], "walls should carry a GlobalId"
    assert walls[0]["material"], "walls should have a resolved material"

    mesh = glb_builder.build_mesh(model)
    assert len(mesh.faces) > 0, "mesh should be non-empty"
    print(f"ok architecture: {st['totalElements']} elements, {len(mesh.faces)} mesh tris")


def test_structural_sample():
    model = _load("Building-Structural.ifc")
    cats = model["stats"]["byCategory"]
    assert cats.get("beam", 0) >= 1, "structural sample should contain beams"
    assert model["stats"]["totalTriangles"] > 0
    print(f"ok structural: {model['stats']['totalElements']} elements, beams={cats.get('beam')}")


def test_metadata_structure():
    model = _load("Building-Architecture.ifc")
    assert model["schema"] == "bim-metadata"
    assert model["project"] and model["project"]["globalId"]
    assert "spatialStructure" in model
    assert "stats" in model
    # property sets should use their IFC name (not the GlobalId)
    walls = [e for e in model["elements"] if e["category"] == "wall"]
    pset_keys = set()
    for w in walls:
        pset_keys.update(w.get("properties", {}).keys())
    assert any(k.startswith("Pset_") for k in pset_keys), f"expected Pset_* keys, got {pset_keys}"
    print(f"ok metadata: property sets = {sorted(pset_keys)}")


if __name__ == "__main__":
    test_architecture_sample()
    test_structural_sample()
    test_metadata_structure()
    print("\nALL PARSER TESTS PASSED")
