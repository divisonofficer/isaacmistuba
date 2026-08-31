#!/usr/bin/env python3
"""Wait for the six L0/L3 support-polar runs, then run the terminal audit.

The active-polar passes are submitted by ``watch_submit_support_active.py``.
This companion watcher never submits or changes render work: it only reads the
durable ledger until those child runs exist and all six runs are terminal, then
executes the strict L0+L3 observation/Stokes audit exactly once.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


TERMINAL_SUCCESS = {"succeeded", "skipped"}
TERMINAL_FAILURE = {"failed", "cancelled"}


def _run_snapshot(ledger: Path, run_id: str) -> tuple[str, int, int, int]:
    uri = f"file:{ledger.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30.0) as conn:
        status_row = conn.execute("SELECT status FROM sweep_runs WHERE run_id = ?", (run_id,)).fetchone()
        if status_row is None:
            raise KeyError(f"run is absent from ledger: {run_id}")
        total, pending, failed = conn.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(CASE WHEN state NOT IN ('succeeded', 'skipped', 'failed', 'cancelled') THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN state IN ('failed', 'cancelled') THEN 1 ELSE 0 END), 0)
            FROM sweep_tasks WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    return str(status_row[0] or ""), int(total or 0), int(pending or 0), int(failed or 0)


def _active_child(ledger: Path, predecessor: str) -> str | None:
    """Find the latest active-polar run explicitly chained to ``predecessor``."""
    uri = f"file:{ledger.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30.0) as conn:
        rows = conn.execute(
            "SELECT run_id, metadata_json FROM sweep_runs ORDER BY run_id DESC"
        ).fetchall()
    for run_id, raw_metadata in rows:
        try:
            metadata: dict[str, Any] = json.loads(raw_metadata or "{}")
        except json.JSONDecodeError:
            continue
        if (
            metadata.get("scene_variant_key") == "perturbed_active_polar"
            and metadata.get("previous_variant_batch_id") == predecessor
        ):
            return str(run_id)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--l0-base-run", required=True)
    parser.add_argument("--l0-perturbed-run", required=True)
    parser.add_argument("--l3-base-run", required=True)
    parser.add_argument("--l3-perturbed-run", required=True)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--audit-script", type=Path, default=Path("tools/audit_support_polar_l3.py"))
    args = parser.parse_args()

    if not args.ledger.is_file():
        parser.error(f"ledger not found: {args.ledger}")
    if not args.audit_script.is_file():
        parser.error(f"audit script not found: {args.audit_script}")

    active_runs: dict[str, str] = {}
    last_summary = ""
    while True:
        try:
            active_runs["l0"] = _active_child(args.ledger, args.l0_perturbed_run) or ""
            active_runs["l3"] = _active_child(args.ledger, args.l3_perturbed_run) or ""
            named_runs = {
                "l0-base": args.l0_base_run,
                "l0-passive": args.l0_perturbed_run,
                "l3-base": args.l3_base_run,
                "l3-passive": args.l3_perturbed_run,
                **({"l0-active": active_runs["l0"]} if active_runs["l0"] else {}),
                **({"l3-active": active_runs["l3"]} if active_runs["l3"] else {}),
            }
            snapshots = {label: _run_snapshot(args.ledger, run_id) for label, run_id in named_runs.items()}
        except (sqlite3.OperationalError, KeyError) as exc:
            print(f"[audit-watch] ledger unavailable: {exc}; retrying", flush=True)
            time.sleep(args.poll_seconds)
            continue

        summary = " | ".join(
            f"{label}={total - pending - failed}/{total} pending={pending} failed={failed}"
            for label, (_status, total, pending, failed) in snapshots.items()
        )
        if summary != last_summary:
            print(f"[audit-watch] {summary}", flush=True)
            last_summary = summary

        failures = [label for label, (_status, _total, _pending, failed) in snapshots.items() if failed]
        if failures:
            print(f"[audit-watch] terminal failure in {', '.join(failures)}; audit withheld", flush=True)
            return 1
        if not active_runs["l0"] or not active_runs["l3"]:
            time.sleep(args.poll_seconds)
            continue
        if any(total == 0 or pending for _status, total, pending, _failed in snapshots.values()):
            time.sleep(args.poll_seconds)
            continue

        command = [
            sys.executable,
            str(args.audit_script),
            "--project", args.project,
            "--scene", args.scene,
            "--plan-dir", args.plan_dir,
            "--l0-base-run", args.l0_base_run,
            "--l0-perturbed-run", args.l0_perturbed_run,
            "--l0-active-run", active_runs["l0"],
            "--l3-base-run", args.l3_base_run,
            "--l3-perturbed-run", args.l3_perturbed_run,
            "--l3-active-run", active_runs["l3"],
            "--require-complete",
        ]
        print("[audit-watch] all six runs terminal-success; running strict audit", flush=True)
        return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
