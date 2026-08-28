from __future__ import annotations

import json
from types import SimpleNamespace

from mitsuba_converter.render_daemon import RenderDaemon, _is_render_queue_proxy_path
from mitsuba_converter.versioned_artifacts import RenderLedger


def test_missing_only_does_not_use_other_camera_root_alias(tmp_path):
    project_dir = tmp_path / "opticalnav-v0.2"
    heading_dir = project_dir / "scenes" / "scene-1" / "observations" / "vp-1" / "h-000"
    (heading_dir / "sensors" / "other-camera").mkdir(parents=True)
    (heading_dir / "rgb.png").write_bytes(b"ambiguous-root-alias")
    (heading_dir / "sensors" / "other-camera" / "rgb.png").write_bytes(b"other")
    request = SimpleNamespace(
        camera_specs=[SimpleNamespace(camera_id="rear-copy")],
        sensor_specs=[], extras={}, job_id="job-base", frame_id="frame-1",
    )
    sweep_request = SimpleNamespace(
        request=request, node_id="vp-1", heading_id="h-000",
        modalities_by_sensor={"rear-copy": ["rgb"]},
    )
    daemon = RenderDaemon(repo_root=tmp_path)

    assert not daemon._opticalnav_sweep_output_exists(project_dir, "scene-1", sweep_request, ["rgb"])
    target = heading_dir / "sensors" / "rear-copy"
    target.mkdir()
    (target / "rgb.png").write_bytes(b"rear")
    assert daemon._opticalnav_sweep_output_exists(project_dir, "scene-1", sweep_request, ["rgb"])


def test_backend_proxy_routes_scene_local_render_progress_to_gpu_queue():
    prefix = "/api/opticalnav/projects/opticalnav-v0.2/scenes/infinigen_office_20260823"
    assert _is_render_queue_proxy_path("GET", f"{prefix}/graph-render-batches/batch-1")
    assert _is_render_queue_proxy_path("GET", f"{prefix}/render-runs/run-1")
    assert _is_render_queue_proxy_path("POST", f"{prefix}/render-runs/run-1/resume")
    assert _is_render_queue_proxy_path("GET", f"{prefix}/render-tasks/task-1/events")
    assert _is_render_queue_proxy_path("GET", f"{prefix}/render-coverage")
    assert _is_render_queue_proxy_path("POST", f"{prefix}/graph/sweep")
    assert not _is_render_queue_proxy_path("GET", f"{prefix}/authoring-map")
    assert not _is_render_queue_proxy_path("GET", "/api/opticalnav/projects/opticalnav-v0.2")


def test_legacy_project_summary_is_catalog_only_and_omits_episode_paths(tmp_path, monkeypatch):
    project_dir = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2"
    project_dir.mkdir(parents=True)
    # Deliberately include a large legacy split list.  A startup summary must
    # count it from the manifest, not scan its files or return every path.
    (project_dir / "dataset.json").write_text(json.dumps({
        "project_name": "opticalnav-v0.2",
        "episode_count": 4228,
        "splits": {"train": [f"episodes/train/e{i}.json" for i in range(4228)]},
        "scenes": ["scene-a", "scene-b"],
        "scene_artifacts": [{
            "scene_id": "scene-a",
            "authoring_map_ref": "scenes/scene-a/authoring_map.json",
            "viewpoint_graph_ref": "scenes/scene-a/viewpoint_graph.json",
        }],
    }), encoding="utf-8")
    daemon = RenderDaemon(repo_root=tmp_path)

    # A catalog request must not reach the old scene-summary/validation path.
    monkeypatch.setattr(daemon, "_compute_scene_summary", lambda *_args: (_ for _ in ()).throw(AssertionError("scene scan")))
    monkeypatch.setattr(daemon, "_cached_validation_report", lambda *_args: (_ for _ in ()).throw(AssertionError("validation scan")))
    summary = daemon._opticalnav_project_summary(project_dir)

    assert summary["catalog_status"] == "legacy_manifest_catalog"
    assert summary["episode_count"] == 4228
    assert summary["split_counts"] == {"train": 4228}
    assert [scene["scene_id"] for scene in summary["scenes"]] == ["scene-a", "scene-b"]
    assert summary["scenes"][0]["authoring_map_exists"] is True
    assert "splits" not in summary["dataset"]

    picker_row = daemon._opticalnav_project_list_entry(project_dir)
    assert picker_row["scene_count"] == 2
    assert picker_row["episode_count"] == 4228
    assert "scenes" not in picker_row


def test_legacy_catalog_includes_new_scene_directory_without_scanning_its_contents(tmp_path):
    project_dir = tmp_path / "opticalnav-v0.2"
    project_dir.mkdir(parents=True)
    (project_dir / "dataset.json").write_text(json.dumps({
        "project_name": "opticalnav-v0.2",
        "scenes": ["catalogued-scene"],
    }), encoding="utf-8")
    imported = project_dir / "scenes" / "infinigen_office_20260823"
    imported.mkdir(parents=True)
    # An invalid nested file proves the picker only uses the directory name.
    (imported / "viewpoint_graph.json").write_text("not JSON", encoding="utf-8")

    summary = RenderDaemon(repo_root=tmp_path)._opticalnav_project_summary(project_dir)

    assert [row["scene_id"] for row in summary["scenes"]] == [
        "catalogued-scene", "infinigen_office_20260823",
    ]
    imported_row = summary["scenes"][1]
    assert imported_row["catalog_source"] == "legacy_manifest"
    assert imported_row["authoring_map_ref"] is None


