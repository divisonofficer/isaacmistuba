#!/usr/bin/env python3
"""Repair OpticalNav scenes that reference a nonexistent source USD.

The repair never re-renders a scene and never touches render XML, mesh/texture
caches, observations, or jobs.  It only clears invalid ``usd_ref`` metadata and
writes an XML-native or authoring-map editor geometry sidecar.

Examples:
  python apps/migrations/repair_opticalnav_editor_geometry.py --project opticalnav-v0.2
  python apps/migrations/repair_opticalnav_editor_geometry.py --project opticalnav-v0.2 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
for source in (
    "modules/mitsuba_converter/src",
    "modules/robomituba_bridge/src",
):
    path = REPO_ROOT / source
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mitsuba_converter.editor_geometry_fallback import (  # noqa: E402
    build_non_usd_editor_geometry,
    write_json_atomic,
)
from robomituba_bridge import resolve_repo_path  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _invalid_usd_ref(usd_ref: Any) -> bool:
    if not isinstance(usd_ref, str) or not usd_ref.strip():
        return False
    try:
        return not resolve_repo_path(REPO_ROOT, usd_ref).is_file()
    except Exception:
        return True


def _scene_entry_index(dataset: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in dataset.get("scenes") or []:
        if isinstance(entry, dict) and isinstance(entry.get("scene_id"), str):
            index[entry["scene_id"]] = entry
    return index


def repair_project(project_id: str, *, apply: bool, scene_ids: set[str] | None = None) -> dict[str, Any]:
    project_dir = REPO_ROOT / "out" / "opticalnav" / project_id
    if not project_dir.is_dir():
        raise FileNotFoundError(project_dir)
    dataset_path = project_dir / "dataset.json"
    dataset = _read_json(dataset_path) if dataset_path.is_file() else {}
    dataset_entries = _scene_entry_index(dataset)
    records: list[dict[str, Any]] = []
    dataset_changed = False

    for scene_dir in sorted((project_dir / "scenes").glob("*")):
        if not scene_dir.is_dir() or (scene_ids and scene_dir.name not in scene_ids):
            continue
        annotation_path = scene_dir / "scene_annotation.json"
        if not annotation_path.is_file():
            continue
        try:
            annotation = _read_json(annotation_path)
        except Exception as exc:
            records.append({"scene_id": scene_dir.name, "status": "error", "error": str(exc)})
            continue
        usd_ref = annotation.get("usd_ref")
        if not _invalid_usd_ref(usd_ref):
            records.append({"scene_id": scene_dir.name, "status": "skipped", "reason": "usd_ref_valid_or_absent"})
            continue

        geometry = build_non_usd_editor_geometry(
            scene_dir,
            scene_dir.name,
            usd_ref=str(usd_ref),
            reason=f"Repaired nonexistent USD ref: {usd_ref}",
        )
        geometry["migration"] = "repair_opticalnav_editor_geometry_v1"
        annotation["usd_ref"] = None
        entry = dataset_entries.get(scene_dir.name)
        if entry is not None:
            entry["usd_ref"] = None
            dataset_changed = True
        record = {
            "scene_id": scene_dir.name,
            "status": "repaired" if geometry.get("status") == "ready" else "repaired_unavailable",
            "previous_usd_ref": usd_ref,
            "source": geometry.get("source"),
        }
        records.append(record)
        if apply:
            write_json_atomic(annotation_path, annotation)
            write_json_atomic(scene_dir / "editor_geometry.json", geometry)

    summary: dict[str, Any] = {
        "migration": "repair_opticalnav_editor_geometry_v1",
        "project_id": project_id,
        "mode": "apply" if apply else "dry_run",
        "summary": {
            "repaired": sum(1 for item in records if item["status"] == "repaired"),
            "repaired_unavailable": sum(1 for item in records if item["status"] == "repaired_unavailable"),
            "skipped": sum(1 for item in records if item["status"] == "skipped"),
            "errors": sum(1 for item in records if item["status"] == "error"),
        },
        "source_counts": {
            source: sum(1 for item in records if item.get("source") == source)
            for source in ("xml_native", "authoring_map", "fallback")
        },
        "scenes": records,
    }
    if apply:
        if dataset_changed and dataset_path.is_file():
            write_json_atomic(dataset_path, dataset)
        write_json_atomic(project_dir / "reports" / "editor_geometry_usd_ref_repair.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--scene", action="append", default=[], help="Limit repair to one or more scene ids.")
    parser.add_argument("--apply", action="store_true", help="Write metadata and sidecars (default: dry-run).")
    args = parser.parse_args()
    result = repair_project(args.project, apply=args.apply, scene_ids=set(args.scene) or None)
    print(json.dumps({key: value for key, value in result.items() if key != "scenes"}, ensure_ascii=False, indent=2))
    if not args.apply:
        print("dry-run only; re-run with --apply to write repaired metadata.")
    return 0 if result["summary"]["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
