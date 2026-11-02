#!/usr/bin/env python3
"""Recover an immutable V4 L0 render contract from its surviving L3 context.

This is deliberately an archive-only recovery.  It does not reactivate an old
Navigation Support graph after its Place Graph was edited; it only restores the
exact observation plan required to finish a render run that was already
submitted against the old validated digest.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from navigation_dataset.navigation_support import (
    PROFILE_ID,
    SUPPORT_ARCHIVE_DIR,
    recover_l0_observation_plan_from_expansion,
    support_render_graph,
)
from navigation_dataset.viewpoint_graph import write_viewpoint_graph


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "opticalnav-v0.2"
SCENE_ID = "infinigen_apartment_20260811"
L3_FILENAME = "support_observation_expansion_l3_context_45.json"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"expected a JSON object: {path}")
    return dict(payload)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--scene", default=SCENE_ID)
    parser.add_argument("--source-expansion", default=L3_FILENAME)
    parser.add_argument("--apply", action="store_true", help="write the immutable archive (default is dry-run)")
    args = parser.parse_args()

    scene_dir = REPO_ROOT / "out" / "opticalnav" / args.project / "scenes" / args.scene
    source_path = scene_dir / args.source_expansion
    expansion = _read_json(source_path)
    digest = str(expansion.get("profile_digest") or "")
    if str(expansion.get("profile_id") or "") != PROFILE_ID or len(digest) != 40:
        raise SystemExit("source is not a digest-qualified adaptive_navigation_support_v4 expansion")
    archive_rel = Path(SUPPORT_ARCHIVE_DIR) / digest
    support_ref = (archive_rel / "navigation_support_graph.json").as_posix()
    l0 = recover_l0_observation_plan_from_expansion(expansion, support_graph_ref=support_ref)
    if len(l0["render_entries"]) != 2454 or int(l0["summary"]["polar_batch_count"]) != 649:
        raise SystemExit("recovered L0 does not match the 2,454-view / 649-batch contract")
    l3 = dict(expansion)
    l3["support_graph_ref"] = support_ref
    l3["base_observation_plan_ref"] = (archive_rel / "support_observation_plan.json").as_posix()
    l3["recovery"] = {
        "kind": "archived_with_reconstructed_l0",
        "source": args.source_expansion,
        "profile_digest": digest,
    }
    l0_keys = {(str(entry["motion_node_id"]), str(entry["heading_id"])) for entry in l0["render_entries"]}
    l3_keys = {(str(entry["motion_node_id"]), str(entry["heading_id"])) for entry in l3.get("render_entries") or []}
    if len(l3_keys) != 1250 or l0_keys & l3_keys or len(l0_keys | l3_keys) != 3704:
        raise SystemExit("recovered L0/L3 logical coverage is not the required disjoint 3,704-view contract")
    capsule = {
        "schema_version": "opticalnav.navigation_support.render_recovery.v1",
        "profile_id": PROFILE_ID,
        "scene_id": args.scene,
        "place_graph_id": l0["place_graph_id"],
        "profile_digest": digest,
        "validation": {
            "ok": True,
            "digest": digest,
            "recovered_render_only": True,
            "source_expansion": args.source_expansion,
        },
        "recovery": {
            "active": False,
            "reason": "place_graph_invalidation_after_render_submission",
            "l0_logical_views": len(l0_keys),
            "l3_additional_logical_views": len(l3_keys),
        },
    }
    archive_dir = scene_dir / archive_rel
    report = {
        "archive_ref": archive_rel.as_posix(),
        "profile_digest": digest,
        "l0_logical_views": len(l0_keys),
        "l3_additional_logical_views": len(l3_keys),
        "total_per_variant": len(l0_keys | l3_keys),
        "apply": bool(args.apply),
    }
    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    _write_json(archive_dir / "navigation_support_graph.json", capsule)
    _write_json(archive_dir / "support_observation_plan.json", l0)
    _write_json(archive_dir / L3_FILENAME, l3)
    write_viewpoint_graph(archive_dir / "support_render_graph.json", support_render_graph(l0))
    _write_json(archive_dir / "archive_manifest.json", {
        "schema_version": "opticalnav.navigation_support_archive.v1",
        "profile_id": PROFILE_ID,
        "profile_digest": digest,
        "active": False,
        "recovered": True,
        "source_expansion": args.source_expansion,
        # Old L0 K=4 tasks were admitted before the topology edit and retain
        # this active-plan ref in their durable metadata.  The ledger resolves
        # only this explicit redirect; the archive never becomes active.
        "stale_render_plan_refs": [
            f"scenes/{args.scene}/support_observation_plan.json",
        ],
        "files": [
            "navigation_support_graph.json",
            "support_observation_plan.json",
            L3_FILENAME,
            "support_render_graph.json",
        ],
        **report,
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
