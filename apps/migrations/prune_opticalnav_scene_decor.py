#!/usr/bin/env python3
"""Prune shape-expensive, non-critical decoration from one OpticalNav scene."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT = "opticalnav-v0.2"
# Ordered from least task-relevant to more visible.  Whole-factory cuts keep the
# policy reproducible rather than selecting arbitrary object ids from one sync.
FACTORY_PRUNE_ORDER = (
    "NatureShelfTrinketsFactory",
    "BookStackFactory",
    "BookColumnFactory",
)


def plan_prune(
    objects: list[dict[str, Any]],
    shape_counts: Counter[str],
    *,
    target_shapes: int,
) -> dict[str, Any]:
    current = sum(shape_counts.values())
    selected_factories: list[str] = []
    removed_ids: list[str] = []
    removed_shapes = 0
    by_factory: dict[str, list[str]] = {}
    for obj in objects:
        metadata = obj.get("metadata") or {}
        navigation = obj.get("navigation") or {}
        # Generic Infinigen furniture imports mark many shelf trinkets as
        # instruction candidates automatically.  That is not a curated landmark
        # contract.  Preserve only actual goal/hazard/emitter roles here.
        if obj.get("is_emitter") or navigation.get("goal_candidate") or navigation.get("hazard_type"):
            continue
        factory = str(metadata.get("factory") or "")
        by_factory.setdefault(factory, []).append(str(obj.get("id") or ""))
    for factory in FACTORY_PRUNE_ORDER:
        if current - removed_shapes <= target_shapes:
            break
        ids = by_factory.get(factory) or []
        if not ids:
            continue
        selected_factories.append(factory)
        removed_ids.extend(ids)
        removed_shapes += sum(int(shape_counts.get(object_id, 0)) for object_id in ids)
    return {
        "current_shapes": current,
        "target_shapes": target_shapes,
        "result_shapes": current - removed_shapes,
        "removed_shapes": removed_shapes,
        "removed_object_ids": sorted(removed_ids),
        "removed_factories": selected_factories,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--target-shapes", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    scene_dir = REPO_ROOT / "out" / "opticalnav" / args.project / "scenes" / args.scene
    authoring_path = scene_dir / "authoring_map.json"
    materialization_path = scene_dir / "render_scene_materialization.json"
    authoring = json.loads(authoring_path.read_text(encoding="utf-8"))
    materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
    shape_counts: Counter[str] = Counter(
        str(record.get("object_id") or "") for record in materialization.get("objects") or []
    )
    plan = plan_prune(
        list(authoring.get("objects") or []), shape_counts,
        target_shapes=max(1, int(args.target_shapes)),
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.apply:
        return 0
    removed = set(plan["removed_object_ids"])
    if not removed:
        print("nothing to prune")
        return 0
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = scene_dir / "manual_backups" / f"{timestamp}_decor_prune"
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(authoring_path, backup_dir / "authoring_map.json")
    authoring["objects"] = [
        obj for obj in authoring.get("objects") or [] if str(obj.get("id") or "") not in removed
    ]
    metadata = dict(authoring.get("metadata") or {})
    metadata["decorative_shape_prune"] = {
        **plan,
        "applied_at": timestamp,
        "backup": str(backup_dir.relative_to(REPO_ROOT)),
    }
    authoring["metadata"] = metadata
    temporary = authoring_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(authoring, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, authoring_path)
    (scene_dir / "decorative_shape_prune.json").write_text(
        json.dumps(metadata["decorative_shape_prune"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"applied: objects={len(authoring['objects'])} backup={backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
