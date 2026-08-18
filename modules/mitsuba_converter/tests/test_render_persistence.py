from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from mitsuba_converter.render_persistence import RenderPersistenceWriter
from mitsuba_converter.render_daemon import RenderDaemon


def test_enqueue_does_not_wait_for_slow_persistence() -> None:
    entered = threading.Event()
    release = threading.Event()

    def persist(_batch):
        entered.set()
        assert release.wait(timeout=2.0)

    writer = RenderPersistenceWriter(persist, batch_interval_s=0.0)
    started = time.monotonic()
    sequence = writer.enqueue({"state": "succeeded"}, run_id="run-1")
    elapsed = time.monotonic() - started

    assert sequence == 1
    assert elapsed < 0.1
    assert entered.wait(timeout=1.0)
    assert writer.health()["pending"] == 1
    release.set()
    writer.flush(run_id="run-1", timeout_s=2.0)
    assert writer.health()["pending"] == 0
    writer.stop(timeout_s=2.0)


def test_worker_terminal_state_does_not_wait_for_slow_persistence(tmp_path) -> None:
    daemon = RenderDaemon(repo_root=tmp_path)
    daemon._render_persistence.stop(timeout_s=1.0)
    entered = threading.Event()
    release = threading.Event()

    def persist(_batch):
        entered.set()
        assert release.wait(timeout=2.0)

    daemon._render_persistence = RenderPersistenceWriter(persist, batch_interval_s=0.0)
    status = SimpleNamespace(
        status="running", finished_at=None, progress_stage="rendering",
        manifest_path=None, error=None, extras={},
    )
    job = SimpleNamespace(
        status=status,
        render_request=SimpleNamespace(extras={}, job_id="job-1"),
    )
    daemon._jobs["job-1"] = job

    started = time.monotonic()
    daemon._mark_succeeded("job-1", manifest_path="out/manifest.json")
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert status.status == "succeeded"
    assert entered.wait(timeout=1.0)
    release.set()
    daemon._render_persistence.stop(timeout_s=2.0)


def test_writer_retries_and_preserves_event_order() -> None:
    attempts = 0
    persisted = []

    def persist(batch):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary NFS error")
        persisted.extend(item["value"] for item in batch)

    writer = RenderPersistenceWriter(
        persist,
        batch_size=8,
        batch_interval_s=0.02,
        max_attempts=3,
        retry_base_s=0.001,
    )
    for value in range(4):
        writer.enqueue({"value": value}, run_id="run-1")
    writer.flush(run_id="run-1", timeout_s=2.0)

    assert attempts == 3
    assert persisted == [0, 1, 2, 3]
    assert writer.health()["status"] == "ok"
    writer.stop(timeout_s=2.0)


def test_permanent_error_surfaces_at_barrier_and_health() -> None:
    def persist(_batch):
        raise PermissionError("read-only ledger")

    writer = RenderPersistenceWriter(
        persist,
        batch_interval_s=0.0,
        max_attempts=2,
        retry_base_s=0.001,
    )
    writer.enqueue({"state": "failed"}, run_id="run-1")

    with pytest.raises(RuntimeError, match="read-only ledger"):
        writer.flush(run_id="run-1", timeout_s=2.0)
    health = writer.health()
    assert health["status"] == "degraded"
    assert health["failed_sequence"] == 1
    with pytest.raises(RuntimeError):
        writer.stop(timeout_s=0.1)
