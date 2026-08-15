"""Diff two processed BIM models (metadata.json) for the compare view.

Matches elements by IFC GlobalId when both models share ids; otherwise falls
back to matching by (category, name). Produces a summary suitable for a
side-by-side comparison UI and for API consumers.
"""
from __future__ import annotations


def _identity(e: dict):
    return e.get("globalId")


def _key(e: dict):
    return (e.get("category"), e.get("name"))


def _semantic(e: dict):
    return {
        "material": e.get("material"),
        "objectType": e.get("objectType"),
        "properties": e.get("properties"),
        "containedIn": e.get("containedIn"),
    }


def compare_models(meta_a: dict, meta_b: dict) -> dict:
    ea = meta_a.get("elements", []) or []
    eb = meta_b.get("elements", []) or []

    gids_a = {_identity(e) for e in ea if _identity(e)}
    gids_b = {_identity(e) for e in eb if _identity(e)}
    use_gid = bool(gids_a & gids_b)

    added = []
    removed = []
    changed = []
    common = 0

    if use_gid:
        map_a = {_identity(e): e for e in ea if _identity(e)}
        map_b = {_identity(e): e for e in eb if _identity(e)}
        for gid in sorted(gids_a):
            a = map_a[gid]
            if gid in gids_b:
                b = map_b[gid]
                common += 1
                if _semantic(a) != _semantic(b):
                    changed.append(_changed_entry(gid, a, b))
            else:
                removed.append(_entry(gid, a))
        for gid in sorted(gids_b):
            if gid not in gids_a:
                added.append(_entry(gid, map_b[gid]))
    else:
        map_a = {_key(e): e for e in ea}
        map_b = {_key(e): e for e in eb}
        keys_a = set(map_a)
        keys_b = set(map_b)
        for k in sorted(keys_a & keys_b):
            common += 1
            if _semantic(map_a[k]) != _semantic(map_b[k]):
                changed.append(_changed_entry(None, map_a[k], map_b[k], key=k))
        for k in sorted(keys_a - keys_b):
            removed.append(_entry(None, map_a[k], key=k))
        for k in sorted(keys_b - keys_a):
            added.append(_entry(None, map_b[k], key=k))

    category_diff = _category_diff(ea, eb)

    return {
        "a": {
            "id": meta_a.get("_jobId"),
            "filename": meta_a.get("_filename"),
            "stats": meta_a.get("stats"),
            "project": (meta_a.get("project") or {}).get("name"),
        },
        "b": {
            "id": meta_b.get("_jobId"),
            "filename": meta_b.get("_filename"),
            "stats": meta_b.get("stats"),
            "project": (meta_b.get("project") or {}).get("name"),
        },
        "elementDiff": {
            "common": common,
            "added": added,
            "removed": removed,
            "changed": changed,
        },
        "categoryDiff": category_diff,
    }


def _entry(gid, e, key=None):
    return {
        "globalId": gid,
        "name": e.get("name"),
        "category": e.get("category"),
        "material": e.get("material"),
        "key": key,
    }


def _changed_entry(gid, a, b, key=None):
    return {
        "globalId": gid,
        "key": key,
        "name": a.get("name") or b.get("name"),
        "category": a.get("category") or b.get("category"),
        "before": _semantic(a),
        "after": _semantic(b),
    }


def _category_diff(ea, eb):
    cats = {}
    for e in ea:
        c = e.get("category") or "unknown"
        cats.setdefault(c, {"a": 0, "b": 0})
        cats[c]["a"] += 1
    for e in eb:
        c = e.get("category") or "unknown"
        cats.setdefault(c, {"a": 0, "b": 0})
        cats[c]["b"] += 1
    return [
        {"category": c, "a": v["a"], "b": v["b"], "delta": v["b"] - v["a"]}
        for c, v in sorted(cats.items(), key=lambda kv: -abs(kv[1]["b"] - kv[1]["a"]))
    ]
