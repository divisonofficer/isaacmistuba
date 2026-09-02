#!/usr/bin/env python3
"""Derive the object anchors a 6-DoF camera pass orbits around."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))

from mitsuba_converter.ir_object_anchors import build_object_anchors  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--max-anchors", type=int, default=40)
    args = parser.parse_args()

    authoring = json.loads((args.scene_dir / "authoring_map.json").read_text(encoding="utf-8"))
    payload = build_object_anchors(authoring, seed=args.seed, max_anchors=args.max_anchors)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.out)
    print(f"[ir-object-anchors] {payload['anchor_count']} anchors "
          f"(digest {payload['anchor_digest'][:12]}) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
