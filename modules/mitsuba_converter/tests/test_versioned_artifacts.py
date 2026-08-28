from __future__ import annotations

import json
from pathlib import Path

from mitsuba_converter.versioned_artifacts import (
    RenderLedger,
    read_task_event_log,
    new_render_version_id,
    resolve_current_bundle_dir,
    scene_version_id,
    versioned_bundle_dir,
    write_current_pointer,
)


def _run(tmp_path: Path):
    scene = tmp_path / "scene.xml"
    scene.write_text("<scene/>", encoding="utf-8")
    scene_id, digest = scene_version_id(tmp_path, scene_ref=scene)
    ledger = RenderLedger(tmp_path)
    ledger.create_scene_version(
        project_id="project", scene_id="scene",
        scene_version_id_value=scene_id, scene_digest=digest,
    )
    render_id = new_render_version_id(digest, now="2026-07-14T01:21:38.123+00:00")
    ledger.create_render_run(
        run_id="run-1", project_id="project", scene_id="scene",
        scene_version_id_value=scene_id, render_version_id=render_id,
    )
    return ledger, scene_id, digest, render_id


def test_scene_digest_changes_when_source_changes(tmp_path: Path):
    scene = tmp_path / "scene.xml"
    scene.write_text("a", encoding="utf-8")
    _sv1, d1 = scene_version_id(tmp_path, scene_ref=scene)
    scene.write_text("b", encoding="utf-8")
    _sv2, d2 = scene_version_id(tmp_path, scene_ref=scene)
    assert d1 != d2
    assert _sv1 != _sv2


def test_scene_digest_changes_when_material_policy_changes(tmp_path: Path):
    scene = tmp_path / "scene.xml"
    policy = tmp_path / "render_scene_material_policy.json"
    scene.write_text("<scene/>", encoding="utf-8")
    policy.write_text('{"surface":"carpet-a"}', encoding="utf-8")
    _sv1, d1 = scene_version_id(tmp_path, scene_ref=scene, extra_refs=(policy,))
    policy.write_text('{"surface":"carpet-b"}', encoding="utf-8")
    _sv2, d2 = scene_version_id(tmp_path, scene_ref=scene, extra_refs=(policy,))
    assert d1 != d2
    assert _sv1 != _sv2


def test_ledger_plan_blob_and_atomic_current_pointer(tmp_path: Path):
    ledger, scene_version, digest, render_id = _run(tmp_path)
    request = {"request_id": "rq", "job_id": "job", "extras": {"task_key": "tk"}}
    blob = ledger.put_request_blob(request)
    assert ledger.get_request_blob(blob) == request
    ledger.put_task(
        task_key_value="tk", run_id="run-1", render_version_id=render_id,
        variant="base", phase="rgb", phase_index=0, ordinal=0,
        node_id="vp_0001", heading_id="h_000", request_blob_digest=blob,
    )
    ledger.update_task("tk", state="succeeded", job_id="job", attempt_count=1)
    bundle = versioned_bundle_dir(
        tmp_path, scene_id="scene", render_version_id=render_id, variant="base",
        node_id="vp_0001", heading_id="h_000",
    )
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({"render_version_id": render_id}), encoding="utf-8")
    pointer = write_current_pointer(
        tmp_path, scene_id="scene", variant="base", node_id="vp_0001", heading_id="h_000",
        render_version_id=render_id, bundle_ref=bundle.relative_to(tmp_path).as_posix(),
        scene_version_id_value=scene_version,
    )
    assert pointer.name == "current.json"
    assert resolve_current_bundle_dir(
        tmp_path, scene_id="scene", variant="base", node_id="vp_0001", heading_id="h_000"
    ) == bundle
    assert not (tmp_path / "bridge_jobs").exists()
    promoted = ledger.promote_version(render_id)
    assert promoted["render_version_id"] == render_id
    assert ledger.list_versions(scene_id="scene")[0]["status"] == "active"


def test_run_operational_update_preserves_immutable_profile_metadata(tmp_path: Path):
    ledger, scene_version, _digest, render_id = _run(tmp_path)
    # Seed the record with the immutable capture identity that is written at
    # submission time, then emulate a later phase/plan status update.
    ledger.update_run(
        "run-1",
        status="planned",
        metadata={"render_profile_id": "rp_768_core", "scene_version_id": scene_version},
    )
    ledger.update_run("run-1", status="planned", metadata={"plan_total": 128})
    payload = ledger.run_payload("run-1")
    assert payload is not None
    assert payload["render_version_id"] == render_id
    assert payload["metadata"] == {
        "plan_total": 128,
        "render_profile_id": "rp_768_core",
        "scene_version_id": scene_version,
    }


