"""Resumable OpticalNav v2 project → v3 scene-workspace migration."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterator
import uuid

from .episode_schema import SPLITS, read_episode
from .scene_dataset import (
    PROJECT_CATALOG_VERSION,
    SCENE_LAYOUT_VERSION,
    SceneDatasetPaths,
    file_sha256,
    write_episode_index,
    write_project_catalog,
    write_scene_dataset,
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _migration_lock(root: Path) -> Iterator[Path]:
    lock = root / ".scene_workspace_v3.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"scene-layout migration is already locked: {lock}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "created_at": _timestamp()}) + "\n")
        yield lock
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _assert_no_active_legacy_runs(root: Path) -> None:
    ledger = root / "render_ledger.sqlite3"
    if not ledger.is_file():
        return
    try:
        connection = sqlite3.connect(f"file:{ledger.as_posix()}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = connection.execute(
                "SELECT scene_id, status, COUNT(*) FROM sweep_runs "
                "WHERE status IN ('queued', 'running') GROUP BY scene_id, status"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot verify active legacy render ledger: {exc}") from exc
    if rows:
        detail = ", ".join(f"{scene_id}:{status}={count}" for scene_id, status, count in rows)
        raise RuntimeError(f"refusing migration while render tasks are active: {detail}")


def _legacy_episode_groups(root: Path) -> tuple[dict[str, list[Path]], dict[str, str], list[dict[str, Any]]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    episode_scene: dict[str, str] = {}
    quarantine: list[dict[str, Any]] = []
    for split in SPLITS:
        for source in sorted((root / "episodes" / split).glob("*.json")):
            try:
                episode = read_episode(source)
            except Exception as exc:
                quarantine.append({"path": source.relative_to(root).as_posix(), "reason": f"invalid_episode:{type(exc).__name__}:{exc}"})
                continue
            if episode.split != split:
                quarantine.append({"path": source.relative_to(root).as_posix(), "reason": f"split_mismatch:{episode.split}"})
                continue
            if not episode.scene_id:
                quarantine.append({"path": source.relative_to(root).as_posix(), "reason": "missing_scene_id"})
                continue
            groups[episode.scene_id].append(source)
            episode_scene[episode.episode_id] = episode.scene_id
    return dict(groups), episode_scene, quarantine


def _legacy_contract_digest(root: Path, groups: dict[str, list[Path]]) -> str:
    """Fingerprint the legacy input cheaply enough for resume safety.

    Staged copies are already SHA-256 verified one by one. This digest detects
    a changed legacy source between an interrupted migration and resume without
    rehashing every original payload.
    """
    digest = hashlib.sha256()
    for scene_id in sorted(groups):
        for source in sorted(groups[scene_id]):
            stat = source.stat()
            digest.update(source.relative_to(root).as_posix().encode("utf-8"))
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    return digest.hexdigest()


def _find_resumable_stage(root: Path, contract_digest: str) -> tuple[Path, dict[str, Any]] | None:
    staging_root = root / ".scene_workspace_v3_staging"
    if not staging_root.is_dir():
        return None
    for candidate in sorted(staging_root.iterdir(), reverse=True):
        state_path = candidate / "migration_state.json"
        if not state_path.is_file():
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(state, dict)
            and state.get("status") in {"staged", "publishing"}
            and state.get("project_root") == root.as_posix()
            and state.get("contract_digest") == contract_digest
        ):
            return candidate, state
    return None


def _copy_scene_episodes(stage_root: Path, scene_id: str, sources: list[Path]) -> dict[str, Any]:
    paths = SceneDatasetPaths.from_project(stage_root, scene_id).ensure_layout()
    copied: list[dict[str, str]] = []
    for source in sources:
        episode = read_episode(source)
        destination = paths.episode_path(episode)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if file_sha256(source) != file_sha256(destination):
            raise RuntimeError(f"episode hash mismatch after staging copy: {source}")
        copied.append({"episode_id": episode.episode_id, "source": source.as_posix(), "sha256": file_sha256(destination)})
    index = write_episode_index(paths)
    write_scene_dataset(paths, metadata={"migrated_from_layout": "opticalnav_v2"})
    return {"scene_id": scene_id, "episodes": len(copied), "episode_digest": index["digest"], "copied": copied}


def _payload_scene_ids(value: Any, *, known_scenes: set[str], episode_scene: dict[str, str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        scene_id = value.get("scene_id")
        if isinstance(scene_id, str) and scene_id in known_scenes:
            found.add(scene_id)
        episode_id = value.get("episode_id")
        if isinstance(episode_id, str) and episode_id in episode_scene:
            found.add(episode_scene[episode_id])
        for child in value.values():
            found.update(_payload_scene_ids(child, known_scenes=known_scenes, episode_scene=episode_scene))
    elif isinstance(value, list):
        for child in value:
            found.update(_payload_scene_ids(child, known_scenes=known_scenes, episode_scene=episode_scene))
    return found


def _stage_legacy_batches(
    root: Path,
    stage_root: Path,
    *,
    known_scenes: set[str],
    episode_scene: dict[str, str],
    quarantine: list[dict[str, Any]],
) -> dict[str, int]:
    copied = {"graph_render_batches": 0, "render_batches": 0}
    for directory_name in copied:
        source_dir = root / directory_name
        if not source_dir.is_dir():
            continue
        for source in sorted(source_dir.glob("*.json")):
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                quarantine.append({"path": source.relative_to(root).as_posix(), "reason": f"invalid_batch:{type(exc).__name__}:{exc}"})
                continue
            scene_ids = _payload_scene_ids(payload, known_scenes=known_scenes, episode_scene=episode_scene)
            if not scene_ids:
                quarantine.append({"path": source.relative_to(root).as_posix(), "reason": "batch_scene_ambiguous"})
                continue
            # A legacy mixed-scene batch becomes explicit scene children.  The
            # original payload remains in the v2 archive and the wrapper makes
            # the relationship auditable instead of guessing a task subset.
            for scene_id in sorted(scene_ids):
                paths = SceneDatasetPaths.from_project(stage_root, scene_id).ensure_layout()
                destination_dir = paths.graph_render_batches_dir if directory_name == "graph_render_batches" else paths.render_batches_dir
                target = destination_dir / f"{source.stem}__legacy_{scene_id}.json"
                wrapper = {
                    "layout_version": SCENE_LAYOUT_VERSION,
                    "scene_id": scene_id,
                    "migration_source_batch_id": source.stem,
                    "migration_source_ref": source.relative_to(root).as_posix(),
                    "legacy_payload": payload,
                }
                _atomic_json(target, wrapper)
                copied[directory_name] += 1
    return copied


def _stage_scene_ledgers(root: Path, stage_root: Path, scene_ids: set[str], quarantine: list[dict[str, Any]]) -> dict[str, str]:
    """Copy only one scene's durable ledger rows into each scene workspace."""
    source = root / "render_ledger.sqlite3"
    if not source.is_file():
        return {}
    result: dict[str, str] = {}
    for scene_id in sorted(scene_ids):
        paths = SceneDatasetPaths.from_project(stage_root, scene_id).ensure_layout()
        destination = paths.ledger_path
        try:
            with sqlite3.connect(source) as input_connection, sqlite3.connect(destination) as output_connection:
                input_connection.backup(output_connection)
                output_connection.execute("PRAGMA foreign_keys=OFF")
                # Foreign-key order matters.  Events/attempts reference tasks,
                # tasks reference runs, and runs reference versions.
                output_connection.execute(
                    "DELETE FROM render_events WHERE run_id IS NULL OR run_id NOT IN (SELECT run_id FROM sweep_runs WHERE scene_id = ?)",
                    (scene_id,),
                )
                output_connection.execute(
                    "DELETE FROM render_attempts WHERE task_key NOT IN (SELECT task_key FROM sweep_tasks WHERE run_id IN (SELECT run_id FROM sweep_runs WHERE scene_id = ?))",
                    (scene_id,),
                )
                output_connection.execute("DELETE FROM sweep_tasks WHERE run_id NOT IN (SELECT run_id FROM sweep_runs WHERE scene_id = ?)", (scene_id,))
                output_connection.execute("DELETE FROM sweep_runs WHERE scene_id != ?", (scene_id,))
                output_connection.execute("DELETE FROM render_versions WHERE scene_id != ?", (scene_id,))
                output_connection.execute("DELETE FROM scene_versions WHERE scene_id != ?", (scene_id,))
                output_connection.execute(
                    "DELETE FROM request_blobs WHERE digest NOT IN (SELECT request_blob_digest FROM sweep_tasks WHERE request_blob_digest IS NOT NULL)"
                )
                output_connection.execute("DELETE FROM ledger_meta WHERE key = 'scene_id'")
                output_connection.execute("INSERT INTO ledger_meta(key, value) VALUES('scene_id', ?)", (scene_id,))
                output_connection.commit()
            result[scene_id] = file_sha256(destination)
        except (OSError, sqlite3.Error) as exc:
            quarantine.append({"path": source.relative_to(root).as_posix(), "scene_id": scene_id, "reason": f"ledger_extract:{type(exc).__name__}:{exc}"})
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
    return result


