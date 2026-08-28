#!/usr/bin/env python3
"""Durable state and log observability for Wide Glass Office v2 runs.

The Infinigen object solver keeps its search state in Blender memory, so a
stopped candidate cannot be resumed mid-anneal.  This module deliberately does
not pretend otherwise: it records the exact deterministic candidate seed and
enough process/log information for the wizard to restart that candidate safely.

It is standard-library only so both the outer wizard and the Infinigen Python
environment can use the same state contract.
"""
from __future__ import annotations

import datetime as _datetime
import copy
import hashlib
import json
import os
import re
import signal
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # Linux/WSL production; keep the module importable on Windows tests.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None


SCHEMA = "robomituba.office_run_state.v2"

_STAGE_RE = re.compile(r"\[logging\]\s+\[INFO\]\s+\|\s+\[([^]]+)\](?:\s+finished.*)?")
_ITER_RE = re.compile(
    r"\[annealing\].*?\bit=(?P<iteration>\d+)/(?P<total>\d+)"
    r".*?\bn=(?P<objects>\d+).*?\bviol=(?P<violations>[\d.]+)"
)
_UNSATISFIED_RE = re.compile(r"(?:abort_unsatisfied|unsatisfied|Solver has failed)", re.IGNORECASE)


def utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return _normalize_state(value)


_EXECUTION_KEYS = (
    "candidate_starts", "transient_retries", "resume_requests",
    "graceful_stops", "terminal_failures",
)
_TERMINAL_STATUSES = {
    "generation_failed", "solver_stalled", "unsatisfied_solver",
    "preflight_error", "contract_error", "audit_failed",
}


def _history_execution(history: list[Any]) -> dict[str, int]:
    """Recover counters for state files written before v2 counters existed.

    The wizard and the child generator both append lifecycle events.  Those
    events are the durable source of truth; mutable counters are only a
    convenient cache and must never make a restart invisible.
    """
    counters = {key: 0 for key in _EXECUTION_KEYS}
    for item in history:
        if not isinstance(item, dict):
            continue
        note = str(item.get("note") or "").lower()
        status = str(item.get("status") or "").lower()
        if "candidate " in note and " started" in note:
            counters["candidate_starts"] += 1
        if "transient same-seed retry" in note:
            counters["transient_retries"] += 1
        if "resume" in note and ("request" in note or "adopted" in note):
            counters["resume_requests"] += 1
        if status == "interrupted" and ("stopped" in note or "sigint" in note or "candidate pid" in note):
            counters["graceful_stops"] += 1
        if status in _TERMINAL_STATUSES and ("failed" in note or "exited" in note):
            counters["terminal_failures"] += 1
    return counters


def _normalize_state(value: dict[str, Any]) -> dict[str, Any]:
    """Make old v2 state files observable without rewriting them eagerly."""
    if value.get("schema") != SCHEMA:
        return value
    execution = value.setdefault("execution", {})
    derived = _history_execution(value.get("history") or [])
    for key in _EXECUTION_KEYS:
        try:
            current = int(execution.get(key, 0))
        except (TypeError, ValueError):
            current = 0
        execution[key] = max(current, derived[key])
    value.setdefault("hazards", [])
    return value


def _event_key(item: Any) -> tuple[str, str, str, str]:
    if not isinstance(item, dict):
        return ("", "", "", repr(item))
    return (str(item.get("at") or ""), str(item.get("status") or ""),
            str(item.get("stage") or ""), str(item.get("note") or ""))


def _merge_history(left: list[Any], right: list[Any]) -> list[Any]:
    merged: dict[tuple[str, str, str, str], Any] = {}
    for item in left + right:
        merged[_event_key(item)] = item
    return sorted(merged.values(), key=lambda item: _event_key(item)[0])


