from __future__ import annotations

import json
from pathlib import Path

import monitor_office_v2_import as monitor


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_import_complete_requires_committed_graph_and_readiness(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(monitor, "REPO", tmp_path)
    imported = tmp_path / "out" / "infinigen_imports" / "kr_20260823_office"
    _write(imported / "scene_manifest.json", {"units": [{"id": "u0"}]})
    scene = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2" / "scenes" / "infinigen_office_20260823"
    (scene / "render_scene.xml").parent.mkdir(parents=True, exist_ok=True)
    (scene / "render_scene.xml").write_text("<scene/>", encoding="utf-8")
    _write(scene / "render_readiness.json", {"ok": True})
    _write(scene / "office_population_audit.json", {"status": "passed"})
    _write(scene / "viewpoint_graph.json", {"metadata": {"modern_office_graph_audit": {"status": "passed"}}})

    assert monitor._import_complete("20260823")

    (scene / "viewpoint_graph.json").write_text(
        json.dumps({"metadata": {"modern_office_graph_audit": {"status": "failed"}}}),
        encoding="utf-8",
    )
    assert not monitor._import_complete("20260823")


def test_solver_log_progress_reads_orphaned_child_heartbeat(tmp_path: Path):
    candidate = tmp_path / "attempts" / "attempt_01"
    candidate.mkdir(parents=True)
    (candidate / "generation.log").write_text(
        "[09:00:00.000] [annealing] [INFO] | it=17/300 dt=1.25 n=118 "
        "loss=0.0e+00 viol=0.0 temp=1.0 diff=0.0\n",
        encoding="utf-8",
    )
    value = {"process": {"candidate_dir": str(candidate)}}
    progress = monitor._solver_log_progress(value)
    assert progress is not None
    assert progress["iteration"] == 17
    assert progress["total_iterations"] == 300
    assert progress["object_count"] == 118
    assert progress["violations"] == 0.0


def test_solver_log_is_stale_when_population_follows(tmp_path: Path):
    candidate = tmp_path / "attempts" / "attempt_01"
    candidate.mkdir(parents=True)
    (candidate / "generation.log").write_text(
        "[09:00:00.000] [annealing] [INFO] | it=17/300 dt=1.25 n=118 "
        "loss=0.0e+00 viol=0.0 temp=1.0 diff=0.0\n"
        "[09:00:01.000] [populate] [INFO] | Populating 402/403 placeholder.name='x'\n",
        encoding="utf-8",
    )
    value = {"process": {"candidate_dir": str(candidate)}}
    progress = monitor._solver_log_progress(value)
    assert progress is not None
    assert progress["trailing_records"] is True
    assert float(progress["log_age_s"]) >= 901.0


def test_population_finished_marker_closes_final_asset(tmp_path: Path):
    candidate = tmp_path / "attempts" / "attempt_01"
    candidate.mkdir(parents=True)
    (candidate / "generation.log").write_text(
        "[09:00:00.000] [populate] [INFO] | Populating 402/403 placeholder.name='x'\n"
        "[09:15:00.000] [logging] [INFO] | [populate_assets] finished in 0:15:00\n",
        encoding="utf-8",
    )
    value = {"process": {"candidate_dir": str(candidate)}}
    progress = monitor._populate_progress(value)
    assert progress is not None
    assert progress["completed"] == 403
