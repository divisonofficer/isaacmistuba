#!/usr/bin/env python3
"""Interactive, resumable OpticalNav export and Google Drive upload wizard.

By default the wizard asks the control-plane daemon to create an export job.
``--local`` instead invokes the repository exporter directly, so packaging and
rclone upload work even while port 8765 is unavailable or busy. Both modes keep
the same durable wizard-run and upload-resume records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from tqdm import tqdm


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = "opticalnav-v0.2"
DEFAULT_REMOTE = "gdrive:"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path, *, label: str | None = None) -> str:
    """Hash a file while making multi-GiB resume preparation observable."""
    total = path.stat().st_size
    completed = 0
    started_at = time.monotonic()
    last_report_at = started_at
    if label:
        print(f"[checksum] {label}: 0/{total:,} bytes", flush=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            completed += len(block)
            now = time.monotonic()
            if label and (completed == total or now - last_report_at >= 5.0):
                elapsed = max(now - started_at, 1e-6)
                rate_mib_s = completed / elapsed / 1048576
                percent = 100.0 * completed / total if total else 100.0
                print(
                    f"[checksum] {label}: {percent:.1f}% · {completed:,}/{total:,} bytes · {rate_mib_s:.1f} MiB/s",
                    flush=True,
                )
                last_report_at = now
    if label:
        print(f"[checksum] {label}: done", flush=True)
    return digest.hexdigest()


def _cached_checksum(manifest_path: Path, file_path: Path) -> str | None:
    """Return a checksum recorded for the exact current file, if available."""
    payload = _read_json(manifest_path, {})
    entries = payload.get("files") if isinstance(payload, Mapping) else None
    for entry in entries or []:
        if not isinstance(entry, Mapping):
            continue
        try:
            same_file = Path(str(entry.get("path") or "")).resolve() == file_path.resolve()
            same_size = int(entry.get("bytes")) == file_path.stat().st_size
        except (OSError, TypeError, ValueError):
            continue
        checksum = entry.get("sha256")
        if same_file and same_size and isinstance(checksum, str) and len(checksum) == 64:
            return checksum
    return None


def _project_dir(project: str) -> Path:
    return REPO_ROOT / "out" / "opticalnav" / project


def _sensor_counts(project_dir: Path, scene_id: str, variant_dir: str) -> dict[str, int]:
    """Count active observations per sensor from stable current.json pointers."""
    root = project_dir / "scenes" / scene_id / variant_dir
    counts: dict[str, int] = {}
    if not root.is_dir():
        return counts
    for pointer in root.rglob("current.json"):
        try:
            payload = _read_json(pointer, {})
            ref = payload.get("bundle_ref") if isinstance(payload, Mapping) else None
            bundle = project_dir / str(ref) if ref else None
            if bundle is not None:
                found_sensor = False
                for root_name in ("sensors", "cameras"):
                    sensors = bundle / root_name
                    if not sensors.is_dir():
                        continue
                    for sensor in sensors.iterdir():
                        # A polar camera is valid even when it has no ordinary
                        # rgb.png: its authoritative payload is Stokes NPZ.
                        if sensor.is_dir() and ((sensor / "rgb.png").is_file() or (sensor / "stokes_data.npz").is_file()):
                            counts[sensor.name] = counts.get(sensor.name, 0) + 1
                            found_sensor = True
                if found_sensor:
                    continue
        except OSError:
            pass
        parts = pointer.relative_to(root).parts
        sensor = next((parts[i + 1] for i, part in enumerate(parts[:-1]) if part in {"sensors", "cameras"}), None)
        if sensor:
            counts[sensor] = counts.get(sensor, 0) + 1
    return counts


def _ledger_sensor_inventory(
    project_dir: Path,
    *,
    scene_ids: Iterable[str] | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """Read completed sensor counts from explicitly selected local ledgers.

    Supplying ``scene_ids`` is the normal export path and is deliberately not a
    filter applied after a project scan: only those exact scene workspaces are
    touched.  The unscoped form is retained solely for the explicit interactive
    ``--list``/scene-picker operation.
    """
    inventory: dict[str, dict[str, dict[str, int]]] = {}
    requested = None if scene_ids is None else sorted({str(scene_id) for scene_id in scene_ids if str(scene_id)})
    if requested is None:
        scene_ledgers = [
            (scene_dir.name, scene_dir / "operations" / "render_ledger.sqlite3")
            for scene_dir in sorted((project_dir / "scenes").iterdir())
            if scene_dir.is_dir() and (scene_dir / "operations" / "render_ledger.sqlite3").is_file()
        ] if (project_dir / "scenes").is_dir() else []
    else:
        scene_ledgers = []
        for scene_id in requested:
            # The CLI scene id is a logical component; never let it turn the
            # export menu into an arbitrary project filesystem traversal.
            if not scene_id or scene_id in {".", ".."} or "/" in scene_id or "\\" in scene_id:
                raise ValueError(f"invalid scene_id: {scene_id!r}")
            ledger = project_dir / "scenes" / scene_id / "operations" / "render_ledger.sqlite3"
            if ledger.is_file():
                scene_ledgers.append((scene_id, ledger))
    # Legacy fallback is intentionally all-or-nothing and disappears after v3
    # migration. A v3 project never needs to consult this shared ledger.
    if requested is None and not scene_ledgers and (project_dir / "render_ledger.sqlite3").is_file():
        scene_ledgers = [("", project_dir / "render_ledger.sqlite3")]
    for scoped_scene_id, ledger in scene_ledgers:
        connection = None
        try:
            connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=30.0)
            connection.execute("PRAGMA busy_timeout = 30000")
            # One newest completed run per scene is the exportable active
            # snapshot. Querying every historical retry run made a simple menu
            # take minutes on an NFS-backed ledger.
            newest: dict[str, list[str]] = {}
            query = "SELECT run_id, scene_id FROM sweep_runs WHERE status IN ('completed', 'ready', 'paused')"
            values: tuple[Any, ...] = ()
            if scoped_scene_id:
                query += " AND scene_id = ?"
                values = (scoped_scene_id,)
            query += " ORDER BY created_at DESC"
            for run_id, scene_id in connection.execute(query, values):
                bucket = newest.setdefault(str(scene_id), [])
                if len(bucket) < 8:
                    bucket.append(str(run_id))
            for scene_id, run_ids in sorted(newest.items()):
                scene_counts = inventory.setdefault(scene_id, {
                    "base": {}, "perturbed": {}, "perturbed_active_polar": {},
                })
                # A resumed sweep stores completed frames in several render
                # versions. Count unique logical views across recent history.
                seen_tasks: dict[str, set[tuple[str, str]]] = {
                    "base": set(), "perturbed": set(), "perturbed_active_polar": set(),
                }
                for run_id in run_ids:
                    for variant, logical_task_key, metadata_raw in connection.execute(
                        "SELECT variant, logical_task_key, metadata_json FROM sweep_tasks "
                        "WHERE run_id = ? AND state IN ('succeeded', 'skipped')",
                        (run_id,),
                    ):
                        try:
                            metadata = json.loads(metadata_raw or "{}")
                        except (TypeError, ValueError):
                            metadata = {}
                        sensor_ids = metadata.get("sensor_ids") or list((metadata.get("modalities_by_sensor") or {}).keys())
                        normalized_variant = str(variant or metadata.get("scene_variant_key") or "base").lower()
                        bucket = (
                            "perturbed_active_polar" if normalized_variant == "perturbed_active_polar"
                            else "perturbed" if normalized_variant == "perturbed"
                            else "base"
                        )
                        for sensor_id in sensor_ids:
                            sensor = str(sensor_id)
                            task_id = str(logical_task_key or "")
                            identity = (sensor, task_id)
                            if task_id and identity in seen_tasks[bucket]:
                                continue
                            if task_id:
                                seen_tasks[bucket].add(identity)
                            scene_counts[bucket][sensor] = scene_counts[bucket].get(sensor, 0) + 1
        except sqlite3.Error:
            # A menu count is advisory; export readiness is decided by the
            # pointer index. Never let a ledger the daemon has locked abort it.
            continue
        finally:
            if connection is not None:
                connection.close()
    return inventory


def discover_scenes(
    project_dir: Path,
    *,
    scene_ids: Iterable[str] | None = None,
    coverage_levels: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return exportable scenes, optionally from exact scene workspaces only."""
    root = project_dir / "scenes"
    scenes: list[dict[str, Any]] = []
    if not root.is_dir():
        return scenes
    requested = None if scene_ids is None else sorted({str(scene_id) for scene_id in scene_ids if str(scene_id)})
    inventory = _ledger_sensor_inventory(project_dir, scene_ids=requested)
    if requested is None:
        candidates = sorted(root.iterdir())
    else:
        candidates = [root / scene_id for scene_id in requested]
    for scene_dir in candidates:
        if not scene_dir.is_dir():
            continue
        counts = inventory.get(scene_dir.name)
        # For a specifically selected scene, stable pointers are authoritative:
        # they represent exactly the currently promotable graph views and do
        # not double-count old resumed versions.  The unscoped picker stays
        # ledger-only so opening it does not recursively walk every scene's
        # NFS observation tree.
        pointer_counts = None
        if requested is not None:
            pointer_counts = _pointer_summary_counts(scene_dir, coverage_levels=coverage_levels)
        # A V4 scene's pointers are expensive to enumerate over NFS and may
        # not exist until export reconciliation. Its selected ledger is the
        # authoritative readiness source at wizard startup.
        is_v4 = bool(coverage_levels) or _v4_plan_group(scene_dir) is not None
        if pointer_counts is None and not is_v4:
            pointer_counts = {
                "base": _sensor_counts(project_dir, scene_dir.name, "observations"),
                "perturbed": _sensor_counts(project_dir, scene_dir.name, "observations_perturbed"),
                "perturbed_active_polar": _sensor_counts(project_dir, scene_dir.name, "observations_perturbed_active_polar"),
            }
        if pointer_counts is not None and any(sum(values.values()) for values in pointer_counts.values()):
            base, perturbed, active_polar = (
                pointer_counts["base"], pointer_counts["perturbed"], pointer_counts["perturbed_active_polar"],
            )
        elif counts is None and not inventory:
            # Legacy projects without a ledger are uncommon. Keep that fallback
            # isolated so a modern project's menu never recursively walks NFS.
            base = _sensor_counts(project_dir, scene_dir.name, "observations")
            perturbed = _sensor_counts(project_dir, scene_dir.name, "observations_perturbed")
            active_polar = _sensor_counts(project_dir, scene_dir.name, "observations_perturbed_active_polar")
        else:
            counts = counts or {"base": {}, "perturbed": {}, "perturbed_active_polar": {}}
            base, perturbed, active_polar = (
                counts["base"], counts["perturbed"], counts["perturbed_active_polar"],
            )
        render_xml = any((scene_dir / name).is_file() for name in ("render_scene.xml", "render_scene_base.xml"))
        # Never recurse over geometry/texture caches just to build a menu: one
        # imported scene can contain hundreds of thousands of cache files.
        freshness_paths = [scene_dir]
        for name in (
            "authoring_map.json", "scene_annotation.json", "render_readiness.json",
            "render_scene.xml", "render_scene_base.xml", "render_scene_perturbed.xml",
            "observations", "observations_perturbed",
        ):
            candidate = scene_dir / name
            if candidate.exists():
                freshness_paths.append(candidate)
        latest = max(path.stat().st_mtime for path in freshness_paths)
        scenes.append({
            "scene_id": scene_dir.name,
            "modified_at": latest,
            "readiness": "ready" if render_xml else "not prepared",
            "base": base,
            "perturbed": perturbed,
            "perturbed_active_polar": active_polar,
            "camera_ids": sorted(set(base) | set(perturbed) | set(active_polar)),
            "exportable": bool(sum(base.values()) + sum(perturbed.values()) + sum(active_polar.values())),
        })
    return sorted(scenes, key=lambda item: item["modified_at"], reverse=True)


