from __future__ import annotations

import json
from types import SimpleNamespace

from mitsuba_converter.render_daemon import RenderDaemon
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