def _stage_graph_revisions(root: Path, stage_root: Path, scene_ids: set[str]) -> dict[str, str]:
    """Byte-preserve each current graph before the v3 workspace publish."""
    revisions: dict[str, str] = {}
    timestamp = _timestamp()
    for scene_id in sorted(scene_ids):
        source = root / "scenes" / scene_id / "viewpoint_graph.json"
        if not source.is_file():
            continue
        paths = SceneDatasetPaths.from_project(stage_root, scene_id).ensure_layout()
        digest = file_sha256(source)
        destination = paths.graph_revisions_dir / f"{timestamp}_{digest[:12]}_before_scene_layout_v3.json"
        shutil.copy2(source, destination)
        if file_sha256(destination) != digest:
            raise RuntimeError(f"graph snapshot hash mismatch: {source}")
        _atomic_json(destination.with_suffix(".metadata.json"), {
            "layout_version": SCENE_LAYOUT_VERSION,
            "scene_id": scene_id,
            "reason": "scene_layout_v3_migration",
            "source_ref": source.relative_to(root).as_posix(),
            "sha256": digest,
            "created_at": _timestamp(),
        })
        revisions[scene_id] = destination.relative_to(stage_root).as_posix()
    return revisions


def _publish_stage(root: Path, stage_root: Path, scene_ids: set[str], archive_root: Path) -> None:
    for scene_id in sorted(scene_ids):
        target = SceneDatasetPaths.from_project(root, scene_id).ensure_layout()
        staged = SceneDatasetPaths.from_project(stage_root, scene_id)
        for name in ("episodes", "splits", "episode_index.json", "dataset.json"):
            source = staged.scene_dir / name
            if not source.exists():
                continue
            destination = target.scene_dir / name
            if destination.exists():
                backup = archive_root / "preexisting_scene_workspace" / scene_id / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
            os.replace(source, destination)
        for name in ("graph_render_batches", "render_batches", "graph_revisions"):
            source = staged.operations_dir / name
            if not source.exists():
                continue
            destination = target.operations_dir / name
            if destination.exists():
                backup = archive_root / "preexisting_scene_operations" / scene_id / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
            os.replace(source, destination)
        if staged.ledger_path.exists():
            destination = target.ledger_path
            if destination.exists():
                backup = archive_root / "preexisting_scene_operations" / scene_id / "render_ledger.sqlite3"
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
            os.replace(staged.ledger_path, destination)