def test_failed_staging_version_can_be_pruned_but_active_cannot(tmp_path: Path):
    ledger, _scene_version, digest, active_id = _run(tmp_path)
    ledger.update_render_version(active_id, status="active")
    try:
        ledger.prune_version(active_id)
    except ValueError:
        pass
    else:
        raise AssertionError("active version must not be prunable")
    staged_id = new_render_version_id(digest, now="2026-07-14T01:21:39.123+00:00")
    ledger.create_render_run(
        run_id="run-2", project_id="project", scene_id="scene",
        scene_version_id_value=_scene_version, render_version_id=staged_id,
    )
    assert ledger.prune_version(staged_id)["status"] == "pruned"


def test_batch_plan_and_complete_lookup(tmp_path: Path):
    ledger, _scene_version, _digest, render_id = _run(tmp_path)
    records = []
    for index in range(8):
        records.append({
            "task_key": f"task-{index}", "run_id": "run-1", "render_version_id": render_id,
            "variant": "base", "phase": "rgb", "phase_index": 0, "ordinal": index,
            "node_id": f"vp_{index:04d}", "heading_id": "h_000",
            "logical_task_key": f"logical-{index}", "metadata": {"index": index},
            "request_payload": {"request_id": str(index)},
        })
    ledger.put_tasks_batch(records)
    ledger.update_tasks_batch([{"task_key": "task-3", "state": "succeeded", "attempt_count": 1}])
    found = ledger.find_complete_tasks(scene_version_id_value=_scene_version, logical_task_keys=["logical-2", "logical-3"])
    assert list(found) == ["logical-3"]
    assert ledger.get_request_blob(found["logical-3"]["request_blob_digest"]) == {"request_id": "3"}


def test_invalid_legacy_skip_is_not_reusable(tmp_path: Path):
    ledger, scene_version, _digest, render_id = _run(tmp_path)
    ledger.put_tasks_batch([{
        "task_key": "false-skip", "run_id": "run-1", "render_version_id": render_id,
        "variant": "base", "phase": "rgb", "ordinal": 0,
        "node_id": "vp-1", "heading_id": "h-000", "logical_task_key": "logical-skip",
        "metadata": {"sensor_ids": ["rear-copy"], "skip_reason": "existing_observation"},
        "state": "skipped",
    }])

    assert ledger.find_complete_tasks(
        scene_version_id_value=scene_version,
        logical_task_keys=["logical-skip"],
    ) == {}
    assert ledger.scene_sensor_progress("scene")[0]["completed"] == 0


def test_atomic_runtime_events_update_attempts_and_terminal_run(tmp_path: Path):
    ledger, _scene_version, _digest, render_id = _run(tmp_path)
    ledger.put_tasks_batch([
        {
            "task_key": f"task-{index}", "run_id": "run-1", "render_version_id": render_id,
            "variant": "base", "phase": "rgb", "phase_index": 0, "ordinal": index,
            "node_id": f"vp_{index:04d}", "heading_id": "h_000",
            "request_payload": {"request_id": str(index)},
        }
        for index in range(2)
    ])
    events = [
        {
            "task_key": "task-0", "run_id": "run-1", "job_id": "job-0",
            "state": "running", "attempt_no": 1, "created_at": "2026-08-13T00:00:00+00:00",
        },
        {
            "task_key": "task-0", "run_id": "run-1", "job_id": "job-0",
            "state": "succeeded", "attempt_no": 1, "created_at": "2026-08-13T00:00:01+00:00",
        },
        {
            "task_key": "task-1", "run_id": "run-1", "job_id": "job-1",
            "state": "succeeded", "attempt_no": 1, "created_at": "2026-08-13T00:00:02+00:00",
        },
    ]
    ledger.apply_task_events_batch(events)
    # A cross-project writer retry may replay a project sub-batch after another
    # project's NFS commit failed. Runtime event keys make that replay idempotent.
    ledger.apply_task_events_batch(events)

    summary = ledger.run_summary("run-1")
    assert summary["status"] == "completed"
    assert summary["state_counts"]["succeeded"] == 2
    assert ledger.list_versions(scene_id="scene")[0]["status"] == "ready"
    with ledger.connection() as conn:
        attempt = conn.execute(
            "SELECT state, started_at, finished_at FROM render_attempts WHERE task_key='task-0'"
        ).fetchone()
        event_count = conn.execute(
            "SELECT COUNT(*) FROM render_events WHERE run_id='run-1'"
        ).fetchone()[0]
    assert tuple(attempt) == (
        "succeeded", "2026-08-13T00:00:00+00:00", "2026-08-13T00:00:01+00:00",
    )
    assert event_count == 3