def test_completed_ledger_wins_when_memory_only_contains_rendered_jobs(tmp_path):
    project_dir = tmp_path / "opticalnav-v0.2"
    batch_id = "batch-missing-only"
    batch_dir = project_dir / "graph_render_batches"
    batch_dir.mkdir(parents=True)
    (batch_dir / f"{batch_id}.json").write_text(
        json.dumps({
            "batch_id": batch_id,
            "project_id": project_dir.name,
            "scene_id": "scene-1",
            "status": "ready",
            "plan_total": 2,
            "requested_jobs": 2,
            "skipped_existing": 1,
            "jobs": [{"job_id": "job-rendered", "task_key": "task-rendered"}],
        }),
        encoding="utf-8",
    )

    ledger = RenderLedger(project_dir)
    ledger.create_scene_version(
        project_id=project_dir.name,
        scene_id="scene-1",
        scene_version_id_value="scene-version-1",
        scene_digest="digest-1",
    )
    ledger.create_render_run(
        run_id=batch_id,
        project_id=project_dir.name,
        scene_id="scene-1",
        scene_version_id_value="scene-version-1",
        render_version_id="render-version-1",
    )
    ledger.put_tasks_batch([
        {
            "task_key": "task-skipped",
            "run_id": batch_id,
            "render_version_id": "render-version-1",
            "variant": "base",
            "phase": "rgb",
            "phase_index": 0,
            "ordinal": 0,
            "node_id": "vp-1",
            "heading_id": "h-000",
            "state": "skipped",
            "request_payload": {"request_id": "request-skipped"},
        },
        {
            "task_key": "task-rendered",
            "run_id": batch_id,
            "render_version_id": "render-version-1",
            "variant": "base",
            "phase": "polar",
            "phase_index": 1,
            "ordinal": 1,
            "node_id": "vp-1",
            "heading_id": "h-000",
            "request_payload": {"request_id": "request-rendered"},
        },
    ])
    ledger.update_tasks_batch([
        {"task_key": "task-rendered", "state": "succeeded", "job_id": "job-rendered", "attempt_count": 1},
    ])

    daemon = RenderDaemon(repo_root=tmp_path)
    daemon._jobs["job-rendered"] = SimpleNamespace(status=SimpleNamespace(status="succeeded"))

    summary = daemon._opticalnav_graph_batch_summary(project_dir, batch_id)

    assert summary["status"] == "completed"
    assert summary["ledger_status"] == "completed"
    assert summary["counts"] == {
        "queued": 0,
        "running": 0,
        "completed": 2,
        "failed": 0,
        "cancelled": 0,
        "unknown": 0,
    }
    assert summary["ledger_counts"] == {"skipped": 1, "succeeded": 1}
    assert summary["progress"] == {
        "completed": 2,
        "failed": 0,
        "total": 2,
        "fraction": 1.0,
    }


def test_ledger_summary_wins_over_stale_memory_for_full_job_list(tmp_path):
    project_dir = tmp_path / "opticalnav-v0.2"
    batch_id = "batch-stale-memory"
    batch_dir = project_dir / "graph_render_batches"
    batch_dir.mkdir(parents=True)
    (batch_dir / f"{batch_id}.json").write_text(
        json.dumps({
            "batch_id": batch_id,
            "project_id": project_dir.name,
            "scene_id": "scene-1",
            "status": "ready",
            "plan_total": 2,
            "jobs": [
                {"job_id": "job-a", "task_key": "task-a"},
                {"job_id": "job-b", "task_key": "task-b"},
            ],
        }),
        encoding="utf-8",
    )
    ledger = RenderLedger(project_dir)
    ledger.create_scene_version(
        project_id=project_dir.name, scene_id="scene-1",
        scene_version_id_value="scene-version-1", scene_digest="digest-1",
    )
    ledger.create_render_run(
        run_id=batch_id, project_id=project_dir.name, scene_id="scene-1",
        scene_version_id_value="scene-version-1", render_version_id="render-version-1",
    )
    ledger.put_tasks_batch([
        {"task_key": "task-a", "run_id": batch_id, "render_version_id": "render-version-1", "variant": "base", "phase": "per_view", "ordinal": 0, "node_id": "vp-a", "heading_id": "h-000", "state": "succeeded"},
        {"task_key": "task-b", "run_id": batch_id, "render_version_id": "render-version-1", "variant": "base", "phase": "per_view", "ordinal": 1, "node_id": "vp-b", "heading_id": "h-000", "state": "succeeded"},
    ])
    ledger.update_tasks_batch([
        {"task_key": "task-a", "state": "succeeded", "job_id": "job-a", "attempt_count": 1},
        {"task_key": "task-b", "state": "succeeded", "job_id": "job-b", "attempt_count": 1},
    ])
    daemon = RenderDaemon(repo_root=tmp_path)
    daemon._jobs["job-a"] = SimpleNamespace(status=SimpleNamespace(status="queued"))
    daemon._jobs["job-b"] = SimpleNamespace(status=SimpleNamespace(status="queued"))

    summary = daemon._opticalnav_graph_batch_summary(project_dir, batch_id)

    assert summary["ledger_status"] == "completed"
    assert summary["counts"]["completed"] == 2
    assert summary["counts"]["queued"] == 0
    assert summary["counts"]["unknown"] == 0


