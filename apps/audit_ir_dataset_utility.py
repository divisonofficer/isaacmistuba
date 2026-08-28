#!/usr/bin/env python3
"""Gate and embed content-aware camera selection provenance before publish."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from mitsuba_converter.ir_scene_statistics import build_scene_statistics


def _pose_utility(pose: dict) -> dict:
    """Return the planner utility for a pose, including showcase poses.

    Showcase camera sets use arbitrary anchor headings and therefore are not
    present in the 15-degree candidate visibility grid.  Their render-plan
    probe is the authoritative visibility measurement; falling back to a raw
    candidate lookup marked every lighting-expanded frame as rejected.
    """
    utility = pose.get("utility")
    if isinstance(utility, dict) and utility.get("utility_class"):
        return utility
    probe = pose.get("probe")
    if not isinstance(probe, dict):
        return {}
    if probe.get("severe_occlusion") or float(probe.get("camera_clearance_m", 0) or 0) < 0.35:
        cls = "rejected"
    elif int(probe.get("specular_eligible_object_count", 0) or 0) > 0 or int(probe.get("visible_pbr_object_count", 0) or 0) >= 2:
        cls = "informative"
    elif int(probe.get("visible_pbr_object_count", 0) or 0) > 0:
        cls = "structural"
    else:
        cls = "sparse_negative"
    return {**probe, "utility_class": cls}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--render-plan", type=Path, required=True)
    parser.add_argument("--visibility", type=Path, required=True)
    parser.add_argument("--content-audit", type=Path, required=True)
    parser.add_argument("--requested-density", default=None)
    parser.add_argument("--material-mix", type=Path)
    parser.add_argument("--material-visibility", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.render_plan.read_text(encoding="utf-8"))
    visibility = json.loads(args.visibility.read_text(encoding="utf-8"))
    content = json.loads(args.content_audit.read_text(encoding="utf-8"))
    selected = [pose for group in plan.get("groups") or [] for pose in group.get("poses") or []]
    classes = {name: 0 for name in ("informative", "structural", "sparse_negative", "rejected")}
    enriched_selected = []
    for pose in selected:
        key = f"{pose['viewpoint_id']}@{float(pose['heading_deg']) % 360.0:.6f}"
        utility = _pose_utility(pose)
        # Non-showcase plans carry a candidate-grid utility.  Showcase plans
        # carry an anchor probe; only use the grid when the plan has neither.
        if not utility.get("utility_class"):
            utility = (visibility.get("candidates") or {}).get(key, {})
        utility_class = utility.get("utility_class", "rejected")
        classes[utility_class] = classes.get(utility_class, 0) + 1
        enriched_selected.append({**pose, "utility": utility})
    total = max(len(selected), 1)
    failures = []
    if classes.get("rejected", 0): failures.append("rejected_view_selected")
    if classes.get("sparse_negative", 0) / total > 0.150001: failures.append("sparse_negative_quota")
    if content.get("status") != "passed": failures.append("scene_content_contract")
    report = {"schema": "robomituba.ir_dataset_utility_audit.v1", "status": "failed" if failures else "passed",
              "selected_pose_count": len(selected), "selected_class_counts": classes,
              "sparse_negative_fraction": classes.get("sparse_negative", 0) / total,
              "render_plan_digest": plan.get("render_plan_digest"), "probe_digest": visibility.get("probe_digest"),
              "content_audit_digest": content.get("audit_digest"), "failures": failures}
    quality = args.dataset / "quality"
    quality.mkdir(parents=True, exist_ok=True)
    for source, name in ((args.render_plan, "render_plan.json"), (args.visibility, "candidate_visibility.json"),
                         (args.content_audit, "scene_content_audit.json")):
        shutil.copy2(source, quality / name)
    for source, name in ((args.material_mix, "material_mix_quality.json"),
                         (args.material_visibility, "material_visibility_qc.json")):
        if source and source.is_file():
            shutil.copy2(source, quality / name)
    material_mix = json.loads(args.material_mix.read_text(encoding="utf-8")) if args.material_mix and args.material_mix.is_file() else None
    material_visibility = json.loads(args.material_visibility.read_text(encoding="utf-8")) if args.material_visibility and args.material_visibility.is_file() else None
    statistics_plan = dict(plan)
    statistics_plan["groups"] = [{**group, "poses": [p for p in enriched_selected
                                                         if p in group.get("poses", [])]}
                                  for group in (plan.get("groups") or [])]
    statistics = build_scene_statistics(content_audit=content, visibility=visibility, render_plan=statistics_plan,
                                        requested_density=args.requested_density, material_mix=material_mix,
                                        material_visibility=material_visibility)
    (quality / "scene_statistics.json").write_text(json.dumps(statistics, ensure_ascii=False, indent=2), encoding="utf-8")
    (quality / "dataset_utility_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
