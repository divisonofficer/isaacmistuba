#!/usr/bin/env python3
"""Index the ABO catalogue for Cornell-box scene composition.

The scene composer needs three facts per ABO model that the archive does not
state directly: its real metric size, whether it offers a horizontal surface
other objects can stand on, and whether it is a luminaire.  None of the three
can be read off `product_type` -- "TABLE" spans a 0.4 m side table and a 2.4 m
dining table, and "LAMP" covers a floor lamp, a table lamp and a bare shade.

Size comes from walking the glTF node hierarchy, not from the accessor min/max
union.  A minority of ABO assets scale their meshes at the node level, and
multiplying every node scale in the file together -- the obvious shortcut --
produced extents of 1e16 on two sofas and silently inflated ~10% of the
catalogue.  Corner-transforming each primitive's bounds under its own node
chain is the only reading that matches the asset.

Support surfaces come from the mesh: faces whose normal is within ~10 deg of
+Y, clustered into height bands with a 1 cm tolerance.  Each band is a
candidate table top or shelf; the composer places props on the topmost band
that is wide enough to hold one.  Materials are skipped during this pass --
ABO ships 4K PNG basecolour/normal maps and decoding them costs far more than
the geometry the pass actually reads.

Sizes are reported in glTF axes (Y-up).  Blender's importer maps +Y to +Z, so
a model's footprint is (ext[0], ext[2]) and its height is ext[1].
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import struct
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

#: Faces within ~10 deg of straight up are candidates for a support surface.
UP_COS = 0.985
#: Two upward faces belong to the same surface when their heights agree to 1 cm.
BAND_TOL_M = 0.010
#: Smaller upward patches are trim and joinery, not a place to stand something.
MIN_BAND_AREA_M2 = 0.02
#: Product types worth testing for a support surface at all.
SUPPORT_HOST_TYPES = frozenset({
    "TABLE", "DESK", "CABINET", "SHELF", "DRESSER", "BENCH", "OTTOMAN",
    "STOOL_SEATING", "NIGHTSTAND", "BOOKCASE", "HOME_FURNITURE_AND_DECOR",
})
#: Two ABO sofas are authored ~100x too large; nothing in the catalogue is
#: legitimately bigger than this, so the composer must not be handed one.
MAX_PLAUSIBLE_EXTENT_M = 4.0


def _node_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    matrix = np.eye(4)
    if "scale" in node:
        matrix = np.diag([*node["scale"], 1.0]) @ matrix
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        rotation = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ])
        embedded = np.eye(4)
        embedded[:3, :3] = rotation
        matrix = embedded @ matrix
    if "translation" in node:
        embedded = np.eye(4)
        embedded[:3, 3] = node["translation"]
        matrix = embedded @ matrix
    return matrix


def read_gltf_json(path: Path, *, probe_bytes: int = 524_288) -> dict[str, Any]:
    """Parse a GLB's JSON chunk without reading its (much larger) binary blob."""
    with path.open("rb") as handle:
        head = handle.read(probe_bytes)
    if head[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    json_length = struct.unpack_from("<I", head, 12)[0]
    if json_length + 20 > len(head):
        with path.open("rb") as handle:
            head = handle.read(json_length + 64)
    return json.loads(head[20:20 + json_length])


def _index_one(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    item_id = path.stem
    try:
        gltf = read_gltf_json(path)
    except Exception as error:  # noqa: BLE001 - one bad asset must not stop the pass
        return {"id": item_id, "error": f"{type(error).__name__}: {error}"[:120]}

    accessors = gltf.get("accessors") or []
    nodes = gltf.get("nodes") or []
    meshes = gltf.get("meshes") or []
    scenes = gltf.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    roots = scenes[int(gltf.get("scene", 0))].get("nodes", [])

    low = np.full(3, np.inf)
    high = np.full(3, -np.inf)
    triangles = 0
    # Counted alongside triangles because faces alone are not an identity for a
    # mesh. A peer's pipeline gated on triangle counts at every stage and passed
    # while two runs of it split the same mesh into 293,820 and 290,428
    # vertices -- identical faces, re-split UV seams, a different interpolated
    # surface and therefore different baked pixels. The pair (faces, vertices)
    # is the identity; either number alone is a projection of it, and every
    # projection has a null space.
    vertices = 0
    stack = [(int(index), np.eye(4)) for index in roots]
    visited = 0
    while stack:
        node_index, parent = stack.pop()
        visited += 1
        if visited > 100_000:  # a cycle in the node graph; the file is broken
            return {"id": item_id, "error": "node hierarchy exceeds 100k visits"}
        node = nodes[node_index]
        world = parent @ _node_matrix(node)
        if "mesh" in node:
            for primitive in meshes[node["mesh"]].get("primitives") or []:
                accessor = accessors[primitive["attributes"]["POSITION"]]
                if "min" not in accessor or "max" not in accessor:
                    continue
                lo = np.array(accessor["min"], dtype=float)
                hi = np.array(accessor["max"], dtype=float)
                corners = np.array([[x, y, z, 1.0]
                                    for x in (lo[0], hi[0])
                                    for y in (lo[1], hi[1])
                                    for z in (lo[2], hi[2])])
                placed = (world @ corners.T).T[:, :3]
                low = np.minimum(low, placed.min(axis=0))
                high = np.maximum(high, placed.max(axis=0))
                vertices += int(accessor["count"])
                if "indices" in primitive:
                    triangles += accessors[primitive["indices"]]["count"] // 3
        for child in node.get("children", []):
            stack.append((int(child), world))

    if not np.isfinite(low).all():
        return {"id": item_id, "error": "no primitive carried POSITION bounds"}

    emissive_materials = 0
    emissive_max = 0.0
    textured = {"base_color": 0, "metallic_roughness": 0, "normal": 0}
    for material in gltf.get("materials") or []:
        pbr = material.get("pbrMetallicRoughness") or {}
        factor = material.get("emissiveFactor") or [0.0, 0.0, 0.0]
        if "emissiveTexture" in material or max(factor) > 0:
            emissive_materials += 1
        emissive_max = max(emissive_max, float(max(factor)))
        textured["base_color"] += "baseColorTexture" in pbr
        textured["metallic_roughness"] += "metallicRoughnessTexture" in pbr
        textured["normal"] += "normalTexture" in material

    return {
        "id": item_id,
        "path": str(path),
        "extent_m": [round(float(v), 4) for v in (high - low)],
        "bounds_lo": [round(float(v), 4) for v in low],
        "bounds_hi": [round(float(v), 4) for v in high],
        "triangles": int(triangles),
        "vertices": int(vertices),
        "material_count": len(gltf.get("materials") or []),
        "textured_slots": textured,
        "emissive_materials": emissive_materials,
        "emissive_max": round(emissive_max, 4),
    }


def _support_bands(path_text: str) -> dict[str, Any]:
    import trimesh  # imported in the worker: it is slow and only this pass needs it

    path = Path(path_text)
    try:
        mesh = trimesh.load(str(path), force="mesh", skip_materials=True, process=False)
    except Exception as error:  # noqa: BLE001
        return {"id": path.stem, "error": f"{type(error).__name__}: {error}"[:120]}
    if mesh.is_empty or len(mesh.faces) == 0:
        return {"id": path.stem, "error": "empty mesh"}

    y_low, y_high = float(mesh.bounds[0][1]), float(mesh.bounds[1][1])
    upward = np.where(mesh.face_normals[:, 1] > UP_COS)[0]
    if len(upward) == 0:
        return {"id": path.stem, "y_range": [round(y_low, 4), round(y_high, 4)], "bands": []}

    heights = mesh.triangles[upward][:, :, 1].mean(axis=1)
    order = np.argsort(heights)
    sorted_heights = heights[order]
    bands: list[dict[str, Any]] = []
    start = 0
    for cut in range(1, len(sorted_heights) + 1):
        if cut == len(sorted_heights) or sorted_heights[cut] - sorted_heights[start] > BAND_TOL_M:
            faces = upward[order[start:cut]]
            area = float(mesh.area_faces[faces].sum())
            if area >= MIN_BAND_AREA_M2:
                footprint = mesh.triangles[faces].reshape(-1, 3)[:, [0, 2]]
                lo = footprint.min(axis=0)
                hi = footprint.max(axis=0)
                bands.append({
                    "height_m": round(float(sorted_heights[start:cut].mean()), 4),
                    "area_m2": round(area, 4),
                    "xz_lo": [round(float(v), 4) for v in lo],
                    "xz_hi": [round(float(v), 4) for v in hi],
                })
            start = cut
    return {"id": path.stem, "y_range": [round(y_low, 4), round(y_high, 4)], "bands": bands}


def _listing_metadata(listings_dir: Path) -> dict[str, dict[str, Any]]:
    """product_type / title / keywords, keyed by item id.

    The lamp archetype guess needs all three: item_name alone left 78% of the
    540 luminaires unclassified, while name plus keywords leaves 5%.
    """
    metadata: dict[str, dict[str, Any]] = {}
    for shard in sorted(glob.glob(str(listings_dir / "*.json.gz"))):
        with gzip.open(shard, "rt") as handle:
            for line in handle:
                record = json.loads(line)
                item_id = record.get("item_id")
                if not item_id:
                    continue
                metadata[item_id] = {
                    "product_type": ((record.get("product_type") or [{}])[0]).get("value", "?"),
                    "name": ((record.get("item_name") or [{}])[0]).get("value", "")[:140],
                    "keywords": [k.get("value", "") for k in (record.get("item_keywords") or [])][:12],
                }
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--abo-root", type=Path, default=Path("/bean/ir_dataset/abo_v1"))
    parser.add_argument("--out", type=Path, required=True, help="index JSON to write")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--support", action="store_true",
                        help="also compute support-surface bands (loads meshes; much slower)")
    parser.add_argument("--limit", type=int, default=0, help="index only the first N assets (smoke runs)")
    args = parser.parse_args()

    models_dir = args.abo_root / "3dmodels" / "original"
    files = sorted(glob.glob(str(models_dir / "*" / "*.glb")))
    if args.limit:
        files = files[:args.limit]
    if not files:
        parser.error(f"no ABO .glb assets under {models_dir}")
    print(f"[abo-index] assets={len(files)}", flush=True)

    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(_index_one, files, chunksize=16))

    metadata = _listing_metadata(args.abo_root / "listings" / "metadata")
    for row in rows:
        row.update(metadata.get(row["id"], {"product_type": "?", "name": "", "keywords": []}))

    indexed = [row for row in rows if "extent_m" in row]
    failed = [row for row in rows if "error" in row]
    print(f"[abo-index] indexed={len(indexed)} failed={len(failed)}", flush=True)

    if args.support:
        hosts = [row["path"] for row in indexed
                 if row["product_type"] in SUPPORT_HOST_TYPES
                 and max(row["extent_m"]) <= MAX_PLAUSIBLE_EXTENT_M]
        print(f"[abo-index] support pass over {len(hosts)} host candidates", flush=True)
        with ProcessPoolExecutor(args.workers) as pool:
            support = {row["id"]: row for row in pool.map(_support_bands, hosts, chunksize=8)}
        carried = 0
        for row in indexed:
            found = support.get(row["id"])
            if found and "bands" in found:
                row["support_bands"] = found["bands"]
                carried += bool(found["bands"])
        print(f"[abo-index] hosts with >=1 support band: {carried}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "robomituba.abo_object_index.v1",
        "abo_root": str(args.abo_root),
        "asset_count": len(indexed),
        "failed": failed,
        "support_pass": bool(args.support),
        "objects": indexed,
    }
    args.out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"[abo-index] wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
