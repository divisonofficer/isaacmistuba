import queue
import threading
import time
from pathlib import Path

from mitsuba_converter.worker_manager import WorkerManager, WorkerStats, _Worker


class _LiveProc:
    def poll(self):
        return None


class _ExitedProc:
    def poll(self):
        return 0


class _KillableLiveProc:
    def __init__(self):
        self.killed = 0

    def poll(self):
        return None

    def kill(self):
        self.killed += 1


class _DummyWorker:
    def __init__(self, gpu_index: int):
        self.stats = WorkerStats(gpu_index=gpu_index)
        self._process = _LiveProc()
        self._outbound = queue.Queue()
        self.submitted = []
        self.stopped = 0
        self.started = 0

    def submit(self, job: dict) -> None:
        self.submitted.append(job)
        self._outbound.put(job)
        self.stats.submitted_count += 1

    def cancel(self, job_id: str) -> bool:
        return False

    def stop(self, *, kill: bool = False, timeout_s: float = 3.0) -> None:
        self.stopped += 1
        self._process = _ExitedProc()

    def start(self) -> None:
        self.started += 1
        self._process = _LiveProc()


def _manager(monkeypatch, backlog: int = 2) -> tuple[WorkerManager, list[_DummyWorker]]:
    monkeypatch.setenv("ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU", str(backlog))
    mgr = WorkerManager(repo_root=Path("."), worker_count=2, gpu_indices=[0, 1])
    workers = [_DummyWorker(0), _DummyWorker(1)]
    mgr._workers = workers  # subprocess-free scheduling contract test
    return mgr, workers


def test_submit_caps_assigned_backlog_until_worker_terminal_event(monkeypatch):
    mgr, workers = _manager(monkeypatch, backlog=2)

    for i in range(4):
        mgr.submit({"job_id": f"job-{i}"})

    assert [len(w.stats.assigned_job_ids) for w in workers] == [2, 2]
    assert len(workers[0].submitted) == 2
    assert len(workers[1].submitted) == 2

    done = threading.Event()

    def _submit_extra():
        mgr.submit({"job_id": "job-4"})
        done.set()

    thread = threading.Thread(target=_submit_extra)
    thread.start()
    time.sleep(0.05)
    assert not done.is_set()

    mgr._release_assignment(workers[1], next(iter(workers[1].stats.assigned_job_ids)))
    assert done.wait(1.0)
    thread.join(timeout=1.0)
    assert "job-4" in workers[1].stats.assigned_job_ids
    assert len(workers[1].stats.assigned_job_ids) == 2


def test_target_gpu_routing_still_available_for_static_shards(monkeypatch):
    mgr, workers = _manager(monkeypatch, backlog=2)

    mgr.submit({"job_id": "targeted", "worker_gpu_index": 1})

    assert workers[0].submitted == []
    assert [job["job_id"] for job in workers[1].submitted] == ["targeted"]
    assert workers[1].stats.assigned_job_ids == {"targeted"}


def test_health_reports_assigned_backlog(monkeypatch):
    mgr, workers = _manager(monkeypatch, backlog=2)
    mgr.submit({"job_id": "a"})
    mgr.submit({"job_id": "b"})

    health = mgr.health()

    assert health["worker_backlog_per_gpu"] == 2
    assert [row["backlog_limit"] for row in health["workers"]] == [2, 2]
    assert sum(row["assigned_count"] for row in health["workers"]) == 2


def test_recycle_idle_workers_restarts_without_failing_jobs(monkeypatch):
    mgr, workers = _manager(monkeypatch, backlog=2)

    result = mgr.recycle_idle_workers(reason="test_phase_boundary", timeout_s=0.1)

    assert result["recycled"] == 2
    assert result["skipped_busy"] == 0
    assert [w.stopped for w in workers] == [1, 1]
    assert [w.started for w in workers] == [1, 1]


def test_stale_reader_exit_after_recycle_does_not_kill_new_worker():
    mgr = WorkerManager(repo_root=Path("."), worker_count=1, gpu_indices=[0])
    worker = _Worker(mgr, gpu_index=0)
    old_proc = _KillableLiveProc()
    new_proc = _KillableLiveProc()
    old_stop = threading.Event()
    old_stop.set()

    worker._process = new_proc
    worker._generation = 2

    worker._on_worker_exited(proc=old_proc, stop_event=old_stop, generation=1)

    assert old_proc.killed == 0
    assert new_proc.killed == 0
    assert not mgr.health()["degraded"]


def test_stale_reader_exit_generation_mismatch_does_not_kill_new_worker():
    mgr = WorkerManager(repo_root=Path("."), worker_count=1, gpu_indices=[0])
    worker = _Worker(mgr, gpu_index=0)
    old_proc = _KillableLiveProc()
    new_proc = _KillableLiveProc()

    worker._process = new_proc
    worker._generation = 2

    worker._on_worker_exited(proc=old_proc, stop_event=threading.Event(), generation=1)

    assert old_proc.killed == 0
    assert new_proc.killed == 0
    assert not mgr.health()["degraded"]


def test_phase_boundary_recovery_clears_degraded_and_respawns_dead_workers(monkeypatch):
    mgr, workers = _manager(monkeypatch, backlog=2)
    workers[0]._process = _ExitedProc()
    mgr._degraded = True

    result = mgr.recycle_idle_workers(
        reason="scene_variant_boundary", timeout_s=0.1, recover_degraded=True,
    )

    assert result["degraded_reset"] is True
    assert result["degraded"] is False
    assert result["started"] == 1
    assert result["recycled"] == 1
    assert workers[0].started == 1
    assert workers[1].started == 1
    assert not mgr.health()["degraded"]
