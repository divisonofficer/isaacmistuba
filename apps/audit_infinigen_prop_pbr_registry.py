#!/usr/bin/env python3
"""Run the reproducible native Infinigen prop/PBR audit outside a job attempt."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLENDER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
AUDIT = REPO_ROOT / "tools" / "infinigen" / "blender_audit_ir_showcase_registry.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path,
                        default=REPO_ROOT / "configs" / "infinigen" / "prop_pbr_registry_v1.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    candidates, out = args.candidates.resolve(), args.out.resolve()
    if not candidates.is_file():
        raise FileNotFoundError(candidates)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite audited registry: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(BLENDER), "--background", "--python", str(AUDIT), "--",
                             "--candidates", str(candidates), "--out", str(out)], cwd=REPO_ROOT)
    if result.returncode:
        raise RuntimeError(f"native prop/PBR registry audit exited with {result.returncode}")
    if not out.is_file():
        raise RuntimeError("native prop/PBR registry audit did not publish its registry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
