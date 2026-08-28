#!/usr/bin/env python3
"""Promote a fixed, ordered OpticalNav polar capture only after full success.

This is deliberately an operations helper rather than a generic scheduler.
It never submits, retries, cancels, or changes a render.  It only watches the
three already-created immutable runs, writes a small durable monitor state, and
uses the control-plane promote API after every task in a run is succeeded (or a
verified source reuse).  Any terminal failure stops promotion and is recorded.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _run_state(db_path: Path, run_id: str) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    try:
        row = conn.execute(
            "SELECT render_version_id, status FROM sweep_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        counts = dict(conn.execute(
            "SELECT state, COUNT(*) FROM sweep_tasks WHERE run_id = ? GROUP BY state", (run_id,)
        ).fetchall())
        return {"render_version_id": str(row[0]), "run_status": str(row[1]), "counts": counts,
                "total": sum(int(value) for value in counts.values())}
    finally:
        conn.close()


def _promote(url: str, project: str, scene: str, version: str) -> dict[str, Any]:
    endpoint = f"{url.rstrip('/')}/api/opticalnav/projects/{project}/scenes/{scene}/render-versions"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"action": "promote", "render_version_id": version}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--scene", required=True)
    parser.add_argument("--run", action="append", required=True, help="ordered run id; repeat three times")
    parser.add_argument("--expected-tasks", type=int, required=True)
    parser.add_argument("--daemon-url", default="http://127.0.0.1:8765")
    parser.add_argument("--poll-s", type=float, default=20.0)
    parser.add_argument(
        "--state-file",
        help="Optional durable monitor-state path. Defaults to final_polar_monitor.json in the scene operations directory.",
    )
    args = parser.parse_args()
    if args.expected_tasks < 1 or not args.run:
        raise SystemExit("--expected-tasks and at least one --run are required")

    scene_dir = Path("out") / "opticalnav" / args.project / "scenes" / args.scene
    db_path = scene_dir / "operations" / "render_ledger.sqlite3"
    state_path = (
        Path(args.state_file).resolve()
        if args.state_file
        else scene_dir / "operations" / "final_polar_monitor.json"
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []
    while True:
        state: dict[str, Any] = {"updated_at": _now(), "scene_id": args.scene,
                                 "runs": list(args.run), "promoted": promoted, "status": "watching"}
        for run_id in args.run:
            try:
                info = _run_state(db_path, run_id)
            except sqlite3.OperationalError as exc:
                # The renderer owns the single writer connection.  A monitor
                # read must never exit just because an NFS/WAL checkpoint held
                # SQLite briefly; record the transient state and retry.
                state.update({"status": "ledger_retry", "current_run": run_id, "ledger_error": str(exc)})
                _write(state_path, state)
                time.sleep(max(1.0, args.poll_s))
                break
            state["current_run"] = run_id
            state["current"] = info
            counts = info["counts"]
            failed = sum(int(counts.get(name, 0)) for name in ("failed", "partial", "blocked", "cancelled"))
            complete = int(counts.get("succeeded", 0)) + int(counts.get("skipped", 0))
            if failed:
                state.update({"status": "failed", "failure": {"run_id": run_id, "counts": counts}})
                _write(state_path, state)
                print(json.dumps(state, ensure_ascii=False), flush=True)
                return 2
            if info["total"] < args.expected_tasks or complete < args.expected_tasks:
                _write(state_path, state)
                time.sleep(max(1.0, args.poll_s))
                break
            if run_id not in promoted:
                try:
                    state["promotion"] = _promote(args.daemon_url, args.project, args.scene, info["render_version_id"])
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                    state.update({"status": "promotion_retry", "promotion_error": str(exc)})
                    _write(state_path, state)
                    time.sleep(max(1.0, args.poll_s))
                    break
                promoted.append(run_id)
                state["promoted"] = promoted
                _write(state_path, state)
        else:
            state.update({"status": "completed", "completed_at": _now()})
            _write(state_path, state)
            print(json.dumps(state, ensure_ascii=False), flush=True)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
