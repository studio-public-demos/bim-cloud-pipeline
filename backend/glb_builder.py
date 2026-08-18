"""Build GLB / GLTF derivatives from the extracted BIM model using trimesh.

Coordinates are converted from IFC millimetres to metres (GLTF convention),
and per-element vertex colours are preserved so the 3D model stays visually
meaningful in any glTF viewer.

numpy/trimesh are imported lazily inside build_mesh() so the API can serve
health/status requests without holding those heavy libraries in memory.
"""
from __future__ import annotations

# Analytical volumes (rooms, zones) are kept in metadata but excluded from the
# visual mesh so they don't occlude the building fabric.
SKIP_CATEGORIES = {"space", "zone", "site", "building", "storey", "project"}


def build_mesh(model: dict, use_placement: bool = True):
    """Return a trimesh.Trimesh with vertex colours from the extracted model."""
    import numpy as np
    import trimesh

    verts = []
    faces = []
    vcolors = []

    for el in model['elements']:
        if el.get('isVirtual'):
            continue
        if el.get('category') in SKIP_CATEGORIES:
            continue
        g = el.get('geometry')
        if not g:
            continue
        el_verts = g['vertices']
        el_tris = g['triangles']
        el_colors = g['colors']
        # colours are per-triangle; default to element colour if mismatched
        for ti, tri in enumerate(el_tris):
            color = el_colors[ti] if ti < len(el_colors) else g.get('color', [0.8, 0.8, 0.8])
            base = len(verts)
            for vi in tri:
                v = el_verts[vi]
                verts.append([v[0] / 1000.0, v[1] / 1000.0, v[2] / 1000.0])
                vcolors.append(color)
            faces.append([base, base + 1, base + 2])

    if not verts:
        # produce an empty mesh so the pipeline never crashes
        return trimesh.Trimesh()

    vertices = np.array(verts, dtype=np.float32)
    faces_arr = np.array(faces, dtype=np.int64)
    colors = np.array(vcolors, dtype=np.float32)
    colors = np.clip(colors, 0.0, 1.0) * 255.0
    colors = colors.astype(np.uint8)

    mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces_arr,
        vertex_colors=colors,
        process=False,
    )
    # remove duplicate / degenerate vertices is handled by `process` when
    # exporting; keeping process=False preserves per-triangle colours exactly.
    return mesh


def export(mesh, glb_path: str, gltf_path: str):
    """Write both a binary .glb and a .gltf (+ .bin) derivative."""
    if len(mesh.faces) == 0:
        raise ValueError("empty mesh - nothing to export")
    mesh.export(glb_path, file_type='glb')
    mesh.export(gltf_path, file_type='gltf')
    return {
        'glb': glb_path,
        'gltf': gltf_path,
        'vertices': int(len(mesh.vertices)),
        'triangles': int(len(mesh.faces)),
    }
