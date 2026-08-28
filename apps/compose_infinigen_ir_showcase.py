#!/usr/bin/env python3
"""Create an immutable IR showcase derivative of an Infinigen source blend."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for source in (REPO_ROOT / "modules" / "mitsuba_converter" / "src",):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mitsuba_converter.ir_showcase import PROFILE, composition_contract, registry_digest, stable_digest  # noqa: E402

BPY_RUNNER = REPO_ROOT / "tools" / "infinigen" / "_run_bpy.py"
COMPOSER = REPO_ROOT / "tools" / "infinigen" / "blender_compose_ir_showcase.py"


def _infinigen_python() -> Path:
    configured = os.environ.get("INFINIGEN_PYTHON")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates += [Path.home() / "miniconda3" / "envs" / "infinigen" / "bin" / "python",
                   Path("/opt/conda/envs/infinigen/bin/python")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Infinigen bpy Python is unavailable; set INFINIGEN_PYTHON")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-blend", type=Path, required=True)
    parser.add_argument("--registry", type=Path,
                        default=REPO_ROOT / "configs" / "infinigen" / "prop_pbr_registry_v1.json")
    parser.add_argument("--out-blend", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--target-prop-count", type=int)
    return parser.parse_args()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _existing_matches(out_blend: Path, manifest: Path, composition: dict) -> bool:
    if not out_blend.is_file() or not manifest.is_file():
        return False
    try:
        current = _read(manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (current.get("profile") == PROFILE
            and current.get("composition_digest") == composition["composition_digest"]
            and current.get("registry_digest") == composition["registry_digest"])


def main() -> int:
    args = _args()
    source, registry_path = args.source_blend.resolve(), args.registry.resolve()
    out_blend, manifest = args.out_blend.resolve(), args.manifest.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    registry = _read(registry_path)
    composition = composition_contract(registry, seed=args.seed, target_count=args.target_prop_count)
    composition["registry_path"] = str(registry_path)
    composition["source_blend"] = str(source)
    composition["source_blend_digest"] = stable_digest({"path": str(source), "size": source.stat().st_size})
    composition["registry_digest"] = registry_digest(registry)
    # Recompute after durable input provenance is present.
    composition["composition_digest"] = stable_digest({key: value for key, value in composition.items() if key != "composition_digest"})
    if _existing_matches(out_blend, manifest, composition):
        print(f"[ir-showcase] reuse verified composition: {out_blend}")
        return 0
    if out_blend.exists() or manifest.exists():
        raise RuntimeError("existing showcase artifact has different provenance; choose a new attempt root")
    out_blend.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ir-showcase-", dir=out_blend.parent) as temporary:
        contract = Path(temporary) / "composition_contract.json"
        contract.write_text(json.dumps(composition, ensure_ascii=False, indent=2), encoding="utf-8")
        # Native Infinigen factories depend on packages (for example tqdm)
        # installed in the Infinigen environment but absent from Blender's
        # bundled Python.  The repository's bpy runner opens the same blend in
        # that complete environment and avoids silently weakening factories.
        command = [str(_infinigen_python()), str(BPY_RUNNER), str(source), str(COMPOSER), "--",
                   "--composition", str(contract), "--out-blend", str(out_blend), "--manifest", str(manifest)]
        completed = subprocess.run(command, cwd=REPO_ROOT)
        if completed.returncode:
            raise RuntimeError(f"showcase Blender composition exited with {completed.returncode}")
    if not _existing_matches(out_blend, manifest, composition):
        raise RuntimeError("showcase composition did not publish matching immutable provenance")
    print(json.dumps({"profile": PROFILE, "derived_blend": str(out_blend), "manifest": str(manifest),
                      "composition_digest": composition["composition_digest"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
