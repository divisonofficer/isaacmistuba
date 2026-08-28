#!/usr/bin/env python3
"""Cancel OpticalNav sweep plans that never reached a GPU worker.

This is intentionally narrower than a general cancel command: a run qualifies
only when its durable state is ``planned`` and it has no task in queued,
running, terminal-success, or terminal-failure state.  It is therefore safe to
use after a daemon dies while preparing a large sweep, without touching any
work that actually ran.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _project_dir(repo_root: Path, project: str) -> Path:
    return repo_root / "out" / "opticalnav" / project


def _candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT r.run_id, COUNT(t.task_key) AS task_count,
                  SUM(CASE WHEN t.state = 'planned' THEN 1 ELSE 0 END) AS planned_count,
                  SUM(CASE WHEN t.state NOT IN ('planned') THEN 1 ELSE 0 END) AS nonplanned_count
             FROM sweep_runs r
             LEFT JOIN sweep_tasks t ON t.run_id = r.run_id
            WHERE r.status = 'planned'
            GROUP BY r.run_id
           HAVING COALESCE(SUM(CASE WHEN t.state NOT IN ('planned') THEN 1 ELSE 0 END), 0) = 0
            ORDER BY r.created_at"""
    ).fetchall()
    return [dict(row) for row in rows]


def _explicit_candidates(conn: sqlite3.Connection, run_ids: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"""SELECT r.run_id, COUNT(t.task_key) AS task_count,
                    SUM(CASE WHEN t.state = 'planned' THEN 1 ELSE 0 END) AS planned_count,
                    SUM(CASE WHEN t.state IN ('succeeded', 'skipped') THEN 1 ELSE 0 END) AS completed_count
               FROM sweep_runs r
               LEFT JOIN sweep_tasks t ON t.run_id = r.run_id
              WHERE r.run_id IN ({placeholders})
              GROUP BY r.run_id
              ORDER BY r.created_at""",
        run_ids,
    ).fetchall()
    result = [dict(row) for row in rows]
    missing = sorted(set(run_ids) - {str(item["run_id"]) for item in result})
    if missing:
        raise SystemExit(f"unknown run id(s): {', '.join(missing)}")
    completed = [item["run_id"] for item in result if int(item["completed_count"] or 0)]
    if completed:
        raise SystemExit(f"refusing to cancel runs with completed tasks: {', '.join(completed)}")
    return result


def _write_batch_cancelled(project_dir: Path, run_id: str) -> None:
    path = project_dir / "graph_render_batches" / f"{run_id}.json"
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    payload["status"] = "cancelled"
    payload["pause_reason"] = "cancelled before GPU submission"
    payload["cancel_reason"] = "cancelled before GPU submission"
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--scene", required=True)
    parser.add_argument("--run-id", action="append", default=[], help="also cancel an explicit failed/paused run that has no completed task")
    parser.add_argument("--apply", action="store_true", help="perform the cancellation (default is dry-run)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    project_dir = _project_dir(repo_root, args.project)
    ledger_path = project_dir / "scenes" / args.scene / "operations" / "render_ledger.sqlite3"
    if not ledger_path.is_file():
        raise SystemExit(f"ledger not found: {ledger_path}")

    conn = sqlite3.connect(ledger_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        candidates = _explicit_candidates(conn, [str(item) for item in args.run_id]) if args.run_id else _candidates(conn)
        task_total = sum(int(item["task_count"] or 0) for item in candidates)
        print(json.dumps({
            "mode": "apply" if args.apply else "dry_run",
            "scene_id": args.scene,
            "run_count": len(candidates),
            "planned_task_count": task_total,
            "runs": candidates,
        }, ensure_ascii=False, indent=2))
        if not args.apply or not candidates:
            return 0

        run_ids = [str(item["run_id"]) for item in candidates]
        placeholders = ",".join("?" for _ in run_ids)
        conn.execute("BEGIN IMMEDIATE")
        explicit_reason = "cancelled after scene-load failure" if args.run_id else "cancelled before GPU submission"
        conn.execute(
            f"UPDATE sweep_tasks SET state = 'cancelled', error = ? "
            f"WHERE run_id IN ({placeholders}) AND state IN ('planned', 'queued', 'running')",
            [explicit_reason, *run_ids],
        )
        status_predicate = "" if args.run_id else " AND status = 'planned'"
        conn.execute(
            f"UPDATE sweep_runs SET status = 'cancelled' WHERE run_id IN ({placeholders}){status_predicate}",
            run_ids,
        )
        conn.commit()
        for run_id in run_ids:
            _write_batch_cancelled(project_dir, run_id)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
