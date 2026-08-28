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
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        try:
            connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
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
            continue
        finally:
            connection.close()
    return inventory


def discover_scenes(project_dir: Path, *, scene_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
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
        if counts is None and not inventory:
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
    return {
        "scene_id": scene["scene_id"], "camera_ids": cameras or None,
        "only_completed": completed, "include_episode_thumbnails": thumbnails,
        "panorama_observations": True, "png_only": not raw,
        "include_birdseye": birdseye, "include_polarization_raw": polar,
        # The daemon materializes passive and active-polar observations into
        # distinct directories and writes a base/passive/active triad index.
        "include_episode_birdseye": False, "eval_perturbation": perturbed,
        "include_active_polar": perturbed,
        "export_profile": profile,
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
    ]
    camera_ids = payload.get("camera_ids")
    if isinstance(camera_ids, list) and camera_ids:
        command.extend(["--camera-ids", ",".join(str(camera) for camera in camera_ids)])
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
    _write_json_atomic(file_manifest, {
        "files": [{"path": str(archive), "bytes": archive.stat().st_size, "sha256": _sha256(archive)}],
    })
    run["exports_root"] = str(run_path.parent)
    status = {"status": "succeeded", "stage": "local-export", "summary": {"zip_ref": str(archive.relative_to(REPO_ROOT))}}
    run["local_status"] = status
    run["status"] = "exported"
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    return status, [archive]


def _upload_run(run: dict[str, Any], run_path: Path, archives: list[Path]) -> None:
    remote_root = str(run["remote_root"]).rstrip("/") + "/"
    remote_dir = remote_root + f"{run['scene_id']}/{run['run_id']}/"
    exports_root = Path(run["exports_root"])
    extras = [path for path in (exports_root / "export_report.json", exports_root / "export_file_manifest.json") if path.is_file()]
    files = archives + extras
    records = dict(run.get("uploads") or {})
    run["status"] = "uploading"
    run["remote_dir"] = remote_dir
    run["upload_started_at"] = run.get("upload_started_at") or _utc_now()
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    for local in files:
        remote_file = remote_dir + local.name
        _upload_file(local, remote_file)
        records[local.name] = {"remote": remote_file, "bytes": local.stat().st_size, "sha256": _sha256(local), "verified": True}
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
    scenes = [scene for scene in discover_scenes(
        project_dir,
        scene_ids=[args.scene] if args.scene else None,
    ) if scene["exportable"]]
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
            "created_at": _utc_now(), "updated_at": _utc_now(),
        }
        print("\nExport summary")
        print(json.dumps({"scene": run["scene_id"], "payload": payload, "drive": remote_root}, ensure_ascii=False, indent=2))
        if not args.yes and not _prompt_bool("Start export?", True):
            return 0
        _write_json_atomic(run_path, run)
    local_mode = str(run.get("mode") or "daemon") == "local"
    if local_mode:
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
