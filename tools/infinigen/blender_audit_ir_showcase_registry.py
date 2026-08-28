"""Offline native-factory audit used to publish a prop PBR registry V1."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

import bpy

REPO_ROOT = Path(__file__).resolve().parents[2]
INFINIGEN_SRC = REPO_ROOT / "modules" / "infinigen"
if str(INFINIGEN_SRC) not in sys.path:
    sys.path.insert(0, str(INFINIGEN_SRC))


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _principled_values(root: bpy.types.Object) -> tuple[float, float, int]:
    metallic, roughness, count = [], [], 0
    for obj in [root, *list(root.children_recursive)]:
        for slot in getattr(obj, "material_slots", ()):
            material = slot.material
            if material is None or not material.use_nodes or material.node_tree is None:
                continue
            node = next((item for item in material.node_tree.nodes if item.type == "BSDF_PRINCIPLED"), None)
            if node is None:
                continue
            count += 1
            metallic.append(float(node.inputs.get("Metallic").default_value if node.inputs.get("Metallic") else 0.0))
            roughness.append(float(node.inputs.get("Roughness").default_value if node.inputs.get("Roughness") else .5))
    return (sum(metallic) / len(metallic) if metallic else 0.0,
            sum(roughness) / len(roughness) if roughness else .5, count)


def _bounds(root: bpy.types.Object) -> tuple[float, float, float]:
    vertices = []
    for obj in [root, *list(root.children_recursive)]:
        if obj.type == "MESH":
            vertices.extend(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
    if not vertices:
        return .0, .0, .0
    return (max(vertex.x for vertex in vertices) - min(vertex.x for vertex in vertices),
            max(vertex.y for vertex in vertices) - min(vertex.y for vertex in vertices),
            max(vertex.z for vertex in vertices) - min(vertex.z for vertex in vertices))


def _clear(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)


def main() -> int:
    args = _args()
    source = json.loads(args.candidates.read_text(encoding="utf-8"))
    records = []
    for index, raw in enumerate(source.get("props") or []):
        record, root = dict(raw), None
        try:
            module, class_name = str(record["factory_import"]).split(":", 1)
            factory = getattr(importlib.import_module(module), class_name)(int(record["asset_seed"]))
            root = factory.spawn_asset(i=index, loc=(0, 0, 0), rot=(0, 0, 0), distance=3.0)
            factory.finalize_assets([root])
            sx, sy, sz = _bounds(root)
            metallic, roughness, material_count = _principled_values(root)
            record["geometry"] = {"valid_support_object": bool(sx > .01 and sy > .01 and sz > .01),
                                  "footprint_m": [round(sx, 6), round(sy, 6)], "height_m": round(sz, 6)}
            record["effective_pbr"] = {"mean_metallic": round(metallic, 6), "mean_roughness": round(roughness, 6),
                                       "principled_material_count": material_count}
            record["audit_status"] = "passed"
        except Exception as exc:  # retain a deterministic, disabled diagnostic record
            record["enabled"] = False
            record["audit_status"] = "failed"
            record["audit_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if root is not None:
                _clear([root, *list(root.children_recursive)])
        records.append(record)
    core = {"schema": "robomituba.infinigen_prop_pbr_registry.v1", "registry_version": "v1",
            "audit_method": "native_factory_offline_audit_v1", "props": records}
    output = {**core, "audit_digest": _digest(core)}
    temporary = args.out.with_name(f".{args.out.name}.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, args.out)
    print(json.dumps({"audited": len(records), "enabled": sum(bool(row.get("enabled", True)) for row in records),
                      "audit_digest": output["audit_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