def test_retry_failure_does_not_pause_run_between_attempts(tmp_path: Path):
    ledger, _scene_version, _digest, render_id = _run(tmp_path)
    ledger.put_tasks_batch([{
        "task_key": "task-0", "run_id": "run-1", "render_version_id": render_id,
        "variant": "base", "phase": "rgb", "phase_index": 0, "ordinal": 0,
        "node_id": "vp_0000", "heading_id": "h_000",
        "request_payload": {"request_id": "0"},
    }])
    ledger.apply_task_events_batch([{
        "task_key": "task-0", "run_id": "run-1", "job_id": "job-0",
        "state": "failed", "task_state": "running", "event_type": "retry_failed",
        "attempt_no": 1, "error": "temporary GPU failure",
    }])

    summary = ledger.run_summary("run-1")
    assert summary["status"] != "paused"
    assert summary["state_counts"] == {"running": 1}
    with ledger.connection() as conn:
        attempt_state = conn.execute(
            "SELECT state FROM render_attempts WHERE task_key='task-0' AND attempt_no=1"
        ).fetchone()[0]
    assert attempt_state == "failed"


def test_task_event_log_returns_bounded_versioned_job_lifecycle(tmp_path: Path):
    ledger, _scene_version, _digest, render_id = _run(tmp_path)
    ledger.put_tasks_batch([{
        "task_key": "task-log", "run_id": "run-1", "render_version_id": render_id,
        "variant": "perturbed", "phase": "per_view", "ordinal": 0,
        "node_id": "vp_0001", "heading_id": "h_330",
        "request_payload": {"request_id": "log"},
    }])
    ledger.apply_task_events_batch([
        {"task_key": "task-log", "run_id": "run-1", "job_id": "job-log", "state": "running", "attempt_no": 1},
        {
            "task_key": "task-log", "run_id": "run-1", "job_id": "job-log",
            "state": "failed", "attempt_no": 1, "error": "MitsubaVariantUnavailable",
        },
    ])

    payload = ledger.task_event_log("task-log")

    assert payload is not None
    assert payload["source"] == "render_ledger"
    assert payload["task"]["job_id"] == "job-log"
    assert [event["event_type"] for event in payload["events"]] == ["running", "failed"]
    assert "MitsubaVariantUnavailable" in payload["lines"][-1]


def test_read_task_event_log_uses_read_only_monitor_path_and_formats_progress(tmp_path: Path):
    ledger, _scene_version, _digest, render_id = _run(tmp_path)
    ledger.put_tasks_batch([{
        "task_key": "task-progress", "run_id": "run-1", "render_version_id": render_id,
        "variant": "base", "phase": "per_view", "ordinal": 0,
        "node_id": "vp_0001", "heading_id": "h_330",
        "request_payload": {"request_id": "progress"},
    }])
    ledger.apply_task_events_batch([{
        "task_key": "task-progress", "run_id": "run-1", "job_id": "job-progress",
        "state": "running", "task_state": "running", "event_type": "progress", "attempt_no": 1,
        "payload": {"stage": "rendering", "message": "pass 2/8"},
    }])

    payload = read_task_event_log(tmp_path, "task-progress")

    assert payload is not None
    assert payload["source"] == "render_ledger"
    assert "rendering: pass 2/8" in payload["lines"][-1]


def test_scene_sensor_progress_deduplicates_resumed_runs(tmp_path: Path):
    ledger, scene_version, _digest, render_id = _run(tmp_path)
    first_run = [
        {
            "task_key": f"first-{index}", "run_id": "run-1", "render_version_id": render_id,
            "variant": "base", "phase": "rgb", "ordinal": index,
            "node_id": f"vp-{index}", "heading_id": "h-000",
            "metadata": {"sensor_ids": ["rgb-cam"]},
            "state": "succeeded" if index == 0 else "planned",
        }
        for index in range(2)
    ]
    ledger.put_tasks_batch(first_run)
    ledger.create_render_run(
        run_id="run-2", project_id="project", scene_id="scene",
        scene_version_id_value=scene_version, render_version_id="render-2",
    )
    ledger.put_tasks_batch([
        {
            "task_key": f"second-{index}", "run_id": "run-2", "render_version_id": "render-2",
            "variant": "base", "phase": "rgb", "ordinal": index,
            "node_id": f"vp-{index}", "heading_id": "h-000",
            "metadata": {"sensor_ids": ["rgb-cam"]},
            "state": "succeeded" if index == 1 else "planned",
        }
        for index in range(2)
    ])

    progress = ledger.scene_sensor_progress("scene")

    assert progress == [{
        "scene_version_id": scene_version,
        "variant": "base",
        "sensor_id": "rgb-cam",
        "completed": 2,
        "running": 0,
        "queued": 0,
        "failed": 0,
        "total": 2,
        "fraction": 1.0,
    }]
