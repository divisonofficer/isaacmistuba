#!/usr/bin/env python3
"""Create an immutable structural-PBR overlay for an independent child scene."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules" / "mitsuba_converter" / "src"))
from mitsuba_converter.ir_structural_pbr import build_manifest, load_registry, validate_registry_files  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stage1-dir", type=Path, required=True)
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--registry-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--child-scene-id", required=True)
    p.add_argument("--parent-scene-id", required=True)
    p.add_argument("--parent-dataset-fingerprint")
    p.add_argument("--material-variant-id", required=True)
    p.add_argument("--material-seed", type=int, required=True)
    a = p.parse_args()
    stage1 = a.stage1_dir.resolve() / "scene_manifest.json"
    registry = load_registry(a.registry.resolve())
    validate_registry_files(registry, a.registry_root.resolve())
    result = build_manifest(stage1_manifest=json.loads(stage1.read_text()), stage1_path=stage1,
        registry=registry, registry_path=a.registry.resolve(), child_scene_id=a.child_scene_id,
        parent_scene_id=a.parent_scene_id, parent_dataset_fingerprint=a.parent_dataset_fingerprint,
        material_variant_id=a.material_variant_id, material_seed=a.material_seed)
    for binding in result["bindings"]:
        binding["resolved_maps"] = {
            key: str((a.registry_root.resolve() / str(value)).resolve())
            for key, value in binding["maps"].items()
        }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    temp = a.out.with_suffix(a.out.suffix + ".tmp")
    temp.write_text(json.dumps(result, indent=2) + "\n")
    os.replace(temp, a.out)
    print(f"[rematerialize] {len(result['bindings'])} structural slots -> {a.out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