@contextmanager
def _state_lock(path: Path):
    """Serialize parent/child state writes without introducing a dependency."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def state_path(root: Path) -> Path:
    return root / "office_run_state.json"


def new_state(*, run_id: str, contract: dict[str, Any], logical_seed: str,
              max_attempts: int, root: Path) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "root": str(root),
        "contract": contract,
        "contract_digest": digest(contract),
        "logical_seed": str(logical_seed),
        "max_attempts": int(max_attempts),
        "status": "planned",
        "stage": "planned",
        "created_at": now,
        "updated_at": now,
        "heartbeat_at": now,
        "attempts": {},
        # Durable counters make repeated manual resumes visible instead of
        # hiding them behind a single mutable ``status`` field.
        "execution": {
            "candidate_starts": 0,
            "transient_retries": 0,
            "resume_requests": 0,
            "graceful_stops": 0,
            "terminal_failures": 0,
        },
        "hazards": [],
        "history": [],
    }


def update_state(path: Path, state: dict[str, Any], *, status: str | None = None,
                 stage: str | None = None, note: str | None = None,
                 **fields: Any) -> dict[str, Any]:
    with _state_lock(path):
        latest = read_json(path) if path.exists() else None
        if latest is not None and latest is not state:
            # A child may have written solver progress after the parent loaded
            # its snapshot. Preserve that progress while applying the
            # caller's explicit lifecycle fields. History and counters are
            # always unioned/maxed so retries cannot disappear.
            incoming_updated = str(state.get("updated_at") or "")
            latest_updated = str(latest.get("updated_at") or "")
            if latest_updated > incoming_updated:
                for key in ("solver", "observed_stage", "elapsed_s", "last_progress_age_s", "last_log_line", "selected_attempt"):
                    if key in latest and key not in fields:
                        state[key] = copy.deepcopy(latest[key])
            state["history"] = _merge_history(
                latest.get("history") or [], state.get("history") or []
            )
            latest_exec = latest.get("execution") or {}
            incoming_exec = state.get("execution") or {}
            state["execution"] = {
                key: max(int(latest_exec.get(key, 0) or 0), int(incoming_exec.get(key, 0) or 0))
                for key in _EXECUTION_KEYS
            }
            # Child and parent update the same attempt record. Prefer the
            # newest disk record when it exists, while retaining newly planned
            # attempts that only the caller knows about.
            merged_attempts = copy.deepcopy(state.get("attempts") or {})
            merged_attempts.update(copy.deepcopy(latest.get("attempts") or {}))
            state["attempts"] = merged_attempts
        if status is not None:
            state["status"] = status
        if stage is not None:
            state["stage"] = stage
        execution = state.setdefault("execution", {})
        for key in _EXECUTION_KEYS:
            execution.setdefault(key, 0)
        state.setdefault("hazards", [])
        state.update(fields)
        # A retrying candidate keeps an in-memory snapshot of the previous
        # attempt.  Every heartbeat is an explicit assertion that the child
        # is live, so terminal fields from that snapshot must not leak back
        # into the running state (e.g. returncode=-15/user_stop).
        if status == "running":
            state["returncode"] = None
            state["termination_reason"] = None
        now = utc_now()
        state["updated_at"] = now
        state["heartbeat_at"] = now
        if note:
            state.setdefault("history", []).append({"at": now, "status": state.get("status"), "stage": state.get("stage"), "note": note})
        write_json_atomic(path, _normalize_state(state))
    return state


def process_matches_candidate(pid: int, candidate_dir: Path) -> bool:
    """Verify a live process is the recorded candidate before signalling it."""
    proc = Path("/proc") / str(pid)
    try:
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except FileNotFoundError:
        return False
    return str(candidate_dir.resolve()) in cmdline


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    # ``kill(pid, 0)`` reports success for a zombie until its parent reaps it.
    # Treating that as live can block --resume/--stop forever on a dead
    # Blender child, so inspect the proc state first when available.
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        right = stat.rfind(")")
        if right >= 0 and len(stat) > right + 2 and stat[right + 2] == "Z":
            return False
    except (FileNotFoundError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_recorded_candidate(state: dict[str, Any], *, force: bool = False,
                            timeout_s: float = 90.0, poll_s: float = 0.25) -> tuple[bool, str]:
    """Signal the current independent candidate process group after validation."""
    process = state.get("process") or {}
    try:
        pid, recorded_pgid = int(process["pid"]), int(process["pgid"])
        candidate = Path(str(process["candidate_dir"])).resolve()
    except (KeyError, TypeError, ValueError):
        return False, "no recorded candidate process"
    if not pid_is_alive(pid):
        return True, "recorded process already exited"
    if not process_matches_candidate(pid, candidate):
        return False, f"refusing to signal pid={pid}: command line does not reference {candidate}"
    # A wrapper/exec transition can leave a state file with the child's old
    # PID/PGID pair while the live process has joined a newly-created session.
    # Never trust that stale PGID blindly: resolve the live PID's group after
    # the command-line ownership check.  The recorded value is retained only
    # for diagnostics.
    try:
        live_pgid = os.getpgid(pid)
    except ProcessLookupError:
        return True, "recorded process group already exited"
    pgid = int(live_pgid)
    sig = signal.SIGTERM if force else signal.SIGINT
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return True, "recorded process group already exited"
    deadline = time.monotonic() + timeout_s
    while pid_is_alive(pid) and time.monotonic() < deadline:
        time.sleep(poll_s)
    if pid_is_alive(pid):
        return False, f"candidate pid={pid} did not exit within {timeout_s:g}s"
    suffix = f" (recorded pgid={recorded_pgid}, live pgid={pgid})" if recorded_pgid != pgid else ""
    return True, f"sent {sig.name} to process group {pgid}{suffix}"


class GenerationLogTracker:
    """Parse an append-only generation log and expose a compact heartbeat."""

    def __init__(self, *, started_monotonic: float | None = None) -> None:
        self.started_monotonic = started_monotonic if started_monotonic is not None else time.monotonic()
        self.stage = "starting"
        self.iteration: int | None = None
        self.total_iterations: int | None = None
        self.objects: int | None = None
        self.violations: float | None = None
        self._last_violation_change_iteration: int | None = None
        self._iteration_times: list[tuple[int, float]] = []
        self._durations: list[float] = []
        self.solver_passes_completed = 0
        self.global_iterations = 0
        self.office_chair_init_failures = 0
        self.unsatisfied_solver = False
        self.last_line = ""
        self.last_progress_monotonic = self.started_monotonic

    def feed(self, line: str, *, now: float | None = None) -> bool:
        """Consume one log line and return true when the stall contract trips."""
        now = now if now is not None else time.monotonic()
        line = line.rstrip("\n")
        self.last_line = line[-800:]
        stage = _STAGE_RE.search(line)
        if stage:
            candidate = stage.group(1).strip()
            if candidate and candidate != self.stage:
                self.stage = candidate
                self.last_progress_monotonic = now
        if "OfficeChairFactory" in line and "Init was invalid" in line:
            self.office_chair_init_failures += 1
        if _UNSATISFIED_RE.search(line):
            self.unsatisfied_solver = True
        match = _ITER_RE.search(line)
        if not match:
            return False
        iteration = int(match.group("iteration"))
        total = int(match.group("total"))
        violations = float(match.group("violations"))
        # A new annealing pass starts at a lower iteration and must not inherit
        # a no-progress counter from the previous pass.
        reset_pass = self.iteration is not None and iteration < self.iteration
        if reset_pass:
            self.solver_passes_completed += 1
            self._last_violation_change_iteration = iteration
            self._iteration_times.clear()
            self._durations.clear()
        if violations <= 0.0:
            self._last_violation_change_iteration = None
        elif self.violations is None or violations < self.violations - 1e-9:
            self._last_violation_change_iteration = iteration
        if self.iteration is not None and iteration > self.iteration:
            previous_iteration, previous_at = self._iteration_times[-1] if self._iteration_times else (self.iteration, self.last_progress_monotonic)
            delta_iterations = iteration - previous_iteration
            if delta_iterations > 0:
                self._durations.append((now - previous_at) / delta_iterations)
                self._durations = self._durations[-20:]
        self.iteration = iteration
        self.total_iterations = total
        self.objects = int(match.group("objects"))
        self.violations = violations
        self._iteration_times.append((iteration, now))
        self._iteration_times = self._iteration_times[-2:]
        # Log output can skip individual iteration numbers; accumulate the
        # actual difference rather than assuming a perfectly dense trace.
        if reset_pass:
            self.global_iterations += iteration
        elif len(self._iteration_times) == 1:
            self.global_iterations += iteration
        else:
            self.global_iterations += max(0, iteration - self._iteration_times[-2][0])
        self.last_progress_monotonic = now
        stalled_iterations = 0 if self._last_violation_change_iteration is None else iteration - self._last_violation_change_iteration
        return violations > 0.0 and self.office_chair_init_failures >= 50 and stalled_iterations >= 20

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.monotonic()
        median_s = statistics.median(self._durations) if self._durations else None
        remaining = None
        if median_s is not None and self.iteration is not None and self.total_iterations is not None:
            remaining = max(0.0, self.total_iterations - self.iteration) * median_s
        stagnant = 0 if self._last_violation_change_iteration is None or self.iteration is None else self.iteration - self._last_violation_change_iteration
        return {
            # ``stage`` is the wizard's lifecycle field. Keep the parser's
            # current Infinigen log stage distinct so callers can safely pass
            # a snapshot alongside ``update_state(..., stage=...)``.
            "observed_stage": self.stage,
            "solver": {
                "iteration": self.iteration,
                "total_iterations": self.total_iterations,
                "pass_index": self.solver_passes_completed + 1,
                "completed_passes": self.solver_passes_completed,
                "global_iterations": self.global_iterations,
                "object_count": self.objects,
                "violations": self.violations,
                "office_chair_init_failures": self.office_chair_init_failures,
                "stagnant_iterations": stagnant,
                "iteration_median_s": median_s,
                "iteration_eta_s": remaining,
                "unsatisfied_solver": self.unsatisfied_solver,
            },
            "elapsed_s": now - self.started_monotonic,
            "last_progress_age_s": now - self.last_progress_monotonic,
            "last_log_line": self.last_line,
        }

    def heartbeat(self, *, candidate: str, now: float | None = None) -> str:
        value = self.snapshot(now=now)
        solver = value["solver"]
        iteration = solver["iteration"]
        total = solver["total_iterations"]
        progress = f"{iteration}/{total}" if iteration is not None and total is not None else "n/a"
        violations = "n/a" if solver["violations"] is None else f"{solver['violations']:g}"
        eta = "unknown"
        if solver["iteration_eta_s"] is not None:
            eta = f"{solver['iteration_eta_s'] / 60.0:.1f}m"
        return (f"[office] stage={value['observed_stage']} candidate={candidate} pass={solver['pass_index']} iteration={progress} "
                f"violations={violations} elapsed={value['elapsed_s'] / 60.0:.1f}m "
                f"iteration_eta={eta} candidate_eta=calibrating")
