#!/usr/bin/env python3
"""Submit a K=1 active-polar support pass only after its passive predecessor ends.

This is intentionally a tiny, durable-process-friendly watcher: it reads the
scene ledger directly with SQLite's Python API rather than relying on shell
quoted SQL in a tmux pane.  A renderer restart therefore cannot turn a valid
terminal predecessor into a second active submission.
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def _counts(ledger: Path, batch_id: str) -> tuple[int, int, int]:
    uri = f"file:{ledger.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30.0) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(CASE WHEN state NOT IN ('succeeded', 'skipped') THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN state IN ('failed', 'cancelled') THEN 1 ELSE 0 END), 0)
            FROM sweep_tasks
            WHERE run_id = ?
            """,
            (batch_id,),
        ).fetchone()
    return tuple(int(value or 0) for value in row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--previous-batch-id", required=True)
    parser.add_argument("--level", choices=("l0", "l3"), required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--submit-script", type=Path, default=Path("tools/submit_support_polar_l3.py"))
    args = parser.parse_args()

    if not args.ledger.is_file():
        parser.error(f"ledger not found: {args.ledger}")
    if not args.submit_script.is_file():
        parser.error(f"submit script not found: {args.submit_script}")

    print(f"[watch] {args.level.upper()} passive predecessor {args.previous_batch_id}", flush=True)
    while True:
        try:
            total, pending, failed = _counts(args.ledger, args.previous_batch_id)
        except sqlite3.OperationalError as exc:
            print(f"[watch] ledger busy: {exc}; retrying", flush=True)
            time.sleep(args.poll_seconds)
            continue
        print(f"[watch] total={total} pending={pending} failed={failed}", flush=True)
        if total == 0:
            print("[watch] predecessor has no durable tasks; refusing active submission", flush=True)
            return 2
        if failed:
            print("[watch] predecessor failed/cancelled; active submission withheld", flush=True)
            return 1
        if pending == 0:
            command = [
                sys.executable,
                str(args.submit_script),
                "--url", args.url,
                "--project", args.project,
                "--scene", args.scene,
                "--plan-dir", args.plan_dir,
                "--levels", args.level,
                "--variants", "perturbed_active_polar",
                "--previous-batch-id", args.previous_batch_id,
                "--apply",
            ]
            print("[watch] passive predecessor complete; submitting K=1 active pass", flush=True)
            return subprocess.run(command, check=False).returncode
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
