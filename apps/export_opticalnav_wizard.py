#!/usr/bin/env python3
"""Interactive, resumable OpticalNav export and Google Drive upload wizard.

The daemon remains the authoritative exporter. This CLI owns only user choices,
durable orchestration, and file-level rclone resume state. A run can therefore
be safely continued after a terminal disconnect with ``--resume <run-id>``.
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
            sensors = bundle / "sensors" if bundle is not None else None
            if sensors is not None and sensors.is_dir():
                for sensor in sensors.iterdir():
                    if sensor.is_dir() and (sensor / "rgb.png").is_file():
                        counts[sensor.name] = counts.get(sensor.name, 0) + 1
                continue
        except OSError:
            pass
        parts = pointer.relative_to(root).parts
        sensor = next((parts[i + 1] for i, part in enumerate(parts[:-1]) if part in {"sensors", "cameras"}), None)
        if sensor:
            counts[sensor] = counts.get(sensor, 0) + 1
    return counts


def _ledger_sensor_inventory(project_dir: Path) -> dict[str, dict[str, dict[str, int]]]:
    """Read completed sensor counts with one indexed SQLite scan, not NFS walks."""
    ledger = project_dir / "render_ledger.sqlite3"
    inventory: dict[str, dict[str, dict[str, int]]] = {}
    if not ledger.is_file():
        return inventory
    try:
        connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
        # One newest completed run per scene is the exportable active snapshot.
        # Querying every historical retry run made a simple menu take minutes on
        # an NFS-backed ledger.
        newest: dict[str, list[str]] = {}
        for run_id, scene_id in connection.execute(
            "SELECT run_id, scene_id FROM sweep_runs "
            "WHERE status IN ('completed', 'ready', 'paused') ORDER BY created_at DESC"
        ):
            bucket = newest.setdefault(str(scene_id), [])
            if len(bucket) < 8:
                bucket.append(str(run_id))
        for scene_id, run_ids in sorted(newest.items()):
            selected: set[str] = set()
            scene_counts = inventory.setdefault(scene_id, {"base": {}, "perturbed": {}})
            for run_id in run_ids:
                run_counts = {"base": {}, "perturbed": {}}
                for variant, metadata_raw in connection.execute(
                    "SELECT variant, metadata_json FROM sweep_tasks WHERE run_id = ? AND state = 'succeeded'",
                    (run_id,),
                ):
                    try:
                        metadata = json.loads(metadata_raw or "{}")
                    except (TypeError, ValueError):
                        metadata = {}
                    sensor_ids = metadata.get("sensor_ids") or list((metadata.get("modalities_by_sensor") or {}).keys())
                    bucket = "perturbed" if "perturb" in str(variant).lower() else "base"
                    for sensor_id in sensor_ids:
                        sensor = str(sensor_id)
                        run_counts[bucket][sensor] = run_counts[bucket].get(sensor, 0) + 1
                for bucket in ("base", "perturbed"):
                    if run_counts[bucket] and bucket not in selected:
                        scene_counts[bucket] = run_counts[bucket]
                        selected.add(bucket)
                if len(selected) == 2:
                    break
    except sqlite3.Error:
        return {}
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    return inventory


def discover_scenes(project_dir: Path) -> list[dict[str, Any]]:
    """Return exportable scenes newest first without contacting a daemon."""
    root = project_dir / "scenes"
    scenes: list[dict[str, Any]] = []
    if not root.is_dir():
        return scenes
    inventory = _ledger_sensor_inventory(project_dir)
    for scene_dir in root.iterdir():
        if not scene_dir.is_dir():
            continue
        counts = inventory.get(scene_dir.name)
        if counts is None and not inventory:
            # Legacy projects without a ledger are uncommon. Keep that fallback
            # isolated so a modern project's menu never recursively walks NFS.
            base = _sensor_counts(project_dir, scene_dir.name, "observations")
            perturbed = _sensor_counts(project_dir, scene_dir.name, "observations_perturbed")
        else:
            base, perturbed = (counts or {"base": {}, "perturbed": {}})["base"], (counts or {"base": {}, "perturbed": {}})["perturbed"]
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
            "camera_ids": sorted(set(base) | set(perturbed)),
            "exportable": bool(sum(base.values()) + sum(perturbed.values())),
        })
    return sorted(scenes, key=lambda item: item["modified_at"], reverse=True)


def _format_scene(scene: Mapping[str, Any], index: int) -> str:
    stamp = datetime.fromtimestamp(float(scene["modified_at"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    def compact(counts: Mapping[str, int]) -> str:
        return ", ".join(f"{key}:{value}" for key, value in sorted(counts.items())) or "—"
    state = "OK" if scene["exportable"] else "NO RENDER"
    return f"[{index:2}] {state:9} {stamp}  {scene['scene_id']}\n     base({compact(scene['base'])})  perturbed({compact(scene['perturbed'])})"


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


def _rclone(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["rclone", *args], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


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
        return
    result = _rclone(["copyto", str(local), remote_file, "--retries", "4", "--low-level-retries", "8", "--stats-one-line"])
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
    polar = not args.no_polar if non_interactive else _prompt_bool("Include polar Stokes extension?", not args.no_polar)
    perturbed = not args.no_perturbed if non_interactive else _prompt_bool("Include perturbed base↔perturbed pairs?", not args.no_perturbed)
    thumbnails = bool(args.thumbnails) if non_interactive else _prompt_bool("Include episode thumbnails?", bool(args.thumbnails))
    birdseye = not args.no_birdseye if non_interactive else _prompt_bool("Include birdseye maps?", not args.no_birdseye)
    completed = not args.include_incomplete if non_interactive else _prompt_bool("Only completed observations?", not args.include_incomplete)
    raw = bool(args.raw) if non_interactive else _prompt_bool("Include raw legacy products (EXR/full Stokes)?", bool(args.raw))
    profile = args.profile
    if not non_interactive:
        profile = _prompt_choice("Package profile: 1 compact core+polar, 2 single lossless, 3 legacy full", ("1", "2", "3"), default="1")
        profile = {"1": "compact_with_polar_extension", "2": "single_lossless_core", "3": "legacy_full"}[profile]
    if raw:
        profile = "legacy_full"
    elif not polar and profile == "compact_with_polar_extension":
        profile = "navigation_only"
    return {
        "scene_id": scene["scene_id"], "camera_ids": cameras or None,
        "only_completed": completed, "include_episode_thumbnails": thumbnails,
        "panorama_observations": True, "png_only": False,
        "include_birdseye": birdseye, "include_polarization_raw": polar,
        "include_episode_birdseye": False, "eval_perturbation": perturbed,
        "export_profile": profile,
    }


def _wait_for_export(base_url: str, project: str, job_id: str, run: dict[str, Any], run_path: Path) -> dict[str, Any]:
    status_url = f"{base_url}/api/opticalnav/projects/{project}/export-jobs/{job_id}"
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
    job_id = run.get("daemon_job_id")
    if job_id:
        status = _http_json(f"{base_url}/api/opticalnav/projects/{project}/export-jobs/{job_id}")
        if status.get("status") == "succeeded":
            return status
        if status.get("status") in {"failed", "cancelled", "interrupted"}:
            _http_json(f"{base_url}/api/opticalnav/projects/{project}/export-jobs/{job_id}/resume", method="POST", payload={})
        return _wait_for_export(base_url, project, str(job_id), run, run_path)
    response = _http_json(f"{base_url}/api/opticalnav/projects/{project}/export-jobs", method="POST", payload=run["export_payload"])
    run["daemon_job_id"] = response["job_id"]
    run["updated_at"] = _utc_now()
    _write_json_atomic(run_path, run)
    return _wait_for_export(base_url, project, str(response["job_id"]), run, run_path)


def _upload_run(run: dict[str, Any], run_path: Path, archives: list[Path]) -> None:
    remote_root = str(run["remote_root"]).rstrip("/") + "/"
    remote_dir = remote_root + f"{run['scene_id']}/{run['run_id']}/"
    exports_root = Path(run["exports_root"])
    extras = [path for path in (exports_root / "export_report.json", exports_root / "export_file_manifest.json") if path.is_file()]
    files = archives + extras
    records = dict(run.get("uploads") or {})
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
    parser.add_argument("--list", action="store_true", help="List candidate scenes and exit.")
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--scene")
    parser.add_argument("--cameras", help="Comma-separated sensor IDs.")
    parser.add_argument("--drive-path", help="Path under gdrive:, e.g. dataset/opticalnav.")
    parser.add_argument("--profile", choices=["compact_with_polar_extension", "single_lossless_core", "navigation_only", "legacy_full"], default="compact_with_polar_extension")
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
    scenes = discover_scenes(project_dir)
    if args.list:
        for index, scene in enumerate(scenes, 1):
            print(_format_scene(scene, index))
        return 0
    runs_root = project_dir / "exports" / "wizard_runs"
    if args.resume:
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
            selected = _select_scene(scenes)
        payload = _choose_payload(selected, args.non_interactive, args)
        remote_root = DEFAULT_REMOTE + args.drive_path.strip("/") + "/" if args.drive_path else _browse_drive(DEFAULT_REMOTE)
        run_id = "export-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        run_path = runs_root / run_id / "run.json"
        run = {
            "run_id": run_id, "project": args.project, "scene_id": selected["scene_id"],
            "daemon_url": args.daemon_url.rstrip("/"), "remote_root": remote_root,
            "export_payload": payload, "daemon_job_id": None, "uploads": {}, "status": "planned",
            "created_at": _utc_now(), "updated_at": _utc_now(),
        }
        print("\nExport summary")
        print(json.dumps({"scene": run["scene_id"], "payload": payload, "drive": remote_root}, ensure_ascii=False, indent=2))
        if not args.yes and not _prompt_bool("Start export?", True):
            return 0
        _write_json_atomic(run_path, run)
    base_url = str(run.get("daemon_url") or args.daemon_url).rstrip("/")
    status = _resume_or_submit(base_url, args.project, run, run_path)
    if status.get("status") != "succeeded":
        print(f"[error] export stopped: {status.get('error') or status.get('message')}; resume with --resume {run['run_id']}", file=sys.stderr)
        return 1
    archives = _archive_paths(status)
    if not archives:
        print("[error] daemon reported success but no archive was found", file=sys.stderr)
        return 1
    run["exports_root"] = str(archives[0].parent)
    _write_json_atomic(run_path, run)
    _upload_run(run, run_path, archives)
    print(f"[done] {run['remote_dir']}\n[resume] python apps/export_opticalnav_wizard.py --project {args.project} --resume {run['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
