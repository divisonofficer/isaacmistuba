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
from mitsuba_converter.ir_material_mix import audit_material_mix
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


def _latest_artifact(pipeline: Path, relative: str) -> Path | None:
    """Return the newest root/attempt artifact for a legacy pipeline.

    Controller recovery keeps immutable attempts instead of copying every
    successful diagnostic back to the pipeline root.  Catalog backfill must
    therefore use the same newest-attempt convention as render-plan recovery.
    """
    candidates = [pipeline / relative, *pipeline.glob(f"attempts/**/{relative}")]
    existing = [path for path in candidates if path.is_file()]
    return max(existing, key=lambda path: path.stat().st_mtime_ns) if existing else None


def _resolve_render_plan(dataset: Path, config: dict, pipeline_root: Path) -> Path:
    """Resolve the immutable plan bound into a dataset contract.

    Most datasets retain their plan at ``.pipeline/<dataset>/render_plan.json``.
    Contract-upgrade children deliberately keep the plan under the parent
    pipeline's ``contract_upgrades/<attempt>/`` directory instead.  The output
    dataset contract already records the authoritative digest, so use it rather
    than guessing from a similarly named pipeline directory.
    """
    expected = str(((config.get("render_plan") or {}).get("render_plan_digest")) or "")
    conventional = pipeline_root / dataset.name
    candidates = [conventional / "render_plan.json",
                  *conventional.glob("attempts/**/render_plan.json")]
    # Contract-upgrade children do not share their output name with the parent
    # pipeline.  This scan is bounded to pipeline artifacts and is only used
    # when a plan digest binds the output to a specific candidate.
    if expected:
        candidates.extend(pipeline_root.glob("*/contract_upgrades/**/render_plan.json"))
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise FileNotFoundError("matching render_plan.json is unavailable")
    if expected:
        matching = []
        for path in existing:
            try:
                if str(_read(path).get("render_plan_digest") or "") == expected:
                    matching.append(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        if not matching:
            raise FileNotFoundError("dataset render-plan digest is unavailable")
        return max(matching, key=lambda path: path.stat().st_mtime_ns)
    return max(existing, key=lambda path: path.stat().st_mtime_ns)


def _room_type(scene_id: str) -> str:
    prefix = "infinigen_single_room_" if scene_id.startswith("infinigen_single_room_") else "infinigen_"
    value = scene_id.removeprefix(prefix).rsplit("_", 1)[0]
    return value.replace("_", "-") if value else "generic"


def _selected_plan_with_utility(plan: dict, visibility: dict) -> dict:
    result = deepcopy(plan)
    candidates = visibility.get("candidates") or {}
    by_viewpoint: dict[str, list[tuple[float, dict]]] = {}
    for key, utility in candidates.items():
        try:
            viewpoint, heading = key.split("@", 1)
            by_viewpoint.setdefault(viewpoint, []).append((float(heading), utility))
        except (TypeError, ValueError):
            continue
    all_options = [(float(key.split("@", 1)[1]), utility) for key, utility in candidates.items() if "@" in key]
    for group in result.get("groups") or []:
        for pose in group.get("poses") or []:
            key = f"{pose.get('viewpoint_id')}@{float(pose.get('heading_deg', 0.0)) % 360.0:.6f}"
            utility = candidates.get(key)
            if utility is None:
                options = by_viewpoint.get(str(pose.get("viewpoint_id")), [])
                if options:
                    target = float(pose.get("heading_deg", 0.0)) % 360.0
                    utility = min(options, key=lambda item: abs((item[0] - target + 180.0) % 360.0 - 180.0))[1]
            if utility is None and all_options:
                # Some old datasets were rendered from a graph snapshot that
                # is no longer installed. Keep the density estimate useful by
                # using the nearest candidate utility and mark provenance as
                # backfilled; this never changes rendered artifacts.
                target = float(pose.get("heading_deg", 0.0)) % 360.0
                utility = min(all_options, key=lambda item: abs((item[0] - target + 180.0) % 360.0 - 180.0))[1]
            if utility is None:
                # The source graph may have been regenerated after rendering.
                # Preserve the pose in the report and let the classifier use
                # source object density; visibility is explicitly recorded as
                # unavailable rather than silently fabricated.
                utility = {"visible_object_count": None, "nonstructural_fraction": None,
                           "utility_class": "visibility_unavailable"}
            pose["utility"] = utility
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


def _dedupe_physical_plan(plan: dict) -> dict:
    """Collapse lighting-expanded poses for scene-density statistics.

    Illumination-diversity plans contain one copy of every physical pose per
    condition.  Counting those copies as independent camera poses both
    inflates the selected count and makes visibility medians meaningless.
    Keep the first copy (the pose itself is lighting-independent) and preserve
    an explicit unavailable utility so the classifier falls back to source
    inventory density when the old graph cannot be probed reliably.
    """
    result = deepcopy(plan)
    seen: set[tuple[str, float]] = set()
    groups = []
    for group in result.get("groups") or []:
        poses = []
        for pose in group.get("poses") or []:
            key = (str(pose.get("viewpoint_id") or ""), round(float(pose.get("heading_deg", 0.0)) % 360.0, 6))
            if key in seen:
                continue
            seen.add(key)
            poses.append({**pose, "utility": {"visible_object_count": None,
                                                  "nonstructural_fraction": None,
                                                  "utility_class": "visibility_unavailable"}})
        if poses:
            groups.append({**group, "poses": poses})
    result["groups"] = groups
    result["physical_pose_count"] = len(seen)
    return result


def _build(dataset: Path, pipeline_root: Path, scene_root: Path, *,
           room_type_overrides: dict[str, str] | None = None,
           source_density_only: bool = False) -> tuple[dict, dict]:
    config = _read(dataset / "dataset_config.json")
    fingerprint = str(config.get("dataset_fingerprint") or "")
    plan_path = _resolve_render_plan(dataset, config, pipeline_root)
    # The material/visibility reports are produced alongside the resolved
    # render plan, including contract-upgrade attempts.
    pipeline = plan_path.parent
    plan = _read(plan_path)
    scene_id = str(plan.get("scene_id") or "")
    authoring_path = scene_root / scene_id / "authoring_map.json"
    graph_path = scene_root / scene_id / "viewpoint_graph.json"
    if not authoring_path.is_file() or not graph_path.is_file():
        raise FileNotFoundError(f"source graph/authoring-map is unavailable for {scene_id}")
    authoring, graph = _read(authoring_path), _read(graph_path)
    room_type = (room_type_overrides or {}).get(scene_id) or _room_type(scene_id)
    content = audit_scene_content(authoring, room_type=room_type, profile="balanced")
    visibility = probe_candidates(_selected_graph(graph, plan), authoring, fov_deg=float(config.get("fov") or 60.0))
    selected_plan = _dedupe_physical_plan(plan) if source_density_only else _selected_plan_with_utility(plan, visibility)
    material_mix_path = _latest_artifact(pipeline, "material_mix_quality.json")
    material_visibility_path = _latest_artifact(pipeline, "qc_stage0/material_visibility_qc.json")
    material_contract_path = _latest_artifact(pipeline, "principled_stage2/principled_material_contract.json")
    material_mix = _read(material_mix_path) if material_mix_path else None
    if material_mix is None and material_contract_path:
        material_mix = audit_material_mix(_read(material_contract_path))
    material_visibility = _read(material_visibility_path) if material_visibility_path else None
    statistics = build_scene_statistics(content_audit=content, visibility=visibility,
                                        render_plan=selected_plan,
                                        requested_density="backfilled",
                                        material_mix=material_mix,
                                        material_visibility=material_visibility)
    if source_density_only:
        statistics["visibility_provenance"] = "source_inventory_only"
        statistics["visibility_note"] = "Physical pose visibility was unavailable or invalid for this lighting-expanded child; density is classified from the bound authoring inventory and room footprint."
    source_paths = [plan_path, authoring_path, graph_path]
    source_paths.extend(path for path in (material_mix_path, material_visibility_path, material_contract_path)
                        if path is not None)
    sources = [{"path": str(path.resolve()), "sha256": _sha256(path)} for path in source_paths]
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
    parser.add_argument("--room-type-override", action="append", default=[], metavar="SCENE_ID=ROOM_TYPE",
                        help="Override room type parsing for generated scene IDs (repeatable).")
    parser.add_argument("--source-density-only", action="store_true",
                        help="Classify density from bound authoring inventory/footprint and deduplicated physical poses.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    wanted = set(args.dataset)
    room_type_overrides = {}
    for item in args.room_type_override:
        if "=" not in item:
            parser.error(f"--room-type-override must be SCENE_ID=ROOM_TYPE: {item}")
        scene_id, room_type = item.split("=", 1)
        room_type_overrides[scene_id.strip()] = room_type.strip()
    reports, failures = [], []
    for dataset in sorted(args.dataset_root.iterdir(), key=lambda item: item.name):
        if wanted and dataset.name not in wanted or not (dataset / "dataset_config.json").is_file():
            continue
        try:
            statistics, report = _build(dataset, args.pipeline_root, args.scene_root,
                                        room_type_overrides=room_type_overrides,
                                        source_density_only=args.source_density_only)
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
