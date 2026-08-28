from __future__ import annotations

import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from office_run_state import GenerationLogTracker, new_state, read_json, update_state, write_json_atomic  # noqa: E402


def test_state_round_trip_is_atomic(tmp_path: Path):
    path = tmp_path / "office_run_state.json"
    state = new_state(run_id="run-1", contract={"seed": "20260824"}, logical_seed="20260824", max_attempts=6, root=tmp_path)
    write_json_atomic(path, state)
    update_state(path, state, status="running", stage="generation", note="candidate started")
    saved = read_json(path)
    assert saved and saved["status"] == "running"
    assert saved["history"][-1]["note"] == "candidate started"


def test_tracker_reports_chair_stall_only_after_no_progress_window():
    tracker = GenerationLogTracker(started_monotonic=0.0)
    for index in range(50):
        tracker.feed("[dof] [WARNING] | Init was invalid for name='OfficeChairFactory'", now=float(index))
    assert not tracker.feed("[annealing] [INFO] | it=1/200 dt=1.0 n=155 loss=0.0 viol=10.0", now=51.0)
    assert not tracker.feed("[annealing] [INFO] | it=20/200 dt=1.0 n=155 loss=0.0 viol=10.0", now=70.0)
    assert tracker.feed("[annealing] [INFO] | it=21/200 dt=1.0 n=155 loss=0.0 viol=10.0", now=71.0)
    snapshot = tracker.snapshot(now=72.0)
    assert snapshot["solver"]["stagnant_iterations"] == 20
    assert snapshot["solver"]["iteration_eta_s"] is not None


def test_tracker_resets_stagnation_when_new_solver_pass_starts():
    tracker = GenerationLogTracker(started_monotonic=0.0)
    for index in range(50):
        tracker.feed("OfficeChairFactory Init was invalid", now=float(index))
    tracker.feed("[annealing] it=30/200 n=100 viol=10.0", now=51.0)
    assert not tracker.feed("[annealing] it=1/200 n=100 viol=10.0", now=52.0)
    assert tracker.snapshot(now=53.0)["solver"]["stagnant_iterations"] == 0


def test_snapshot_can_be_merged_with_lifecycle_stage_without_keyword_collision(tmp_path: Path):
    path = tmp_path / "office_run_state.json"
    state = new_state(run_id="run-merge", contract={}, logical_seed="1", max_attempts=1, root=tmp_path)
    write_json_atomic(path, state)
    tracker = GenerationLogTracker(started_monotonic=0.0)
    snapshot = tracker.snapshot(now=1.0)
    assert "stage" not in snapshot
    assert snapshot["observed_stage"] == "starting"
    update_state(path, state, status="running", stage="generation", **snapshot)
    assert read_json(path)["stage"] == "generation"


def test_zero_violation_pass_is_not_reported_as_stalled():
    tracker = GenerationLogTracker(started_monotonic=0.0)
    for index in range(50):
        tracker.feed("OfficeChairFactory Init was invalid", now=float(index))
    assert not tracker.feed("[annealing] it=1/300 n=100 viol=0.0", now=51.0)
    assert not tracker.feed("[annealing] it=80/300 n=100 viol=0.0", now=130.0)
    solver = tracker.snapshot(now=131.0)["solver"]
    assert solver["stagnant_iterations"] == 0
    assert solver["pass_index"] == 1
    assert solver["global_iterations"] == 80


def test_stop_requires_matching_candidate_command(monkeypatch, tmp_path: Path):
    from office_run_state import stop_recorded_candidate

    state = {"process": {"pid": 123, "pgid": 456, "candidate_dir": str(tmp_path / "attempt")}}
    monkeypatch.setattr("office_run_state.pid_is_alive", lambda _pid: True)
    monkeypatch.setattr("office_run_state.process_matches_candidate", lambda *_args: False)
    called = []
    monkeypatch.setattr("office_run_state.os.killpg", lambda *args: called.append(args))
    ok, message = stop_recorded_candidate(state)
    assert not ok
    assert "refusing" in message
    assert called == []


def test_stop_uses_live_process_group_when_recorded_pgid_is_stale(monkeypatch, tmp_path: Path):
    from office_run_state import stop_recorded_candidate

    state = {"process": {"pid": 123, "pgid": 456, "candidate_dir": str(tmp_path / "attempt")}}
    alive = iter((True, False, False))
    monkeypatch.setattr("office_run_state.pid_is_alive", lambda _pid: next(alive))
    monkeypatch.setattr("office_run_state.process_matches_candidate", lambda *_args: True)
    monkeypatch.setattr("office_run_state.os.getpgid", lambda _pid: 789)
    called = []
    monkeypatch.setattr("office_run_state.os.killpg", lambda *args: called.append(args))
    ok, message = stop_recorded_candidate(state)
    assert ok
    assert called == [(789, signal.SIGINT)]
    assert "recorded pgid=456" in message
    assert "live pgid=789" in message


def test_legacy_history_recovers_restart_counters(tmp_path: Path):
    path = tmp_path / "office_run_state.json"
    state = new_state(run_id="run-history", contract={}, logical_seed="1", max_attempts=6, root=tmp_path)
    state.pop("execution", None)
    state["history"] = [
        {"at": "2026-08-25T00:00:00Z", "status": "running", "note": "candidate attempt_01 started"},
        {"at": "2026-08-25T00:01:00Z", "status": "planned", "note": "candidate 1 transient same-seed retry"},
        {"at": "2026-08-25T00:02:00Z", "status": "unsatisfied_solver", "note": "candidate 1 failed: unsatisfied_solver"},
    ]
    write_json_atomic(path, state)
    saved = read_json(path)
    assert saved and saved["execution"]["candidate_starts"] == 1
    assert saved["execution"]["transient_retries"] == 1
    assert saved["execution"]["terminal_failures"] == 1


def test_state_update_merges_child_history_and_counters(tmp_path: Path):
    path = tmp_path / "office_run_state.json"
    state = new_state(run_id="run-merge-history", contract={}, logical_seed="1", max_attempts=6, root=tmp_path)
    write_json_atomic(path, state)
    child = read_json(path)
    child["history"].append({"at": "2026-08-25T00:00:01Z", "status": "running", "note": "candidate attempt_01 started"})
    child["execution"]["candidate_starts"] = 1
    update_state(path, child, status="running", stage="generation", note="child heartbeat")
    parent = read_json(path)
    assert parent and parent["execution"]["candidate_starts"] == 1
    assert {item["note"] for item in parent["history"]} >= {"candidate attempt_01 started", "child heartbeat"}


def test_running_heartbeat_clears_previous_terminal_fields(tmp_path: Path):
    path = tmp_path / "office_run_state.json"
    state = new_state(run_id="run-retry", contract={}, logical_seed="1", max_attempts=6, root=tmp_path)
    state["returncode"] = -15
    state["termination_reason"] = "user_stop"
    write_json_atomic(path, state)
    update_state(path, state, status="running", stage="solve_large")
    saved = read_json(path)
    assert saved and saved["returncode"] is None
    assert saved["termination_reason"] is None
