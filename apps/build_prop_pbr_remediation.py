#!/usr/bin/env python3
"""Build an immutable, slot-local small-prop PBR remediation manifest."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "navigation_dataset" / "src"))
from navigation_dataset.ir_prop_pbr import build_manifest, load_registry

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stage1-dir", type=Path, required=True)
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--child-scene-id", required=True)
    p.add_argument("--parent-scene-id", required=True)
    p.add_argument("--parent-dataset-fingerprint")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    stage1 = a.stage1_dir.resolve()
    manifest = json.loads((stage1 / "scene_manifest.json").read_text(encoding="utf-8"))
    states = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in (stage1 / ".stage1_unit_state").glob("*.json")}
    result = build_manifest(stage1_manifest=manifest, unit_states=states, registry=load_registry(a.registry.resolve()),
                            registry_path=a.registry.resolve(), child_scene_id=a.child_scene_id,
                            parent_scene_id=a.parent_scene_id, parent_dataset_fingerprint=a.parent_dataset_fingerprint,
                            seed=a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{a.out.name}.", dir=a.out.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(result, f, ensure_ascii=False, indent=2)
    os.replace(tmp, a.out)
    print(json.dumps({"out":str(a.out), "counts":result["counts"], "digest":result["digest"]}))
    return 0
if __name__ == "__main__": raise SystemExit(main())
