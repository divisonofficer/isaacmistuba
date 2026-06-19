"""Manager for ``preview_worker`` subprocesses (Phase R, 2026-04-30).

Owns one (Phase R) or N (Phase M3) ``preview_worker`` subprocesses.
Each worker:
  * is launched via ``python -m mitsuba_converter.preview_worker``
  * has a single GPU pinned via ``CUDA_VISIBLE_DEVICES``
  * communicates with the manager over JSONL on stdin/stdout
  * inherits the daemon's stderr fd, so worker logs interleave with the
    daemon log (preserves ``[daemon] preview_bench:`` lines unchanged)

Public surface used by :mod:`render_daemon`::

    mgr = WorkerManager(repo_root=Path("..."))
    mgr.add_listener(on_event)              # called for every JSONL event
    mgr.start()                             # eager-spawn worker(s)
    mgr.submit({"job_id": ..., "kind": ..., "spec": ...})
    mgr.health()                            # for /health
    mgr.shutdown()                          # graceful

Threads (per worker):
  * writer   — pulls from outbound queue, writes JSONL to worker stdin
  * reader   — reads JSONL from worker stdout, dispatches to listeners
  * watchdog — checks heartbeat freshness; kills + restarts on stall

Crash policy (matches plan anti-improvements):
  * Worker exit (any code) → in-flight job marked failed
    (synthetic event ``{type:'failed', reason:'worker_exited'}``)
  * Queued jobs marked failed (``reason:'worker_restarting'``)
  * Cooldown 30 s before respawn
  * 3 unexpected exits within 5 min → manager enters ``degraded`` state;
    ``health()`` reports it; no further auto-respawn until manual reset
"""
from __future__ import annotations

import json
import os
import queue as _queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Optional


HEARTBEAT_TIMEOUT_S = 30.0
ENV_WORKER_HEARTBEAT_TIMEOUT_S = "ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S"
ENV_WORKER_BACKLOG_PER_GPU = "ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU"
RESTART_COOLDOWN_S = 30.0
DEGRADED_WINDOW_S = 5 * 60.0
DEGRADED_MAX_EXITS = 3
WRITER_QUEUE_HIGH_WATER = 1024  # warn (not drop) above this depth


# Optional alternate Mitsuba build env vars. When the host driver can't
# initialise the OptiX SDK the primary build was compiled against (most
# commonly: docker host stuck on driver R525 while mitsuba 3.7.x was built
# for OptiX 8 → R535+), the operator can point the worker subprocess at a
# different Python interpreter (e.g. a conda env with mitsuba 3.4.x wheel
# whose CUDA variants were built against OptiX 7).
#
#   ROBOMITUBA_MITSUBA_PYTHON      → absolute path to a Python interpreter
#                                    (e.g. /root/miniconda3/envs/<name>/bin/python).
#                                    Overrides sys.executable for the worker.
#   ROBOMITUBA_MITSUBA_PYTHONPATH  → prepended to PYTHONPATH inside the worker
#                                    so a checkout-style build (without site-install)
#                                    wins over any other mitsuba on the path.
#
# These are read at WorkerManager.start() time per worker; restart picks
# them up again so an operator can flip the env and bounce the worker
# without restarting the whole daemon.
ENV_WORKER_PYTHON = "ROBOMITUBA_MITSUBA_PYTHON"
ENV_WORKER_PYTHONPATH = "ROBOMITUBA_MITSUBA_PYTHONPATH"


EventListener = Callable[[dict], None]


def _stderr(message: str) -> None:
    print(f"[daemon] {message}", file=sys.stderr, flush=True)


def _resolve_worker_python() -> str:
    override = (os.environ.get(ENV_WORKER_PYTHON) or "").strip()
    if override:
        try:
            ok = Path(override).is_file() or Path(override).is_symlink()
        except (OSError, PermissionError):
            # Path under another user / namespace — assume valid and let
            # the subsequent subprocess.Popen surface a real exec error.
            ok = True
        if ok:
            return override
        _stderr(
            f"worker: {ENV_WORKER_PYTHON}={override!r} not found, "
            f"falling back to sys.executable={sys.executable}"
        )
    return sys.executable


def _resolve_worker_pythonpath() -> str | None:
    override = (os.environ.get(ENV_WORKER_PYTHONPATH) or "").strip()
    return override or None


