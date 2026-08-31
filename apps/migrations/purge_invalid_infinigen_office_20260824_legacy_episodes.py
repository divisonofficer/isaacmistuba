#!/usr/bin/env python3
"""Remove the 50 known-invalid legacy graph episodes for Infinigen Office 0824.

The migration is deliberately narrow and dry-run by default.  It refuses to
delete anything unless all 50 target manifests are present and the scene render
ledger has no queued/rendered task records, then rebuilds the scene index,
scene dataset, and project catalog from the remaining files.

    python apps/migrations/purge_invalid_infinigen_office_20260824_legacy_episodes.py
    python apps/migrations/purge_invalid_infinigen_office_20260824_legacy_episodes.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
NAV_SRC = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(NAV_SRC) not in sys.path:
    sys.path.insert(0, str(NAV_SRC))

from navigation_dataset.scene_dataset import (  # noqa: E402
    SceneDatasetPaths,
    write_episode_index,
    write_project_catalog,
    write_scene_dataset,
)


PROJECT_ID = "opticalnav-v0.2"
SCENE_ID = "infinigen_office_20260824"
EXPECTED_COUNT = 50


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _ledger_counts(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {"sweep_tasks": 0, "sweep_runs": 0, "request_blobs": 0}
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("sweep_tasks", "sweep_runs", "request_blobs")
        }


def run(*, project_id: str = PROJECT_ID, scene_id: str = SCENE_ID, apply: bool = False) -> dict[str, Any]:
    project_dir = REPO_ROOT / "out" / "opticalnav" / project_id
    paths = SceneDatasetPaths.from_project(project_dir, scene_id)
    if not paths.scene_dir.is_dir():
        raise FileNotFoundError(paths.scene_dir)
    targets: list[Path] = []
    ignored: list[str] = []
    for path, episode in paths.iter_episodes():
        is_target = (
            episode.navigation_mode == "viewpoint_graph"
            and episode.episode_id.startswith(f"{scene_id}_")
            and "_graph_" in episode.episode_id
        )
        if is_target:
            targets.append(path)
        else:
            ignored.append(path.relative_to(paths.scene_dir).as_posix())
    ledger_counts = _ledger_counts(paths.ledger_path)
    report: dict[str, Any] = {
        "migration": "purge_invalid_infinigen_office_20260824_legacy_episodes_v1",
        "project_id": project_id,
        "scene_id": scene_id,
        "mode": "apply" if apply else "dry_run",
        "expected_target_count": EXPECTED_COUNT,
        "target_count": len(targets),
        "targets": [path.relative_to(paths.scene_dir).as_posix() for path in targets],
        "non_target_episode_count": len(ignored),
        "ledger_counts": ledger_counts,
        "render_artifacts_deleted": False,
    }
    if len(targets) != EXPECTED_COUNT:
        raise RuntimeError(f"expected exactly {EXPECTED_COUNT} legacy graph episodes, found {len(targets)}")
    if any(ledger_counts.values()):
        raise RuntimeError("render ledger is not empty; refusing to remove episode manifests")
    if not apply:
        return report
    for path in targets:
        path.unlink()
    index = write_episode_index(paths)
    scene_dataset = write_scene_dataset(paths)
    project_catalog = write_project_catalog(project_dir)
    report.update({
        "deleted_episode_count": len(targets),
        "episode_index_total": index["total"],
        "scene_episode_count": scene_dataset["episode_count"],
        "project_scene_count": len(project_catalog.get("scenes") or []),
    })
    _atomic_json(project_dir / "reports" / "purge_invalid_infinigen_office_20260824_legacy_episodes.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--scene", default=SCENE_ID)
    parser.add_argument("--apply", action="store_true", help="Delete only the verified 50 manifests.")
    args = parser.parse_args()
    result = run(project_id=args.project, scene_id=args.scene, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.apply:
        print("dry-run only; re-run with --apply after reviewing the target list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
