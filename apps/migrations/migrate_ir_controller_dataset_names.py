#!/usr/bin/env python3
"""Repair legacy controller jobs that shared one dataset/pipeline name.

The controller must be stopped before running this migration.  Generated
Infinigen source artifacts are not moved: only the durable job binding and its
future IR artifact roots are rewritten.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile


SOURCE_RE = re.compile(r"^kr_(\d{8})_(.+)$")


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _canonical_scene_id(request: dict) -> str:
    source = Path(str(request["existing_output"]))
    match = SOURCE_RE.fullmatch(source.parent.name)
    if not match:
        raise RuntimeError(f"cannot derive canonical scene ID from {source.parent.name}")
    date, descriptor = match.groups()
    return f"infinigen_{descriptor}_{date}"


def _paths(work_root: Path, bean_root: Path, dataset_name: str) -> dict[str, str]:
    pipeline = work_root / ".pipeline" / dataset_name
    return {
        "pipeline": str(pipeline),
        "geometry": str(pipeline / "ir_geometry"),
        "prepared": str(pipeline / "principled_stage2"),
        "qc": str(pipeline / "qc_stage0"),
        "render_plan": str(pipeline / "render_plan.json"),
        "qc_render_plan": str(pipeline / "qc_render_plan.json"),
        "dataset": str(work_root / dataset_name),
        "published": str(bean_root / dataset_name),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-name", required=True)
    parser.add_argument("--work-root", type=Path, default=Path("/bean/ir_dataset_work"))
    parser.add_argument("--bean-root", type=Path, default=Path("/bean/ir_dataset"))
    args = parser.parse_args()
    control = args.work_root / ".control" / "jobs"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    migrated: list[tuple[str, str, bool]] = []

    for snapshot in sorted(control.glob("*.json")):
        value = json.loads(snapshot.read_text(encoding="utf-8"))
        request = value.get("request") or {}
        if request.get("dataset_name") != args.old_name:
            continue
        if value.get("status") == "running" or value.get("pid"):
            raise RuntimeError(f"job {value.get('job_id')} is still running")

        scene_id = _canonical_scene_id(request)
        dataset_name = f"{scene_id}_rgb_active_nir_v2"
        paths = _paths(args.work_root, args.bean_root, dataset_name)
        collisions = [Path(paths[key]) for key in ("pipeline", "dataset", "published") if Path(paths[key]).exists()]
        if collisions:
            raise FileExistsError(f"destination already exists for {dataset_name}: {collisions}")

        source_complete = (Path(request["existing_output"]) / "scene.blend").is_file()
        request["scene_id"] = scene_id
        request["dataset_name"] = dataset_name
        request["paths"] = paths
        value["request"] = request
        value["paths"] = paths
        value["status"] = "queued"
        value["stage"] = "queued"
        value["error"] = None
        value["pid"] = None
        value["current_command"] = None
        value["finished_at"] = None
        value["updated_at"] = now
        value["resource_class"] = "blender_heavy" if source_complete else "infinigen_generate"
        value["resource_state"] = "waiting_resource"
        value["queue_position"] = None
        results = value.get("stage_results") or {}
        value["stage_results"] = ({"generate": results["generate"]}
                                  if source_complete and results.get("generate", {}).get("status") == "succeeded"
                                  else {})
        _atomic_json(snapshot, value)

        log_path = snapshot.with_suffix(".jsonl")
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "at": now,
                "event": "dataset_binding_migrated",
                "old_dataset_name": args.old_name,
                "dataset_name": dataset_name,
                "scene_id": scene_id,
                "source_complete": source_complete,
            }, ensure_ascii=False) + "\n")
        migrated.append((value["job_id"], dataset_name, source_complete))

    for job_id, name, complete in migrated:
        print(f"{job_id} -> {name} generate_reused={str(complete).lower()}")
    print(f"migrated={len(migrated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