def test_bounded_admission_summary_includes_not_yet_persisted_plan(tmp_path):
    """The large-sweep monitor stays truthful before every task is admitted."""
    project_dir = tmp_path / "opticalnav-v0.2"
    batch_id = "batch-windowed"
    batch_dir = project_dir / "graph_render_batches"
    batch_dir.mkdir(parents=True)
    (batch_dir / f"{batch_id}.json").write_text(
        json.dumps({
            "batch_id": batch_id,
            "project_id": project_dir.name,
            "scene_id": "scene-1",
            "status": "submitting",
            "plan_total": 4,
            "jobs": [],
        }),
        encoding="utf-8",
    )
    ledger = RenderLedger(project_dir)
    ledger.create_scene_version(
        project_id=project_dir.name, scene_id="scene-1",
        scene_version_id_value="scene-version-1", scene_digest="digest-1",
    )
    ledger.create_render_run(
        run_id=batch_id, project_id=project_dir.name, scene_id="scene-1",
        scene_version_id_value="scene-version-1", render_version_id="render-version-1",
    )
    ledger.put_tasks_batch([
        {"task_key": "task-done", "run_id": batch_id, "render_version_id": "render-version-1", "variant": "base", "phase": "per_view", "ordinal": 0, "node_id": "vp-a", "heading_id": "h-000", "state": "succeeded"},
        {"task_key": "task-live", "run_id": batch_id, "render_version_id": "render-version-1", "variant": "base", "phase": "per_view", "ordinal": 1, "node_id": "vp-b", "heading_id": "h-000", "state": "running"},
    ])

    summary = RenderDaemon(repo_root=tmp_path)._opticalnav_graph_batch_summary(project_dir, batch_id)

    assert summary["status"] == "submitting"
    assert summary["counts"] == {
        "queued": 2, "running": 1, "completed": 1,
        "failed": 0, "cancelled": 0, "unknown": 0,
    }
    assert summary["progress"] == {
        "completed": 1, "failed": 0, "total": 4, "fraction": 0.25,
    }


def test_ledger_summary_exposes_bounded_failed_task_diagnostics(tmp_path):
    project_dir = tmp_path / "opticalnav-v0.2"
    batch_id = "batch-diagnostics"
    batch_dir = project_dir / "graph_render_batches"
    batch_dir.mkdir(parents=True)
    (batch_dir / f"{batch_id}.json").write_text(
        json.dumps({
            "batch_id": batch_id,
            "project_id": project_dir.name,
            "scene_id": "scene-1",
            "plan_total": 2,
            "jobs": [{"job_id": "job-failed", "task_key": "task-failed"}],
        }),
        encoding="utf-8",
    )
    ledger = RenderLedger(project_dir)
    ledger.create_scene_version(
        project_id=project_dir.name, scene_id="scene-1",
        scene_version_id_value="scene-version-1", scene_digest="digest-1",
    )
    ledger.create_render_run(
        run_id=batch_id, project_id=project_dir.name, scene_id="scene-1",
        scene_version_id_value="scene-version-1", render_version_id="render-version-1",
    )
    ledger.put_tasks_batch([
        {"task_key": "task-failed", "run_id": batch_id, "render_version_id": "render-version-1", "variant": "perturbed_active_polar", "phase": "per_view", "ordinal": 0, "node_id": "vp-55", "heading_id": "h-330"},
        {"task_key": "task-running", "run_id": batch_id, "render_version_id": "render-version-1", "variant": "perturbed_active_polar", "phase": "per_view", "ordinal": 1, "node_id": "vp-54", "heading_id": "h-330"},
    ])
    ledger.update_tasks_batch([
        {"task_key": "task-failed", "state": "failed", "job_id": "job-failed", "attempt_count": 1, "error": "worker assigned but never started (120s); rc=-9"},
        {"task_key": "task-running", "state": "running", "job_id": "job-running", "attempt_count": 1},
    ])

    summary = RenderDaemon(repo_root=tmp_path)._opticalnav_graph_batch_summary(project_dir, batch_id)

    assert summary["jobs"] == []
    assert summary["counts"]["failed"] == 1
    assert [job["job_id"] for job in summary["diagnostic_jobs"]] == ["job-failed", "job-running"]
    assert summary["diagnostic_jobs"][0]["status"] == {
        "status": "failed",
        "progress_stage": "failed",
        "error": "worker assigned but never started (120s); rc=-9",
    }
    assert summary["diagnostic_jobs"][0]["node_id"] == "vp-55"