def _heartbeat_timeout_s() -> float:
    raw = os.environ.get(ENV_WORKER_HEARTBEAT_TIMEOUT_S)
    if raw is None:
        return HEARTBEAT_TIMEOUT_S
    try:
        return max(5.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return HEARTBEAT_TIMEOUT_S


def _worker_backlog_per_gpu() -> int:
    raw = os.environ.get(ENV_WORKER_BACKLOG_PER_GPU)
    if raw is None:
        return 2
    try:
        return max(1, int(str(raw).strip()))
    except (TypeError, ValueError):
        return 2


@dataclass
class WorkerStats:
    pid: Optional[int] = None
    gpu_index: int = 0
    started_at: Optional[float] = None
    last_heartbeat: float = 0.0
    in_flight_job_id: Optional[str] = None
    in_flight_started_at: Optional[float] = None
    submitted_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    unexpected_exits: Deque[float] = field(default_factory=deque)
    assigned_job_ids: set[str] = field(default_factory=set)


class _Worker:
    """One subprocess + its IO threads.

    Lifecycle is owned by :class:`WorkerManager`; tests should not
    instantiate this directly.
    """

    def __init__(
        self,
        manager: "WorkerManager",
        gpu_index: int,
    ) -> None:
        self._manager = manager
        self._gpu_index = gpu_index
        self._process: subprocess.Popen[bytes] | None = None
        self._stdin_lock = threading.Lock()
        self._outbound: _queue.Queue[dict] = _queue.Queue()
        self._writer_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.stats = WorkerStats(gpu_index=gpu_index)

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            self._stop_event = threading.Event()
            env = dict(os.environ)
            # Pin this worker to a single GPU. CUDA_VISIBLE_DEVICES is the
            # ONLY supported isolation mechanism (anti-improvement #6).
            env["CUDA_VISIBLE_DEVICES"] = str(self._gpu_index)
            env["ROBOMITUBA_RENDER_WORKER_GPU_INDEX"] = str(self._gpu_index)
            python_exe = _resolve_worker_python()
            # When the operator points the worker at an alternate Python
            # (e.g. a conda env that has the OptiX-7-compatible mitsuba
            # wheel), our own modules (``mitsuba_converter``,
            # ``robomituba_bridge``) must still be on its PYTHONPATH —
            # they live in this repo's modules tree, not in the wheel env.
            # Always prepend the repo's src dirs; sys.executable already
            # has them via the standard daemon launch path, so this is a
            # no-op there.
            project_src_paths = self._manager._project_src_paths()
            extra_pythonpath = _resolve_worker_pythonpath()
            parts: list[str] = list(project_src_paths)
            if extra_pythonpath:
                parts.insert(0, extra_pythonpath)
            existing = env.get("PYTHONPATH", "")
            if existing:
                parts.append(existing)
            if parts:
                env["PYTHONPATH"] = os.pathsep.join(parts)
            cmd = [
                python_exe,
                "-u",  # unbuffered stdout — JSONL events arrive promptly
                "-m",
                "mitsuba_converter.preview_worker",
                "--gpu-index",
                str(self._gpu_index),
            ]
            using_alt = python_exe != sys.executable or bool(extra_pythonpath)
            _stderr(
                f"worker: spawn python={python_exe} "
                f"pythonpath={extra_pythonpath or '<none>'} "
                f"gpu_index={self._gpu_index}"
                + (" [alt-build]" if using_alt else "")
            )
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,  # inherit daemon stderr — worker log interleaves
                env=env,
                bufsize=0,
            )
            self.stats.pid = self._process.pid
            self.stats.started_at = time.time()
            self.stats.last_heartbeat = time.time()
            self.stats.in_flight_job_id = None
            self.stats.in_flight_started_at = None
            self.stats.assigned_job_ids.clear()

            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                name=f"render-worker-writer-{self._gpu_index}",
                daemon=True,
            )
            self._writer_thread.start()

            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"render-worker-reader-{self._gpu_index}",
                daemon=True,
            )
            self._reader_thread.start()

            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                name=f"render-worker-watchdog-{self._gpu_index}",
                daemon=True,
            )
            self._watchdog_thread.start()

        _stderr(f"worker: spawned pid={self.stats.pid} gpu_index={self._gpu_index}")

    def stop(self, *, kill: bool = False, timeout_s: float = 3.0) -> None:
        with self._lock:
            self._stop_event.set()
            proc = self._process
        if proc is None:
            return
        try:
            if kill:
                proc.kill()
            else:
                # Closing stdin signals the worker's stdin loop to exit.
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass
                proc.terminate()
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    pass
        except Exception:
            pass

    # ── outbound / inbound IO ────────────────────────────────────────

    def submit(self, job: dict) -> None:
        self._outbound.put(job)
        self.stats.submitted_count += 1

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued or in-flight job owned by this worker.

        Returns True when the job was found. In-flight cancellation uses
        worker kill/restart because Mitsuba calls are not cooperatively
        interruptible once inside CUDA/OptiX.
        """
        if self.stats.in_flight_job_id == job_id:
            self._manager._request_restart(self, reason="job_cancelled")
            return True
        kept: list[dict] = []
        found = False
        while True:
            try:
                item = self._outbound.get_nowait()
            except _queue.Empty:
                break
            if str(item.get("job_id") or "") == job_id:
                found = True
                self._inject_event({
                    "job_id": job_id,
                    "type": "failed",
                    "reason": "job_cancelled",
                    "message": "job cancelled before worker start",
                })
            else:
                kept.append(item)
        for item in kept:
            self._outbound.put(item)
        return found

    def _writer_loop(self) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            return
        stdin = proc.stdin
        while not self._stop_event.is_set():
            try:
                job = self._outbound.get(timeout=0.5)
            except _queue.Empty:
                continue
            try:
                payload = json.dumps(job, ensure_ascii=False) + "\n"
            except (TypeError, ValueError) as exc:
                # Malformed job: synthesize a failed event so the daemon's
                # listener tears down its tracking state.
                self._inject_event({
                    "job_id": str(job.get("job_id") or ""),
                    "type": "failed",
                    "reason": "bad_outbound_json",
                    "message": f"{type(exc).__name__}: {exc}",
                })
                continue
            with self._stdin_lock:
                try:
                    stdin.write(payload.encode("utf-8"))
                    stdin.flush()
                except (BrokenPipeError, ValueError):
                    # Pipe closed — worker is dead. Re-queue the job so
                    # the manager can fail it once we know the exit reason.
                    self._inject_event({
                        "job_id": str(job.get("job_id") or ""),
                        "type": "failed",
                        "reason": "worker_pipe_broken",
                        "message": "stdin pipe closed before write",
                    })
                    return

    def _reader_loop(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        stdout = proc.stdout
        try:
            for raw in iter(stdout.readline, b""):
                if self._stop_event.is_set():
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    _stderr(f"worker: malformed JSON from worker: {line[:200]!r}")
                    continue
                if not isinstance(event, dict):
                    continue
                self._handle_event(event)
        finally:
            self._on_worker_exited()

    def _handle_event(self, event: dict) -> None:
        kind = str(event.get("type") or "")
        job_id = event.get("job_id")
        if kind == "heartbeat":
            self.stats.last_heartbeat = time.time()
            return
        if kind == "ready":
            self.stats.last_heartbeat = time.time()
            _stderr(f"worker: ready pid={event.get('pid')} gpu_index={event.get('gpu_index')}")
            self._dispatch_listeners(event)
            return
        # Track in-flight bookkeeping for the watchdog & failure synth.
        if kind == "started" and isinstance(job_id, str):
            self.stats.in_flight_job_id = job_id
            self.stats.in_flight_started_at = time.time()
        elif kind in ("completed", "failed") and isinstance(job_id, str):
            if kind == "completed":
                self.stats.completed_count += 1
            else:
                self.stats.failed_count += 1
            if self.stats.in_flight_job_id == job_id:
                self.stats.in_flight_job_id = None
                self.stats.in_flight_started_at = None
            self._manager._release_assignment(self, job_id)
        # Any non-heartbeat event also refreshes liveness — the worker is
        # clearly alive if it just produced output.
        self.stats.last_heartbeat = time.time()
        self._dispatch_listeners(event)

    def _dispatch_listeners(self, event: dict) -> None:
        for listener in list(self._manager._listeners):
            try:
                listener(event)
            except Exception as exc:
                _stderr(f"worker: listener raised: {type(exc).__name__}: {exc}")

    def _inject_event(self, event: dict) -> None:
        """Inject a synthetic event (used when we know the worker can't
        emit it, e.g. broken pipe before write)."""
        self._handle_event(event)

    def _watchdog_loop(self) -> None:
        timeout_s = _heartbeat_timeout_s()
        while not self._stop_event.wait(1.0):
            if time.time() - self.stats.last_heartbeat > timeout_s:
                _stderr(
                    f"worker: heartbeat stalled "
                    f"(last={time.time() - self.stats.last_heartbeat:.1f}s ago) "
                    f"pid={self.stats.pid} — restarting"
                )
                self._manager._request_restart(self, reason="heartbeat_timeout")
                return

    def _on_worker_exited(self) -> None:
        proc = self._process
        if proc is None:
            return
        rc = proc.poll()
        if self._stop_event.is_set():
            # Manager-initiated stop; nothing to recover.
            return
        # drjit's "Critical Dr.Jit compiler failure" path (CUDA OOM, OptiX
        # init failure, etc) closes stdout from inside the worker but does
        # NOT terminate the process — abort() runs after some atexit
        # cleanup that hangs. The worker is now zombie-stuck. Force-kill
        # so the next respawn doesn't collide with a stale pid; without
        # this the manager would think the worker is alive (rc=None) and
        # try to send the next job to a broken pipe.
        if rc is None:
            try:
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
                rc = proc.poll()
            except Exception:
                pass
        # Synthesize failures for whatever was in flight or queued.
        in_flight_id = self.stats.in_flight_job_id
        if in_flight_id:
            self._manager._release_assignment(self, in_flight_id)
            self._dispatch_listeners({
                "job_id": in_flight_id,
                "type": "failed",
                "reason": "worker_exited",
                "message": f"worker process exited rc={rc} (stdout EOF — likely drjit critical / CUDA OOM)",
            })
            self.stats.in_flight_job_id = None
            self.stats.failed_count += 1
        # Drain pending outbound queue.
        drained = 0
        while True:
            try:
                pending = self._outbound.get_nowait()
            except _queue.Empty:
                break
            drained += 1
            pending_job_id = str(pending.get("job_id") or "")
            self._manager._release_assignment(self, pending_job_id)
            self._dispatch_listeners({
                "job_id": pending_job_id,
                "type": "failed",
                "reason": "worker_restarting",
                "message": "worker restarted before this job ran",
            })
        if drained:
            _stderr(f"worker: drained {drained} pending jobs after worker exit rc={rc}")
        # A job can already have been written to the worker stdin/OS pipe but not
        # yet emitted ``started`` when the worker dies. It is no longer in the
        # outbound queue and not marked in-flight, so fail any remaining assigned
        # jobs here to keep daemon job state from hanging forever.
        remaining_assigned = list(self.stats.assigned_job_ids)
        for pending_job_id in remaining_assigned:
            self._manager._release_assignment(self, pending_job_id)
            self._dispatch_listeners({
                "job_id": pending_job_id,
                "type": "failed",
                "reason": "worker_restarting",
                "message": "worker restarted before this assigned job started",
            })
        if remaining_assigned:
            _stderr(f"worker: failed {len(remaining_assigned)} assigned-but-not-started jobs after worker exit rc={rc}")
        # Track for degraded-mode detection.
        now = time.time()
        self.stats.unexpected_exits.append(now)
        while self.stats.unexpected_exits and now - self.stats.unexpected_exits[0] > DEGRADED_WINDOW_S:
            self.stats.unexpected_exits.popleft()
        _stderr(
            f"worker: exit pid={self.stats.pid} rc={rc} "
            f"recent_exits={len(self.stats.unexpected_exits)}/{DEGRADED_MAX_EXITS}"
        )
        self._manager._on_worker_exited(self, rc)


class WorkerManager:
    """Owns one or more :class:`_Worker` instances.

    The manager keeps one long-lived worker per configured GPU. Jobs are
    routed to the least-busy live worker so independent viewpoint jobs can
    spread across multiple GPUs while each worker keeps its resident scene
    cache warm.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        worker_count: int = 1,
        gpu_indices: list[int] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        if gpu_indices is None:
            # Env override: ROBOMITUBA_RENDER_GPU_INDICES="2" or "0,2,3"
            # picks the host GPU(s) the worker(s) attach to. Useful on
            # shared multi-GPU boxes where GPU 0 is busy and 1/2 are idle.
            env_raw = (os.environ.get("ROBOMITUBA_RENDER_GPU_INDICES") or "").strip()
            if env_raw:
                try:
                    gpu_indices = [int(x) for x in env_raw.replace(",", " ").split() if x.strip()]
                except ValueError:
                    _stderr(
                        f"worker: ROBOMITUBA_RENDER_GPU_INDICES={env_raw!r} "
                        "invalid (expected int or comma-separated ints), defaulting to [0]"
                    )
                    gpu_indices = list(range(max(1, worker_count)))
                else:
                    worker_count = len(gpu_indices)
            else:
                gpu_indices = list(range(max(1, worker_count)))
        elif worker_count != len(gpu_indices):
            raise ValueError("worker_count must match len(gpu_indices)")
        if not gpu_indices:
            gpu_indices = [0]
        self._gpu_indices = list(gpu_indices)
        self._workers: list[_Worker] = []
        self._listeners: list[EventListener] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._backlog_per_gpu = _worker_backlog_per_gpu()
        self._degraded = False
        self._restart_lock = threading.Lock()
        self._rr_cursor = 0
        self._shutting_down = False

    def _project_src_paths(self) -> list[str]:
        """Return src dirs that must be on the worker's PYTHONPATH so its
        Python (possibly from an alt conda env) can still find our project
        modules. Falls back gracefully if a path doesn't exist.
        """
        modules_root = self.repo_root / "modules"
        candidates = (
            modules_root / "mitsuba_converter" / "src",
            modules_root / "robomituba_bridge" / "src",
        )
        return [str(p) for p in candidates if p.exists()]

    # ── public API ────────────────────────────────────────────────────

    def add_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def start(self) -> None:
        with self._lock:
            if self._workers:
                return
            for gpu_index in self._gpu_indices:
                w = _Worker(self, gpu_index=gpu_index)
                self._workers.append(w)
                w.start()

    def submit(self, job: dict) -> None:
        """Route a job to a worker with bounded per-GPU backlog.

        The daemon can enqueue a large sweep very quickly. Without a cap,
        thousands of jobs are pushed into private per-worker queues and a slow
        GPU can strand work while faster GPUs go idle. Keep only a small number
        of assigned jobs per worker so completed GPUs pull the next job.
        """
        job_id = str(job.get("job_id") or "")
        target_gpu_index = self._target_gpu_index(job)
        routing_fallback_event: dict | None = None
        while True:
            with self._condition:
                if self._degraded:
                    event = {
                        "job_id": job_id,
                        "type": "failed",
                        "reason": "manager_degraded",
                        "message": "worker manager is in degraded state — manual reset required",
                    }
                    break
                live = self._live_workers()
                if not live:
                    event = {
                        "job_id": job_id,
                        "type": "failed",
                        "reason": "no_worker",
                        "message": "no worker available",
                    }
                    break
                worker: _Worker | None = None
                if target_gpu_index is not None:
                    worker = self._pick_target_worker_unlocked(target_gpu_index, live)
                    if worker is None:
                        worker = self._pick_worker_unlocked(live)
                        if worker is not None:
                            routing_fallback_event = {
                                "job_id": job_id,
                                "type": "routing_fallback",
                                "reason": "target_worker_unavailable",
                                "target_gpu_index": target_gpu_index,
                                "routed_gpu_index": worker.stats.gpu_index,
                                "message": (
                                    f"target gpu {target_gpu_index} unavailable; "
                                    f"routed to gpu {worker.stats.gpu_index}"
                                ),
                            }
                else:
                    worker = self._pick_worker_unlocked(live)
                if worker is None:
                    self._condition.wait(timeout=0.5)
                    continue
                if self._worker_assigned_count(worker) < self._backlog_per_gpu:
                    if job_id:
                        worker.stats.assigned_job_ids.add(job_id)
                    worker.submit(job)
                    self._condition.notify_all()
                    event = routing_fallback_event
                    break
                self._condition.wait(timeout=0.5)
        if event is not None:
            self._dispatch_synthetic(event)

    def cancel(self, job_id: str) -> bool:
        found = False
        for worker in list(self._workers):
            try:
                found = worker.cancel(job_id) or found
            except Exception:
                pass
        return found

    def shutdown(self) -> None:
        with self._lock:
            self._shutting_down = True
            workers = list(self._workers)
        for w in workers:
            try:
                w.stop()
            except Exception:
                pass

    def health(self) -> dict[str, Any]:
        """Snapshot for ``/health``. Cheap — never blocks on workers."""
        worker_states = []
        for w in self._workers:
            worker_states.append({
                "gpu_index": w.stats.gpu_index,
                "pid": w.stats.pid,
                "in_flight_job_id": w.stats.in_flight_job_id,
                "queue_depth": self._worker_queue_depth(w),
                "assigned_count": self._worker_assigned_count(w),
                "assigned_job_ids": list(w.stats.assigned_job_ids)[:8],
                "backlog_limit": self._backlog_per_gpu,
                "load_score": self._worker_load(w),
                "submitted": w.stats.submitted_count,
                "completed": w.stats.completed_count,
                "failed": w.stats.failed_count,
                "last_heartbeat_age_s": (
                    round(time.time() - w.stats.last_heartbeat, 2)
                    if w.stats.last_heartbeat > 0 else None
                ),
                "recent_unexpected_exits": len(w.stats.unexpected_exits),
            })
        return {
            "degraded": self._degraded,
            "shutting_down": self._shutting_down,
            "worker_backlog_per_gpu": self._backlog_per_gpu,
            "workers": worker_states,
        }

    # ── internals ─────────────────────────────────────────────────────

    def _worker_queue_depth(self, worker: _Worker) -> int:
        try:
            return max(0, int(worker._outbound.qsize()))
        except Exception:
            return 0

    def _worker_assigned_count(self, worker: _Worker) -> int:
        return len(worker.stats.assigned_job_ids)

    def _worker_load(self, worker: _Worker) -> int:
        """Best-effort load score used for routing/health."""
        return self._worker_assigned_count(worker)

    def _release_assignment(self, worker: _Worker, job_id: str | None) -> None:
        if not job_id:
            return
        with self._condition:
            worker.stats.assigned_job_ids.discard(str(job_id))
            self._condition.notify_all()

    def _target_gpu_index(self, job: dict) -> int | None:
        raw = job.get("worker_gpu_index")
        if raw is None and isinstance(job.get("spec"), dict):
            raw = job["spec"].get("worker_gpu_index")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _live_workers(self) -> list[_Worker]:
        return [
            w for w in self._workers
            if w._process is not None and w._process.poll() is None
        ]

    def _pick_target_worker(self, gpu_index: int) -> _Worker | None:
        return self._pick_target_worker_unlocked(gpu_index, self._live_workers())

    def _pick_target_worker_unlocked(self, gpu_index: int, live: list[_Worker]) -> _Worker | None:
        for worker in live:
            if int(worker.stats.gpu_index) == int(gpu_index):
                return worker
        return None

    def _pick_worker(self) -> Optional[_Worker]:
        """Return the least-assigned live worker, rotating ties."""
        return self._pick_worker_unlocked(self._live_workers())

    def _pick_worker_unlocked(self, live: list[_Worker]) -> Optional[_Worker]:
        if not live:
            return self._workers[0] if self._workers else None

        available = [w for w in live if self._worker_assigned_count(w) < self._backlog_per_gpu]
        if not available:
            return None
        start = self._rr_cursor % len(available)
        ordered = available[start:] + available[:start]
        best = min(ordered, key=lambda w: (self._worker_load(w), ordered.index(w)))
        self._rr_cursor = (available.index(best) + 1) % len(available)
        return best

    def _dispatch_synthetic(self, event: dict) -> None:
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                pass

    def _request_restart(self, worker: _Worker, *, reason: str) -> None:
        # Stop the stalled worker; ``_on_worker_exited`` will drive recovery.
        try:
            worker.stop(kill=True, timeout_s=2.0)
        except Exception as exc:
            _stderr(f"worker: stop on restart raised: {type(exc).__name__}: {exc}")

    def _on_worker_exited(self, worker: _Worker, rc: int | None) -> None:
        if self._shutting_down:
            return
        if len(worker.stats.unexpected_exits) >= DEGRADED_MAX_EXITS:
            self._degraded = True
            _stderr(
                f"worker: DEGRADED — {DEGRADED_MAX_EXITS} unexpected exits within "
                f"{DEGRADED_WINDOW_S:.0f}s on gpu_index={worker.stats.gpu_index} (rc={rc})"
            )
            return
        # Cooldown then restart in a background thread so the reader
        # thread that called us can return cleanly.
        def _delayed_restart() -> None:
            _stderr(
                f"worker: cooldown {RESTART_COOLDOWN_S:.0f}s before respawn "
                f"gpu_index={worker.stats.gpu_index}"
            )
            time.sleep(RESTART_COOLDOWN_S)
            if self._shutting_down:
                return
            try:
                worker.start()
            except Exception as exc:
                _stderr(f"worker: respawn failed: {type(exc).__name__}: {exc}")

        with self._restart_lock:
            t = threading.Thread(
                target=_delayed_restart,
                name=f"render-worker-respawn-{worker.stats.gpu_index}",
                daemon=True,
            )
            t.start()


__all__ = ["WorkerManager", "WorkerStats"]
