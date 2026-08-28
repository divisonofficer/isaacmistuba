#!/usr/bin/env python3
"""Audit a generated ``modern_glass_office_v2`` Blender scene.

Run through ``tools/infinigen/run_bundled_blender.py``.  The script never saves
the opened blend: it reports factory-root population and room containment only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
from office_population_audit import audit_population  # noqa: E402
from infinigen_office_workstations import _factory_owner, _room_for as _workstation_room_for, _world_bounds  # noqa: E402


_BOX_RE = re.compile(
    r"shapely\.box\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)"
)


def _arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workstation-layout", type=Path, required=False,
                        help="Post-solve desk/chair pairing marker required by Office v2 publication.")
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def _boxes(floor_plan: Path) -> dict[str, tuple[float, float, float, float]]:
    value = json.loads(floor_plan.read_text(encoding="utf-8"))
    result = {}
    for room, spec in (value.get("rooms") or {}).items():
        match = _BOX_RE.search(str(spec.get("shape") or ""))
        if not match:
            raise ValueError(f"cannot parse floor-plan box for {room}")
        result[room] = tuple(float(match.group(index)) for index in range(1, 5))
    return result


def _factory_name(obj) -> tuple[str | None, str]:
    """Resolve one logical generated asset, matching workstation postprocess.

    Placeholder/spawned/child meshes are multiple views of one factory asset.
    Reusing the authoritative resolver prevents inflated desk/chair counts.
    """
    owner, factory = _factory_owner(obj)
    return factory, owner.name if owner is not None else obj.name


def _room_for(x: float, y: float, boxes: dict[str, tuple[float, float, float, float]]) -> str | None:
    hits = [name for name, (x0, y0, x1, y1) in boxes.items() if x0 - 1e-4 <= x <= x1 + 1e-4 and y0 - 1e-4 <= y <= y1 + 1e-4]
    # A root precisely on a shared wall has no trustworthy room assignment and
    # must fail strict audit rather than silently being credited twice.
    return hits[0] if len(hits) == 1 else None


def _records(boxes: dict[str, tuple[float, float, float, float]]) -> list[dict]:
    seen: set[str] = set()
    records = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        owner, factory = _factory_owner(obj)
        if owner is None or factory is None or owner.name in seen:
            continue
        key = owner.name
        seen.add(key)
        bounds = _world_bounds(owner)
        center_x = (bounds[0] + bounds[2]) * 0.5
        center_y = (bounds[1] + bounds[3]) * 0.5
        records.append({
            "asset_key": key,
            "name": owner.name,
            "factory": factory,
            "center_m": [round(float(center_x), 4), round(float(center_y), 4)],
            "room": _workstation_room_for(bounds, boxes),
            "cell": [int(float(center_x) // 2.0), int(float(center_y) // 2.0)],
        })
    return records


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    args = _arguments()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("profile") != "modern_glass_office_v2" or manifest.get("office_style") != "modern_glass_v2":
        raise ValueError("population audit requires a modern_glass_office_v2 manifest")
    floor_plan = (args.manifest.parent / str(manifest.get("source_floor_plan") or "floor_plan.json")).resolve()
    boxes = _boxes(floor_plan)
    payload = dict(manifest)
    payload["room_ids"] = sorted(boxes)
    payload["work_bay_rooms"] = list(manifest.get("work_bay_rooms") or [])
    panes = [obj for obj in bpy.data.objects if obj.get("glass_pane")]
    payload["installed_pane_count"] = len(panes)
    payload["installed_partition_ids"] = sorted({str(obj.get("glass_partition_id")) for obj in panes if obj.get("glass_partition_id")})
    if args.workstation_layout is not None:
        layout = json.loads(args.workstation_layout.read_text(encoding="utf-8"))
        payload["workstation_layout"] = {
            "status": layout.get("status"),
            "layout_digest": layout.get("layout_digest"),
            "mapping_count": len(layout.get("mappings") or []),
            "expected_rooms": list(layout.get("expected_rooms") or []),
        }
    records = _records(boxes)
    result = audit_population(records, payload)
    # Keep the deduplicated root records in the diagnostic artifact.  This is
    # intentionally an audit-side index (not a render payload) and makes a
    # failed quota repair actionable without reopening the multi-GB blend.
    result["records"] = records
    result["source_blend"] = str(Path(bpy.data.filepath).resolve()) if bpy.data.filepath else None
    result["source_manifest"] = str(args.manifest.resolve())
    _write_atomic(args.out.resolve(), result)
    print(json.dumps({"status": result["status"], "asset_count": result["asset_count"], "errors": result["errors"]}, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
