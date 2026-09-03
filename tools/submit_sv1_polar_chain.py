#!/usr/bin/env python3
"""Submit and durably manage base -> perturbed -> perturbed_active_polar SV1
episode-heading polar renders for one scene, then keep polling until terminal.

Adapted from tools/submit_support_polar_l3.py (payload shape) and
apps/continue_opticalnav_polar_chain.py (durable chaining/polling), but
self-contained: it submits every stage itself (no pre-existing templates
needed) and discovers each stage's plan_total dynamically from the ledger
instead of requiring it as an argument.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path("/jarvis/project/robomituba")
PROJECT_ID = "opticalnav-v0.2"
SCENE_ID = "infinigen_apartment_natural_v1_20260827"
DAEMON_URL = "http://127.0.0.1:8766"
POLL_SECONDS = 30.0
TERMINAL = {"succeeded", "skipped", "failed", "cancelled"}
VARIANTS = ("base", "perturbed", "perturbed_active_polar")
POLAR_MODALITIES = ["polar_rgb_preview", "s1_over_s0", "s2_over_s0", "dop", "aolp", "s1", "s2"]

SCENE_DIR = REPO_ROOT / "out" / "opticalnav" / PROJECT_ID / "scenes" / SCENE_ID
LEDGER = SCENE_DIR / "operations" / "render_ledger.sqlite3"
STATE_PATH = SCENE_DIR / "operations" / "sv1_polar_chain_state.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _post_json(url: str, body: Mapping[str, Any]) -> dict[str, Any]:
    request = Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"POST {url} failed: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("batch_id"):
        raise RuntimeError(f"queue did not return a batch id: {payload}")
    return payload


def _polar_camera_spec() -> dict[str, Any]:
    rig = _read_json(REPO_ROOT / "out" / "control_plane_cache" / "camera_rigs" / "ranger_mini_default.json")
    sensor = next(
        (item for item in rig.get("sensors", []) if isinstance(item, Mapping) and item.get("sensor_id") == "polar_cam"),
        None,
    )
    if not isinstance(sensor, Mapping):
        raise ValueError("ranger_mini_default.json does not define polar_cam")
    intrinsics = sensor.get("intrinsics") if isinstance(sensor.get("intrinsics"), Mapping) else {}
    mount = sensor.get("mount") if isinstance(sensor.get("mount"), Mapping) else {}
    source_xyz = list(mount.get("xyz_m") or [0.0, 0.1, 1.5])
    robot_mount = {
        "parent_frame": str(mount.get("parent_frame") or "base_link"),
        "xyz_m": [float(source_xyz[0]), float(source_xyz[2]), float(source_xyz[1])],
        "rpy_deg": [float(value) for value in list(mount.get("rpy_deg") or [0.0, 0.0, 0.0])],
        "source_schema": "camera_rig_v1",
    }
    resolution = list(intrinsics.get("resolution") or [512, 384])
    return {
        "camera_id": "polar_cam",
        "name": str(sensor.get("label") or "polar_cam"),
        "camera_to_world": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, robot_mount["xyz_m"][1], 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "fov_deg": float(intrinsics.get("fov_h_deg") or 90.0),
        "resolution": resolution,
        "sensor_modality": "polarization",
        "sensor_sync_group": "camera_rig",
        "calibration_ref": None,
        "extras": {
            "robot_mount": robot_mount,
            "camera_rig_id": str(rig.get("rig_id") or "ranger_mini_default"),
            "base_frame": robot_mount["parent_frame"],
            "source_sensor_modality": "polarization",
            "render_modality": "polar_rgb_preview",
            "camera_rig_source": "global_json_preset",
            "canonical_sensor_type": "polar_camera",
            "canonical_modalities": list(POLAR_MODALITIES),
            "render_modalities": list(POLAR_MODALITIES),
            "polarization": dict(sensor.get("polarization") or {}),
            # Match the just-tested saved request's render settings exactly
            # (polar_cam 512x384, spp=1024, rgb_stokes_12 default).
            "render": {"path_spp": 4096, "aov_spp": 16, "polar_spp": 1024},
        },
    }


def submit_variant(*, variant: str, sequence: int, total: int, previous_batch_id: str | None,
                    submission_group: str, profile_digest: str) -> str:
    active_policy = "k1" if variant == "perturbed_active_polar" else None
    # samples_per_pass bounds the Dr.Jit wavefront: the K=4 Stokes batch film
    # (2048x384 @ 1024spp) with an unbounded wavefront needs ~29 GB of VRAM;
    # 256/pass renders the same image in 4 passes at ~1/4 the transient memory.
    render_settings: dict[str, Any] = {
        "ambient_radiance": 1, "path_spp": 4096, "aov_spp": 16,
        "polar_spp": 1024,
    }
    if active_policy is not None:
        render_settings["active_polar_batch_policy"] = active_policy
        render_settings["active_polar_batch_min_separation_m"] = 6.0
    body = {
        "observation_plan_ref": "support_observation_plan.json",
        "sweep_coverage_ref": "support_sweep_coverage_sv1_episode_headings.json",
        "profile_digest": profile_digest,
        "backend": "daemon",
        "camera_height_m": 1.5,
        "sensor_scope": "selected",
        "sensor_ids": ["polar_cam"],
        "camera_specs": [_polar_camera_spec()],
        "modalities": list(POLAR_MODALITIES),
        "render_settings": render_settings,
        "only_missing": True,
        "scene_variant_key": variant,
        "submission_group_id": submission_group,
        "variant_sequence_index": sequence,
        "variant_sequence_total": total,
        **({"previous_variant_batch_id": previous_batch_id} if previous_batch_id else {}),
    }
    endpoint = f"{DAEMON_URL}/api/opticalnav/projects/{PROJECT_ID}/scenes/{SCENE_ID}/render-plan/submit"
    response = _post_json(endpoint, body)
    return str(response["batch_id"])


def run_counts(run_id: str) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("pragma busy_timeout=30000")
        counts = dict(connection.execute(
            "select state, count(*) from sweep_tasks where run_id=? group by state", (run_id,)
        ))
    finally:
        connection.close()
    return counts


def run_plan_total(run_id: str) -> int | None:
    connection = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("pragma busy_timeout=30000")
        row = connection.execute(
            "select metadata_json from sweep_runs where run_id=?", (run_id,)
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[0]:
        return None
    try:
        total = int(json.loads(str(row[0])).get("plan_total") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return total if total > 0 else None


def run_terminal(run_id: str, expected: int) -> tuple[bool, dict[str, int]]:
    counts = run_counts(run_id)
    completed = sum(int(counts.get(state, 0)) for state in TERMINAL)
    failed = int(counts.get("failed", 0)) + int(counts.get("cancelled", 0))
    return completed >= expected and not failed and not (set(counts) - TERMINAL), counts


def retry_terminal_jobs(run_id: str) -> tuple[int, list[str]]:
    connection = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("pragma busy_timeout=30000")
        job_ids = [
            str(row[0]) for row in connection.execute(
                """select distinct job_id from sweep_tasks
                   where run_id=? and state in ('failed', 'cancelled')
                     and job_id is not null and job_id != ''""",
                (run_id,),
            )
        ]
    finally:
        connection.close()
    retried: list[str] = []
    errors: list[str] = []
    for job_id in job_ids:
        request = Request(f"{DAEMON_URL}/api/render-jobs/{job_id}/retry", data=b"", method="POST")
        try:
            with urlopen(request, timeout=60) as response:
                if int(response.status) == 202:
                    retried.append(job_id)
                else:
                    errors.append(f"{job_id}: HTTP {response.status}")
        except Exception as exc:
            errors.append(f"{job_id}: {exc}")
    return len(retried), errors


def restart_daemon_for_clean_memory() -> None:
    """Kill and relaunch the local render daemon so the next scene_variant_key
    starts with a clean VRAM slate instead of relying on in-process eviction.

    The user asked for this explicitly: base -> free memory -> perturbed ->
    free memory -> perturbed_active_polar, each on a fresh worker.
    """
    import subprocess
    import time as _time

    print("[sv1-chain] restarting daemon for a clean VRAM slate before the next variant", flush=True)
    try:
        pids = subprocess.run(
            ["pgrep", "-f", r"run_render_daemon\.py.*--port 8766"],
            capture_output=True, text=True, check=False,
        ).stdout.split()
    except Exception as exc:
        print(f"[sv1-chain] pgrep failed: {exc}", flush=True)
        pids = []
    for pid in pids:
        try:
            subprocess.run(["kill", pid], check=False)
            print(f"[sv1-chain] killed daemon pid={pid}", flush=True)
        except Exception as exc:
            print(f"[sv1-chain] kill {pid} failed: {exc}", flush=True)
    _time.sleep(3)

    # The launcher reads every tunable from the environment with ``:=``, and
    # this orchestrator was started from a plain shell -- so inheriting os.environ
    # would relaunch the daemon on the launcher's default port with the planner's
    # K instead of the K=12 strip this run is measured against, and the readiness
    # poll below would then time out against a daemon that never bound 8766.
    # Pin the whole render contract explicitly so a variant handoff reproduces
    # the same worker the previous variant ran on.
    daemon_env = {
        **os.environ,
        "RENDER_QUEUE_PORT": "8766",
        "ROBOMITUBA_RESIDENT_STOKES_BATCH_SLOTS": "12",
        "ROBOMITUBA_POLAR_SAVE_WORKERS": "4",
        "ROBOMITUBA_RENDER_DRJIT_FREEZE": "1",
        "ROBOMITUBA_TEXTURE_MAX_RESOLUTION": "512",
        # Overlap each batch's host-side tail with the next batch's GPU render.
        # `base` ran without it; it arms here, at the first variant handoff, so
        # the two variants stay individually comparable and any regression is
        # attributable to this one switch.
        "ROBOMITUBA_POLAR_SAVE_PIPELINE": "1",
    }
    print(
        "[sv1-chain] daemon env: port=%s K=%s save_workers=%s pipeline=%s freeze=%s tex=%s"
        % (
            daemon_env["RENDER_QUEUE_PORT"],
            daemon_env["ROBOMITUBA_RESIDENT_STOKES_BATCH_SLOTS"],
            daemon_env["ROBOMITUBA_POLAR_SAVE_WORKERS"],
            daemon_env["ROBOMITUBA_POLAR_SAVE_PIPELINE"],
            daemon_env["ROBOMITUBA_RENDER_DRJIT_FREEZE"],
            daemon_env["ROBOMITUBA_TEXTURE_MAX_RESOLUTION"],
        ),
        flush=True,
    )
    # Repo-relative so a different operator (or agent) can run this without the
    # scratch directory of whoever wrote it.
    restart_log = Path(
        os.environ.get(
            "SV1_CHAIN_DAEMON_LOG",
            str(SCENE_DIR / "operations" / "daemon_variant_restart.log"),
        )
    )
    restart_log.parent.mkdir(parents=True, exist_ok=True)
    with open(restart_log, "a") as logf:
        subprocess.Popen(
            ["bash", "scripts/run_render_queue_local.sh"],
            cwd=str(REPO_ROOT), stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True, env=daemon_env,
        )
    # Probe a constant-time endpoint. /api/render-jobs enumerates every job
    # directory under out/bridge_jobs (2,400+ of them, on a CIFS mount), which
    # takes minutes -- the daemon was up and serving in 17 ms while this probe
    # timed out and killed the chain at the first variant handoff.
    deadline = _time.time() + 120
    while _time.time() < deadline:
        try:
            with urlopen(f"{DAEMON_URL}/api/health", timeout=10) as resp:
                if resp.status == 200:
                    print("[sv1-chain] daemon back up and responding", flush=True)
                    return
        except Exception:
            pass
        _time.sleep(5)
    raise RuntimeError("daemon did not come back up within 120s after restart")


def main() -> None:
    support_graph = _read_json(SCENE_DIR / "navigation_support_graph.json")
    profile_digest = str((support_graph.get("validation") or {}).get("digest") or "")
    if not profile_digest:
        raise SystemExit("navigation support validation digest is missing")

    if STATE_PATH.exists():
        state = _read_json(STATE_PATH)
    else:
        submission_group = f"sv1-{SCENE_ID}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        state = {
            "schema": "opticalnav.sv1_polar_chain.v1",
            "submission_group_id": submission_group,
            "profile_digest": profile_digest,
            "variants": {name: {"batch_id": None, "plan_total": None, "counts": {}, "retry_rounds": 0} for name in VARIANTS},
        }
        _atomic_json(STATE_PATH, state)

    print(f"[sv1-chain] state file: {STATE_PATH}", flush=True)
    previous_batch_id: str | None = None
    for index, variant in enumerate(VARIANTS):
        vstate = state["variants"][variant]
        if vstate["batch_id"] is None:
            if index > 0:
                restart_daemon_for_clean_memory()
            batch_id = submit_variant(
                variant=variant, sequence=index, total=len(VARIANTS),
                previous_batch_id=previous_batch_id,
                submission_group=state["submission_group_id"],
                profile_digest=state["profile_digest"],
            )
            vstate["batch_id"] = batch_id
            vstate["submitted_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_json(STATE_PATH, state)
            print(f"[sv1-chain] submitted {variant}: batch_id={batch_id}", flush=True)
        run_id = vstate["batch_id"]

        while True:
            plan_total = vstate.get("plan_total")
            if not plan_total:
                plan_total = run_plan_total(run_id)
                vstate["plan_total"] = plan_total
                _atomic_json(STATE_PATH, state)
            if not plan_total:
                print(f"[sv1-chain] {variant} ({run_id}): plan not materialized yet, waiting", flush=True)
                time.sleep(POLL_SECONDS)
                continue
            ready, counts = run_terminal(run_id, plan_total)
            vstate["counts"] = counts
            _atomic_json(STATE_PATH, state)
            terminal_count = sum(int(counts.get(k, 0)) for k in TERMINAL)
            failed_count = int(counts.get("failed", 0)) + int(counts.get("cancelled", 0))
            print(
                f"[sv1-chain] {variant} ({run_id}): plan_total={plan_total} "
                f"terminal={terminal_count} failed={failed_count} counts={counts}",
                flush=True,
            )
            if ready:
                break
            if failed_count and terminal_count >= plan_total and vstate.get("retry_rounds", 0) < 2:
                retried, errors = retry_terminal_jobs(run_id)
                vstate["retry_rounds"] = vstate.get("retry_rounds", 0) + 1
                vstate["last_retry_count"] = retried
                vstate["last_retry_errors"] = errors
                _atomic_json(STATE_PATH, state)
                print(f"[sv1-chain] {variant} ({run_id}): retried {retried} failed jobs (errors={errors})", flush=True)
            time.sleep(POLL_SECONDS)

        vstate["completed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(STATE_PATH, state)
        print(f"[sv1-chain] {variant} COMPLETE", flush=True)
        previous_batch_id = run_id

    print("[sv1-chain] ALL VARIANTS COMPLETE", flush=True)


if __name__ == "__main__":
    main()
