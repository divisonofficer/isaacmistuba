"""Asynchronous persistence for render-worker state transitions.

The worker stdout reader is a latency-sensitive control path: if it performs
NFS or SQLite I/O, the child worker eventually blocks while writing progress
events and stops feeding its GPU.  This module provides a single ordered,
batched writer plus watermark barriers for the few places that require durable
state before continuing (phase/variant boundaries and shutdown).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import queue
import threading
import time
from typing import Any, Callable, Mapping, Sequence


PersistBatch = Callable[[Sequence[Mapping[str, Any]]], None]


@dataclass(frozen=True)
class _PendingEvent:
    sequence: int
    run_id: str
    enqueued_at: float
    payload: dict[str, Any]


class RenderPersistenceWriter:
    """One unbounded input queue feeding one ordered persistence thread."""

    def __init__(
        self,
        persist_batch: PersistBatch,
        *,
        batch_size: int = 64,
        batch_interval_s: float = 0.05,
        max_attempts: int = 5,
        retry_base_s: float = 0.1,
    ) -> None:
        self._persist_batch = persist_batch
        self._batch_size = max(1, int(batch_size))
        self._batch_interval_s = max(0.0, float(batch_interval_s))
        self._max_attempts = max(1, int(max_attempts))
        self._retry_base_s = max(0.0, float(retry_base_s))
        self._queue: queue.Queue[_PendingEvent | None] = queue.Queue()
        self._condition = threading.Condition()
        self._next_sequence = 0
        self._completed_sequence = 0
        self._run_watermarks: dict[str, int] = {}
        self._pending_times: list[float] = []
        self._failed_sequence: int | None = None
        self._last_error: str | None = None
        self._last_success_at: str | None = None
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run,
            name="render-persistence-writer",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, payload: Mapping[str, Any], *, run_id: str = "") -> int:
        with self._condition:
            if self._stopping:
                raise RuntimeError("render persistence writer is stopping")
            self._next_sequence += 1
            sequence = self._next_sequence
            now = time.monotonic()
            event = _PendingEvent(sequence, str(run_id or ""), now, dict(payload))
            self._pending_times.append(now)
            if event.run_id:
                self._run_watermarks[event.run_id] = sequence
        self._queue.put(event)
        return sequence

    def watermark(self, *, run_id: str | None = None) -> int:
        with self._condition:
            if run_id is not None:
                return int(self._run_watermarks.get(str(run_id), 0))
            return self._next_sequence

    def flush(
        self,
        *,
        run_id: str | None = None,
        target_sequence: int | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        target = int(target_sequence if target_sequence is not None else self.watermark(run_id=run_id))
        if target <= 0:
            return
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while self._completed_sequence < target:
                if self._failed_sequence is not None and self._failed_sequence <= target:
                    raise RuntimeError(self._last_error or "render persistence failed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"render persistence flush timed out at "
                        f"{self._completed_sequence}/{target}"
                    )
                self._condition.wait(timeout=min(0.25, remaining))

    def health(self) -> dict[str, Any]:
        with self._condition:
            oldest_age = (
                max(0.0, time.monotonic() - self._pending_times[0])
                if self._pending_times else 0.0
            )
            return {
                "status": "degraded" if self._failed_sequence is not None else "ok",
                "pending": len(self._pending_times),
                "oldest_age_s": round(oldest_age, 3),
                "enqueued_sequence": self._next_sequence,
                "completed_sequence": self._completed_sequence,
                "failed_sequence": self._failed_sequence,
                "last_success_at": self._last_success_at,
                "last_error": self._last_error,
            }

    def stop(self, *, timeout_s: float = 30.0) -> None:
        try:
            self.flush(timeout_s=timeout_s)
        finally:
            with self._condition:
                self._stopping = True
            self._queue.put(None)
            self._thread.join(timeout=max(0.0, float(timeout_s)))

    def _run(self) -> None:
        while True:
            first = self._queue.get()
            if first is None:
                return
            batch = [first]
            stop_after_batch = False
            deadline = time.monotonic() + self._batch_interval_s
            while len(batch) < self._batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if item is None:
                    with self._condition:
                        self._stopping = True
                    stop_after_batch = True
                    break
                batch.append(item)

            error: Exception | None = None
            for attempt in range(1, self._max_attempts + 1):
                try:
                    self._persist_batch([item.payload for item in batch])
                    error = None
                    break
                except Exception as exc:  # writer must surface, not silently die
                    error = exc
                    if attempt < self._max_attempts:
                        time.sleep(self._retry_base_s * (2 ** (attempt - 1)))

            with self._condition:
                del self._pending_times[:len(batch)]
                if error is None:
                    self._completed_sequence = batch[-1].sequence
                    self._last_success_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                else:
                    self._failed_sequence = batch[0].sequence
                    self._last_error = f"{type(error).__name__}: {error}"
                self._condition.notify_all()
            if stop_after_batch:
                return
