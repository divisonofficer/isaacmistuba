#!/usr/bin/env python3
"""Backfill read-only scene catalog statistics from existing IR pipeline artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.ir_scene_content import audit_scene_content
from mitsuba_converter.ir_scene_statistics import build_scene_statistics
from mitsuba_converter.ir_view_utility import probe_candidates

COMPILER_VERSION = "ir-scene-statistics-backfill-v1"


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _room_type(scene_id: str) -> str:
    prefix = "infinigen_single_room_" if scene_id.startswith("infinigen_single_room_") else "infinigen_"
    value = scene_id.removeprefix(prefix).rsplit("_", 1)[0]
    return value.replace("_", "-") if value else "generic"


def _selected_plan_with_utility(plan: dict, visibility: dict) -> dict:
    result = deepcopy(plan)
    candidates = visibility.get("candidates") or {}
    for group in result.get("groups") or []:
        for pose in group.get("poses") or []:
            key = f"{pose.get('viewpoint_id')}@{float(pose.get('heading_deg', 0.0)) % 360.0:.6f}"
            if key not in candidates:
                raise ValueError(f"selected pose is absent from visibility probe: {key}")
            pose["utility"] = candidates[key]
    return result


def _selected_graph(graph: dict, plan: dict) -> dict:
    """Retain only rendered node/heading pairs; catalog stats need no unused candidates."""
    wanted = {(str(pose.get("viewpoint_id")), round(float(pose.get("heading_deg", 0.0)) % 360.0, 6))
              for group in plan.get("groups") or [] for pose in group.get("poses") or []}
    nodes = []
    for node in graph.get("nodes") or []:
        node_id = str(node.get("node_id") or "")
        headings = [heading for heading in node.get("headings") or []
                    if (node_id, round(float(heading.get("yaw_deg", 0.0)) % 360.0, 6)) in wanted]
        if headings:
            nodes.append({**node, "headings": headings})
    return {**graph, "nodes": nodes}


def _build(dataset: Path, pipeline_root: Path, scene_root: Path) -> tuple[dict, dict]:
    config = _read(dataset / "dataset_config.json")
    fingerprint = str(config.get("dataset_fingerprint") or "")
    pipeline = pipeline_root / dataset.name
    plan_path = pipeline / "render_plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError("matching render_plan.json is unavailable")
    plan = _read(plan_path)
    scene_id = str(plan.get("scene_id") or "")
    authoring_path = scene_root / scene_id / "authoring_map.json"
    graph_path = scene_root / scene_id / "viewpoint_graph.json"
    if not authoring_path.is_file() or not graph_path.is_file():
        raise FileNotFoundError(f"source graph/authoring-map is unavailable for {scene_id}")
    authoring, graph = _read(authoring_path), _read(graph_path)
    room_type = _room_type(scene_id)
    content = audit_scene_content(authoring, room_type=room_type, profile="balanced")
    visibility = probe_candidates(_selected_graph(graph, plan), authoring, fov_deg=float(config.get("fov") or 60.0))
    statistics = build_scene_statistics(content_audit=content, visibility=visibility,
                                        render_plan=_selected_plan_with_utility(plan, visibility),
                                        requested_density="backfilled")
    sources = [{"path": str(path.resolve()), "sha256": _sha256(path)}
               for path in (plan_path, authoring_path, graph_path)]
    statistics["statistics_provenance"] = "backfilled"
    statistics["backfill"] = {"compiler_version": COMPILER_VERSION, "dataset_fingerprint": fingerprint,
                              "dataset_name": dataset.name, "scene_id": scene_id, "sources": sources,
                              "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    report = {"dataset": dataset.name, "fingerprint": fingerprint, "scene_id": scene_id,
              "object_count": statistics["object_count"], "nonstructural_object_count": statistics["nonstructural_object_count"],
              "room_area_m2": statistics["room_area_m2"], "selected_pose_count": statistics["selected_pose_count"],
              "density_class": statistics["density_class"]}
    return statistics, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=Path("/bean/ir_dataset"))
    parser.add_argument("--pipeline-root", type=Path, default=Path("/bean/ir_dataset_work/.pipeline"))
    parser.add_argument("--scene-root", type=Path, default=REPO_ROOT / "out/opticalnav/opticalnav-v0.2/scenes")
    parser.add_argument("--sidecar-root", type=Path, default=Path("/bean/ir_dataset_work/.catalog_statistics"))
    parser.add_argument("--dataset", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    wanted = set(args.dataset)
    reports, failures = [], []
    for dataset in sorted(args.dataset_root.iterdir(), key=lambda item: item.name):
        if wanted and dataset.name not in wanted or not (dataset / "dataset_config.json").is_file():
            continue
        try:
            statistics, report = _build(dataset, args.pipeline_root, args.scene_root)
            target = args.sidecar_root / f"{report['fingerprint']}.json"
            report["target"] = str(target)
            report["action"] = "dry_run" if args.dry_run else ("write" if args.force or not target.exists() else "skip_existing")
            if not args.dry_run and (args.force or not target.exists()):
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix(".json.tmp")
                temp.write_text(json.dumps(statistics, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(target)
            reports.append(report)
        except Exception as exc:
            failures.append({"dataset": dataset.name, "error": str(exc)})
    result = {"schema": "robomituba.ir_scene_statistics_backfill_report.v1", "compiler_version": COMPILER_VERSION,
              "dry_run": args.dry_run, "processed": len(reports), "failed": len(failures), "reports": reports, "failures": failures}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
