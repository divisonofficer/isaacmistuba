"""Versioned OpticalNav render artifacts and durable sweep ledger.

The legacy render daemon used one directory under ``out/bridge_jobs`` per
attempt.  This module provides the new, project-scoped storage boundary:

* a small SQLite ledger for runs, tasks, attempts and render versions;
* content-addressed scene version identifiers;
* immutable render-version observation directories with an atomic ``current``
  pointer.

The API is deliberately dependency-free so it can also be used by migration
tools and by tests without importing Mitsuba.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import zlib
from typing import Any, Iterator, Mapping, Sequence


LEDGER_SCHEMA_VERSION = 2


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_payload(value: Any, *, prefix: str = "") -> str:
    digest = hashlib.sha256(_canonical_json(value)).hexdigest()
    return f"{prefix}{digest}" if prefix else digest


def digest_file(path: str | Path, *, prefix: str = "") -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"{prefix}{hasher.hexdigest()}" if prefix else hasher.hexdigest()


def scene_version_id(
    repo_root: str | Path,
    *,
    scene_ref: str | Path,
    extra_refs: Sequence[str | Path] = (),
    graph_revision: str | None = None,
    calibration_refs: Sequence[str | Path] = (),
) -> tuple[str, str]:
    """Return ``(scene_version_id, raw_digest)`` for immutable scene inputs."""

    root = Path(repo_root).resolve()
    records: list[dict[str, Any]] = []
    for raw in [scene_ref, *extra_refs, *calibration_refs]:
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        record: dict[str, Any] = {"path": str(path)}
        try:
            stat = path.stat()
            # mtime is intentionally excluded: touching an unchanged asset
            # must not create a new scene version.
            record.update({"size": stat.st_size})
            # Hash scene files; metadata-only files are cheap and still get a
            # digest so a changed GLB/XML cannot reuse an old render version.
            record["sha256"] = digest_file(path)
        except OSError:
            record["missing"] = True
        records.append(record)
    payload = {"inputs": records, "graph_revision": graph_revision}
    raw_digest = digest_payload(payload)
    return f"sv_{raw_digest[:20]}", raw_digest


def new_render_version_id(scene_digest: str, *, now: str | None = None) -> str:
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    stamp = stamp.replace("+00:00", "Z").replace(":", "").replace("-", "")
    # The digest makes versions stable/readable while the nonce prevents two
    # same-millisecond retries from colliding.
    return f"rv_{stamp[:15]}_{scene_digest[:12]}_{secrets.token_hex(3)}"


def task_key(payload: Mapping[str, Any]) -> str:
    return digest_payload(dict(payload), prefix="tk_")


def project_ledger_path(project_dir: str | Path) -> Path:
    return Path(project_dir).resolve() / "render_ledger.sqlite3"


def scene_ledger_path(project_dir: str | Path, scene_id: str) -> Path:
    """Authoritative v3 scene-local ledger location."""
    value = str(scene_id).strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid scene_id for ledger path: {scene_id!r}")
    return Path(project_dir).resolve() / "scenes" / value / "operations" / "render_ledger.sqlite3"


def _task_event_payload_from_connection(
    conn: sqlite3.Connection,
    task_key_value: str,
    *,
    limit: int = 80,
) -> dict[str, Any] | None:
    """Read and format the bounded durable event stream for one task."""
    row = conn.execute(
        """SELECT t.task_key, t.job_id, t.variant, t.phase, t.node_id,
                  t.heading_id, t.state, t.attempt_count, t.error,
                  t.metadata_json, t.run_id, t.render_version_id
             FROM sweep_tasks t WHERE t.task_key = ?""",
        (task_key_value,),
    ).fetchone()
    if row is None:
        return None
    task = dict(row)
    task["metadata"] = json.loads(task.pop("metadata_json") or "{}")
    rows = conn.execute(
        """SELECT event_type, created_at, payload_json
             FROM render_events WHERE task_key = ?
             ORDER BY event_id DESC LIMIT ?""",
        (task_key_value, max(1, min(int(limit), 250))),
    ).fetchall()
    events: list[dict[str, Any]] = []
    for event_row in reversed(rows):
        event = dict(event_row)
        event["payload"] = json.loads(event.pop("payload_json") or "{}")
        events.append(event)
    lines: list[str] = []
    for event in events:
        payload = dict(event.get("payload") or {})
        event_type = str(event.get("event_type") or "event")
        stage = str(payload.get("stage") or "").strip()
        message = str(payload.get("message") or payload.get("error") or "")
        if not message and event_type in {"failed", "retry_failed", "cancelled"}:
            message = str(task.get("error") or "")
        if not message:
            message = stage or event_type or "state changed"
        stage_prefix = f"{stage}: " if stage and message != stage else ""
        lines.append(
            f"[{event.get('created_at') or ''}] "
            f"[{event_type.upper():<12}] {stage_prefix}{message}"
        )
    if not lines:
        lines.append(
            f"[ledger] {task.get('state') or 'planned'}"
            + (f" · {task['error']}" if task.get("error") else "")
        )
    return {"task": task, "events": events, "lines": lines, "total_lines": len(lines), "source": "render_ledger"}


def read_task_event_log(
    project_dir: str | Path,
    task_key_value: str,
    *,
    limit: int = 80,
    scene_id: str | None = None,
) -> dict[str, Any] | None:
    """Read a task event log without schema setup or a writer-lock wait.

    The WebUI opens this during active sweeps.  Unlike ``RenderLedger`` this
    never performs WAL/schema initialization, so it remains a concurrent
    reader beside the daemon's single persistence writer.
    """
    path = scene_ledger_path(project_dir, scene_id) if scene_id is not None else project_ledger_path(project_dir)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 2000")
        return _task_event_payload_from_connection(conn, task_key_value, limit=limit)
    finally:
        conn.close()


def version_root(project_dir: str | Path, scene_id: str, render_version_id: str) -> Path:
    return Path(project_dir).resolve() / "scenes" / scene_id / "observations" / "versions" / render_version_id


def versioned_bundle_dir(
    project_dir: str | Path,
    *,
    scene_id: str,
    render_version_id: str,
    variant: str,
    node_id: str,
    heading_id: str,
    phase: str | None = None,
) -> Path:
    parts = [version_root(project_dir, scene_id, render_version_id), variant or "base", node_id, heading_id]
    if phase:
        parts.append(phase)
    return Path(*parts)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def current_pointer_path(project_dir: str | Path, scene_id: str, variant: str, node_id: str, heading_id: str) -> Path:
    return (
        Path(project_dir).resolve()
        / "scenes"
        / scene_id
        / ("observations_perturbed" if variant == "perturbed" else "observations")
        / node_id
        / heading_id
        / "current.json"
    )


def write_current_pointer(
    project_dir: str | Path,
    *,
    scene_id: str,
    variant: str,
    node_id: str,
    heading_id: str,
    render_version_id: str,
    bundle_ref: str,
    scene_version_id_value: str,
) -> Path:
    path = current_pointer_path(project_dir, scene_id, variant, node_id, heading_id)
    _atomic_write_json(
        path,
        {
            "schema_version": 1,
            "scene_id": scene_id,
            "variant": variant,
            "node_id": node_id,
            "heading_id": heading_id,
            "render_version_id": render_version_id,
            "scene_version_id": scene_version_id_value,
            "bundle_ref": bundle_ref,
            "updated_at": utc_now_iso(),
        },
    )
    return path


def resolve_current_bundle_dir(
    project_dir: str | Path,
    *,
    scene_id: str,
    variant: str,
    node_id: str,
    heading_id: str,
) -> Path | None:
    pointer = current_pointer_path(project_dir, scene_id, variant, node_id, heading_id)
    if pointer.exists():
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            ref = payload.get("bundle_ref")
            if isinstance(ref, str) and ref:
                path = (Path(project_dir).resolve() / ref).resolve()
                if path.exists():
                    return path
        except (OSError, ValueError):
            pass
    # Compatibility with pre-versioned consolidated output.
    legacy = current_pointer_path(project_dir, scene_id, variant, node_id, heading_id).parent
    return legacy if legacy.exists() else None


@dataclass(frozen=True)
class LedgerRun:
    run_id: str
    project_id: str
    scene_id: str
    scene_version_id: str
    render_version_id: str
    status: str
    created_at: str
    source_run_id: str | None = None


class RenderLedger:
    """Small SQLite repository for durable sweep/version state.

    ``scene_id`` selects the v3 scene-private ledger.  The optional legacy
    project-wide form is retained only for migration/read compatibility; new
    scene work must always provide it.
    """

    def __init__(self, project_dir: str | Path, *, scene_id: str | None = None):
        self.project_dir = Path(project_dir).resolve()
        self.scene_id = str(scene_id) if scene_id is not None else None
        self.path = scene_ledger_path(self.project_dir, self.scene_id) if self.scene_id is not None else project_ledger_path(self.project_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ledger_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scene_versions (
                    scene_version_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scene_id TEXT NOT NULL,
                    scene_digest TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    created_at TEXT NOT NULL,
                    supersedes_version_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS render_versions (
                    render_version_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scene_id TEXT NOT NULL,
                    scene_version_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'staging',
                    created_at TEXT NOT NULL,
                    supersedes_render_version_id TEXT,
                    run_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(scene_version_id) REFERENCES scene_versions(scene_version_id)
                );
                CREATE TABLE IF NOT EXISTS sweep_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scene_id TEXT NOT NULL,
                    scene_version_id TEXT NOT NULL,
                    render_version_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL,
                    source_run_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(render_version_id) REFERENCES render_versions(render_version_id)
                );
                CREATE TABLE IF NOT EXISTS sweep_tasks (
                    task_key TEXT PRIMARY KEY,
                    logical_task_key TEXT,
                    run_id TEXT NOT NULL,
                    render_version_id TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    phase_index INTEGER NOT NULL DEFAULT 0,
                    ordinal INTEGER NOT NULL,
                    node_id TEXT NOT NULL,
                    heading_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'planned',
                    job_id TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    request_blob_digest TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(run_id, ordinal),
                    FOREIGN KEY(run_id) REFERENCES sweep_runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS render_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_key TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(task_key, attempt_no),
                    FOREIGN KEY(task_key) REFERENCES sweep_tasks(task_key)
                );
                CREATE TABLE IF NOT EXISTS request_blobs (
                    digest TEXT PRIMARY KEY,
                    payload BLOB NOT NULL,
                    encoding TEXT NOT NULL DEFAULT 'json',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS render_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT,
                    run_id TEXT,
                    task_key TEXT,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_run_state ON sweep_tasks(run_id, state);
                CREATE INDEX IF NOT EXISTS idx_tasks_version ON sweep_tasks(render_version_id, state);
                CREATE INDEX IF NOT EXISTS idx_events_run ON render_events(run_id, event_id);
                """
            )
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(sweep_tasks)").fetchall()}
            if "logical_task_key" not in columns:
                conn.execute("ALTER TABLE sweep_tasks ADD COLUMN logical_task_key TEXT")
            event_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(render_events)").fetchall()}
            if "event_key" not in event_columns:
                conn.execute("ALTER TABLE render_events ADD COLUMN event_key TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_logical ON sweep_tasks(logical_task_key, state)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_events_key ON render_events(event_key)")
            conn.execute(
                "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES('schema_version', ?)",
                (str(LEDGER_SCHEMA_VERSION),),
            )
            if self.scene_id is not None:
                row = conn.execute("SELECT value FROM ledger_meta WHERE key = 'scene_id'").fetchone()
                if row is not None and str(row["value"]) != self.scene_id:
                    raise ValueError(
                        f"scene-local ledger metadata mismatch: {row['value']!r} != {self.scene_id!r}"
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES('scene_id', ?)",
                    (self.scene_id,),
                )
            conn.commit()

    def _assert_scene_scope(self, scene_id: str) -> None:
        if self.scene_id is not None and str(scene_id) != self.scene_id:
            raise ValueError(
                f"scene-local ledger {self.path} cannot accept scene_id={scene_id!r}; expected {self.scene_id!r}"
            )

    def put_request_blob(self, payload: Mapping[str, Any]) -> str:
        raw = _canonical_json(payload)
        digest = hashlib.sha256(raw).hexdigest()
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO request_blobs(digest, payload, encoding, created_at) VALUES(?, ?, 'zlib-json', ?)",
                (digest, zlib.compress(raw, level=6), utc_now_iso()),
            )
            conn.commit()
        return digest

    def put_tasks_batch(self, records: Sequence[Mapping[str, Any]]) -> dict[str, str | None]:
        """Insert request blobs and planned tasks in one SQLite transaction."""
        result: dict[str, str | None] = {}
        rows = list(records)
        if not rows:
            return result
        with self.connection() as conn:
            for record in rows:
                if self.scene_id is not None:
                    metadata = record.get("metadata") if isinstance(record.get("metadata"), Mapping) else {}
                    request = record.get("request_payload") if isinstance(record.get("request_payload"), Mapping) else {}
                    extras = request.get("extras") if isinstance(request.get("extras"), Mapping) else {}
                    scoped_scene_id = str(metadata.get("scene_id") or extras.get("opticalnav_scene_id") or "")
                    self._assert_scene_scope(scoped_scene_id)
                task_key_value = str(record["task_key"])
                request_payload = record.get("request_payload")
                digest = record.get("request_blob_digest")
                if request_payload is not None:
                    raw = _canonical_json(request_payload)
                    digest = hashlib.sha256(raw).hexdigest()
                    conn.execute(
                        "INSERT OR IGNORE INTO request_blobs(digest, payload, encoding, created_at) VALUES(?, ?, 'zlib-json', ?)",
                        (digest, zlib.compress(raw, level=6), utc_now_iso()),
                    )
                digest_value = str(digest) if digest else None
                conn.execute(
                    """INSERT OR IGNORE INTO sweep_tasks
                    (task_key, logical_task_key, run_id, render_version_id, variant, phase, phase_index, ordinal, node_id, heading_id, state, metadata_json, request_blob_digest)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        task_key_value,
                        record.get("logical_task_key"),
                        record["run_id"],
                        record["render_version_id"],
                        record["variant"],
                        record["phase"],
                        int(record.get("phase_index", 0)),
                        int(record["ordinal"]),
                        record["node_id"],
                        record["heading_id"],
                        str(record.get("state") or "planned"),
                        json.dumps(dict(record.get("metadata") or {}), ensure_ascii=False, sort_keys=True),
                        digest_value,
                    ),
                )
                result[task_key_value] = digest_value
            conn.commit()
        return result

    def find_complete_tasks(
        self,
        *,
        scene_version_id_value: str,
        logical_task_keys: Sequence[str],
    ) -> dict[str, dict[str, Any]]:
        """Resolve completed logical tasks with bounded, batched SQL queries."""
        keys = list(dict.fromkeys(str(key) for key in logical_task_keys if str(key)))
        if not keys:
            return {}
        result: dict[str, dict[str, Any]] = {}
        with self.connection() as conn:
            for start in range(0, len(keys), 500):
                chunk = keys[start:start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""SELECT t.*, r.scene_version_id FROM sweep_tasks t
                        JOIN sweep_runs r ON r.run_id = t.run_id
                        WHERE r.scene_version_id = ? AND t.logical_task_key IN ({placeholders})
                          AND (
                            t.state = 'succeeded'
                            OR (t.state = 'skipped' AND json_extract(t.metadata_json, '$.source_bundle_ref') IS NOT NULL)
                          )""",
                    [scene_version_id_value, *chunk],
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    logical = str(item.get("logical_task_key") or "")
                    if not logical:
                        continue
                    prior = result.get(logical)
                    rank = (int(item.get("attempt_count") or 0), int(item.get("ordinal") or 0))
                    prior_rank = (int(prior.get("attempt_count") or 0), int(prior.get("ordinal") or 0)) if prior else (-1, -1)
                    if prior is None or rank >= prior_rank:
                        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
                        result[logical] = item
        return result

    def update_tasks_batch(
        self,
        updates: Sequence[Mapping[str, Any]],
        *,
        run_id: str | None = None,
        event_type: str | None = None,
    ) -> None:
        """Apply many task state changes and optional events in one transaction."""
        rows = list(updates)
        if not rows:
            return
        with self.connection() as conn:
            touched_runs: set[str] = set()
            for update in rows:
                task_key_value = str(update["task_key"])
                fields = ["state = ?", "error = ?"]
                values: list[Any] = [str(update.get("state") or "planned"), update.get("error")]
                if update.get("job_id") is not None:
                    fields.append("job_id = ?")
                    values.append(update["job_id"])
                if update.get("attempt_count") is not None:
                    fields.append("attempt_count = ?")
                    values.append(int(update["attempt_count"]))
                values.append(task_key_value)
                conn.execute(f"UPDATE sweep_tasks SET {', '.join(fields)} WHERE task_key = ?", values)
                task_row = conn.execute("SELECT run_id FROM sweep_tasks WHERE task_key = ?", (task_key_value,)).fetchone()
                if task_row is not None:
                    touched_runs.add(str(task_row["run_id"]))
                if event_type:
                    conn.execute(
                        "INSERT INTO render_events(run_id, task_key, event_type, created_at, payload_json) VALUES(?, ?, ?, ?, ?)",
                        (run_id, task_key_value, event_type, utc_now_iso(), json.dumps(dict(update.get("payload") or {}), ensure_ascii=False, sort_keys=True)),
                    )
            for touched_run in touched_runs:
                states = [str(row[0] or "planned") for row in conn.execute("SELECT state FROM sweep_tasks WHERE run_id = ?", (touched_run,)).fetchall()]
                if states and all(state in {"succeeded", "skipped"} for state in states):
                    conn.execute("UPDATE sweep_runs SET status = 'completed' WHERE run_id = ?", (touched_run,))
                    conn.execute("UPDATE render_versions SET status = 'ready' WHERE render_version_id = (SELECT render_version_id FROM sweep_runs WHERE run_id = ?) AND status = 'staging'", (touched_run,))
                elif any(state in {"failed", "partial", "blocked"} for state in states):
                    conn.execute("UPDATE sweep_runs SET status = 'paused' WHERE run_id = ?", (touched_run,))
            conn.commit()

    def apply_task_events_batch(self, events: Sequence[Mapping[str, Any]]) -> None:
        """Persist ordered runtime task events in one transaction.

        This is the hot-path counterpart to :meth:`put_tasks_batch`.  A render
        daemon may hand events to this method from a background writer after
        several GPU workers finish close together.  Task state, attempt state,
        audit events, and run/version terminal state therefore become durable
        together instead of requiring three connections and commits per event.
        """
        rows = list(events)
        if not rows:
            return
        with self.connection() as conn:
            touched_runs: set[str] = set()
            for event in rows:
                if self.scene_id is not None:
                    self._assert_scene_scope(str(event.get("scene_id") or ""))
                task_key_value = str(event["task_key"])
                state = str(event.get("state") or "planned")
                task_state = str(event.get("task_state") or state)
                run_id = str(event.get("run_id") or "")
                job_id = str(event.get("job_id") or "")
                error = event.get("error")
                attempt_no = max(1, int(event.get("attempt_no", 1) or 1))
                created_at = str(event.get("created_at") or utc_now_iso())
                payload = dict(event.get("payload") or {})

                conn.execute(
                    """UPDATE sweep_tasks
                       SET state = ?, error = ?, job_id = ?, attempt_count = ?
                       WHERE task_key = ?""",
                    (task_state, error, job_id or None, attempt_no, task_key_value),
                )
                task_row = conn.execute(
                    "SELECT run_id FROM sweep_tasks WHERE task_key = ?",
                    (task_key_value,),
                ).fetchone()
                effective_run_id = str(task_row["run_id"]) if task_row is not None else run_id
                if effective_run_id:
                    touched_runs.add(effective_run_id)

                started_at = created_at if state in {"queued", "running"} else None
                finished_at = created_at if state in {"succeeded", "failed", "cancelled"} else None
                conn.execute(
                    """INSERT INTO render_attempts
                       (task_key, job_id, attempt_no, state, created_at, started_at, finished_at, error)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(task_key, attempt_no) DO UPDATE SET
                         job_id=excluded.job_id,
                         state=excluded.state,
                         started_at=COALESCE(render_attempts.started_at, excluded.started_at),
                         finished_at=COALESCE(excluded.finished_at, render_attempts.finished_at),
                         error=excluded.error""",
                    (
                        task_key_value, job_id, attempt_no, state, created_at,
                        started_at, finished_at, error,
                    ),
                )
                event_type = str(event.get("event_type") or state)
                event_key = str(
                    event.get("event_key")
                    or f"{task_key_value}:{attempt_no}:{event_type}"
                )
                conn.execute(
                    """INSERT OR IGNORE INTO render_events
                       (event_key, run_id, task_key, event_type, created_at, payload_json)
                       VALUES(?, ?, ?, ?, ?, ?)""",
                    (
                        event_key,
                        effective_run_id or None,
                        task_key_value,
                        event_type,
                        created_at,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    ),
                )

            for touched_run in touched_runs:
                aggregate = conn.execute(
                    """SELECT
                         COUNT(*) AS total,
                         SUM(CASE WHEN state NOT IN ('succeeded', 'skipped') THEN 1 ELSE 0 END) AS unfinished,
                         SUM(CASE WHEN state IN ('failed', 'partial', 'blocked') THEN 1 ELSE 0 END) AS failed
                       FROM sweep_tasks WHERE run_id = ?""",
                    (touched_run,),
                ).fetchone()
                total = int(aggregate["total"] or 0)
                unfinished = int(aggregate["unfinished"] or 0)
                failed = int(aggregate["failed"] or 0)
                if total > 0 and unfinished == 0:
                    conn.execute(
                        "UPDATE sweep_runs SET status = 'completed' WHERE run_id = ?",
                        (touched_run,),
                    )
                    conn.execute(
                        """UPDATE render_versions SET status = 'ready'
                           WHERE render_version_id = (
                             SELECT render_version_id FROM sweep_runs WHERE run_id = ?
                           ) AND status = 'staging'""",
                        (touched_run,),
                    )
                elif failed > 0:
                    conn.execute(
                        "UPDATE sweep_runs SET status = 'paused' WHERE run_id = ?",
                        (touched_run,),
                    )
            conn.commit()

    def get_request_blob(self, digest: str) -> dict[str, Any] | None:
        """Read a request payload stored by :meth:`put_request_blob`."""
        with self.connection() as conn:
            row = conn.execute("SELECT payload, encoding FROM request_blobs WHERE digest = ?", (digest,)).fetchone()
            if row is None:
                return None
            raw = bytes(row["payload"])
            encoding = str(row["encoding"] or "json")
            if encoding == "zlib-json":
                raw = zlib.decompress(raw)
            elif encoding != "json":
                raise ValueError(f"unsupported request blob encoding: {encoding}")
            value = json.loads(raw.decode("utf-8"))
            return dict(value) if isinstance(value, Mapping) else None

    def get_request_blobs(self, digests: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Read many request payloads using bounded queries on one connection.

        Resume planning can need hundreds of incomplete requests.  Opening a
        fresh SQLite/NFS connection for each one makes an otherwise ready
        queue look stuck for minutes after a daemon restart.
        """
        requested = list(dict.fromkeys(str(value) for value in digests if str(value)))
        result: dict[str, dict[str, Any]] = {}
        if not requested:
            return result
        with self.connection() as conn:
            for start in range(0, len(requested), 500):
                chunk = requested[start:start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT digest, payload, encoding FROM request_blobs WHERE digest IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    raw = bytes(row["payload"])
                    encoding = str(row["encoding"] or "json")
                    if encoding == "zlib-json":
                        raw = zlib.decompress(raw)
                    elif encoding != "json":
                        continue
                    value = json.loads(raw.decode("utf-8"))
                    if isinstance(value, Mapping):
                        result[str(row["digest"])] = dict(value)
        return result

    def scene_version_payload(self, scene_version_id_value: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM scene_versions WHERE scene_version_id = ?", (scene_version_id_value,)).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            return item

    def create_scene_version(
        self,
        *,
        project_id: str,
        scene_id: str,
        scene_version_id_value: str,
        scene_digest: str,
        metadata: Mapping[str, Any] | None = None,
        supersedes_version_id: str | None = None,
    ) -> None:
        self._assert_scene_scope(scene_id)
        with self.connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO scene_versions
                (scene_version_id, project_id, scene_id, scene_digest, status, created_at, supersedes_version_id, metadata_json)
                VALUES(?, ?, ?, ?, 'available', ?, ?, ?)""",
                (
                    scene_version_id_value,
                    project_id,
                    scene_id,
                    scene_digest,
                    utc_now_iso(),
                    supersedes_version_id,
                    json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()

    def create_render_run(
        self,
        *,
        run_id: str,
        project_id: str,
        scene_id: str,
        scene_version_id_value: str,
        render_version_id: str,
        metadata: Mapping[str, Any] | None = None,
        source_run_id: str | None = None,
        supersedes_render_version_id: str | None = None,
    ) -> LedgerRun:
        self._assert_scene_scope(scene_id)
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO render_versions
                (render_version_id, project_id, scene_id, scene_version_id, status, created_at, supersedes_render_version_id, run_id, metadata_json)
                VALUES(?, ?, ?, ?, 'staging', ?, ?, ?, ?)""",
                (
                    render_version_id,
                    project_id,
                    scene_id,
                    scene_version_id_value,
                    now,
                    supersedes_render_version_id,
                    run_id,
                    json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.execute(
                """INSERT OR IGNORE INTO sweep_runs
                (run_id, project_id, scene_id, scene_version_id, render_version_id, status, created_at, source_run_id, metadata_json)
                VALUES(?, ?, ?, ?, ?, 'planned', ?, ?, ?)""",
                (
                    run_id,
                    project_id,
                    scene_id,
                    scene_version_id_value,
                    render_version_id,
                    now,
                    source_run_id,
                    json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()
        return LedgerRun(run_id, project_id, scene_id, scene_version_id_value, render_version_id, "planned", now, source_run_id)

    def put_task(
        self,
        *,
        task_key_value: str,
        run_id: str,
        render_version_id: str,
        variant: str,
        phase: str,
        phase_index: int,
        ordinal: int,
        node_id: str,
        heading_id: str,
        metadata: Mapping[str, Any] | None = None,
        request_blob_digest: str | None = None,
        logical_task_key: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sweep_tasks
                (task_key, logical_task_key, run_id, render_version_id, variant, phase, phase_index, ordinal, node_id, heading_id, metadata_json, request_blob_digest)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_key_value,
                    logical_task_key,
                    run_id,
                    render_version_id,
                    variant,
                    phase,
                    int(phase_index),
                    int(ordinal),
                    node_id,
                    heading_id,
                    json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                    request_blob_digest,
                ),
            )
            conn.commit()

    def find_complete_task(self, *, scene_version_id_value: str, logical_task_key_value: str) -> dict[str, Any] | None:
        """Find a succeeded/skipped task from any prior run of this scene version."""
        with self.connection() as conn:
            row = conn.execute(
                """SELECT t.*, r.scene_version_id FROM sweep_tasks t
                   JOIN sweep_runs r ON r.run_id = t.run_id
                   WHERE r.scene_version_id = ? AND t.logical_task_key = ?
                     AND (
                       t.state = 'succeeded'
                       OR (t.state = 'skipped' AND json_extract(t.metadata_json, '$.source_bundle_ref') IS NOT NULL)
                     )
                   ORDER BY t.attempt_count DESC, t.ordinal DESC LIMIT 1""",
                (scene_version_id_value, logical_task_key_value),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            return item

    def record_event(self, event_type: str, *, run_id: str | None = None, task_key_value: str | None = None, payload: Mapping[str, Any] | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO render_events(run_id, task_key, event_type, created_at, payload_json) VALUES(?, ?, ?, ?, ?)",
                (run_id, task_key_value, event_type, utc_now_iso(), json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True)),
            )
            conn.commit()

    def record_attempt(self, task_key_value: str, *, job_id: str, attempt_no: int, state: str, error: str | None = None) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO render_attempts(task_key, job_id, attempt_no, state, created_at, started_at, finished_at, error)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(task_key, attempt_no) DO UPDATE SET state=excluded.state, finished_at=excluded.finished_at, error=excluded.error""",
                (task_key_value, job_id, int(attempt_no), state, now, now if state in {"queued", "running"} else None, now if state in {"succeeded", "failed", "cancelled"} else None, error),
            )
            conn.commit()

    def update_task(self, task_key_value: str, *, state: str, job_id: str | None = None, error: str | None = None, attempt_count: int | None = None) -> None:
        fields = ["state = ?", "error = ?"]
        values: list[Any] = [state, error]
        if job_id is not None:
            fields.append("job_id = ?")
            values.append(job_id)
        if attempt_count is not None:
            fields.append("attempt_count = ?")
            values.append(int(attempt_count))
        values.append(task_key_value)
        with self.connection() as conn:
            conn.execute(f"UPDATE sweep_tasks SET {', '.join(fields)} WHERE task_key = ?", values)
            run_row = conn.execute("SELECT run_id, render_version_id FROM sweep_tasks WHERE task_key = ?", (task_key_value,)).fetchone()
            if run_row is not None:
                rows = conn.execute("SELECT state FROM sweep_tasks WHERE run_id = ?", (run_row["run_id"],)).fetchall()
                states = [str(row["state"] or "planned") for row in rows]
                if states and all(state in {"succeeded", "skipped"} for state in states):
                    conn.execute("UPDATE sweep_runs SET status = 'completed' WHERE run_id = ?", (run_row["run_id"],))
                    conn.execute("UPDATE render_versions SET status = 'ready' WHERE render_version_id = ? AND status = 'staging'", (run_row["render_version_id"],))
                elif any(state in {"failed", "partial", "blocked"} for state in states):
                    conn.execute("UPDATE sweep_runs SET status = 'paused' WHERE run_id = ?", (run_row["run_id"],))
            conn.commit()

    def update_run(self, run_id: str, *, status: str, metadata: Mapping[str, Any] | None = None) -> None:
        with self.connection() as conn:
            if metadata is None:
                conn.execute("UPDATE sweep_runs SET status = ? WHERE run_id = ?", (status, run_id))
            else:
                # Operational updates (phase/retry/plan count) must not erase
                # immutable identity metadata from create_render_run(), notably
                # render_profile_id.  Otherwise a later resume can appear
                # compatible with a different SPP or visualization policy.
                row = conn.execute(
                    "SELECT metadata_json FROM sweep_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                try:
                    existing = json.loads(row["metadata_json"] or "{}") if row is not None else {}
                except (TypeError, ValueError):
                    existing = {}
                existing.update(dict(metadata))
                conn.execute(
                    "UPDATE sweep_runs SET status = ?, metadata_json = ? WHERE run_id = ?",
                    (status, json.dumps(existing, ensure_ascii=False, sort_keys=True), run_id),
                )
            conn.commit()

    def update_render_version(self, render_version_id: str, *, status: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE render_versions SET status = ? WHERE render_version_id = ?", (status, render_version_id))
            conn.commit()

    def run_payload(self, run_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            run = conn.execute("SELECT * FROM sweep_runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                return None
            tasks = conn.execute("SELECT * FROM sweep_tasks WHERE run_id = ? ORDER BY ordinal", (run_id,)).fetchall()
            payload = dict(run)
            payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
            payload["tasks"] = []
            for task in tasks:
                item = dict(task)
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
                payload["tasks"].append(item)
            return payload

    def task_event_log(self, task_key_value: str, *, limit: int = 80) -> dict[str, Any] | None:
        """Return the durable lifecycle log for one immutable sweep task.

        Versioned sweeps intentionally do not write ``render_progress.log``
        beside every bridge job.  This small lookup is the Jobs drawer's
        replacement: it reads only the selected task plus its bounded event
        history, never the whole sweep.
        """
        with self.connection() as conn:
            return _task_event_payload_from_connection(conn, task_key_value, limit=limit)

    def run_summary(self, run_id: str, *, diagnostic_limit: int = 12) -> dict[str, Any] | None:
        """Return a constant-size progress view without materializing every task.

        Graph sweeps commonly contain thousands of tasks.  ``run_payload`` is
        deliberately detailed for resume/debugging, whereas monitor refreshes
        need only the run row and a grouped state count.  A small, bounded set
        of failed/running tasks is included so the monitor can still explain a
        failure without reloading thousands of task rows.
        """
        with self.connection() as conn:
            run = conn.execute("SELECT * FROM sweep_runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                return None
            state_rows = conn.execute(
                "SELECT state, COUNT(*) AS count FROM sweep_tasks WHERE run_id = ? GROUP BY state",
                (run_id,),
            ).fetchall()
            payload = dict(run)
            payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
            payload["state_counts"] = {
                str(row["state"] or "planned"): int(row["count"] or 0)
                for row in state_rows
            }
            payload["task_count"] = sum(payload["state_counts"].values())
            limit = max(0, min(int(diagnostic_limit), 50))
            diagnostic_rows = conn.execute(
                """SELECT task_key, job_id, variant, phase, phase_index, ordinal,
                          node_id, heading_id, state, attempt_count, error, metadata_json
                     FROM sweep_tasks
                    WHERE run_id = ? AND state IN ('failed', 'partial', 'blocked', 'running')
                    ORDER BY CASE WHEN state IN ('failed', 'partial', 'blocked') THEN 0 ELSE 1 END,
                             ordinal
                    LIMIT ?""",
                (run_id, limit),
            ).fetchall()
            payload["diagnostic_tasks"] = []
            for row in diagnostic_rows:
                item = dict(row)
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
                payload["diagnostic_tasks"].append(item)
            return payload

    def scene_sensor_progress(self, scene_id: str) -> list[dict[str, Any]]:
        """Return deduplicated render coverage per scene variant and sensor.

        Repeated, resumed, and paused sweeps may all contain the same
        viewpoint/heading.  Monitor coverage must count that logical view once
        and consider it complete when *any* run for the latest scene version
        produced or reused a valid bundle.
        """
        self._assert_scene_scope(scene_id)
        with self.connection() as conn:
            rows = conn.execute(
                """WITH expanded_all AS (
                     SELECT r.scene_version_id, r.created_at, t.run_id, t.variant,
                            CAST(sensor.value AS TEXT) AS sensor_id,
                            t.node_id, t.heading_id, t.state, t.metadata_json
                     FROM sweep_tasks t
                     JOIN sweep_runs r ON r.run_id = t.run_id
                     JOIN json_each(t.metadata_json, '$.sensor_ids') AS sensor
                     WHERE r.scene_id = ? AND CAST(sensor.value AS TEXT) <> ''
                   ), latest_versions AS (
                     SELECT variant, scene_version_id
                     FROM (
                       SELECT variant, scene_version_id, MAX(created_at) AS latest_at,
                              ROW_NUMBER() OVER (
                                PARTITION BY variant ORDER BY MAX(created_at) DESC, scene_version_id DESC
                              ) AS rank
                       FROM expanded_all
                       GROUP BY variant, scene_version_id
                     ) WHERE rank = 1
                   ), expanded AS (
                     SELECT e.* FROM expanded_all e
                     JOIN latest_versions latest
                       ON latest.variant = e.variant
                      AND latest.scene_version_id = e.scene_version_id
                   ), run_totals AS (
                     SELECT scene_version_id, variant, sensor_id, run_id, COUNT(*) AS total
                     FROM expanded
                     GROUP BY scene_version_id, variant, sensor_id, run_id
                   ), expected AS (
                     SELECT scene_version_id, variant, sensor_id, MAX(total) AS total
                     FROM run_totals
                     GROUP BY scene_version_id, variant, sensor_id
                   ), pairs AS (
                     SELECT scene_version_id, variant, sensor_id, node_id, heading_id,
                            MAX(CASE WHEN state = 'succeeded' OR (
                                  state = 'skipped' AND json_extract(metadata_json, '$.source_bundle_ref') IS NOT NULL
                                ) THEN 1 ELSE 0 END) AS complete,
                            MAX(CASE WHEN state = 'running' THEN 1 ELSE 0 END) AS running,
                            MAX(CASE WHEN state IN ('failed', 'partial', 'blocked') THEN 1 ELSE 0 END) AS failed
                     FROM expanded
                     GROUP BY scene_version_id, variant, sensor_id, node_id, heading_id
                   ), progress AS (
                     SELECT scene_version_id, variant, sensor_id,
                            COUNT(*) AS observed_total,
                            SUM(CASE WHEN complete = 1 THEN 1 ELSE 0 END) AS completed,
                            SUM(CASE WHEN complete = 0 AND running = 1 THEN 1 ELSE 0 END) AS running,
                            SUM(CASE WHEN complete = 0 AND running = 0 AND failed = 1 THEN 1 ELSE 0 END) AS failed
                     FROM pairs
                     GROUP BY scene_version_id, variant, sensor_id
                   )
                   SELECT p.scene_version_id, p.variant, p.sensor_id,
                          MAX(e.total, p.observed_total) AS total,
                          p.completed, p.running, p.failed
                   FROM progress p
                   JOIN expected e
                     ON e.scene_version_id = p.scene_version_id
                    AND e.variant = p.variant
                    AND e.sensor_id = p.sensor_id
                   ORDER BY p.sensor_id, p.variant""",
                (str(scene_id),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            total = int(row["total"] or 0)
            completed = int(row["completed"] or 0)
            running = int(row["running"] or 0)
            failed = int(row["failed"] or 0)
            queued = max(0, total - completed - running - failed)
            result.append({
                "scene_version_id": str(row["scene_version_id"] or ""),
                "variant": str(row["variant"] or "base"),
                "sensor_id": str(row["sensor_id"] or "unknown"),
                "completed": completed,
                "running": running,
                "queued": queued,
                "failed": failed,
                "total": total,
                "fraction": completed / max(1, total),
            })
        return result

    def list_versions(self, *, scene_id: str | None = None) -> list[dict[str, Any]]:
        if scene_id is not None:
            self._assert_scene_scope(scene_id)
        elif self.scene_id is not None:
            scene_id = self.scene_id
        with self.connection() as conn:
            if scene_id:
                rows = conn.execute("SELECT * FROM render_versions WHERE scene_id = ? ORDER BY created_at DESC", (scene_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM render_versions ORDER BY created_at DESC").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
                result.append(item)
            return result

    def promote_version(self, render_version_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM render_versions WHERE render_version_id = ?", (render_version_id,)).fetchone()
            if row is None:
                raise KeyError(render_version_id)
            old = conn.execute(
                "SELECT render_version_id FROM render_versions WHERE project_id = ? AND scene_id = ? AND status = 'active' AND render_version_id != ?",
                (row["project_id"], row["scene_id"], render_version_id),
            ).fetchall()
            conn.execute("UPDATE render_versions SET status = 'superseded' WHERE project_id = ? AND scene_id = ? AND status = 'active'", (row["project_id"], row["scene_id"]))
            conn.execute("UPDATE render_versions SET status = 'active' WHERE render_version_id = ?", (render_version_id,))
            conn.execute("UPDATE scene_versions SET status = 'active' WHERE scene_version_id = ?", (row["scene_version_id"],))
            conn.commit()
            return {"render_version_id": render_version_id, "superseded": [item["render_version_id"] for item in old]}

    def prune_version(self, render_version_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT status, project_id, scene_id FROM render_versions WHERE render_version_id = ?", (render_version_id,)).fetchone()
            if row is None:
                raise KeyError(render_version_id)
            if row["status"] == "active":
                raise ValueError("active render version cannot be pruned")
            conn.execute("UPDATE render_versions SET status = 'pruned' WHERE render_version_id = ?", (render_version_id,))
            conn.commit()
            return {"render_version_id": render_version_id, "status": "pruned"}
