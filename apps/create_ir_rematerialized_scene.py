#!/usr/bin/env python3
"""Create an independent OpticalNav child scene plus structural-PBR overlay.

Only metadata/graph files are copied; Stage-1 geometry stays an immutable
read-only parent input.  This avoids duplicating large GLBs while making scene
identity, output roots, resume state and publish target independent.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--parent-scene-dir", type=Path, required=True)
    p.add_argument("--child-scene-dir", type=Path, required=True)
    p.add_argument("--stage1-dir", type=Path, required=True)
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--registry-root", type=Path, required=True)
    p.add_argument("--parent-dataset-fingerprint")
    p.add_argument("--material-variant-id", required=True)
    p.add_argument("--material-seed", type=int, required=True)
    a = p.parse_args()
    parent, child = a.parent_scene_dir.resolve(), a.child_scene_dir.resolve()
    if child.exists():
        raise FileExistsError(child)
    if not (parent / "viewpoint_graph.json").is_file():
        raise FileNotFoundError(parent / "viewpoint_graph.json")
    child.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{child.name}.staging-", dir=child.parent))
    try:
        # Navigation metadata is deliberately copied, not linked: an editor or
        # future graph regeneration cannot mutate the parent scene.
        for item in parent.iterdir():
            if item.name in {"render_scene.xml", "meshes", "textures", ".staging"}: continue
            target = staging / item.name
            if item.is_dir(): shutil.copytree(item, target, symlinks=False)
            else: shutil.copy2(item, target)
        scene_id = child.name
        graph = json.loads((staging / "viewpoint_graph.json").read_text())
        graph["scene_id"] = scene_id
        (staging / "viewpoint_graph.json").write_text(json.dumps(graph, indent=2) + "\n")
        lineage = {"schema": "robomituba.ir_scene_lineage.v1", "scene_id": scene_id,
                   "parent_scene_id": parent.name, "material_variant_id": a.material_variant_id,
                   "material_seed": a.material_seed, "stage1_dir": str(a.stage1_dir.resolve())}
        (staging / "scene_lineage.json").write_text(json.dumps(lineage, indent=2) + "\n")
        subprocess.run([sys.executable, str(ROOT / "apps" / "rematerialize_ir_structural_scene.py"),
            "--stage1-dir", str(a.stage1_dir.resolve()), "--registry", str(a.registry.resolve()),
            "--registry-root", str(a.registry_root.resolve()), "--out", str(staging / "structural_rematerialization.json"),
            "--child-scene-id", scene_id, "--parent-scene-id", parent.name,
            "--material-variant-id", a.material_variant_id, "--material-seed", str(a.material_seed),
            *( ["--parent-dataset-fingerprint", a.parent_dataset_fingerprint] if a.parent_dataset_fingerprint else [])], check=True)
        os.replace(staging, child)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    print(f"[rematerialize] independent scene {child.name} created from {parent.name}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
