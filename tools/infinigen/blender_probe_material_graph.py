"""Dump reachable PBR channel sources for selected objects in a .blend.

The traversal is shared with ``blender_audit_original_pbr.py`` and starts at
Material Output.Surface, including nested group bindings.  It is intentionally
read-only and does not render or modify the source blend.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_audit_original_pbr import _material_audit  # noqa: E402
from blender_export_scene import _pbr_input_contract  # noqa: E402


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-regex", default="SinkFactory|Microwave|Sink")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    pattern = re.compile(args.object_regex, re.IGNORECASE)
    rows = []
    for obj in sorted((x for x in bpy.data.objects if x.type == "MESH"), key=lambda x: x.name):
        if not pattern.search(obj.name):
            continue
        material_face_counts = {}
        for polygon in obj.data.polygons:
            key = str(int(polygon.material_index))
            record = material_face_counts.setdefault(key, {"polygons": 0, "triangles": 0, "area": 0.0})
            record["polygons"] += 1
            record["triangles"] += max(1, len(polygon.vertices) - 2)
            record["area"] += float(polygon.area)
        rows.append({
            "object": obj.name,
            "used_material_indices": sorted({
                int(poly.material_index) for poly in obj.data.polygons
            }),
            "material_face_counts": material_face_counts,
            # Keep this next to the source-graph audit: a disagreement is an
            # exporter bug, not evidence that a linked procedural source may
            # silently collapse to a scalar glTF factor.
            "export_pbr_input_contract": _pbr_input_contract(obj),
            "materials": [
                _material_audit(slot.material) for slot in obj.material_slots
            ],
        })
    result = {
        "schema": "robomituba.infinigen.material_graph_probe.v1",
        "source_blend": bpy.data.filepath,
        "object_regex": args.object_regex,
        "objects": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"objects": len(rows), "out": str(args.out)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
