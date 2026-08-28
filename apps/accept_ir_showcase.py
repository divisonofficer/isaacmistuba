#!/usr/bin/env python3
"""Apply the durable showcase primary-frame and camera-set acceptance gates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))
from mitsuba_converter.ir_showcase import PROFILE, acceptance_report, stable_digest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--composition", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    composition = json.loads(args.composition.read_text(encoding="utf-8"))
    if probe.get("profile") != PROFILE or composition.get("profile") != PROFILE:
        raise RuntimeError("showcase profile provenance mismatch")
    report = acceptance_report(probe.get("camera_sets") or {}, composition=composition, probe=probe)
    set_metrics = probe.get("set_metrics") or {}
    failures = list(report["failures"])
    for set_id, metric in set_metrics.items():
        if int(metric.get("shared_object_count") or 0) < 8:
            failures.append(f"camera_set_shared_objects_below_8:{set_id}")
        if int(metric.get("union_object_count") or 0) < 12:
            failures.append(f"camera_set_union_objects_below_12:{set_id}")
        if not metric.get("no_severe_occlusion") or not metric.get("no_near_wall"):
            failures.append(f"camera_set_member_safety_failed:{set_id}")
        if any(int(count) < 2 for count in (metric.get("target_view_counts") or {}).values()):
            failures.append(f"camera_set_target_seen_fewer_than_2_views:{set_id}")
    report["set_metrics"] = set_metrics
    report["failures"] = sorted(set(failures))
    report["status"] = "passed" if not report["failures"] else "failed"
    report["acceptance_digest"] = stable_digest({key: value for key, value in report.items() if key != "acceptance_digest"})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({"status": report["status"], "actual_pose_count": report["actual_pose_count"], "failures": report["failures"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
