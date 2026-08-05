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


LEDGER_SCHEMA_VERSION = 1


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
    """Small SQLite repository for durable sweep/version state."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.path = project_ledger_path(self.project_dir)
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_logical ON sweep_tasks(logical_task_key, state)")
            conn.execute(
                "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES('schema_version', ?)",
                (str(LEDGER_SCHEMA_VERSION),),
            )
            conn.commit()

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
                          AND t.state IN ('succeeded', 'skipped')""",
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
                     AND t.state IN ('succeeded', 'skipped')
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
                conn.execute("UPDATE sweep_runs SET status = ?, metadata_json = ? WHERE run_id = ?", (status, json.dumps(dict(metadata), ensure_ascii=False, sort_keys=True), run_id))
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

    def run_summary(self, run_id: str) -> dict[str, Any] | None:
        """Return a constant-size progress view without materializing every task.

        Graph sweeps commonly contain thousands of tasks.  ``run_payload`` is
        deliberately detailed for resume/debugging, whereas monitor refreshes
        need only the run row and a grouped state count.
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
            return payload

    def list_versions(self, *, scene_id: str | None = None) -> list[dict[str, Any]]:
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

