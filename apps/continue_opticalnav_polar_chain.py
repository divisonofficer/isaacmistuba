#!/usr/bin/env python3
"""Durably continue a base -> perturbed -> active-polar graph sweep chain.

This is intentionally a small operational tool: graph batches may survive a
render-daemon restart as ledger rows without their submitter thread.  Given a
completed base run and two prior batch manifests as request templates, it
submits fresh missing-only downstream batches with the *actual* predecessor
batch IDs, then records every transition in ``operations/``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any


TERMINAL = {"succeeded", "skipped", "failed", "cancelled"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def run_terminal(ledger: Path, run_id: str, expected: int) -> tuple[bool, dict[str, int]]:
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("pragma busy_timeout=30000")
        counts = dict(connection.execute(
            "select state, count(*) from sweep_tasks where run_id=? group by state", (run_id,)
        ))
    finally:
        connection.close()
    completed = sum(int(counts.get(state, 0)) for state in TERMINAL)
    failed = int(counts.get("failed", 0)) + int(counts.get("cancelled", 0))
    return completed >= expected and not failed and not (set(counts) - TERMINAL), counts


def run_plan_total(ledger: Path, run_id: str) -> int | None:
    """Return the daemon-materialized plan size, once it is available.

    An ``auto`` graph-sweep request legitimately has ``plan_total == 0`` in
    its client-side stub manifest: the daemon needs to read the graph before
    it can expand the active-polar phase.  Treating that zero as a terminal
    plan made a continuation exit immediately after submission, before the
    daemon had created a single durable task.
    """
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=30)
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


def payload_from_template(template: dict[str, Any], *, predecessor: str) -> dict[str, Any]:
    profile = dict(template["render_profile"])
    return {
        "backend": "daemon",
        "modalities": list(profile["modalities"]),
        "camera_specs": list(profile.get("camera_specs") or ()),
        "sensor_specs": list(profile.get("sensor_specs") or ()),
        "active_lights": list(profile.get("active_lights") or ()),
        "render_settings": dict(profile.get("render_settings") or {}),
        "sensor_scope": "selected",
        "sensor_ids": list(profile.get("sensor_ids") or ()),
        "scene_variant_key": str(template["scene_variant_key"]),
        "submission_group_id": str(template.get("submission_group_id") or "opticalnav-polar-chain"),
        "variant_sequence_index": int(template.get("variant_sequence_index", 0)),
        "variant_sequence_total": int(template.get("variant_sequence_total", 3)),
        "previous_variant_batch_id": predecessor,
        "sweep_execution_policy": str(template.get("execution_policy") or "per_view"),
        "only_missing": True,
        "variant": "cuda_ad_rgb_polarized",
    }


def submit(url: str, project: str, scene: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{url.rstrip('/')}/api/opticalnav/projects/{project}/scenes/{scene}/graph/sweep",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def retry_terminal_jobs(ledger: Path, run_id: str, daemon_url: str) -> tuple[int, list[str]]:
    """Requeue durable failed/cancelled jobs retained by a live daemon.

    A worker may be restarted while its first large-scene load is still
    progressing.  The ledger correctly marks the one affected task failed,
    but a chain that only waits for an all-success terminal state would then
    wait forever.  Retrying only once the run otherwise reaches a terminal
    boundary avoids competing with normal scheduling and never duplicates a
    stable job ID.
    """
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=30)
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
        request = urllib.request.Request(
            f"{daemon_url.rstrip('/')}/api/render-jobs/{job_id}/retry",
            data=b"", method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if int(response.status) == 202:
                    retried.append(job_id)
                else:
                    errors.append(f"{job_id}: HTTP {response.status}")
        except Exception as exc:
            errors.append(f"{job_id}: {exc}")
    return len(retried), errors


def verify_active_polar_artifacts(scene_dir: Path, ledger: Path, run_id: str) -> dict[str, Any]:
    """Verify the compact polar artifact contract after a fully successful run."""
    connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("pragma busy_timeout=30000")
        rows = list(connection.execute(
            """select render_version_id, variant, node_id, heading_id
               from sweep_tasks where run_id=? and state='succeeded'
               order by ordinal""",
            (run_id,),
        ))
    finally:
        connection.close()
    missing: list[str] = []
    required = ("stokes_data.npz", "polar_rgb_preview.png", "aolp_rainbow_colorbar.png")
    for version_id, variant, node_id, heading_id in rows:
        camera_dir = (
            scene_dir / "observations" / "versions" / str(version_id) / str(variant)
            / str(node_id) / str(heading_id) / "cameras" / "polar_cam"
        )
        absent = [name for name in required if not (camera_dir / name).is_file()]
        if absent:
            missing.append(f"{node_id}/{heading_id}: {', '.join(absent)}")
            if len(missing) >= 32:
                break
    return {
        "checked_successes": len(rows),
        "required": list(required),
        "missing_count": len(missing),
        "missing_examples": missing,
        "ok": not missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--scene", required=True)
    parser.add_argument("--base-run", required=True)
    parser.add_argument("--base-plan-total", type=int, required=True)
    parser.add_argument(
        "--perturbed-run",
        help="Start from an already submitted perturbed run and only continue to active-polar.",
    )
    parser.add_argument("--perturbed-template", type=Path, required=True)
    parser.add_argument("--active-template", type=Path, required=True)
    parser.add_argument("--daemon-url", default="http://127.0.0.1:8766")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument(
        "--terminal-retry-rounds", type=int, default=2,
        help="Maximum recovery rounds for failed/cancelled jobs after a run otherwise becomes terminal.",
    )
    parser.add_argument(
        "--state-path", type=Path,
        help="Optional durable state file. Use a new file when continuing from a resumed run.",
    )
    args = parser.parse_args()

    scene_dir = Path("out/opticalnav") / args.project / "scenes" / args.scene
    ledger = scene_dir / "operations" / "render_ledger.sqlite3"
    state_path = args.state_path or (scene_dir / "operations" / "polar_chain_continuation.json")
    pert_template, active_template = read_json(args.perturbed_template), read_json(args.active_template)
    state = read_json(state_path) if state_path.exists() else {
        "schema": "opticalnav.polar_chain_continuation.v1", "base_run": args.base_run,
        "base_plan_total": args.base_plan_total, "perturbed": args.perturbed_run, "active": None,
    }
    max_terminal_retry_rounds = max(0, int(args.terminal_retry_rounds))

    while True:
        if state["perturbed"] is None:
            ready, counts = run_terminal(ledger, args.base_run, args.base_plan_total)
            state["base_counts"] = counts
            if not ready:
                atomic_json(state_path, state)
                time.sleep(args.poll_seconds)
                continue
            response = submit(args.daemon_url, args.project, args.scene,
                              payload_from_template(pert_template, predecessor=args.base_run))
            state["perturbed"] = response["batch_id"]
            state["perturbed_response"] = response
            atomic_json(state_path, state)

        if state["active"] is None:
            perturbed_id = str(state["perturbed"])
            # ``graph/sweep`` returns immediately with a building stub whose
            # plan_total is deliberately 0.  The immutable template carries
            # the actual graph plan, so never let that transient 0 make the
            # active variant race the perturbed submitter thread.
            expected = int(pert_template["plan_total"])
            ready, counts = run_terminal(ledger, perturbed_id, expected)
            state["perturbed_counts"] = counts
            if not ready:
                atomic_json(state_path, state)
                time.sleep(args.poll_seconds)
                continue
            response = submit(args.daemon_url, args.project, args.scene,
                              payload_from_template(active_template, predecessor=perturbed_id))
            state["active"] = response["batch_id"]
            state["active_response"] = response
            atomic_json(state_path, state)

        active_id = str(state["active"])
        # ``perturbed_active_polar`` templates are intentionally an ``auto``
        # stub (plan_total=0). Wait for the daemon's immutable expanded plan
        # instead of interpreting zero as an already completed sweep.
        expected = int(active_template.get("plan_total") or 0)
        if expected <= 0:
            expected = run_plan_total(ledger, active_id) or 0
            state["active_plan_total"] = expected or None
            if expected <= 0:
                atomic_json(state_path, state)
                time.sleep(args.poll_seconds)
                continue
        ready, counts = run_terminal(ledger, active_id, expected)
        state["active_counts"] = counts
        terminal_count = sum(int(counts.get(key, 0)) for key in TERMINAL)
        failed_count = int(counts.get("failed", 0)) + int(counts.get("cancelled", 0))
        retry_rounds = int(state.get("active_terminal_retry_rounds", 0) or 0)
        if (
            failed_count
            and terminal_count >= expected
            and retry_rounds < max_terminal_retry_rounds
        ):
            retried, retry_errors = retry_terminal_jobs(ledger, active_id, args.daemon_url)
            state["active_terminal_retry_rounds"] = retry_rounds + 1
            state["active_terminal_retry_count"] = retried
            state["active_terminal_retry_errors"] = retry_errors
            atomic_json(state_path, state)
            time.sleep(args.poll_seconds)
            continue
        atomic_json(state_path, state)
        if ready:
            verification = verify_active_polar_artifacts(scene_dir, ledger, active_id)
            state["active_artifact_verification"] = verification
            atomic_json(state_path, state)
            if not verification["ok"]:
                raise RuntimeError(
                    "active-polar run completed but compact artifact verification failed: "
                    + "; ".join(verification["missing_examples"])
                )
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