def migrate_scene_layout(
    project_root: str | Path,
    *,
    dry_run: bool = False,
    resume: bool = True,
) -> dict[str, Any]:
    """Migrate all legacy episodes and operations into v3 scene workspaces.

    This intentionally never deletes legacy data.  Apply archives the original
    project-level paths under ``.legacy_opticalnav_v2/<timestamp>/`` only after
    every staged hash and scene manifest has been validated.
    """
    root = Path(project_root).resolve()
    current_catalog = root / "dataset.json"
    if current_catalog.is_file():
        try:
            existing_catalog = json.loads(current_catalog.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing_catalog = {}
        if isinstance(existing_catalog, dict) and existing_catalog.get("layout_version") == PROJECT_CATALOG_VERSION:
            # Do not treat a v3 project as legacy input on a second invocation:
            # doing so would archive its already-published scene workspaces.
            return {
                "layout_version": SCENE_LAYOUT_VERSION,
                "project_root": root.as_posix(),
                "dry_run": bool(dry_run),
                "already_migrated": True,
                "catalog": existing_catalog,
            }
    groups, episode_scene, quarantine = _legacy_episode_groups(root)
    scenes_dir = root / "scenes"
    existing_scene_ids = {item.name for item in scenes_dir.iterdir() if item.is_dir()} if scenes_dir.is_dir() else set()
    known_scenes = set(groups) | existing_scene_ids
    report: dict[str, Any] = {
        "layout_version": SCENE_LAYOUT_VERSION,
        "project_root": root.as_posix(),
        "dry_run": bool(dry_run),
        "legacy_episode_count": sum(len(values) for values in groups.values()),
        "scenes": {scene_id: len(paths) for scene_id, paths in sorted(groups.items())},
        "quarantine": quarantine,
    }
    if dry_run:
        return report
    _assert_no_active_legacy_runs(root)
    with _migration_lock(root):
        contract_digest = _legacy_contract_digest(root, groups)
        resumed = _find_resumable_stage(root, contract_digest) if resume else None
        if resumed is not None:
            stage_root, state = resumed
            run_id = str(state["run_id"])
            archive_root = root / ".legacy_opticalnav_v2" / run_id
            scene_reports = list(state.get("scene_reports") or [])
            batch_counts = dict(state.get("batch_counts") or {})
            ledger_hashes = dict(state.get("ledger_hashes") or {})
            quarantine.extend(list(state.get("quarantine") or []))
            report["resumed_from_stage"] = stage_root.relative_to(root).as_posix()
        else:
            run_id = f"{_timestamp()}_{uuid.uuid4().hex[:8]}"
            stage_root = root / ".scene_workspace_v3_staging" / run_id
            archive_root = root / ".legacy_opticalnav_v2" / run_id
            stage_root.mkdir(parents=True, exist_ok=False)
            scene_reports = [_copy_scene_episodes(stage_root, scene_id, sources) for scene_id, sources in sorted(groups.items())]
            # A scene with no episodes is still a complete workspace. This is
            # the critical case for a freshly imported Office scene: Paths reads
            # this tiny local empty index instead of all legacy episodes.
            for scene_id in sorted(known_scenes - set(groups)):
                paths = SceneDatasetPaths.from_project(stage_root, scene_id).ensure_layout()
                index = write_episode_index(paths)
                write_scene_dataset(paths, metadata={"migrated_from_layout": "opticalnav_v2", "empty_scene_workspace": True})
                scene_reports.append({"scene_id": scene_id, "episodes": 0, "episode_digest": index["digest"], "copied": []})
            batch_counts = _stage_legacy_batches(
                root, stage_root, known_scenes=known_scenes, episode_scene=episode_scene, quarantine=quarantine,
            )
            ledger_hashes = _stage_scene_ledgers(root, stage_root, known_scenes, quarantine)
            graph_revisions = _stage_graph_revisions(root, stage_root, known_scenes)
            _atomic_json(stage_root / "migration_state.json", {
                "status": "staged",
                "run_id": run_id,
                "project_root": root.as_posix(),
                "contract_digest": contract_digest,
                "scene_reports": scene_reports,
                "batch_counts": batch_counts,
                "ledger_hashes": ledger_hashes,
                "graph_revisions": graph_revisions,
                "quarantine": quarantine,
                "updated_at": _timestamp(),
            })
        if resumed is not None:
            graph_revisions = dict(state.get("graph_revisions") or {})
        # Re-read the staged indexes before changing any live path.
        for scene in scene_reports:
            paths = SceneDatasetPaths.from_project(stage_root, scene["scene_id"])
            if not paths.dataset_path.is_file() or not paths.episode_index_path.is_file():
                raise RuntimeError(f"incomplete staging workspace: {paths.scene_dir}")
        _atomic_json(stage_root / "migration_state.json", {
            "status": "publishing",
            "run_id": run_id,
            "project_root": root.as_posix(),
            "contract_digest": contract_digest,
            "scene_reports": scene_reports,
            "batch_counts": batch_counts,
            "ledger_hashes": ledger_hashes,
            "graph_revisions": graph_revisions,
            "quarantine": quarantine,
            "updated_at": _timestamp(),
        })
        _publish_stage(root, stage_root, known_scenes, archive_root)
        archive_root.mkdir(parents=True, exist_ok=True)
        for name in ("episodes", "splits", "render_batches", "graph_render_batches", "exports", "render_ledger.sqlite3", "dataset.json"):
            source = root / name
            if source.exists():
                os.replace(source, archive_root / name)
        catalog = write_project_catalog(root)
        report.update({
            "run_id": run_id,
            "archive_root": archive_root.relative_to(root).as_posix(),
            "scene_reports": scene_reports,
            "batch_counts": batch_counts,
            "ledger_hashes": ledger_hashes,
            "graph_revisions": graph_revisions,
            "catalog": catalog,
            "quarantine": quarantine,
        })
        _atomic_json(root / ".scene_workspace_v3_migrations" / f"{run_id}.json", report)
        # Stage has been published; removing it is safe and does not affect user
        # data.  It contains only copies made during this migration.
        shutil.rmtree(stage_root)
    return report