_OBSERVATION_ROOT_BY_VARIANT = {
    "base": "observations",
    "perturbed": "observations_perturbed",
    "perturbed_active_polar": "observations_perturbed_active_polar",
}


def _legacy_graph_view_keys(scene_dir: Path) -> set[tuple[str, str]]:
    """Return the legacy viewpoint-graph viewpoint/heading universe."""
    graph = _read_json(scene_dir / "viewpoint_graph.json", {})
    if not isinstance(graph, Mapping):
        return set()
    keys: set[tuple[str, str]] = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("node_id") or "")
        if not node_id:
            continue
        for heading in node.get("headings") or []:
            heading_id = str(heading.get("heading_id") or "") if isinstance(heading, Mapping) else str(heading or "")
            if heading_id:
                keys.add((node_id, heading_id))
    return keys


def _v4_plan_view_keys(paths: Iterable[Path]) -> set[tuple[str, str]]:
    """Read the native support-pose universe from a V4 plan group."""
    keys: set[tuple[str, str]] = set()
    for path in paths:
        payload = _read_json(path, {})
        if not isinstance(payload, Mapping) or str(payload.get("profile_id") or "") != "adaptive_navigation_support_v4":
            continue
        for entry in payload.get("render_entries") or []:
            if not isinstance(entry, Mapping):
                continue
            node_id = str(entry.get("motion_node_id") or entry.get("node_id") or "")
            heading_id = str(entry.get("heading_id") or "")
            if node_id and heading_id:
                keys.add((node_id, heading_id))
    return keys


