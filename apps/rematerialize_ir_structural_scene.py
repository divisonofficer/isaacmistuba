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
from mitsuba_converter.ir_structural_finish import load_policy, roughness_index  # noqa: E402


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
    p.add_argument("--structural-finish-policy", type=Path, default=None,
                   help="finish budget for the room shell; omitted keeps the uniform draw "
                        "and reproduces an existing manifest byte for byte")
    a = p.parse_args()
    stage1 = a.stage1_dir.resolve() / "scene_manifest.json"
    registry = load_registry(a.registry.resolve())
    validate_registry_files(registry, a.registry_root.resolve())
    finish_policy = roughness = None
    if a.structural_finish_policy is not None:
        # Measuring every roughness map costs a few seconds and only happens
        # when a policy asks for it; the result rides along in the manifest so
        # nothing downstream has to open the maps again.
        finish_policy = load_policy(a.structural_finish_policy.resolve())
        roughness = roughness_index(registry, a.registry_root.resolve(),
                                    smooth=float(finish_policy.get("smooth_roughness", 0.30)))
    result = build_manifest(stage1_manifest=json.loads(stage1.read_text()), stage1_path=stage1,
        registry=registry, registry_path=a.registry.resolve(), child_scene_id=a.child_scene_id,
        parent_scene_id=a.parent_scene_id, parent_dataset_fingerprint=a.parent_dataset_fingerprint,
        material_variant_id=a.material_variant_id, material_seed=a.material_seed,
        finish_policy=finish_policy, roughness_index=roughness)
    for binding in result["bindings"]:
        binding["resolved_maps"] = {
            key: str((a.registry_root.resolve() / str(value)).resolve())
            for key, value in binding["maps"].items()
        }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    temp = a.out.with_suffix(a.out.suffix + ".tmp")
    temp.write_text(json.dumps(result, indent=2) + "\n")
    os.replace(temp, a.out)
    report = result.get("structural_finish")
    if report:
        print(f"[rematerialize] shell smooth {report['shell_smooth_fraction']} "
              f"(target {report['shell_smooth_target']}, within={report['within_target']})")
        for role, v in report["roles"].items():
            print(f"[rematerialize]   {role:8} {v['slots']:3d} slots  "
                  f"mean smooth {v['mean_smooth_fraction']:.3f}")
    print(f"[rematerialize] {len(result['bindings'])} structural slots -> {a.out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
