from __future__ import annotations

import json
from pathlib import Path

from mitsuba_converter.versioned_artifacts import (
    RenderLedger,
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