def _v4_plan_group(scene_dir: Path) -> tuple[list[Path], str] | None:
    """Choose the V4 plan group named by the latest durable L3 submission.

    V4 stores its reusable L0 plan and additive L3 plan in an archive directory
    after a graph revision.  The generic viewpoint graph remains in the scene
    for editing, but is not the render/export contract for support poses.
    """
    submissions = sorted(
        scene_dir.glob("support_l3_submission_*.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    roots: list[tuple[Path, str]] = []
    for submission in submissions:
        payload = _read_json(submission, {})
        plan_dir = payload.get("plan_dir") if isinstance(payload, Mapping) else None
        if not isinstance(plan_dir, str) or not plan_dir:
            continue
        candidate = (scene_dir / plan_dir).resolve()
        try:
            candidate.relative_to(scene_dir.resolve())
        except ValueError:
            continue
        roots.append((candidate, f"v4 submission {submission.name}"))
    # A freshly generated V4 scene may not yet have a submission receipt.
    roots.append((scene_dir, "v4 scene-local plans"))
    archives = scene_dir / "navigation_support_archives"
    if archives.is_dir():
        roots.extend((path, f"v4 archive {path.name}") for path in sorted(
            (candidate for candidate in archives.iterdir() if candidate.is_dir()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        ))
    seen: set[Path] = set()
    for root, source in roots:
        if root in seen:
            continue
        seen.add(root)
        base = root / "support_observation_plan.json"
        if not base.is_file():
            continue
        paths = [base, *sorted(root.glob("support_observation_expansion_*.json"))]
        if _v4_plan_view_keys(paths):
            return paths, source
    return None


def _coverage_level_plan_group(scene_dir: Path, level_ids: Iterable[str]) -> tuple[list[Path], str]:
    """Resolve an explicit union of rendered sweep-coverage levels.

    A V4 scene keeps its full L0 observation plan (every support pose × every
    heading) while a render campaign deliberately submits a much smaller
    coverage level, and often several of them in sequence.  Exporting such a
    campaign means packaging exactly the union of the submitted levels, not the
    L0 universe the levels were selected from.
    """
    paths: list[Path] = []
    for raw in level_ids:
        level_id = str(raw).strip()
        # A level id names a scene-local sibling file, never a traversal.
        if not level_id or "/" in level_id or "\\" in level_id or level_id in {".", ".."}:
            raise RuntimeError(f"invalid sweep coverage level id: {raw!r}")
        path = scene_dir / f"support_sweep_coverage_{level_id}.json"
        if not path.is_file():
            raise RuntimeError(f"sweep coverage level is missing: {path}")
        if path not in paths:
            paths.append(path)
    if not paths:
        raise RuntimeError("no sweep coverage level selected")
    if not _v4_plan_view_keys(paths):
        raise RuntimeError(f"sweep coverage levels declare no render entries: {[path.name for path in paths]}")
    return paths, "sweep coverage levels " + "+".join(
        str(level).strip() for level in level_ids if str(level).strip()
    )


def _current_export_view_universe(
    scene_dir: Path,
    *,
    coverage_levels: Iterable[str] | None = None,
) -> tuple[set[tuple[str, str]], dict[str, Any]]:
    """Return the active export universe for legacy graphs or support V4."""
    levels = [str(level).strip() for level in (coverage_levels or []) if str(level).strip()]
    if levels:
        paths, source = _coverage_level_plan_group(scene_dir, levels)
        scene_root = scene_dir.resolve()
        fingerprints = [
            {"path": path.relative_to(scene_root).as_posix(), "mtime_ns": path.stat().st_mtime_ns, "size": path.stat().st_size}
            for path in paths
        ]
        return _v4_plan_view_keys(paths), {
            "kind": "adaptive_navigation_support_v4",
            "source": source,
            "coverage_levels": levels,
            "plans": fingerprints,
        }
    v4_group = _v4_plan_group(scene_dir)
    if v4_group is not None:
        paths, source = v4_group
        scene_root = scene_dir.resolve()
        fingerprints = [
            {"path": path.relative_to(scene_root).as_posix(), "mtime_ns": path.stat().st_mtime_ns, "size": path.stat().st_size}
            for path in paths
        ]
        return _v4_plan_view_keys(paths), {"kind": "adaptive_navigation_support_v4", "source": source, "plans": fingerprints}
    graph_path = scene_dir / "viewpoint_graph.json"
    graph_stat = graph_path.stat() if graph_path.is_file() else None
    return _legacy_graph_view_keys(scene_dir), {
        "kind": "viewpoint_graph", "path": "viewpoint_graph.json",
        "mtime_ns": graph_stat.st_mtime_ns if graph_stat else None,
        "size": graph_stat.st_size if graph_stat else None,
    }


def _pointer_summary_counts(
    scene_dir: Path,
    *,
    coverage_levels: Iterable[str] | None = None,
) -> dict[str, dict[str, int]] | None:
    """Read a reconciliation summary when it still matches the current graph."""
    summary = _read_json(scene_dir / "operations" / "export_current_pointer_index.json", {})
    if not isinstance(summary, Mapping):
        return None
    try:
        _, universe = _current_export_view_universe(scene_dir, coverage_levels=coverage_levels)
    except RuntimeError:
        return None
    if summary.get("view_universe") != universe:
        return None
    variants = summary.get("variants")
    if not isinstance(variants, Mapping):
        return None
    result: dict[str, dict[str, int]] = {}
    for variant in _OBSERVATION_ROOT_BY_VARIANT:
        value = variants.get(variant)
        sensors = value.get("sensors") if isinstance(value, Mapping) else None
        result[variant] = {
            str(sensor): int(count)
            for sensor, count in (sensors or {}).items()
            if str(sensor) and int(count) > 0
        } if isinstance(sensors, Mapping) else {}
    return result


def _safe_bundle_ref(project_dir: Path, ref: str) -> Path | None:
    """Resolve a project-relative versioned bundle without escaping the project."""
    candidate = Path(str(ref))
    if not ref or candidate.is_absolute():
        return None
    try:
        resolved = (project_dir / candidate).resolve()
        resolved.relative_to(project_dir.resolve())
    except (OSError, ValueError):
        return None
    return resolved if (resolved / "manifest.json").is_file() else None


def _v4_heading_batch_bundles(
    project_dir: Path,
    bundle: Path,
    metadata: Mapping[str, Any],
    *,
    default_key: tuple[str, str],
    expected: set[tuple[str, str]],
) -> list[tuple[tuple[str, str], Path]]:
    """Expand a V4 spatial-Stokes batch into its per-heading bundles.

    V4 records a task at a batch representative heading, while the renderer
    writes one immutable sibling bundle per heading. Treating that task as one
    view loses the other three (or fewer) headings in every batch.
    """
    raw_views = metadata.get("stokes_heading_batch_view_keys")
    if not isinstance(raw_views, list):
        return [(default_key, bundle)]
    resolved: list[tuple[tuple[str, str], Path]] = []
    for raw in raw_views:
        if not isinstance(raw, Mapping):
            continue
        key = (str(raw.get("node_id") or ""), str(raw.get("heading_id") or ""))
        if not all(key) or key not in expected:
            continue
        # A batch never crosses nodes. Still keep the check explicit so a
        # malformed ledger row cannot redirect an export pointer elsewhere.
        if key[0] != default_key[0]:
            continue
        sibling = bundle.parent / key[1]
        try:
            sibling.resolve().relative_to(project_dir.resolve())
        except (OSError, ValueError):
            continue
        if (sibling / "manifest.json").is_file():
            resolved.append((key, sibling))
    return resolved or [(default_key, bundle)]


class _LedgerReader:
    """Read-only ledger access that survives a concurrently writing daemon.

    The ledger lives on the NFS project mount and the render daemon keeps it
    open in WAL mode.  NFS cannot provide the shared memory WAL wants, so a
    reader intermittently fails with SQLITE_PROTOCOL ("locking protocol") --
    and once a connection has seen it, every later statement on that same
    connection fails too.  Retrying therefore has to reconnect, not just
    re-issue.  If the mount stays wedged, fall back to reading a local snapshot
    of the database and its WAL: slight staleness is harmless here because every
    candidate bundle is independently verified on disk before it is promoted.
    """

    def __init__(self, ledger_path: Path, *, attempts: int = 6) -> None:
        self._path = ledger_path
        self._attempts = attempts
        self._connection: sqlite3.Connection | None = None
        self._snapshot_dir: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> "_LedgerReader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
            self._connection = None
        if self._snapshot_dir is not None:
            self._snapshot_dir.cleanup()
            self._snapshot_dir = None

    def _connect(self, path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _snapshot(self) -> Path:
        """Copy the database and its sidecars so the read has no NFS locking."""
        if self._snapshot_dir is None:
            self._snapshot_dir = tempfile.TemporaryDirectory(prefix="opticalnav-ledger-")
        target_dir = Path(self._snapshot_dir.name)
        target = target_dir / self._path.name
        for suffix in ("", "-wal", "-shm"):
            source = self._path.with_name(self._path.name + suffix)
            if source.is_file():
                shutil.copy2(source, target_dir / source.name)
        return target

    def query(self, sql: str, params: tuple[Any, ...], *, what: str) -> list[tuple[Any, ...]]:
        delay = 0.5
        last: sqlite3.Error | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                if self._connection is None:
                    self._connection = self._connect(self._path)
                return list(self._connection.execute(sql, params))
            except sqlite3.Error as exc:
                last = exc
                self.close()
                if attempt == self._attempts:
                    break
                print(
                    f"[pointers] ledger busy ({what}, attempt {attempt}/{self._attempts}): {exc}; "
                    f"reconnecting in {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
        print(f"[pointers] ledger stayed locked ({what}); reading a local snapshot instead", flush=True)
        try:
            snapshot = self._snapshot()
            self._connection = self._connect(snapshot)
            return list(self._connection.execute(sql, params))
        except (sqlite3.Error, OSError) as exc:
            raise RuntimeError(f"ledger read failed ({what}): {last or exc}") from (last or exc)


def _adopt_orphan_bundles(
    project_dir: Path,
    *,
    scene_id: str,
    variant: str,
    expected: set[tuple[str, str]],
    chosen: dict[tuple[str, str], tuple[str, str, str, tuple[str, ...]]],
) -> int:
    """Promote immutable bundles the ledger never recorded a task row for.

    A spatial-Stokes sweep writes one immutable bundle per heading but records
    only the batch representative as a task, and a daemon restart mid-batch can
    leave the surviving siblings without any ledger row at all.  The bundles are
    still complete and self-describing, so an export that ignored them would
    silently drop thousands of rendered frames.  Only render versions that
    already exist for this scene are scanned, newest first, and a bundle is
    adopted solely when it carries its own manifest.
    """
    versions_root = project_dir / "scenes" / scene_id / "observations" / "versions"
    if not versions_root.is_dir():
        return 0
    try:
        version_dirs = sorted(
            (path for path in versions_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError:
        return 0
    adopted = 0
    outstanding = expected - set(chosen)
    print(
        f"[pointers] {variant}: scanning {len(version_dirs)} render versions for "
        f"{len(outstanding):,} bundles the ledger did not record ...",
        flush=True,
    )
    for version_dir in version_dirs:
        if not outstanding:
            break
        variant_dir = version_dir / variant
        if not variant_dir.is_dir():
            continue
        for node_id, heading_id in sorted(outstanding):
            bundle = variant_dir / node_id / heading_id
            if not (bundle / "manifest.json").is_file():
                continue
            manifest = _read_json(bundle / "manifest.json", {})
            sensors: tuple[str, ...] = ()
            if isinstance(manifest, Mapping):
                sensors = tuple(dict.fromkeys(
                    str(artifact.get("camera_id"))
                    for artifact in manifest.get("artifacts") or []
                    if isinstance(artifact, Mapping) and artifact.get("camera_id")
                ))
            chosen[(node_id, heading_id)] = (
                bundle.relative_to(project_dir).as_posix(), version_dir.name, "", sensors,
            )
            adopted += 1
        outstanding = expected - set(chosen)
    return adopted


def _reconcile_current_pointers(
    project_dir: Path,
    *,
    scene_id: str,
    variants: Iterable[str],
    allow_partial_v4: bool = False,
    coverage_levels: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Promote the current graph's completed versioned bundles for export.

    Older resumable sweeps may be fully complete in the ledger while never
    having one render version that contains every frame.  The regular daemon
    promote action intentionally refuses such fragmented versions.  Exporting
    is different: it needs one stable pointer per logical current view.  This
    reconciliation chooses the newest valid completed bundle for each current
    graph view and writes only those small ``current.json`` pointers. V4
    support plans can intentionally be exported while a long L3 recovery is
    still incomplete; when requested, that mode promotes the completed subset
    and records the missing native support-pose views rather than silently
    substituting the legacy viewpoint graph.
    """
    scene_dir = project_dir / "scenes" / scene_id
    expected, view_universe = _current_export_view_universe(scene_dir, coverage_levels=coverage_levels)
    if not expected:
        return {"expected": {"views": 0}, "variants": {}}
    ledger_path = scene_dir / "operations" / "render_ledger.sqlite3"
    if not ledger_path.is_file():
        raise RuntimeError(f"render ledger is missing: {ledger_path}")

    selected = []
    for raw in variants:
        variant = str(raw).strip().lower()
        if variant not in _OBSERVATION_ROOT_BY_VARIANT:
            raise RuntimeError(f"unsupported export variant: {variant}")
        if variant not in selected:
            selected.append(variant)

    report: dict[str, Any] = {}
    with _LedgerReader(ledger_path) as ledger:
        for variant in selected:
            chosen: dict[tuple[str, str], tuple[str, str, str, tuple[str, ...]]] = {}
            # Query one newest run at a time.  A global task history sort is
            # prohibitively slow on NFS after many interrupted resumes; each
            # run contains at most one compact plan window's task history and
            # lets us stop as soon as all current views have a candidate.
            #
            # ``planned`` runs are included because a chained campaign records
            # its adopted cross-run coverage in a run that never transitions
            # out of ``planned``.  This cannot invent frames: every candidate
            # below is still admitted only through ``_safe_bundle_ref``, which
            # requires an immutable bundle with a manifest on disk.
            run_rows = ledger.query(
                """
                SELECT run_id, scene_version_id
                FROM sweep_runs
                WHERE scene_id = ? AND status IN ('completed', 'ready', 'paused', 'planned')
                ORDER BY created_at DESC
                """,
                (scene_id,),
                what=f"{variant} sweep runs",
            )
            print(
                f"[pointers] {variant}: resolving {len(expected):,} {view_universe['kind']} views "
                f"from {len(run_rows)} ledger runs ...",
                flush=True,
            )
            with tqdm(total=len(expected), desc=f"resolve {variant}", unit="view", dynamic_ncols=True, file=sys.stdout) as progress:
                for run_index, (run_id, scene_version_id) in enumerate(run_rows, 1):
                    before = len(chosen)
                    # Materialize one run's task window before parsing it: a
                    # lock error raised mid-iteration cannot be retried, and a
                    # single run's history is small enough to hold in memory.
                    rows = ledger.query(
                        """
                        SELECT node_id, heading_id, render_version_id, metadata_json
                        FROM sweep_tasks
                        WHERE run_id = ? AND variant = ? AND state IN ('succeeded', 'skipped')
                        """,
                        (run_id, variant),
                        what=f"{variant} tasks of {run_id}",
                    )
                    for node_id_raw, heading_id_raw, render_version_id, metadata_raw in rows:
                        key = (str(node_id_raw), str(heading_id_raw))
                        if key not in expected or key in chosen:
                            continue
                        metadata: Any = {}
                        try:
                            metadata = json.loads(metadata_raw or "{}")
                        except (TypeError, ValueError):
                            metadata = {}
                        sensor_ids = metadata.get("sensor_ids") if isinstance(metadata, Mapping) else None
                        sensors = tuple(str(sensor) for sensor in sensor_ids if str(sensor)) if isinstance(sensor_ids, list) else ()
                        source_ref = metadata.get("source_bundle_ref") if isinstance(metadata, Mapping) else None
                        bundle = _safe_bundle_ref(project_dir, str(source_ref or ""))
                        if bundle is None:
                            fallback = (
                                f"scenes/{scene_id}/observations/versions/{render_version_id}/"
                                f"{variant}/{key[0]}/{key[1]}"
                            )
                            bundle = _safe_bundle_ref(project_dir, fallback)
                        if bundle is None:
                            continue
                        if view_universe.get("kind") == "adaptive_navigation_support_v4":
                            bundle_views = _v4_heading_batch_bundles(
                                project_dir, bundle, metadata, default_key=key, expected=expected,
                            )
                        else:
                            bundle_views = [(key, bundle)]
                        for view_key, view_bundle in bundle_views:
                            if view_key in chosen:
                                continue
                            chosen[view_key] = (
                                view_bundle.relative_to(project_dir).as_posix(),
                                str(render_version_id), str(scene_version_id), sensors,
                            )
                    progress.update(len(chosen) - before)
                    progress.set_postfix(runs=f"{run_index}/{len(run_rows)}", found=len(chosen))
                    if len(chosen) == len(expected):
                        break

            adopted_from_disk = 0
            if len(chosen) < len(expected):
                adopted_from_disk = _adopt_orphan_bundles(
                    project_dir, scene_id=scene_id, variant=variant,
                    expected=expected, chosen=chosen,
                )

            missing = sorted(expected - set(chosen))
            # V4 support plans are intentionally rendered/archived in
            # independently resumable L0/L3 and variant batches. Exporting is
            # a packaging operation, not a new coverage admission gate: ship
            # every immutable bundle that exists and make the per-variant
            # coverage explicit in the generated pointer index.  Legacy graph
            # exports retain their strict all-view contract.
            allow_partial = view_universe.get("kind") == "adaptive_navigation_support_v4"
            if missing and not allow_partial:
                examples = ", ".join(f"{node}/{heading}" for node, heading in missing[:5])
                raise RuntimeError(
                    f"{variant} has {len(missing)}/{len(expected)} current graph views without a valid bundle "
                    f"(examples: {examples})"
                )
            if not chosen:
                raise RuntimeError(f"{variant} has no valid completed bundle for the active export universe")
            observation_root = _OBSERVATION_ROOT_BY_VARIANT[variant]
            sensor_counts: dict[str, int] = {}
            with tqdm(total=len(chosen), desc=f"write {variant} pointers", unit="view", dynamic_ncols=True, file=sys.stdout) as progress:
                for (node_id, heading_id), (bundle_ref, render_version_id, scene_version_id, sensors) in chosen.items():
                    pointer = scene_dir / observation_root / node_id / heading_id / "current.json"
                    pointer_payload = {
                        "schema_version": 1,
                        "scene_id": scene_id,
                        "variant": variant,
                        "node_id": node_id,
                        "heading_id": heading_id,
                        "render_version_id": render_version_id,
                        "scene_version_id": scene_version_id,
                        "bundle_ref": bundle_ref,
                        "updated_at": _utc_now(),
                    }
                    existing = _read_json(pointer, {})
                    # Reconciliation is normally invoked again on a resumable
                    # upload. Do not turn that into thousands of NFS writes
                    # when the stable target bundle has not changed.
                    stable_keys = ("scene_id", "variant", "node_id", "heading_id", "render_version_id", "scene_version_id", "bundle_ref")
                    if not isinstance(existing, Mapping) or any(existing.get(key) != pointer_payload[key] for key in stable_keys):
                        _write_json_atomic(pointer, pointer_payload)
                    for sensor in sensors:
                        sensor_counts[sensor] = sensor_counts.get(sensor, 0) + 1
                    progress.update(1)
            report[variant] = {
                "expected": len(expected), "promoted": len(chosen), "missing": len(missing),
                "missing_examples": [f"{node}/{heading}" for node, heading in missing[:5]],
                "partial": bool(missing),
                "adopted_from_disk": adopted_from_disk,
                "sensors": sensor_counts,
            }
    result: dict[str, Any] = {"expected": {"views": len(expected), "universe": view_universe}, "variants": report}
    _write_json_atomic(scene_dir / "operations" / "export_current_pointer_index.json", {
        "schema_version": 1,
        "scene_id": scene_id,
        "view_universe": view_universe,
        "updated_at": _utc_now(),
        "variants": report,
    })
    return result


def _format_scene(scene: Mapping[str, Any], index: int) -> str:
    stamp = datetime.fromtimestamp(float(scene["modified_at"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    def compact(counts: Mapping[str, int]) -> str:
        return ", ".join(f"{key}:{value}" for key, value in sorted(counts.items())) or "—"
    state = "OK" if scene["exportable"] else "NO RENDER"
    return (
        f"[{index:2}] {state:9} {stamp}  {scene['scene_id']}\n"
        f"     base({compact(scene['base'])})  perturbed({compact(scene['perturbed'])})  "
        f"active-polar({compact(scene.get('perturbed_active_polar', {}))})"
    )


def _prompt_choice(prompt: str, choices: Iterable[str], *, default: str | None = None) -> str:
    allowed = {choice.lower(): choice for choice in choices}
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if not value and default:
            return default
        if value.lower() in allowed:
            return allowed[value.lower()]
        print(f"Choose one of: {', '.join(choices)}")


def _prompt_bool(prompt: str, default: bool) -> bool:
    answer = _prompt_choice(prompt, ("y", "n"), default="y" if default else "n")
    return answer == "y"


def _http_json(url: str, *, method: str = "GET", payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(dict(payload)).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return dict(result) if isinstance(result, Mapping) else {"result": result}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", body)
        except ValueError:
            detail = body
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach render daemon: {exc.reason}") from exc


def _rclone(args: list[str], *, stream: bool = False) -> subprocess.CompletedProcess[str]:
    """Run rclone, optionally forwarding its combined progress stream live.

    ``copyto`` can run for hours for a multi-dozen-GiB dataset archive.  Do
    not hide its stats behind ``subprocess.run(..., stdout=PIPE)``: callers
    that request streaming still receive the complete output for an error
    message, while the interactive wizard shows transfer rate and ETA as they
    are emitted.
    """
    command = ["rclone", *args]
    if not stream:
        return subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        # rclone's --stats-one-line records are already compact; keeping its
        # text intact makes ETA/rate copy-pasteable from the terminal log.
        print(f"[rclone] {line.rstrip()}", flush=True)
    return subprocess.CompletedProcess(command, process.wait(), "".join(lines))


def _browse_drive(remote: str) -> str:
    current = remote.rstrip(":") + ":"
    while True:
        result = _rclone(["lsd", current])
        entries = [] if result.returncode else [line.split()[-1] for line in result.stdout.splitlines() if line.split()]
        print(f"\nGoogle Drive: {current}")
        for index, entry in enumerate(entries, 1):
            print(f"  {index}. {entry}")
        print("  [enter] use this folder · [number] enter folder · [..] parent · [path] use a relative path")
        value = input("Drive target: ").strip()
        if not value:
            return current
        if value == "..":
            body = current[len(remote):].strip("/")
            parent = "/".join(body.split("/")[:-1])
            current = remote + (parent + "/" if parent else "")
            continue
        if value.isdigit() and 1 <= int(value) <= len(entries):
            current += entries[int(value) - 1] + "/"
            continue
        if value.startswith(remote):
            return value.rstrip("/") + "/"
        return remote + value.strip("/") + "/"


def _remote_file_size(remote_file: str) -> int | None:
    result = _rclone(["size", remote_file, "--json"])
    if result.returncode:
        return None
    try:
        return int(json.loads(result.stdout).get("bytes"))
    except (ValueError, TypeError):
        return None


def _upload_file(local: Path, remote_file: str) -> None:
    if _remote_file_size(remote_file) == local.stat().st_size:
        print(f"[upload] already verified {local.name}", flush=True)
        return
    print(f"[upload] starting {local.name} ({local.stat().st_size:,} bytes)", flush=True)
    result = _rclone([
        "copyto", str(local), remote_file,
        "--retries", "4", "--low-level-retries", "8",
        "--stats", "5s", "--stats-one-line", "--stats-log-level", "NOTICE",
    ], stream=True)
    if result.returncode:
        raise RuntimeError(f"rclone upload failed for {local.name}: {result.stdout.strip()}")
    if _remote_file_size(remote_file) != local.stat().st_size:
        raise RuntimeError(f"rclone size verification failed for {local.name}")


def _select_scene(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    for index, scene in enumerate(scenes, 1):
        print(_format_scene(scene, index))
    while True:
        value = input("Select an exportable scene number: ").strip()
        if value.isdigit() and 1 <= int(value) <= len(scenes):
            selected = scenes[int(value) - 1]
            if selected["exportable"]:
                return selected
            print("That scene has no active rendered observation.")


def _choose_payload(scene: Mapping[str, Any], non_interactive: bool, args: argparse.Namespace) -> dict[str, Any]:
    all_cameras = list(scene["camera_ids"])
    if args.cameras:
        cameras = [item.strip() for item in args.cameras.split(",") if item.strip()]
    elif non_interactive or _prompt_bool(f"Use all cameras ({', '.join(all_cameras) or 'none'})?", True):
        cameras = all_cameras
    else:
        cameras = [item.strip() for item in input("Comma-separated camera IDs: ").split(",") if item.strip()]
    polar = not args.no_polar if non_interactive else _prompt_bool("Include canonical Stokes core?", not args.no_polar)
    perturbed = not args.no_perturbed if non_interactive else _prompt_bool(
        "Include passive + active-polar branches (separate observations_perturbed[_active_polar] paths)?",
        not args.no_perturbed,
    )
    thumbnails = bool(args.thumbnails) if non_interactive else _prompt_bool("Include episode thumbnails?", bool(args.thumbnails))
    birdseye = not args.no_birdseye if non_interactive else _prompt_bool("Include birdseye maps?", not args.no_birdseye)
    completed = not args.include_incomplete if non_interactive else _prompt_bool("Only completed observations?", not args.include_incomplete)
    raw = bool(args.raw) if non_interactive else _prompt_bool("Include raw legacy products (EXR/full Stokes)?", bool(args.raw))
    profile = args.profile
    if not non_interactive:
        profile = _prompt_choice(
            "Package profile: 1 compact core+polar, 2 single lossless, 3 legacy full, 4 PNG+Stokes core",
            ("1", "2", "3", "4"),
            default="1",
        )
        profile = {
            "1": "compact_with_polar_extension",
            "2": "single_lossless_core",
            "3": "legacy_full",
            "4": "png_stokes_core",
        }[profile]
    if raw:
        profile = "legacy_full"
    elif not polar and profile == "compact_with_polar_extension":
        profile = "navigation_only"
    modalities = [item.strip() for item in (args.modalities or "").split(",") if item.strip()]
    return {
        "scene_id": scene["scene_id"], "camera_ids": cameras or None,
        "modalities": modalities or None,
        "only_completed": completed, "include_episode_thumbnails": thumbnails,
        "panorama_observations": True, "png_only": not raw,
        "include_birdseye": birdseye, "include_polarization_raw": polar,
        # The daemon materializes passive and active-polar observations into
        # distinct directories and writes a base/passive/active triad index.
        "include_episode_birdseye": False, "eval_perturbation": perturbed,
        "include_active_polar": perturbed,
        "export_profile": profile,
        "coverage_levels": [item.strip() for item in (args.coverage_levels or "").split(",") if item.strip()] or None,
    }


def _daemon_upload_payload(remote_root: str) -> dict[str, Any]:
    """Translate the wizard's Drive browser result into the daemon-safe API."""
    root = remote_root.rstrip("/") + "/"
    if not root.startswith(DEFAULT_REMOTE):
        raise ValueError(f"Wizard Drive root must stay below {DEFAULT_REMOTE}")
    destination = root[len(DEFAULT_REMOTE):].strip("/") or "dataset/opticalnav"
    if any(part in {"", ".", ".."} for part in destination.split("/")):
        raise ValueError("Drive path must be a safe relative folder")
    return {
        "enabled": True,
        "target": "google_drive",
        "destination_subpath": destination,
    }


def _wait_for_export(base_url: str, project: str, scene_id: str, job_id: str, run: dict[str, Any], run_path: Path) -> dict[str, Any]:
    status_url = f"{base_url}/api/opticalnav/projects/{project}/scenes/{scene_id}/export-jobs/{job_id}"
    last = None
    while True:
        state = _http_json(status_url)
        marker = (state.get("status"), state.get("stage"), state.get("current"), state.get("total"))
        if marker != last:
            print(f"[export] {state.get('status')} {state.get('stage')} {state.get('current', 0)}/{state.get('total', 0)} {state.get('message', '')}")
            last = marker
        run["daemon_status"] = state
        run["updated_at"] = _utc_now()
        _write_json_atomic(run_path, run)
        if state.get("status") in {"succeeded", "failed", "cancelled", "interrupted"}:
            return state
        time.sleep(2)


def _archive_paths(status: Mapping[str, Any]) -> list[Path]:
    summary = status.get("summary") if isinstance(status.get("summary"), Mapping) else {}
    refs: list[str] = []
    for entry in summary.get("archives", []) if isinstance(summary, Mapping) else []:
        if isinstance(entry, Mapping) and isinstance(entry.get("zip_ref"), str):
            refs.append(entry["zip_ref"])
    for key in ("zip_ref",):
        if isinstance(summary.get(key), str):
            refs.append(summary[key])
    return [REPO_ROOT / ref for ref in dict.fromkeys(refs) if (REPO_ROOT / ref).is_file()]


def _resume_or_submit(base_url: str, project: str, run: dict[str, Any], run_path: Path) -> dict[str, Any]:
    scene_id = str(run["scene_id"])
    job_id = run.get("daemon_job_id")
    if job_id:
        status = _http_json(f"{base_url}/api/opticalnav/projects/{project}/scenes/{scene_id}/export-jobs/{job_id}")
        if status.get("status") == "succeeded":
            return status
        if status.get("status") in {"failed", "cancelled", "interrupted"}:
            _http_json(f"{base_url}/api/opticalnav/projects/{project}/scenes/{scene_id}/export-jobs/{job_id}/resume", method="POST", payload={})
        return _wait_for_export(base_url, project, scene_id, str(job_id), run, run_path)
    response = _http_json(f"{base_url}/api/opticalnav/projects/{project}/scenes/{scene_id}/export-jobs", method="POST", payload=run["export_payload"])
    run["daemon_job_id"] = response["job_id"]
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    return _wait_for_export(base_url, project, scene_id, str(response["job_id"]), run, run_path)


def _local_export_command(run: Mapping[str, Any], run_path: Path) -> tuple[list[str], Path, Path]:
    """Build the direct exporter command and its deterministic bundle paths."""
    payload = run["export_payload"]
    run_dir = run_path.parent
    bundle_dir = run_dir / "bundle"
    archive = bundle_dir.with_suffix(".zip")
    command = [
        sys.executable, str(REPO_ROOT / "apps" / "export_optical_nav_dataset.py"),
        "--scene", str(run["scene_id"]), "--exact-scene",
        # Point at exactly one project: the direct exporter can then inspect
        # only this scene's active pointers rather than every project below
        # out/opticalnav on an NFS mount.
        "--versioned-root", str(_project_dir(str(run["project"]))),
        "--out", str(bundle_dir), "--image-format", "jpeg", "--jpeg-quality", "95",
        "--no-from-exr", "--keep-manifests", "--zip", "--no-legacy-bridge-jobs",
        "--polarization-raw-format", "minimal-f16",
    ]
    camera_ids = payload.get("camera_ids")
    if isinstance(camera_ids, list) and camera_ids:
        command.extend(["--camera-ids", ",".join(str(camera) for camera in camera_ids)])
    modalities = payload.get("modalities")
    if isinstance(modalities, list) and modalities:
        command.extend(["--modalities", ",".join(str(modality) for modality in modalities)])
    levels = payload.get("coverage_levels")
    if isinstance(levels, list) and levels:
        command.extend(["--coverage-levels", ",".join(str(level) for level in levels)])
    if not payload.get("include_polarization_raw", False):
        command.append("--no-polarization-raw")
    if not payload.get("include_birdseye", True):
        command.append("--no-birdseye")
    if not payload.get("eval_perturbation", False):
        command.extend(["--variants", "base"])
    return command, bundle_dir, archive


def _run_local_export(run: dict[str, Any], run_path: Path) -> tuple[dict[str, Any], list[Path]]:
    """Export without HTTP; only rclone remains an external dependency."""
    command, bundle_dir, archive = _local_export_command(run, run_path)
    if not archive.is_file():
        run["status"] = "exporting"
        run["updated_at"] = _utc_now()
        _write_json_atomic(run_path, run)
        print("[local-export] " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=REPO_ROOT, text=True)
        if result.returncode:
            status = {"status": "failed", "stage": "local-export", "error": f"exporter exited {result.returncode}"}
            run["local_status"] = status
            run["status"] = "failed"
            _write_json_atomic(run_path, run)
            return status, []
    if not archive.is_file():
        status = {"status": "failed", "stage": "local-export", "error": f"archive missing: {archive}"}
        run["local_status"] = status
        run["status"] = "failed"
        _write_json_atomic(run_path, run)
        return status, []
    report = run_path.parent / "export_report.json"
    file_manifest = run_path.parent / "export_file_manifest.json"
    _write_json_atomic(report, {
        "mode": "local", "scene_id": run["scene_id"], "bundle": str(bundle_dir),
        "archive": str(archive), "completed_at": _utc_now(),
    })
    archive_checksum = _cached_checksum(file_manifest, archive)
    if archive_checksum is None:
        archive_checksum = _sha256(archive, label=f"hashing {archive.name}")
    _write_json_atomic(file_manifest, {
        "files": [{"path": str(archive), "bytes": archive.stat().st_size, "sha256": archive_checksum}],
    })
    run["exports_root"] = str(run_path.parent)
    status = {"status": "succeeded", "stage": "local-export", "summary": {"zip_ref": str(archive.relative_to(REPO_ROOT))}}
    run["local_status"] = status
    run["status"] = "exported"
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    return status, [archive]


def _split_archive(archive: Path, part_bytes: int) -> list[Path]:
    """Cut a large archive into fixed-size parts next to it.

    Upload progress is recorded per file, so a single multi-dozen-GiB archive
    is all-or-nothing: an interrupted transfer restarts from zero, which on a
    slow link throws away hours. Parts are recorded individually, so a resume
    re-sends at most one part. Concatenating the parts in order reproduces the
    archive byte for byte -- no unzip-aware tooling is required to rebuild it.
    """
    parts_dir = archive.parent / (archive.name + ".parts")
    total = archive.stat().st_size
    expected = (total + part_bytes - 1) // part_bytes
    existing = sorted(parts_dir.glob(f"{archive.name}.part*")) if parts_dir.is_dir() else []
    if len(existing) == expected and sum(item.stat().st_size for item in existing) == total:
        print(f"[split] reusing {expected} existing parts for {archive.name}", flush=True)
        return existing
    parts_dir.mkdir(parents=True, exist_ok=True)
    for stale in existing:
        stale.unlink()
    parts: list[Path] = []
    with archive.open("rb") as handle:
        for index in range(expected):
            part = parts_dir / f"{archive.name}.part{index:03d}"
            remaining = part_bytes
            with part.open("wb") as out:
                while remaining > 0:
                    chunk = handle.read(min(1 << 24, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            parts.append(part)
            print(f"[split] {part.name} ({part.stat().st_size:,} bytes) - {index + 1}/{expected}", flush=True)
    return parts


def _write_parts_manifest(archive: Path, parts: list[Path], archive_sha: str | None) -> Path:
    manifest = archive.parent / (archive.name + ".parts.json")
    _write_json_atomic(manifest, {
        "archive": archive.name,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": archive_sha,
        "part_count": len(parts),
        "reassemble": f"cat {archive.name}.part* > {archive.name}",
        "parts": [{"name": part.name, "bytes": part.stat().st_size} for part in parts],
    })
    return manifest


def _upload_run(run: dict[str, Any], run_path: Path, archives: list[Path]) -> None:
    remote_root = str(run["remote_root"]).rstrip("/") + "/"
    remote_dir = remote_root + f"{run['scene_id']}/{run['run_id']}/"
    exports_root = Path(run["exports_root"])
    extras = [path for path in (exports_root / "export_report.json", exports_root / "export_file_manifest.json") if path.is_file()]
    split_bytes = int(run.get("split_size_bytes") or 0)
    uploadable: list[Path] = []
    for archive in archives:
        if split_bytes > 0 and archive.stat().st_size > split_bytes:
            parts = _split_archive(archive, split_bytes)
            uploadable.extend(parts)
            uploadable.append(_write_parts_manifest(
                archive, parts, _cached_checksum(exports_root / "export_file_manifest.json", archive)))
        else:
            uploadable.append(archive)
    files = uploadable + extras
    records = dict(run.get("uploads") or {})
    checksum_manifest = exports_root / "export_file_manifest.json"
    run["status"] = "uploading"
    run["remote_dir"] = remote_dir
    run["upload_started_at"] = run.get("upload_started_at") or _utc_now()
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    for local in files:
        remote_file = remote_dir + local.name
        _upload_file(local, remote_file)
        existing = records.get(local.name)
        checksum = (
            str(existing.get("sha256"))
            if isinstance(existing, Mapping)
            and int(existing.get("bytes") or -1) == local.stat().st_size
            and isinstance(existing.get("sha256"), str)
            else _cached_checksum(checksum_manifest, local)
        )
        if checksum is None:
            checksum = _sha256(local, label=f"hashing {local.name} for upload record")
        records[local.name] = {"remote": remote_file, "bytes": local.stat().st_size, "sha256": checksum, "verified": True}
        run["uploads"] = records
        run["updated_at"] = _utc_now()
        _write_json_atomic(run_path, run)
        print(f"[upload] verified {local.name}")
    success = run_path.parent / "_SUCCESS.json"
    _write_json_atomic(success, {"run_id": run["run_id"], "scene_id": run["scene_id"], "completed_at": _utc_now(), "files": records})
    _upload_file(success, remote_dir + success.name)
    run["status"] = "succeeded"
    run["remote_dir"] = remote_dir
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--daemon-url", default="http://127.0.0.1:8765")
    parser.add_argument("--local", action="store_true", help="Export directly in this process; do not contact port 8765.")
    parser.add_argument("--list", action="store_true", help="List candidate scenes and exit.")
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--scene")
    parser.add_argument("--cameras", help="Comma-separated sensor IDs.")
    parser.add_argument(
        "--coverage-levels",
        help=(
            "Comma-separated sweep coverage level IDs whose union is the export universe "
            "(e.g. sv1_episode_headings,sv2_base_panorama_12). Each names a scene-local "
            "support_sweep_coverage_<level>.json. Defaults to the scene's V4 L0 plan or viewpoint graph."
        ),
    )
    parser.add_argument(
        "--modalities",
        help=(
            "Comma-separated artifact modalities to export as images (e.g. s0). "
            "Defaults to every modality the observation manifest declares."
        ),
    )
    parser.add_argument("--drive-path", help="Path under gdrive:, e.g. dataset/opticalnav.")
    parser.add_argument(
        "--profile",
        choices=["compact_with_polar_extension", "single_lossless_core", "navigation_only", "png_stokes_core", "legacy_full"],
        default="compact_with_polar_extension",
    )
    parser.add_argument("--no-polar", action="store_true")
    parser.add_argument("--no-perturbed", action="store_true")
    parser.add_argument("--thumbnails", action="store_true")
    parser.add_argument("--no-birdseye", action="store_true")
    parser.add_argument("--include-incomplete", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Skip final interactive confirmation.")
    parser.add_argument("--split-size-gib", type=float, default=8.0,
                        help="Split archives larger than this into parts so an interrupted upload resumes "
                             "per part instead of restarting the whole archive. 0 disables splitting.")
    return parser.parse_args()


def main() -> int:
    args = _args()
    project_dir = _project_dir(args.project)
    if not project_dir.is_dir():
        print(f"[error] project not found: {project_dir}", file=sys.stderr)
        return 2
    # The wizard is an export launcher, not a scene browser.  Hide imported
    # or authoring-only scenes that have no completed observation to avoid a
    # several-hundred-row menu where nearly every choice is unusable.
    # A selected scene is a hard workspace boundary.  Do not build the export
    # picker by enumerating every other scene/ledger first.
    stage_started = time.monotonic()
    scope = args.scene or "all scenes (picker)"
    print(f"[stage] inspect export readiness: {scope} ...", flush=True)
    coverage_levels = [level.strip() for level in (args.coverage_levels or "").split(",") if level.strip()]
    if coverage_levels and not args.scene:
        print("[error] --coverage-levels requires --scene", file=sys.stderr)
        return 2
    scenes = [scene for scene in discover_scenes(
        project_dir,
        scene_ids=[args.scene] if args.scene else None,
        coverage_levels=coverage_levels or None,
    ) if scene["exportable"]]
    print(f"[stage] readiness complete in {time.monotonic() - stage_started:.1f}s · {len(scenes)} exportable scene(s)", flush=True)
    if args.list:
        for index, scene in enumerate(scenes, 1):
            print(_format_scene(scene, index))
        return 0
    if args.resume:
        if not args.scene:
            print("[error] --resume requires --scene so no other scene workspace is scanned", file=sys.stderr)
            return 2
        runs_root = project_dir / "scenes" / args.scene / "operations" / "exports" / "wizard_runs"
        run_path = runs_root / args.resume / "run.json"
        run = _read_json(run_path)
        if not isinstance(run, Mapping):
            print(f"[error] unknown wizard run: {args.resume}", file=sys.stderr)
            return 2
        run = dict(run)
    else:
        if args.scene:
            selected = next((scene for scene in scenes if scene["scene_id"] == args.scene), None)
            if selected is None or not selected["exportable"]:
                print("[error] --scene must identify an exportable scene", file=sys.stderr)
                return 2
        else:
            if args.non_interactive:
                print("[error] --non-interactive requires --scene and --drive-path", file=sys.stderr)
                return 2
            if not scenes:
                print("[error] no scenes with completed observations are available for export", file=sys.stderr)
                return 2
            selected = _select_scene(scenes)
        payload = _choose_payload(selected, args.non_interactive, args)
        remote_root = DEFAULT_REMOTE + args.drive_path.strip("/") + "/" if args.drive_path else _browse_drive(DEFAULT_REMOTE)
        payload["upload"] = _daemon_upload_payload(remote_root)
        run_id = "export-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        runs_root = project_dir / "scenes" / selected["scene_id"] / "operations" / "exports" / "wizard_runs"
        run_path = runs_root / run_id / "run.json"
        run = {
            "run_id": run_id, "project": args.project, "scene_id": selected["scene_id"],
            "daemon_url": args.daemon_url.rstrip("/"), "mode": "local" if args.local else "daemon", "remote_root": remote_root,
            "export_payload": payload, "daemon_job_id": None, "uploads": {}, "status": "planned",
            "split_size_bytes": int(args.split_size_gib * (1 << 30)) if args.split_size_gib > 0 else 0,
            # Persisted so a resumed run reconciles the same view universe it
            # was planned against, even if the scene gains coverage later.
            "coverage_levels": coverage_levels,
            "created_at": _utc_now(), "updated_at": _utc_now(),
        }
        print("\nExport summary")
        print(json.dumps({"scene": run["scene_id"], "payload": payload, "drive": remote_root}, ensure_ascii=False, indent=2))
        if not args.yes and not _prompt_bool("Start export?", True):
            return 0
        _write_json_atomic(run_path, run)

    payload = run.get("export_payload") if isinstance(run.get("export_payload"), Mapping) else {}
    export_variants = ["base"]
    if bool(payload.get("eval_perturbation", False)):
        export_variants.append("perturbed")
    if bool(payload.get("include_active_polar", False)):
        export_variants.append("perturbed_active_polar")
    try:
        print(f"[stage] reconcile completed observations for {run['scene_id']} ...", flush=True)
        reconcile_started = time.monotonic()
        reconciliation = _reconcile_current_pointers(
            project_dir,
            scene_id=str(run["scene_id"]),
            variants=export_variants,
            # ``only_completed`` means a V4 recovery may be packaged from the
            # immutable observations that already exist; missing native poses
            # are surfaced in the export manifest instead of being replaced by
            # stale legacy vp_* graph entries.
            allow_partial_v4=bool(payload.get("only_completed", False)),
            coverage_levels=[
                str(level) for level in (run.get("coverage_levels") or []) if str(level).strip()
            ] or None,
        )
    except RuntimeError as exc:
        run["status"] = "blocked"
        run["pointer_reconciliation_error"] = str(exc)
        run["updated_at"] = _utc_now()
        _write_json_atomic(run_path, run)
        print(f"[error] export pointer reconciliation failed: {exc}", file=sys.stderr)
        return 1
    run["pointer_reconciliation"] = reconciliation
    # A retry that succeeds must not leave the previous attempt's error behind:
    # a resumed run is written in place, so a stale key here reads as a failure
    # on a run whose status is "succeeded".
    run.pop("pointer_reconciliation_error", None)
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    print(
        f"[stage] reconciliation complete in {time.monotonic() - reconcile_started:.1f}s\n"
        "[pointers] " + json.dumps(reconciliation, ensure_ascii=False, sort_keys=True),
        flush=True,
    )

    local_mode = str(run.get("mode") or "daemon") == "local"
    if local_mode:
        print("[stage] begin local bundle export ...", flush=True)
        status, archives = _run_local_export(run, run_path)
    else:
        base_url = str(run.get("daemon_url") or args.daemon_url).rstrip("/")
        status = _resume_or_submit(base_url, args.project, run, run_path)
        archives = _archive_paths(status)
    if status.get("status") != "succeeded":
        print(f"[error] export stopped: {status.get('error') or status.get('message')}; resume with --resume {run['run_id']}", file=sys.stderr)
        return 1
    if local_mode:
        _upload_run(run, run_path, archives)
        print(f"[done] {run['remote_dir']}\n[resume] python apps/export_opticalnav_wizard.py --project {args.project} --resume {run['run_id']}")
        return 0
    summary = status.get("summary") if isinstance(status.get("summary"), Mapping) else {}
    upload = summary.get("upload") if isinstance(summary.get("upload"), Mapping) else {}
    remote_dir = upload.get("remote_dir") or status.get("remote_dir") or run.get("remote_dir")
    if not remote_dir:
        print("[error] daemon export succeeded but Google Drive upload state is missing", file=sys.stderr)
        return 1
    run["status"] = "succeeded"
    run["daemon_status"] = status
    run["remote_dir"] = remote_dir
    run["uploads"] = upload.get("files") or status.get("uploads") or {}
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    print(f"[done] {remote_dir}\n[resume] python apps/export_opticalnav_wizard.py --project {args.project} --resume {run['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
