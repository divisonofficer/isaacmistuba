#!/usr/bin/env python3
"""Wait for Office v2 generation and run the existing import pipeline.

Generation and import are deliberately separate processes: a large Blender
generation child must be allowed to finish and publish its audited ``full``
directory before another Blender process opens it.  This monitor is durable
and intentionally conservative; it never starts import for a merely partial
candidate.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from office_run_state import pid_is_alive, process_matches_candidate, read_json as read_run_state  # noqa: E402


REPO = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO / "data" / "infinigen_generated" / "outputs" / "office-v2-hazard-report.json"
_POPULATE_RE = re.compile(r"\bPopulating\s+(\d+)\s*/\s*(\d+)\s+placeholder")
_ANNEAL_RE = re.compile(
    r"\|\s*it=(\d+)\s*/\s*(\d+)\s+"
    r"dt=([-+0-9.eE]+)\s+n=(\d+).*?\bviol=([-+0-9.eE]+)"
)
_LOG_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s+\[([^\]]+)\]")


def _candidate_log_tail(value: dict | None, *, max_bytes: int = 262_144) -> tuple[Path, str, float] | None:
    """Return the current candidate log tail and its age.

    The controller can disappear while its detached Infinigen child keeps
    writing the append-only log.  Reading this file directly is therefore
    more reliable than treating ``office_run_state.json`` as the sole
    heartbeat source.
    """
    if not value:
        return None
    process = value.get("process") or {}
    candidate = process.get("candidate_dir")
    if not candidate:
        return None
    log_path = Path(str(candidate)) / "generation.log"
    try:
        stat = log_path.stat()
        with log_path.open("rb") as handle:
            handle.seek(max(0, stat.st_size - max_bytes))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    return log_path, tail, max(0.0, time.time() - stat.st_mtime)


def _utc_age(value: object) -> float | None:
    """Return age in seconds for a state timestamp, or None if malformed."""
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        stamp = _datetime.datetime.fromisoformat(text)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=_datetime.timezone.utc)
        return max(0.0, (_datetime.datetime.now(_datetime.timezone.utc) - stamp).total_seconds())
    except (TypeError, ValueError):
        return None


def _state(seed: str) -> tuple[dict | None, Path]:
    root = REPO / "data" / "infinigen_generated" / "outputs" / f"kr_{seed}_office"
    path = root / "office_run_state.json"
    if not path.is_file():
        return None, root
    try:
        value = read_run_state(path)
        return value, root
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[office-import] seed={seed} state unreadable: {exc}", flush=True)
        return None, root


def _populate_progress(value: dict | None) -> dict[str, object] | None:
    """Read durable Blender population progress when solver fields are stale.

    ``office_run_state.json`` is updated by the solver parser, but asset
    population can spend minutes inside one Blender factory call without
    changing its solver iteration.  The generation log is append-only and is
    therefore the authoritative progress source for that stage.  Do not gate
    this on ``state.stage``: if the controller/parent died, the child can keep
    populating while the shared state still says ``solve_small``.  Parsing the
    candidate log lets the monitor observe and safely recover that orphaned
    child instead of presenting a misleading frozen solver heartbeat.
    """
    payload = _candidate_log_tail(value)
    if payload is None:
        return None
    log_path, tail, log_age_s = payload
    matches = list(_POPULATE_RE.finditer(tail))
    if not matches:
        return None
    match = matches[-1]
    completed, total = (int(match.group(1)), int(match.group(2)))
    # Infinigen logs the final asset batch as a stage summary rather than a
    # ``Populating 403/403`` line.  Treat that durable marker as completion so
    # the monitor does not remain one asset short while floating/layout work
    # is already running.
    finished_marker = tail.rfind("[populate_assets] finished")
    if finished_marker >= match.end():
        completed = total
    return {
        "completed": completed,
        "total": total,
        "fraction": completed / total if total else 0.0,
        "log_path": str(log_path),
        "log_age_s": log_age_s,
    }


def _solver_log_progress(value: dict | None) -> dict[str, object] | None:
    """Parse the newest annealing heartbeat from the candidate log.

    ``infinigen_gen.py`` owns state updates, but a shell disconnect can leave
    the generation child orphaned.  In that case the state's iteration/pass
    fields stop changing even though annealing continues (and may restart a
    new pass).  Keep the state pass for historical accounting and expose the
    log iteration as the live progress source.
    """
    payload = _candidate_log_tail(value)
    if payload is None:
        return None
    log_path, tail, log_age_s = payload
    matches = list(_ANNEAL_RE.finditer(tail))
    if not matches:
        return None
    match = matches[-1]
    try:
        iteration, total = int(match.group(1)), int(match.group(2))
        dt_s = float(match.group(3))
        objects = int(match.group(4))
        violations = float(match.group(5))
    except (TypeError, ValueError):
        return None
    # If a later non-annealing record (for example a long Blender populate
    # call) follows this match, the file mtime alone would incorrectly make
    # the old solver heartbeat look current.  Mark it stale while retaining
    # the parsed values for diagnostics.
    # The regex intentionally stops at ``viol=...`` while the same annealing
    # line continues with temperature/action fields.  Only content after the
    # *newline containing* the match represents a later log record.
    line_end = tail.find("\n", match.end())
    trailing_records = bool(tail[line_end + 1 :].strip()) if line_end >= 0 else False
    effective_age = max(log_age_s, 901.0) if trailing_records else log_age_s
    return {
        "iteration": iteration,
        "total_iterations": total,
        "object_count": objects,
        "violations": violations,
        "dt_s": dt_s,
        "log_path": str(log_path),
        "log_age_s": effective_age,
        "trailing_records": trailing_records,
    }


def _log_stage(value: dict | None) -> dict[str, object] | None:
    """Return the latest named Infinigen stage from the append-only log."""
    payload = _candidate_log_tail(value)
    if payload is None:
        return None
    log_path, tail, log_age_s = payload
    stage = None
    last_line = ""
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _LOG_PREFIX_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        if name == "logging":
            marker = re.search(r"\|\s+\[([^\]]+)\]", line)
            if marker:
                name = marker.group(1)
        # Blender compatibility/dof warnings are diagnostic records, not a
        # pipeline stage; keep reporting the preceding durable stage.
        if name in {"compatibility", "dof"}:
            continue
        stage = name
        last_line = line
    if stage is None:
        return None
    return {"stage": stage, "last_line": last_line, "log_path": str(log_path), "log_age_s": log_age_s}
def _active_import_wizard(seed: str) -> bool:
    """Return whether the seed's wizard is still owning the import phase.

    The v2 wizard performs generation *and* import in one process when
    invoked with ``--import``.  There is a short state transition where the
    candidate is marked ``published`` before the wizard records
    ``stage=import``.  Starting a second wizard in that window can race on
    the same scene directory.  Inspecting command lines is intentionally
    best-effort and only used to avoid duplicate recovery work; a missing or
    unreadable ``/proc`` entry is treated as inactive.
    """
    proc_root = Path("/proc")
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return False
    seed = str(seed)
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        if not argv:
            continue
        if not any(part.endswith("scripts/infinigen_wizard.py") or part == "infinigen_wizard.py" for part in argv):
            continue
        if "--import" not in argv or "--archetype" not in argv or "office" not in argv:
            continue
        try:
            seed_index = argv.index("--seed")
            if seed_index + 1 < len(argv) and argv[seed_index + 1] == seed:
                return True
        except ValueError:
            continue
    return False


def _execution_summary(seed: str) -> dict[str, int]:
    """Aggregate counters across the active root and preserved run archives.

    Archived roots are deliberately included because a new deterministic run
    starts with a fresh state file.  Deduplicate by run_id so a copied state
    file cannot inflate the restart count.
    """
    base = REPO / "data" / "infinigen_generated" / "outputs"
    seen: set[str] = set()
    totals = {key: 0 for key in (
        "candidate_starts", "transient_retries", "resume_requests",
        "graceful_stops", "terminal_failures",
    )}
    for root in sorted(base.glob(f"kr_{seed}_office*")):
        if not root.is_dir():
            continue
        try:
            value = read_run_state(root / "office_run_state.json")
        except OSError:
            # The writer uses atomic replace, but a NAS/overlay hiccup must
            # not take down the monitor.  The next poll will retry.
            continue
        if not value:
            continue
        run_id = str(value.get("run_id") or root.name)
        if run_id in seen:
            continue
        seen.add(run_id)
        execution = value.get("execution") or {}
        for key in totals:
            try:
                totals[key] += max(0, int(execution.get(key, 0) or 0))
            except (TypeError, ValueError):
                continue
    totals["restarts"] = max(0, totals["candidate_starts"] - len(seen))
    return totals


def _disk_hazards(paths: list[Path]) -> list[str]:
    """Warn before local overlay exhaustion can kill Blender/temporary bakes."""
    hazards: list[str] = []
    checked: set[str] = set()
    for path in paths:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        # Check each mount only once.  /jarvis is NAS while /tmp and / are
        # normally the same local overlay, so the path itself is reported.
        mount_key = str(path.stat().st_dev) if path.exists() else str(path)
        if mount_key in checked:
            continue
        checked.add(mount_key)
        free_gib = usage.free / (1024 ** 3)
        used_ratio = usage.used / max(1, usage.total)
        label = "local_disk" if path == Path("/") else path.name or str(path)
        if free_gib < 25:
            hazards.append(f"{label}_disk_critical_{free_gib:.0f}GiB_free")
        elif free_gib < 100 or used_ratio >= 0.95:
            hazards.append(f"{label}_disk_low_{free_gib:.0f}GiB_free")
    return hazards


def _hazards(value: dict | None) -> list[str]:
    """Return warnings without changing or killing a generation process."""
    if not value or value.get("status") != "running":
        return []
    hazards = list(value.get("hazards") or [])
    process = value.get("process") or {}
    try:
        pid = int(process.get("pid", 0))
        candidate = Path(str(process.get("candidate_dir", ""))).resolve()
    except (TypeError, ValueError):
        pid, candidate = 0, None
    if not pid or not pid_is_alive(pid):
        hazards.append("recorded_process_not_alive")
    elif candidate is None or not process_matches_candidate(pid, candidate):
        hazards.append("process_candidate_mismatch")
    population = _populate_progress(value)
    solver_log = _solver_log_progress(value)
    stage_log = _log_stage(value)
    population_log_fresh = bool(population and float(population.get("log_age_s") or 0) <= 900)
    solver_log_fresh = bool(solver_log and float(solver_log.get("log_age_s") or 0) <= 900)
    stage_log_fresh = bool(stage_log and float(stage_log.get("log_age_s") or 0) <= 900)
    # ``floating_objs`` does not update the solver iteration fields.  Its
    # append-only log is therefore the only durable heartbeat for this stage;
    # surface a warning when it has gone quiet for the same 15-minute window
    # used by the solver heartbeat checks.  This is deliberately diagnostic
    # only: the Blender process may still be CPU-bound on a raycast-heavy
    # floating-object placement and is not killed by the monitor.
    stage = str(value.get("stage") or "")
    if stage.startswith("floating"):
        candidate_dir = process.get("candidate_dir")
        try:
            log_age = time.time() - (Path(str(candidate_dir)) / "generation.log").stat().st_mtime
        except (OSError, TypeError):
            log_age = None
        if log_age is not None and log_age > 900:
            hazards.append("floating_stage_log_older_than_15m")
    # Population progress is independent of solver heartbeat.  Do not report
    # a false 15-minute heartbeat hazard while the append-only log is moving.
    if float(value.get("last_progress_age_s") or 0) > 900 and not (population_log_fresh or solver_log_fresh or stage_log_fresh):
        hazards.append("heartbeat_older_than_15m")
    heartbeat_age = _utc_age(value.get("heartbeat_at"))
    if heartbeat_age is not None and heartbeat_age > 900 and not (population_log_fresh or solver_log_fresh or stage_log_fresh):
        hazards.append("state_heartbeat_older_than_15m")
    solver = value.get("solver") or {}
    if solver_log_fresh:
        # Log values are the live child heartbeat; state values may belong to
        # the previous solver pass when the controller is gone.
        violations = float(solver_log.get("violations") or 0)
    else:
        violations = float(solver.get("violations") or 0)
    stagnant_iterations = int(solver.get("stagnant_iterations") or 0)
    if violations > 0:
        hazards.append("solver_nonzero_violation_active")
        # The historical break-room failure stayed at one violation for an
        # entire pass.  Surface an early warning after 20 unchanged
        # iterations, while retaining a distinct long-stall signal for
        # terminal-risk monitoring.
        if stagnant_iterations >= 20:
            hazards.append("solver_nonzero_violation_stagnation_20")
        if stagnant_iterations >= 100:
            hazards.append("solver_nonzero_violation_stagnation")
    last_line = str(value.get("last_log_line") or "").lower()
    if "solver has failed" in last_line or "unsatisfied_solver" in last_line:
        hazards.append("known_unsatisfied_solver_error")
    if value.get("status") == "running" and int(value.get("current_attempt") or 0) >= int(value.get("max_attempts") or 1):
        hazards.append("attempt_budget_exhausted")
    return sorted(set(hazards))


def _process_check(value: dict | None) -> dict[str, object]:
    """Expose the ownership check used by the hazard detector in reports."""
    process = (value or {}).get("process") or {}
    try:
        pid = int(process.get("pid", 0))
        candidate = Path(str(process.get("candidate_dir", ""))).resolve()
    except (TypeError, ValueError):
        return {"pid": 0, "alive": False, "candidate_match": False}
    alive = bool(pid and pid_is_alive(pid))
    return {
        "pid": pid,
        "alive": alive,
        "candidate_match": bool(alive and candidate and process_matches_candidate(pid, candidate)),
    }


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _write_report(path: Path, reports: dict[str, dict]) -> None:
    _atomic_write(path, {
        "schema": "robomituba.office_v2_hazard_report.v1",
        "updated_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "seeds": reports,
        "local_disk_hazards": _disk_hazards([Path("/"), Path("/tmp")]),
    })


def _ready(seed: str) -> tuple[bool, str]:
    value, root = _state(seed)
    if value is None:
        return False, "waiting for office_run_state.json"
    status = value.get("status")
    full = root / "full"
    required = (full / "scene.blend", full / "workstation_layout.json", full / "office_population_audit.json")
    if status == "published" and all(path.is_file() for path in required):
        try:
            audit = json.loads((full / "office_population_audit.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"published audit unreadable: {exc}"
        if audit.get("status") != "passed":
            return False, f"published audit status={audit.get('status')!r}"
        return True, "published audited scene ready"

    # ``infinigen_gen.py`` records ``scene_ready`` when the expensive Blender
    # generation child exits successfully, but the wizard is responsible for
    # the subsequent repair/audit/publish/import stages.  A wizard can be
    # detached or die while its generation child remains alive (notably after
    # a terminal shell disconnect), leaving a valid candidate under
    # ``attempts/`` with no owner to advance it.  Treat only a complete
    # post-process candidate as resumable; a bare scene.blend is deliberately
    # insufficient because workstation pairing and the manifest contract may
    # still be incomplete.
    if status in {"scene_ready", "audit", "audit_failed", "generation_failed"}:
        candidates: list[Path] = []
        process = value.get("process") or {}
        process_candidate = process.get("candidate_dir")
        if process_candidate:
            candidates.append(Path(str(process_candidate)))
        attempts = value.get("attempts") or {}
        for entry in attempts.values() if isinstance(attempts, dict) else ():
            if isinstance(entry, dict) and entry.get("candidate_dir"):
                candidates.append(Path(str(entry["candidate_dir"])))
        candidates.extend(sorted((root / "attempts").glob("attempt_*")))
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                candidate = candidate.resolve()
            except OSError:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            if not candidate.is_dir():
                continue
            candidate_required = (
                candidate / "scene.blend",
                candidate / "office_layout_manifest.json",
                candidate / "workstation_layout.json",
            )
            if all(path.is_file() for path in candidate_required):
                return True, f"resumable audited-candidate inputs at {candidate}"

    if status == "running":
        process = value.get("process") or {}
        try:
            pid = int(process.get("pid", 0))
            candidate = Path(str(process.get("candidate_dir", ""))).resolve()
        except (TypeError, ValueError):
            pid, candidate = 0, None
        process_lost = (
            not pid
            or not pid_is_alive(pid)
            or candidate is None
            or not process_matches_candidate(pid, candidate)
        )
        # A wizard/controller can disappear while its detached generation
        # child keeps running.  When that child exits successfully it cannot
        # update the controller-owned state file, so the state remains
        # ``running`` even though a complete candidate is now available.
        # Recognise only the recorded candidate (never an arbitrary attempt
        # directory) and hand it to the normal ``--resume --import`` path for
        # post-process audit/publish.  A live/matching process still owns the
        # candidate and must not be raced by the monitor.
        if process_lost and process.get("candidate_dir") and candidate is not None:
            candidate_required = (
                candidate / "scene.blend",
                candidate / "office_layout_manifest.json",
                candidate / "workstation_layout.json",
            )
            if all(path.is_file() for path in candidate_required):
                return True, f"orphaned candidate complete; resume/import at {candidate}"
        heartbeat_age = _utc_age(value.get("heartbeat_at"))
        # A short wrapper/exec transition is benign.  Once the state has been
        # quiet for two minutes, however, waiting forever is worse than
        # surfacing a resumable failure to the operator.
        if process_lost and heartbeat_age is not None and heartbeat_age >= 120.0:
            return False, "generation process lost; explicit --resume required"
    if status in {"generation_failed", "solver_stalled", "unsatisfied_solver", "audit_failed"}:
        return False, f"terminal generation state={status}"
    return False, f"status={status!r}, waiting for audited publish"


def _import(seed: str, *, bake_pbr: bool) -> int:
    command = [
        sys.executable,
        "scripts/infinigen_wizard.py",
        "--archetype", "office",
        "--seed", seed,
        "--resume",
        "--import",
        "--yes",
    ]
    if bake_pbr:
        command.append("--bake-pbr")
    print(f"[office-import] seed={seed} starting audited import", flush=True)
    return subprocess.run(command, cwd=REPO).returncode


def _import_complete(seed: str) -> bool:
    """Return whether the seed already has a committed OpticalNav import.

    A published Office candidate is not sufficient evidence that Stage 1 and
    the graph audit finished: the wizard intentionally records publication
    before importing.  Conversely, once the committed manifest, render scene,
    readiness record, and modern-office graph audit are present, invoking the
    wizard again with ``--import`` only reopens the expensive Blender staging
    path.  Keep this check separate from ``_ready`` so generation recovery can
    still use the latter while completed seeds are removed from the monitor's
    pending set without any write.
    """
    import_root = REPO / "out" / "infinigen_imports" / f"kr_{seed}_office"
    manifest = import_root / "scene_manifest.json"
    if not manifest.is_file():
        return False
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(value.get("units"), list) or not value["units"]:
            return False
    except (OSError, json.JSONDecodeError):
        return False
    scene_root = REPO / "out" / "opticalnav" / "opticalnav-v0.2" / "scenes" / f"infinigen_office_{seed}"
    required = (
        scene_root / "render_scene.xml",
        scene_root / "render_readiness.json",
        scene_root / "viewpoint_graph.json",
        scene_root / "office_population_audit.json",
    )
    if not all(path.is_file() for path in required):
        return False
    try:
        readiness = json.loads(required[1].read_text(encoding="utf-8"))
        graph = json.loads(required[2].read_text(encoding="utf-8"))
        population_audit = json.loads(required[3].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    graph_audit = graph.get("metadata", {}).get("modern_office_graph_audit", {})
    return (
        readiness.get("ok") is True
        and population_audit.get("status") == "passed"
        and graph_audit.get("status") == "passed"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="20260822,20260823,20260824")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--hazard-report", type=Path, default=DEFAULT_REPORT,
                        help="atomic JSON report for restart counts and live hazards")
    parser.add_argument("--bake-pbr", action="store_true", default=True)
    parser.add_argument("--no-bake-pbr", dest="bake_pbr", action="store_false")
    args = parser.parse_args(argv)
    seeds = [seed.strip() for seed in args.seeds.split(",") if seed.strip()]
    if not seeds:
        parser.error("at least one seed is required")

    pending = list(seeds)
    terminal_failures: list[str] = []
    while pending:
        next_pending: list[str] = []
        report_rows: dict[str, dict] = {}
        for seed in pending:
            if _import_complete(seed):
                print(f"[office-import] seed={seed} import already complete; skipping re-import", flush=True)
                continue
            ready, reason = _ready(seed)
            if not ready:
                print(f"[office-import] seed={seed} {reason}", flush=True)
                value, _ = _state(seed)
                if value:
                    execution = value.get("execution") or {}
                    solver = value.get("solver") or {}
                    hazards = _hazards(value)
                    execution_all = _execution_summary(seed)
                    hazards = sorted(set(hazards + _disk_hazards([Path("/"), Path("/tmp")])))
                    report_rows[seed] = {
                        "status": value.get("status"),
                        "stage": value.get("stage"),
                        "current_attempt": value.get("current_attempt"),
                        "solver": solver,
                        "solver_log": _solver_log_progress(value),
                        "log_stage": _log_stage(value),
                        "population": _populate_progress(value),
                        "hazards": hazards,
                        "execution_current": execution,
                        "execution_aggregate": execution_all,
                        "heartbeat_at": value.get("heartbeat_at"),
                        "process": value.get("process") or {},
                        "process_check": _process_check(value),
                    }
                    population = _populate_progress(value)
                    solver_log = _solver_log_progress(value)
                    log_stage = _log_stage(value)
                    population_text = ""
                    if population:
                        population_text = (
                            f" population={population['completed']}/{population['total']}"
                            f" log_age={float(population['log_age_s']):.0f}s"
                        )
                    solver_log_text = ""
                    if solver_log:
                        solver_log_text = (
                            f" log_it={solver_log['iteration']}/{solver_log['total_iterations']}"
                            f" log_objects={solver_log['object_count']}"
                            f" log_violations={solver_log['violations']}"
                            f" log_age={float(solver_log['log_age_s']):.0f}s"
                        )
                    log_stage_text = ""
                    if log_stage:
                        log_stage_text = (
                            f" log_stage={log_stage['stage']}"
                            f" log_stage_age={float(log_stage['log_age_s']):.0f}s"
                        )
                    # The controller-owned state can legitimately lag while
                    # an orphaned generation child continues writing its
                    # append-only log.  Make the human-facing heartbeat use
                    # that live log stage/pass when available; retain the
                    # state fields in the structured report for provenance.
                    display_stage = (log_stage or {}).get("stage") or value.get("stage")
                    display_iteration = (
                        f"{solver_log['iteration']}/{solver_log['total_iterations']}"
                        if solver_log else
                        f"{solver.get('iteration')}/{solver.get('total_iterations')}"
                    )
                    print(
                        f"[office-import] seed={seed} restarts={max(0, int(execution.get('candidate_starts', 0)) - 1)} "
                        f"aggregate_restarts={execution_all['restarts']} "
                        f"starts={execution.get('candidate_starts', 0)} transient={execution.get('transient_retries', 0)} "
                        f"stage={display_stage} pass={solver.get('pass_index')} "
                        f"iteration={display_iteration} "
                        f"objects={solver.get('object_count')} eta_s={solver.get('iteration_eta_s')}"
                        f"{population_text} "
                        f"{solver_log_text} "
                        f"{log_stage_text} "
                        f"violations={solver.get('violations')} hazards={','.join(hazards) if hazards else 'none'}",
                        flush=True,
                    )
                if value and value.get("status") in {"generation_failed", "solver_stalled", "unsatisfied_solver", "audit_failed"}:
                    print(f"[office-import] seed={seed} will not import a failed generation", flush=True)
                    terminal_failures.append(seed)
                    continue
                if reason.startswith("generation process lost"):
                    print(f"[office-import] seed={seed} {reason}; leaving generation state untouched", flush=True)
                    terminal_failures.append(seed)
                    continue
                next_pending.append(seed)
                continue
            if _active_import_wizard(seed):
                # The wizard owns the normal generation -> import transition.
                # Keep polling so a later crash after publication can still be
                # recovered, but never launch a second importer concurrently.
                print(f"[office-import] seed={seed} published; active wizard owns import, waiting", flush=True)
                next_pending.append(seed)
                continue
            rc = _import(seed, bake_pbr=args.bake_pbr)
            if rc:
                print(f"[office-import] seed={seed} import failed rc={rc}; leaving it for explicit retry", flush=True)
                terminal_failures.append(seed)
            else:
                print(f"[office-import] seed={seed} import complete", flush=True)
        if report_rows:
            _write_report(args.hazard_report, report_rows)
        if next_pending:
            pending = next_pending
            time.sleep(max(1.0, args.poll_seconds))
    return 1 if terminal_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
