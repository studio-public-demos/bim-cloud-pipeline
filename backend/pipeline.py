"""Processing pipeline: input file -> GLB/GLTF + structured metadata JSON.

Supports three input routes:
  - .ifc  : real parse (geometry + metadata) via ifc_parser + glb_builder
  - .gltf / .glb : validate and re-export through the same derivative pipeline
  - .rvt  : Revit route via Autodesk APS (Model Derivative) -> IFC derivative
            -> native IFC pipeline. Requires APS_CLIENT_ID / APS_CLIENT_SECRET;
            without them the job fails with a clear error (no silent sample
            substitution).

Every stage is logged so the dashboard can show live progress.
"""
from __future__ import annotations

import gc
import json
import os
import shutil
import time

import aps_adapter
import glb_builder
import ifc_parser
import storage


def detect_format(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext


def run_pipeline(job_id: str, src_path: str, store):
    job = store.get(job_id)
    fmt = job["format"]

    def log(msg):
        store.log(job_id, msg)

    def stage(name, status, msg=""):
        store.stage(job_id, name, status, msg)

    try:
        store.update(job_id, status="processing", progress=5)
        stage("uploaded", "done", "File received and queued")
        log(f"Received {job['filename']} ({fmt}, {job['sizeBytes']} bytes)")

        time.sleep(0.4)
        stage("validated", "running", "Detecting format and validating")
        store.update(job_id, progress=15)

        if fmt in ("gltf", "glb"):
            _process_gltf(job_id, src_path, store, log, stage)
        elif fmt == "ifc":
            _process_ifc(job_id, src_path, store, log, stage)
        elif fmt == "rvt":
            _process_rvt(job_id, src_path, store, log, stage)
        else:
            raise ValueError(
                f"Unsupported format '.{fmt}'. Supported: .ifc, .rvt, .gltf, .glb"
            )

        store.update(job_id, status="completed", progress=100)
        stage("metadata", "done", "Structured metadata JSON written")
        log("Pipeline complete.")
    except Exception as exc:  # noqa: BLE001
        store.update(job_id, status="failed", progress=100, error=str(exc))
        log(f"ERROR: {exc}")
    finally:
        # Release any large in-memory geometry from this job before the next one.
        gc.collect()


def _process_ifc(job_id, src_path, store, log, stage):
    log("Valid IFC (STEP) file. Parsing entities...")
    stage("validated", "done", "IFC STEP structure recognised")

    with open(src_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    model = ifc_parser.extract_model(text)
    stage("parsed", "done", f"{model['stats']['totalElements']} elements")
    log(f"Parsed {model['stats']['totalElements']} elements "
        f"({model['stats']['totalTriangles']} triangles)")
    store.update(job_id, progress=40)

    time.sleep(0.4)
    stage("geometry", "running", "Building optimised triangle mesh")
    mesh = glb_builder.build_mesh(model)
    stage("geometry", "done", f"{len(mesh.faces)} triangles")
    log(f"Built mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} triangles")
    store.update(job_id, progress=60)

    out_dir = store.output_dir(job_id)
    glb_path = os.path.join(out_dir, "model.glb")
    gltf_path = os.path.join(out_dir, "model.gltf")

    time.sleep(0.4)
    stage("optimized", "running", "Exporting GLB / GLTF derivatives")
    glb_builder.export(mesh, glb_path, gltf_path)
    log(f"Exported {os.path.basename(glb_path)} "
        f"({os.path.getsize(glb_path):,} bytes)")
    log(f"Exported {os.path.basename(gltf_path)} + .bin")
    stage("optimized", "done", "GLB / GLTF exported")
    store.update(job_id, progress=80)

    meta_path = os.path.join(out_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(model, fh, ensure_ascii=False)
    log(f"Wrote metadata.json ({os.path.getsize(meta_path):,} bytes)")

    _finalize(job_id, store, out_dir, model['stats'], model)


def _process_gltf(job_id, src_path, store, log, stage):
    import trimesh
    log("Valid glTF/GLB file. Normalising...")
    stage("validated", "done", "glTF/GLB structure recognised")
    try:
        scene = trimesh.load(src_path, force="scene")
        geoms = getattr(scene, "geometry", {}) or {}
        if not geoms:
            geoms = {"mesh": scene}
        total_tris = sum(int(len(g.faces)) for g in geoms.values())
        total_verts = sum(int(len(g.vertices)) for g in geoms.values())
        stats = {
            "totalElements": len(geoms),
            "byCategory": {"mesh": len(geoms)},
            "totalTriangles": total_tris,
            "totalVertices": total_verts,
        }
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not parse glTF/GLB: {exc}")

    stage("parsed", "done", f"{stats['totalTriangles']} triangles")
    stage("geometry", "done", "Mesh normalised")
    store.update(job_id, progress=60)

    out_dir = store.output_dir(job_id)
    glb_path = os.path.join(out_dir, "model.glb")
    gltf_path = os.path.join(out_dir, "model.gltf")
    try:
        scene.export(glb_path, file_type="glb")
        scene.export(gltf_path, file_type="gltf")
    except Exception:  # noqa: BLE001
        dst = glb_path if src_path.lower().endswith(".glb") else gltf_path
        shutil.copy2(src_path, dst)
    log(f"Exported {os.path.basename(glb_path)}")

    meta = {
        "schema": "bim-metadata", "version": "1.0",
        "project": {"name": store.get(job_id)["filename"]},
        "spatialStructure": {}, "elements": [],
        "stats": stats,
        "note": "Uploaded glTF/GLB normalised through the derivative pipeline.",
    }
    meta_path = os.path.join(out_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False)
    _finalize(job_id, store, out_dir, stats, meta)


def _process_rvt(job_id, src_path, store, log, stage):
    aps = aps_adapter.APSAdapter()
    if not aps.configured:
        raise ValueError(
            "Revit (.rvt) conversion requires Autodesk APS credentials. "
            "Set APS_CLIENT_ID and APS_CLIENT_SECRET to convert this file, "
            "or upload an IFC/glTF/GLB file (or run the bundled samples)."
        )

    log("Autodesk APS credentials found -> Model Derivative route")
    stage("validated", "done", "Revit (RVT) recognised")
    try:
        ifc_path = aps.convert(src_path, job_id, log)
        stage("parsed", "done", "APS translated RVT -> IFC")
        log("Feeding APS IFC output through the native parser...")
        _process_ifc(job_id, ifc_path, store, log, stage)
        store.update(job_id, format="rvt")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"APS conversion failed: {exc}") from exc


def _finalize(job_id, store, out_dir, stats, model):
    outputs = {
        "modelGlb": f"/api/jobs/{job_id}/download/model.glb",
        "modelGltf": f"/api/jobs/{job_id}/download/model.gltf",
        "metadata": f"/api/jobs/{job_id}/download/metadata.json",
    }
    # Optional cloud copy (S3) with presigned URLs.
    try:
        cloud = storage.get_storage().publish(
            job_id, out_dir, ["model.glb", "model.gltf", "model.bin", "metadata.json"]
        )
        if cloud:
            outputs["cloud"] = cloud
    except Exception as exc:  # noqa: BLE001
        store.log(job_id, f"WARN: cloud storage publish skipped: {exc}")

    store.update(job_id, outputs=outputs, summary=stats)
