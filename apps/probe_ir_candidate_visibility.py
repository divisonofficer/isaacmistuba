#!/usr/bin/env python3
"""Build the cheap content-visibility contract used by IR render-plan v2."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mitsuba_converter.ir_view_utility import probe_candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--authoring-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fov", type=float, default=70.0)
    parser.add_argument("--ray-count", type=int, default=96)
    args = parser.parse_args()
    result = probe_candidates(json.loads(args.graph.read_text(encoding="utf-8")),
                              json.loads(args.authoring_map.read_text(encoding="utf-8")),
                              fov_deg=args.fov, ray_count=args.ray_count)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({key: result[key] for key in ("candidate_count", "class_counts", "probe_digest")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
