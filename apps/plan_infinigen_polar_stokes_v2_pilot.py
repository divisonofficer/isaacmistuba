#!/usr/bin/env python3
"""Write the reproducible 10-view RGB-Stokes v2 pilot contract.

This intentionally plans only the pilot.  It does not submit GPU jobs or mutate
the source scene; the resulting JSON is the reviewable input for the renderer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from navigation_dataset.polar_pilot import (
    build_pilot_contract,
    scores_from_base_previews,
    select_pilot_views,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument(
        "--heading-scores", type=Path,
        help="Optional JSON object keyed by 'node_id/heading_id'; overrides local base-preview scoring.",
    )
    args = parser.parse_args()
    graph_path = args.scene_dir / "viewpoint_graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if args.heading_scores:
        raw_scores = json.loads(args.heading_scores.read_text(encoding="utf-8"))
        if not isinstance(raw_scores, dict):
            raise SystemExit("--heading-scores must be a JSON object keyed by node_id/heading_id")
        scores = {
            tuple(str(key).split("/", 1)): float(value)
            for key, value in raw_scores.items()
            if "/" in str(key)
        }
        score_source = str(args.heading_scores)
    else:
        scores = scores_from_base_previews(args.scene_dir)
        score_source = "base_preview_low_resolution_content_score"
    views = select_pilot_views(graph, count=args.count, seed=args.seed, heading_scores=scores)
    if len(views) != args.count:
        raise SystemExit(f"graph contains only {len(views)} selectable views; expected {args.count}")
    payload = build_pilot_contract(
        scene_id=str(graph.get("scene_id") or args.scene_dir.name),
        graph_revision=str((graph.get("metadata") or {}).get("revision") or "") or None,
        views=views,
    )
    payload["selection"] = {
        "method": "graph_farthest_point + low_resolution_content_score",
        "seed": args.seed,
        "score_source": score_source,
        "scored_heading_count": len(scores),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "views": len(views), "captures": payload["expected_capture_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
