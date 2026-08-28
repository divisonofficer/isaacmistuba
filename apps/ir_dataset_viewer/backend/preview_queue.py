"""Small priority gate for expensive preview decode/encode work."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PreviewLease:
    priority: str
    waited_ms: float


class PreviewWorkScheduler:
    """Reserve two work slots for direct interaction and one for idle work.

    Cache hits never enter this scheduler.  Separate semaphores are deliberate:
    a prefetch may consume at most one CPU-heavy slot, leaving both interactive
    slots available even while the user moves through headings quickly.
    """

    PRIORITIES = {"interactive", "comparison", "prefetch"}

    def __init__(self, *, interactive_slots: int = 2, background_slots: int = 1):
        self._interactive = threading.BoundedSemaphore(interactive_slots)
        self._background = threading.BoundedSemaphore(background_slots)

    def acquire(self, priority: str, *, cancelled: Callable[[], bool] | None = None) -> PreviewLease | None:
        if priority not in self.PRIORITIES:
            raise ValueError(f"unknown preview priority: {priority}")
        semaphore = self._interactive if priority in {"interactive", "comparison"} else self._background
        started = time.perf_counter()
        while True:
            if cancelled is not None and cancelled():
                return None
            if semaphore.acquire(timeout=0.025):
                return PreviewLease(priority=priority, waited_ms=(time.perf_counter() - started) * 1000.0)

    def release(self, lease: PreviewLease) -> None:
        semaphore = self._interactive if lease.priority in {"interactive", "comparison"} else self._background
        semaphore.release()
