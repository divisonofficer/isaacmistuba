from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from mitsuba_converter.render_persistence import RenderPersistenceWriter
from mitsuba_converter.render_daemon import RenderDaemon
from mitsuba_converter.versioned_artifacts import RenderLedger


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


def test_versioned_job_is_persisted_only_after_worker_started(tmp_path) -> None:
    """A large graph submission must not persist every dispatcher handoff."""
    daemon = RenderDaemon(repo_root=tmp_path)
    daemon._render_persistence.stop(timeout_s=1.0)
    persisted = []
    daemon._render_persistence = RenderPersistenceWriter(
        lambda batch: persisted.extend(batch), batch_interval_s=0.0,
    )
    status = SimpleNamespace(
        status="queued", started_at=None, worker_started_at=None,
        finished_at=None, progress_stage="queued", manifest_path=None,
        error=None, extras={},
    )
    job = SimpleNamespace(
        status=status,
        render_request=SimpleNamespace(
            job_id="job-1",
            extras={
                "render_version_id": "rv-1", "run_id": "run-1", "task_key": "task-1",
                "opticalnav_project_id": "project", "opticalnav_scene_id": "scene",
            },
        ),
    )
    daemon._jobs["job-1"] = job
    daemon._persist_status_unlocked = lambda _job: pytest.fail("versioned prefetch wrote a legacy status")
    daemon._append_job_log_line = lambda *_args, **_kwargs: pytest.fail("versioned prefetch wrote a legacy log")

    daemon._handle_render_job_event("job-1", "assigned", {"ts": "2026-08-27T00:00:00+00:00", "gpu_index": 4})
    assert status.status == "queued"
    assert status.extras["assigned_gpu_index"] == 4
    assert persisted == []

    daemon._handle_render_job_event("job-1", "started", {"ts": "2026-08-27T00:00:01+00:00", "gpu_index": 4})
    assert status.status == "running"
    assert status.started_at is not None
    daemon._render_persistence.flush(run_id="run-1", timeout_s=1.0)
    assert [item["state"] for item in persisted] == ["running"]
    daemon._render_persistence.stop(timeout_s=1.0)


def test_variant_wait_polls_ledger_summary_without_flushing_whole_predecessor(tmp_path) -> None:
    """A base→perturbed barrier cannot wait on a moving persistence watermark."""
    project_dir = tmp_path / "project"
    ledger = RenderLedger(project_dir, scene_id="scene-a")
    ledger.create_scene_version(
        project_id="project", scene_id="scene-a", scene_version_id_value="sv-test",
        scene_digest="digest-test",
    )
    ledger.create_render_run(
        run_id="base-run", project_id="project", scene_id="scene-a",
        scene_version_id_value="sv-test", render_version_id="rv-test",
    )
    ledger.update_run("base-run", status="completed")

    daemon = RenderDaemon(repo_root=tmp_path)
    original_flush = daemon._render_persistence.flush
    daemon._render_persistence.flush = lambda **_kwargs: pytest.fail("variant wait must not flush full predecessor")
    payload = daemon._wait_for_graph_batch_terminal(project_dir, "scene-a", "base-run", timeout_s=0.1)
    assert payload["status"] == "completed"
    daemon._render_persistence.flush = original_flush
    daemon._render_persistence.stop(timeout_s=1.0)
