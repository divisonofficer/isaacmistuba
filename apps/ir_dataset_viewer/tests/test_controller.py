from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from apps.ir_dataset_viewer.backend.controller import (
    ROOM_TYPES, STAGE2_COMPILER_VERSION, ControllerJob, IRDatasetController, _atomic_json,
)


def _controller(tmp_path: Path) -> IRDatasetController:
    controller = IRDatasetController(
        repo_root=tmp_path / "repo", work_root=tmp_path / "work", bean_root=tmp_path / "bean"
    )
    controller.data_root = tmp_path / "generated"
    controller.scene_root = tmp_path / "scenes"
    return controller


def test_quality_rejected_scene_is_hidden_but_history_remains_queryable(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    rejected = ControllerJob(
        job_id="rejected-scene",
        status="failed",
        stage="scene_content_audit",
        error="scene content audit failed: forbidden_room_content",
        request={"dataset_name": "bad_room", "scene_id": "bad_room"},
    )
    resumable = ControllerJob(
        job_id="recoverable-timeout",
        status="interrupted",
        stage="geometry",
        error="geometry exceeded 3600s; preserving checkpoints",
        request={"dataset_name": "large_room", "scene_id": "large_room"},
    )
    with controller._lock:
        controller._jobs[rejected.job_id] = rejected
        controller._jobs[resumable.job_id] = resumable
        controller._save(rejected, "failed")
        controller._save(resumable, "interrupted")
        assert controller._unrecoverable_reason(rejected)
        controller.set_job_visibility(rejected.job_id, hidden=True)
        visible = controller.list_jobs()
        all_jobs = controller.list_jobs(include_hidden=True)
    assert [row["job_id"] for row in visible["jobs"]] == [resumable.job_id]
    assert all_jobs["hidden_job_count"] == 1
    archived = next(row for row in all_jobs["jobs"] if row["job_id"] == rejected.job_id)
    assert archived["hidden_from_ui"] is True
    assert archived["hidden_reason"]


def test_waiting_gpu_stage_is_requeued_not_interrupted_on_controller_restart(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    waiting = ControllerJob(
        job_id="waiting-gpu-restart",
        status="running",
        stage="qc_render",
        resource_class="gpu_render",
        resource_state="waiting_gpu",
        desired_gpu_indices=[3],
        request={"dataset_name": "waiting_scene", "gpu_indices": [3]},
    )
    with controller._lock:
        controller._save(waiting, "resource_waiting")
        controller._jobs.clear()
        controller._queue.clear()
        controller._restore()
        restored = controller._jobs[waiting.job_id]
        assert restored.status == "queued"
        assert restored.stage == "queued"
        assert restored.error is None
        assert restored.resource_state == "pending"
        assert restored.desired_gpu_indices == []
        assert waiting.job_id in controller._queue


def test_running_ready_stage_without_child_is_requeued_on_controller_restart(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    ready = ControllerJob(
        job_id="ready-restart", status="running", stage="ready",
        resource_class="cpu_light", resource_state="pending",
        request={"dataset_name": "ready_scene"},
    )
    with controller._lock:
        controller._save(ready, "stage_ready")
        controller._jobs.clear()
        controller._queue.clear()
        controller._restore()
        restored = controller._jobs[ready.job_id]
        assert restored.status == "queued"
        assert restored.stage == "queued"
        assert restored.error is None
        assert ready.job_id in controller._queue


def test_completed_render_marker_is_requeued_for_verify_on_controller_restart(tmp_path: Path) -> None:
    """A queue that finished while the controller was down is not interrupted."""
    controller = _controller(tmp_path)
    dataset = tmp_path / "work" / "completed-render"
    dataset.mkdir(parents=True)
    _atomic_json(dataset / "rolling_queue_state.json", {
        "frame_count": 2, "completed": ["vp_000001", "vp_000002"], "pending": [], "failed": {},
    })
    finished = ControllerJob(
        job_id="completed-render-restart", status="running", stage="full_render",
        resource_class="gpu_render", resource_state="running", pid=99999,
        request={"dataset_name": "completed-render", "paths": {"dataset": str(dataset)}},
    )
    with controller._lock:
        controller._save(finished, "process_started")
        controller._jobs.clear()
        controller._queue.clear()
        controller._restore()
        restored = controller._jobs[finished.job_id]
        assert restored.status == "queued"
        assert restored.stage == "queued"
        assert restored.stage_results["full_render"]["status"] == "succeeded"
        assert restored.error is None
        assert finished.job_id in controller._queue


def test_external_adoption_rejects_reused_pid_with_different_command(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    process = subprocess.Popen(["/bin/sleep", "5"])
    try:
        job = ControllerJob(job_id="pid-identity", request={}, pid=process.pid,
                            current_command=["/bin/sleep", "5"])
        # Give the child one scheduling quantum to cross exec() on overloaded
        # CI workers before inspecting /proc.
        for _ in range(20):
            if controller._external_pids(job) == [process.pid]:
                break
            time.sleep(0.01)
        assert controller._external_pids(job) == [process.pid]
        job.current_command = ["/bin/sleep", "6"]
        assert controller._external_pids(job) == []
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_controller_atomic_snapshot_allows_concurrent_saves(tmp_path: Path) -> None:
    target = tmp_path / "job.json"
    errors: list[Exception] = []

    def write(index: int) -> None:
        try:
            for sequence in range(20):
                _atomic_json(target, {"writer": index, "sequence": sequence})
        except Exception as exc:  # pragma: no cover - assertion reports the actual race
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert set(json.loads(target.read_text())) == {"writer", "sequence"}
    assert not list(tmp_path.glob(".*.tmp"))


def test_submit_resolves_deferred_seed_and_builds_safe_commands(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    # Hold the runner lock so its background thread cannot consume this test job.
    with controller._lock:
        job = controller.submit({
            "source_mode": "generate", "dataset_name": "kitchen_v2",
            "gpu_indices": [2, 0, 2], "archetype": "single_room", "room_type": "kitchen",
            "density": "normal_lived_in", "generation_stage": "full", "seed": "today",
        })
        current = controller._jobs[job["job_id"]]
        assert current.request["seed"].isdigit() and len(current.request["seed"]) == 8
        assert current.request["scene_id"] == f"infinigen_single_room_kitchen_{current.request['seed']}_v00"
        assert current.request["effective_scene_seed"].isdigit()
        assert current.request["graph_max_nodes"] == 70
        assert current.request["graph_heading_count"] == 24
        assert current.request["graph_min_node_spacing"] == 0.25
        assert current.request["gpu_indices"] == list(range(8))
        assert current.request["requested_gpu_indices"] == [0, 2]
        assert current.request["pipeline_revision"] == "ir-content-aware-v2"
        assert current.request["import_profile"] == "ir-bootstrap-v1"
        assert current.request["nir_passive"] is True
        assert "--nir-passive" in controller._command(current, "full_render")
        assert "scene_content_audit" in controller._pipeline(current)
        assert "view_probe" in controller._pipeline(current)
        assert "dataset_utility_audit" in controller._pipeline(current)
        assert controller._command(current, "view_probe")[1] == "apps/probe_ir_candidate_visibility.py"
        assert "today" not in controller._command(current, "generate")
        generate_command = controller._command(current, "generate")
        assert generate_command[generate_command.index("--ir-material-profile") + 1] == "principled_rich_v1"
        graph_command = controller._command(current, "navigation_compile")
        assert graph_command[graph_command.index("--max-nodes") + 1] == "70"
        assert graph_command[graph_command.index("--heading-count") + 1] == "24"
        assert str(controller.data_root) in current.request["existing_output"]
        assert controller._command(current, "geometry")[:2] == ["python3", "apps/build_ir_geometry_profile.py"]
        controller.cancel_job(current.job_id)


def test_unrendered_legacy_job_upgrades_to_reference_subset_plan(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    qc = tmp_path / "qc"
    dataset = tmp_path / "dataset"
    job = ControllerJob(
        job_id="legacy-unrendered",
        status="queued",
        stage="geometry",
        request={
            "illumination_diversity": True,
            "paired_fraction": .25,
            "paths": {"qc": str(qc), "dataset": str(dataset)},
        },
        stage_results={"view_plan": {"status": "succeeded"}, "geometry": {"status": "succeeded"}},
    )
    controller._upgrade_unrendered_illumination_plan(job)
    assert job.request["illumination_pairing_policy"] == "reference_subset_v2"
    assert job.request["paired_fraction"] == .20
    assert "view_plan" not in job.stage_results
    assert job.stage_results["geometry"]["status"] == "succeeded"


def test_rendered_legacy_job_is_not_implicitly_replanned(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    qc = tmp_path / "qc"
    (qc / "frames").mkdir(parents=True)
    (qc / "frames" / "vp_000001.json").write_text("{}", encoding="utf-8")
    job = ControllerJob(
        job_id="legacy-rendered",
        status="interrupted",
        stage="principled_prepare",
        request={
            "illumination_diversity": True,
            "paired_fraction": .25,
            "paths": {"qc": str(qc), "dataset": str(tmp_path / "dataset")},
        },
        stage_results={"view_plan": {"status": "succeeded"}},
    )
    controller._upgrade_unrendered_illumination_plan(job)
    assert "illumination_pairing_policy" not in job.request
    assert job.stage_results["view_plan"]["status"] == "succeeded"


def test_spatial_coverage_metallic_is_a_qc_diagnostic_not_a_hard_failure(tmp_path: Path) -> None:
    """A texture-driven coverage blend is valid Principled GT.

    Uniform fractional metalness is rejected earlier by the material contract;
    this test protects the distinct spatial-texture path from being rejected
    merely because bilinear filtering produces intermediate pixels.
    """
    controller = _controller(tmp_path)
    root = tmp_path / "qc"
    root.mkdir()
    paths = {
        "metallic": "metallic.png", "gt_defined_mask": "defined.png",
        "replacement_mask": "replacement.png", "fallback_mask": "fallback.png",
        "material_id": "material_id.png", "roughness": "roughness.png",
        "base_color_rgb": "base.png", "normal_shading_world": "normal.png",
        "metallic_family_id": "family.png", "exposed_metal_mask": "exposed.png",
    }
    shape = (6, 6)
    assert cv2.imwrite(str(root / paths["metallic"]), np.full(shape, 32768, np.uint16))
    for key in ("gt_defined_mask",):
        assert cv2.imwrite(str(root / paths[key]), np.full(shape, 255, np.uint8))
    for key in ("replacement_mask", "fallback_mask", "exposed_metal_mask"):
        assert cv2.imwrite(str(root / paths[key]), np.zeros(shape, np.uint8))
    assert cv2.imwrite(str(root / paths["material_id"]), np.ones(shape, np.uint16))
    assert cv2.imwrite(str(root / paths["roughness"]), np.full(shape, 32768, np.uint16))
    assert cv2.imwrite(str(root / paths["base_color_rgb"]), np.full((*shape, 3), 32768, np.uint16))
    assert cv2.imwrite(str(root / paths["normal_shading_world"]), np.full((*shape, 3), 32768, np.uint16))
    assert cv2.imwrite(str(root / paths["metallic_family_id"]), np.full(shape, 2, np.uint8))

    report = controller._material_visibility_qc(
        root, [{"frame_id": "f", "paths": paths}],
        job=ControllerJob(job_id="coverage", request={"ir_composition_profile": "inverse_rendering_showcase_v1"}),
    )

    assert report["status"] == "passed"
    assert report["physical_failures"] == []
    assert "coverage_mixed_continuous_approximation" in report["diagnostic_findings"]


def test_passive_backfill_is_a_gpu_queued_job_and_preserves_target_dataset(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    dataset = controller.work_root / "completed_scene"
    prepared = controller.pipeline_root / "completed_scene" / "principled_stage2"
    dataset.mkdir(parents=True)
    prepared.mkdir(parents=True)
    (dataset / "index.jsonl").write_text("{\"frame_id\": \"vp_000001\"}\n", encoding="utf-8")
    _atomic_json(dataset / "dataset_config.json", {"schema": "robomituba.ir_principled_dataset.v2"})
    _atomic_json(dataset / "rolling_queue_state.json", {
        "schema": "robomituba.ir_principled_rolling_queue.v1",
        "frame_count": 1, "completed": ["vp_000001"], "pending": [], "failed": {},
    })
    (prepared / "derived_ir_principled_v1.blend").write_bytes(b"fixture")
    _atomic_json(prepared / "principled_material_contract.json", {"schema": "fixture"})
    with controller._lock:
        submitted = controller.submit({
            "source_mode": "nir_passive_backfill", "dataset_name": "backfill_completed_scene",
            "backfill_dataset": str(dataset), "prepared_scene_dir": str(prepared),
            "gpu_indices": [3], "backfill_limit": 1, "priority": 5,
        })
        job = controller._jobs[submitted["job_id"]]
        assert controller._pipeline(job) == ["nir_passive_backfill"]
        assert controller._resource_class("nir_passive_backfill") == "gpu_render"
        job.resource_gpu_indices = [3]
        command = controller._command(job, "nir_passive_backfill")
        assert command[:2] == ["python3", "apps/backfill_ir_nir_passive.py"]
        assert command[command.index("--dataset") + 1] == str(dataset)
        assert command[command.index("--prepared-scene-dir") + 1] == str(prepared)
        assert command[command.index("--gpu-index") + 1] == "3"
        assert command[command.index("--limit") + 1] == "1"
        assert job.request["paths"]["dataset"] == str(dataset)
        controller.cancel_job(job.job_id)


def test_regular_render_pipeline_does_not_schedule_redundant_passive_backfill(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    regular = ControllerJob(
        job_id="regular-passive", request={
            "source_mode": "generate", "nir_passive": True,
            "pipeline_revision": "ir-content-aware-v2",
        },
    )
    assert "nir_passive_backfill" not in controller._pipeline(regular)
    retrofit = ControllerJob(job_id="retrofit-passive", request={"source_mode": "nir_passive_backfill"})
    assert controller._pipeline(retrofit) == ["nir_passive_backfill"]


def test_passive_backfill_smoke_allows_unbounded_followup(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    dataset = controller.work_root / "completed_scene"
    prepared = controller.pipeline_root / "completed_scene" / "principled_stage2"
    dataset.mkdir(parents=True)
    prepared.mkdir(parents=True)
    (dataset / "index.jsonl").write_text('{"frame_id": "vp_000001"}\n', encoding="utf-8")
    _atomic_json(dataset / "dataset_config.json", {"schema": "robomituba.ir_principled_dataset.v2"})
    _atomic_json(dataset / "rolling_queue_state.json", {
        "schema": "robomituba.ir_principled_rolling_queue.v1",
        "frame_count": 1, "completed": ["vp_000001"], "pending": [], "failed": {},
    })
    (prepared / "derived_ir_principled_v1.blend").write_bytes(b"fixture")
    _atomic_json(prepared / "principled_material_contract.json", {"schema": "fixture"})
    with controller._lock:
        smoke = controller.submit({
            "source_mode": "nir_passive_backfill", "dataset_name": "backfill_smoke",
            "backfill_dataset": str(dataset), "prepared_scene_dir": str(prepared),
            "gpu_indices": [0], "backfill_limit": 1,
        })
        smoke_job = controller._jobs[smoke["job_id"]]
        smoke_job.status = "succeeded"
        _atomic_json(dataset / ".nir_passive_backfill" / "state.json", {
            "status": "partial", "partial_run": True, "remaining": 1,
        })
        followup = controller.submit({
            "source_mode": "nir_passive_backfill", "dataset_name": "backfill_full",
            "backfill_dataset": str(dataset), "prepared_scene_dir": str(prepared),
            "gpu_indices": [0],
        })
        assert followup["request"]["backfill_limit"] is None
        controller.cancel_job(smoke_job.job_id)
        controller.cancel_job(followup["job_id"])


def test_adopted_passive_backfill_exit_is_recognized_as_completed(tmp_path: Path) -> None:
    """A clean CLI exit must not be downgraded to ``interrupted`` by the watcher."""
    controller = _controller(tmp_path)
    state_path = tmp_path / "dataset" / ".nir_passive_backfill" / "state.json"
    state_path.parent.mkdir(parents=True)
    _atomic_json(state_path, {"status": "succeeded", "completed": ["vp_000001"], "failed": {}})
    job = ControllerJob(
        job_id="adopted-backfill",
        stage="nir_passive_backfill",
        status="running",
        request={"paths": {"backfill_state": str(state_path)}},
    )
    assert controller._external_stage_completed(job)
    _atomic_json(state_path, {"status": "partial", "completed": ["vp_000001"], "failed": {}})
    assert not controller._external_stage_completed(job)
    job.request["backfill_limit"] = 1
    assert controller._external_stage_completed(job)
    _atomic_json(state_path, {"status": "succeeded", "completed": [], "failed": {"vp_2": "bad"}})
    assert not controller._external_stage_completed(job)


def test_adopted_passive_backfill_never_reserves_extra_idle_gpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller(tmp_path)
    dataset = tmp_path / "dataset"; dataset.mkdir()
    with controller._lock:
        backfill = ControllerJob(
            job_id="backfill", status="running", stage="nir_passive_backfill",
            resource_class="gpu_render", external_adopted=True, pid=123,
            resource_gpu_indices=[5], desired_gpu_indices=[0, 3, 5, 7],
            request={"gpu_indices": list(range(8)), "paths": {"dataset": str(dataset)}},
        )
        waiting = ControllerJob(
            job_id="waiting", request={"gpu_indices": list(range(8))},
            created_at="2026-08-14T00:00:01Z",
        )
        for job in (backfill, waiting):
            job.eligible_gpu_indices = controller._eligible_gpus(job)
            controller._jobs[job.job_id] = job
        monkeypatch.setattr(controller, "_pid_alive", lambda pid: bool(pid == 123))
        controller._sync_render_worker_state()
        assert backfill.desired_gpu_indices == [5]
        controller._rebalance_gpu_targets([(waiting, "qc_render")])
        assert backfill.desired_gpu_indices == [5]
        assert 5 not in waiting.desired_gpu_indices


def test_research_balanced_uses_rich_defaults_and_isolated_attempt_paths(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        submitted = controller.submit({
            "source_mode": "generate", "dataset_name": "metal_room", "gpu_indices": [0],
            "archetype": "single_room", "room_type": "kitchen", "seed": "20260818",
            "density": "normal_lived_in", "anchor_richness": "balanced", "surface_clutter": "low",
            "content_profile": "research_balanced",
        })
        job = controller._jobs[submitted["job_id"]]
        assert job.request["density"] == "family_home"
        assert job.request["anchor_richness"] == "rich"
        assert job.request["surface_clutter"] == "rich"
        assert job.request["ir_composition_profile"] == "inverse_rendering_showcase_v1"
        assert "showcase_composition" in controller._pipeline(job)
        assert "showcase_raster_probe" in controller._pipeline(job)
        assert "showcase_acceptance" in controller._pipeline(job)
        assert controller._command(job, "showcase_composition")[1] == "apps/compose_infinigen_ir_showcase.py"
        composition = controller._command(job, "showcase_composition")
        assert composition[composition.index("--source-blend") + 1].endswith("/full/scene.blend")
        assert controller._command(job, "import")[2] == job.request["paths"]["showcase_blend"]
        audit = controller._command(job, "scene_content_audit")
        assert audit[audit.index("--source-blend") + 1] == job.request["paths"]["showcase_blend"]
        geometry = controller._command(job, "geometry")
        assert geometry[geometry.index("--source-blend") + 1] == job.request["paths"]["showcase_blend"]
        assert "--import-name" in controller._command(job, "import")
        assert controller._import_dir(job.request).name == job.request["showcase_import_name"]
        assert "/attempts/v00/" in job.request["paths"]["geometry"]
        assert "scene_quality_gate" in controller._pipeline(job)
        assert "material_mix_audit" in controller._pipeline(job)
        before = job.request["effective_scene_seed"]
        assert controller._next_quality_variation(job, failed_stage="scene_quality_gate", error="fixture") is True
        assert job.request["variation_id"] == 1
        assert job.request["effective_scene_seed"] != before
        assert job.request["scene_id"].endswith("_v01")
        assert "/attempts/v01/" in job.request["paths"]["prepared"]
        assert job.request["quality_attempts"][0]["failed_stage"] == "scene_quality_gate"
        controller.cancel_job(job.job_id)


def test_same_seed_placement_profiles_have_isolated_sources_and_commands(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    jobs = []
    with controller._lock:
        for profile in ("legacy_clutter_v1", "upstream_residential_v1", "collision_aware_clutter_v1"):
            submitted = controller.submit({
                "source_mode": "generate", "dataset_name": f"pilot_{profile}", "gpu_indices": [0],
                "archetype": "single_room", "room_type": "kitchen", "seed": "20260828",
                "placement_profile": profile,
            })
            job = controller._jobs[submitted["job_id"]]
            jobs.append(job)
            command = controller._command(job, "generate")
            assert command[command.index("--placement-profile") + 1] == profile
        assert len({job.request["effective_scene_seed"] for job in jobs}) == 1
        assert len({job.request["existing_output"] for job in jobs}) == 3
        assert len({job.request["scene_id"] for job in jobs}) == 3
        for job in jobs:
            controller.cancel_job(job.job_id)


def test_scene_quality_gate_reads_showcase_probe_visibility(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    content = tmp_path / "content.json"
    plan = tmp_path / "plan.json"
    quality = tmp_path / "quality.json"
    _atomic_json(content, {
        "status": "passed", "nonstructural_object_count": 30,
        "room_footprint": {"area_m2": 5.0},
    })
    _atomic_json(plan, {"groups": [{"poses": [{
        "probe": {"visible_pbr_object_count": 12, "visible_object_ids": ["a", "b"]},
    }]}]})
    job = ControllerJob(job_id="showcase-quality", request={
        "paths": {"content_audit": str(content), "render_plan": str(plan),
                  "scene_quality": str(quality)},
        "variation_id": 0, "logical_seed": "20260821", "effective_scene_seed": "1",
    })
    controller._scene_quality_gate(job)
    report = json.loads(quality.read_text())
    assert report["status"] == "passed"
    assert report["selected_visible_object_median"] == 12.0
    assert job.stage_results["scene_quality_gate"]["status"] == "succeeded"
    assert job.stage_results["scene_quality_gate"]["quality_status"] == "passed"


def test_render_parent_allowlist_is_full_eligible_pool_not_current_lease(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        submitted = controller.submit({
            "source_mode": "generate", "dataset_name": "gpu_handoff", "gpu_indices": [0, 2],
            "archetype": "single_room", "room_type": "kitchen", "seed": "20260821",
        })
        job = controller._jobs[submitted["job_id"]]
        job.desired_gpu_indices = [0]
        command = controller._command(job, "full_render")
        assert command[command.index("--gpu-indices") + 1] == "0,1,2,3,4,5,6,7"
        assert command[command.index("--workers") + 1] == "8"
        controller.cancel_job(job.job_id)


def test_failed_research_balanced_job_can_archive_and_retry_with_showcase_profile(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        submitted = controller.submit({
            "source_mode": "generate", "dataset_name": "retry_showcase", "gpu_indices": [0],
            "archetype": "single_room", "room_type": "kitchen", "seed": "20260818",
            "content_profile": "research_balanced", "ir_composition_profile": "",
        })
        job = controller._jobs[submitted["job_id"]]
        # Simulate a legacy failed request which predates the default profile.
        job.request["ir_composition_profile"] = ""
        job.status, job.stage, job.error = "failed", "scene_quality_gate", "legacy fixture"
        old_paths = dict(job.request["paths"])
        retried = controller.retry_with_showcase(job.job_id)
        assert retried["status"] == "queued"
        assert job.request["ir_composition_profile"] == "inverse_rendering_showcase_v1"
        assert job.request["variation_id"] == 1
        assert job.request["showcase_retry_archives"][0]["paths"] == old_paths
        assert "/attempts/v01/" in job.request["paths"]["showcase_blend"]
        controller.cancel_job(job.job_id)


def test_generate_scene_id_override_is_preserved(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        submitted = controller.submit({
            "source_mode": "generate", "dataset_name": "custom_scene", "scene_id": "my_optical_scene",
            "gpu_indices": [0], "archetype": "office", "seed": "20260814",
        })
        job = controller._jobs[submitted["job_id"]]
        assert job.request["scene_id"] == "my_optical_scene"
        controller.cancel_job(job.job_id)


def test_failed_generated_scene_replacement_links_parent_and_child(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        submitted = controller.submit({
            "source_mode": "generate", "dataset_name": "bad_office", "gpu_indices": [0],
            "archetype": "single_room", "room_type": "office", "seed": "20260818",
            "content_profile": "research_balanced",
        })
        parent = controller._jobs[submitted["job_id"]]
        parent.status, parent.stage = "failed", "scene_content_audit"
        child_payload = controller.replace_failed_generated_scene(parent.job_id, logical_seed="20260821")
        child = controller._jobs[child_payload["job_id"]]
        assert child.request["dataset_name"] == "infinigen_single_room_office_20260821_v00_rgb_active_nir_v2"
        assert child.request["ir_composition_profile"] == "inverse_rendering_showcase_v1"
        assert child.request["replaces_job_id"] == parent.job_id
        assert parent.request["replaced_by_job_id"] == child.job_id
        controller.cancel_job(child.job_id)


def test_generated_office_controller_does_not_forward_wizard_only_style(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        submitted = controller.submit({
            "source_mode": "generate", "dataset_name": "modern_office", "gpu_indices": [0],
            "archetype": "office", "seed": "20260818",
        })
        job = controller._jobs[submitted["job_id"]]
        generate = controller._command(job, "generate")
        assert generate[generate.index("--archetype") + 1] == "office"
        assert "--office-style" not in generate
        graph = controller._command(job, "navigation_compile")
        assert "--modern-office-glass-count" not in graph
        assert graph[graph.index("--max-nodes") + 1] == "70"
        controller.cancel_job(job.job_id)


@pytest.mark.parametrize("room_type", sorted(ROOM_TYPES))
def test_submit_accepts_every_infinigen_single_room_semantic(tmp_path: Path, room_type: str) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        job = controller.submit({
            "source_mode": "generate", "dataset_name": f"room_{room_type}",
            "scene_id": f"scene_{room_type}", "gpu_indices": [0],
            "archetype": "single_room", "room_type": room_type,
            "density": "normal_lived_in", "generation_stage": "layout",
            "seed": "20260814",
        })
        assert controller._jobs[job["job_id"]].request["room_type"] == room_type
        controller.cancel_job(job["job_id"])


def test_existing_input_must_be_generated_output_and_name_collisions_fail(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    source = controller.data_root / "kr_20260813_single_room_kitchen" / "full"
    source.mkdir(parents=True)
    (source / "scene.blend").write_bytes(b"fixture")
    with controller._lock:
        job = controller.submit({"source_mode": "existing", "existing_output": source.relative_to(controller.data_root).as_posix(),
                                 "dataset_name": "safe", "gpu_indices": [0]})
        controller.cancel_job(job["job_id"])
        import_dir = controller.repo_root / "out" / "infinigen_imports" / source.parent.name
        import_dir.mkdir(parents=True)
        (import_dir / "scene_manifest.json").write_text(json.dumps({"stage1_profile": "ir-bootstrap-v1"}))
        scene = controller.scene_root / controller._jobs[job["job_id"]].request["scene_id"]
        scene.mkdir(parents=True)
        for name in ("render_scene.xml", "xml_scene_index.json", "render_scene_material_policy.json", "authoring_map.json"):
            (scene / name).write_text("{}")
        command = controller._command(controller._jobs[job["job_id"]], "import")
        assert "--skip-export" in command
        assert command[command.index("--stage1-profile") + 1] == "ir-bootstrap-v1"
        assert "--bake-pbr" not in command
    with pytest.raises(ValueError, match="existing_output"):
        controller.submit({"source_mode": "existing", "existing_output": "../../etc", "dataset_name": "unsafe", "gpu_indices": [0]})
    (controller.work_root / "taken").mkdir()
    with pytest.raises(FileExistsError, match="already exists"):
        controller.submit({"source_mode": "existing", "existing_output": source.relative_to(controller.data_root).as_posix(),
                           "dataset_name": "taken", "gpu_indices": [0]})


def test_priority_retry_and_restart_recovery_are_durable(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    request = {"dataset_name": "restored", "gpu_indices": [1], "paths": {"dataset": str(tmp_path / "work" / "restored")}}
    interrupted = ControllerJob(job_id="running", request=request, status="running", stage="full_render", pid=99999)
    controller._save(interrupted, "fixture")
    restarted = _controller(tmp_path)
    restored = restarted.get("running")
    assert restored["status"] == "interrupted"
    assert restored["stage"] == "interrupted"
    assert restored["resource_state"] == "pending"
    assert restored["queue_position"] is None
    with restarted._lock:
        retried = restarted.retry("running")
        assert retried["status"] == "queued"
        assert restarted.priority("running", 4)["priority"] == 4
        restarted.cancel_job("running")


def test_running_pipeline_priority_applies_to_following_resource_queue(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    job = ControllerJob(job_id="showcase", request={}, status="running", stage="geometry")
    controller._jobs[job.job_id] = job
    assert controller.priority(job.job_id, 100)["priority"] == 100


def test_corrected_plan_replan_archives_legacy_plan_and_queues_full_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(tmp_path)
    plan_path = tmp_path / "work" / ".pipeline" / "scene" / "render_plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(json.dumps({"render_plan_digest": "a" * 64}))
    dataset = tmp_path / "work" / "dataset"; dataset.mkdir(parents=True)
    (dataset / "dataset_config.json").write_text(json.dumps({"dataset_fingerprint": "old"}))
    job = ControllerJob(job_id="replan", request={"dataset_name": "dataset", "scene_id": "scene", "fov": 60,
        "width": 64, "height": 48, "rgb_spp": 4, "nir_spp": 4, "flash_energy_scale": 1, "ambient_fill_energy_scale": 1,
        "paths": {"render_plan": str(plan_path), "dataset": str(dataset), "qc": str(tmp_path / "qc"), "prepared": str(tmp_path / "prepared"), "overview_proxy": str(tmp_path / "proxy"),
    }}, status="cancelled", stage="full_render")
    job.stage_results = {"full_render": {"status": "failed"}, "full_verify": {"status": "failed"}}
    controller._jobs[job.job_id] = job
    monkeypatch.setattr(controller, "_build_view_plan", lambda current: current.stage_results.update({"view_plan": {"status": "succeeded"}}))
    result = controller.replan(job.job_id)
    assert result["status"] == "queued"
    archive = plan_path.with_name("render_plan.legacy-" + "a" * 16 + ".json")
    assert archive.is_file()
    assert job.request["plan_adoption_legacy_plan"] == str(archive)
    assert "full_render" not in job.stage_results
    job.desired_gpu_indices = [0]
    command = controller._command(job, "full_render")
    assert command[command.index("--adopt-compatible-plan") + 1] == str(archive)
    controller.cancel_job(job.job_id)


def test_existing_row_adoption_prefers_current_plan_and_matching_config(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    dataset = tmp_path / "dataset"; frames = dataset / "frames"; frames.mkdir(parents=True)
    pipeline = tmp_path / "pipeline"; pipeline.mkdir()
    current_plan = pipeline / "render_plan.json"
    current_plan.write_text(json.dumps({"render_plan_digest": "a" * 64}))
    (pipeline / "render_plan.legacy-old.json").write_text(json.dumps({"render_plan_digest": "c" * 64}))
    (frames / "current.json").write_text(json.dumps({
        "dataset_fingerprint": "b" * 64, "lighting": {"render_plan_digest": "a" * 64},
    }))
    (frames / "old.json").write_text(json.dumps({
        "dataset_fingerprint": "d" * 64, "lighting": {"render_plan_digest": "c" * 64},
    }))

    plan, config, row_only = controller._existing_row_adoption_inputs(dataset, current_plan)
    assert plan == current_plan and config is None and row_only

    legacy_config = pipeline / "dataset_config.legacy-current.json"
    legacy_config.write_text(json.dumps({
        "dataset_fingerprint": "b" * 64,
        "render_plan": {"render_plan_digest": "a" * 64},
    }))
    plan, config, row_only = controller._existing_row_adoption_inputs(dataset, current_plan)
    assert plan == current_plan and config == legacy_config and not row_only


def test_prepared_v1_or_missing_effective_audit_is_rejected(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    prepared = tmp_path / "prepared"; prepared.mkdir()
    request = {"dataset_name": "audit", "gpu_indices": [0], "paths": {"prepared": str(prepared)}}
    job = ControllerJob(job_id="audit", request=request)
    (prepared / "principled_material_contract.json").write_text(json.dumps({"schema": "robomituba.ir_principled_material_contract.v1"}))
    with pytest.raises(RuntimeError, match="v4"):
        controller._assert_prepared_v2(job)
    (prepared / "principled_material_contract.json").write_text(json.dumps({
        "schema": "robomituba.ir_principled_material_contract.v4",
        "contract_version": "blender42-principled-metallic-roughness-v4",
        "compiler_version": STAGE2_COMPILER_VERSION,
        "materials": [{"metallic_contract": {"schema": "robomituba.metallic_contract.v2"}}],
    }))
    with pytest.raises(RuntimeError, match="effective-input"):
        controller._assert_prepared_v2(job)


def test_stale_prepared_stage_is_rebuilt_only_via_archive_flag(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    geometry = tmp_path / "geometry"
    prepared = tmp_path / "prepared"; prepared.mkdir()
    job = ControllerJob(
        job_id="stale-stage2",
        request={"scene_id": "fixture", "paths": {"geometry": str(geometry), "prepared": str(prepared)}},
    )
    command = controller._command(job, "principled_prepare")
    assert "--rebuild-stale" in command
    assert "--force" not in command


def test_stage2_recovery_audit_rejects_an_old_compiler_even_with_v4_schema(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    prepared = tmp_path / "prepared"; prepared.mkdir()
    (prepared / "principled_material_contract.json").write_text(json.dumps({
        "schema": "robomituba.ir_principled_material_contract.v4",
        "contract_version": "blender42-principled-metallic-roughness-v4",
        "compiler_version": "ir-principled-stage2-v11-obsolete",
        "materials": [],
    }), encoding="utf-8")
    job = ControllerJob(job_id="old-compiler", request={"paths": {"prepared": str(prepared)}})
    assert controller._stage_artifact_state(job, "principled_prepare") == "stale"


def test_rendered_stale_stage2_resume_forks_an_isolated_v4_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never replace a prepared scene underneath committed legacy frames."""
    controller = _controller(tmp_path)
    pipeline = tmp_path / "pipe"; pipeline.mkdir()
    geometry = tmp_path / "geometry"; geometry.mkdir()
    prepared = pipeline / "principled_stage2"; prepared.mkdir()
    dataset = tmp_path / "legacy_dataset"; dataset.mkdir()
    (dataset / "index.jsonl").write_text('{"frame_id":"legacy"}\n', encoding="utf-8")
    paths = {
        "pipeline": str(pipeline), "geometry": str(geometry), "prepared": str(prepared),
        "qc": str(pipeline / "qc"), "dataset": str(dataset),
        "published": str(tmp_path / "published" / "legacy_dataset"),
        "render_plan": str(pipeline / "render_plan.json"),
        "qc_render_plan": str(pipeline / "qc_render_plan.json"),
    }
    job = ControllerJob(
        job_id="legacy-stage2", status="failed", stage="principled_prepare",
        request={"source_mode": "existing", "dataset_name": "legacy_dataset", "paths": paths,
                 "illumination_diversity": True},
    )
    controller._jobs[job.job_id] = job
    monkeypatch.setattr(controller, "recovery_plan", lambda _job_id: {"recommended_rerun_from": "principled_prepare"})
    monkeypatch.setattr(controller, "_stage_artifact_state", lambda _job, stage: "stale" if stage == "principled_prepare" else "verified")

    assert controller._fork_rendered_contract_upgrade_if_needed(job)
    assert job.request["dataset_name"].startswith("legacy_dataset__pbr_v4")
    assert job.request["paths"]["geometry"] == str(geometry)
    assert job.request["paths"]["prepared"] != str(prepared)
    assert job.request["paths"]["dataset"] != str(dataset)
    assert job.request["contract_upgrade_parent_paths"] == paths
    assert (dataset / "index.jsonl").read_text(encoding="utf-8") == '{"frame_id":"legacy"}\n'


def test_resume_refuses_a_live_importer_for_the_same_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(tmp_path)
    source = controller.data_root / "kr_20260814_single_room_bedroom" / "full"
    source.mkdir(parents=True); (source / "scene.blend").write_bytes(b"fixture")
    with controller._lock:
        submitted = controller.submit({"source_mode": "existing", "dataset_name": "resume_guard", "gpu_indices": [0],
                                       "existing_output": source.relative_to(controller.data_root).as_posix()})
        job = controller._jobs[submitted["job_id"]]
        job.status = job.stage = "interrupted"; controller._save(job, "fixture")
        monkeypatch.setattr(controller, "_active_import_pids", lambda _job: [12345])
        with pytest.raises(RuntimeError, match="12345"):
            controller.resume(job.job_id)
        monkeypatch.setattr(controller, "_active_import_pids", lambda _job: [])
        resumed = controller.resume(job.job_id)
        assert resumed["status"] == "queued"
        controller.cancel_job(job.job_id)


def test_adopt_external_import_keeps_job_visible_and_cancellable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(tmp_path)
    job = ControllerJob(job_id="orphan", request={"existing_output": str(tmp_path / "scene"), "paths": {}}, status="interrupted")
    controller._jobs[job.job_id] = job
    monkeypatch.setattr(controller, "_active_import_pids", lambda _job: [4242])
    adopted = controller.adopt_external_import(job.job_id)
    assert adopted["status"] == "running"
    assert adopted["external_import_pids"] == [4242]
    assert job.external_adopted is True
    assert controller._can_start("blender_bootstrap", job) is True


def test_adopted_generation_uses_stage_clock_not_original_job_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller(tmp_path)
    controller.infinigen_generate_timeout_s = 1
    job = ControllerJob(
        job_id="legacy-generator", status="running", stage="generate", external_adopted=True,
        pid=4242, started_at="2000-01-01T00:00:00Z", stage_started_at=None,
        request={"source_mode": "generate", "scene_id": "fixture"},
    )
    controller._jobs[job.job_id] = job
    monkeypatch.setattr(controller, "_external_pids", lambda _job: [4242])
    controller._refresh_external_jobs()
    assert job.status == "running"
    assert job.stage_started_at is not None
    assert "generate exceeded" not in str(job.error or "")


def test_geometry_progress_uses_atomic_unit_checkpoints(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    geometry = tmp_path / "work" / ".pipeline" / "scene" / "ir_geometry"
    state = geometry / "stage1" / ".stage1_unit_state"
    state.mkdir(parents=True)
    for index in range(3):
        (state / f"{index}.json").write_text("{}")
    job = ControllerJob(job_id="geometry", request={"paths": {"geometry": str(geometry)}})
    controller._jobs[job.job_id] = job
    controller._log_path(job).parent.mkdir(parents=True, exist_ok=True)
    controller._log_path(job).write_text(json.dumps({"event": "output", "line": "[export] exporting 10 units (bake=on)…"}) + "\n")
    progress = controller._stage_progress(job)["geometry"]
    assert progress["completed"] == 3 and progress["total"] == 10
    assert progress["percent"] == 30.0


def test_geometry_command_distinguishes_partial_resume_from_published_finalize(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    source = controller.data_root / "kr_20260814_single_room_bedroom" / "full"
    source.mkdir(parents=True); (source / "scene.blend").write_bytes(b"fixture")
    geometry = tmp_path / "work" / ".pipeline" / "bedroom" / "ir_geometry"
    job = ControllerJob(job_id="geometry-command", request={
        "existing_output": str(source), "scene_id": "bedroom",
        "paths": {"geometry": str(geometry)},
    })

    fresh = controller._command(job, "geometry")
    assert "--resume" not in fresh and "--finalize-existing" not in fresh
    assert fresh[fresh.index("--cycles-device") + 1] == "OPTIX"
    assert fresh[fresh.index("--cycles-fallback") + 1] == "CPU"

    (geometry / "stage1" / ".stage1_unit_state").mkdir(parents=True)
    partial = controller._command(job, "geometry")
    assert "--resume" in partial and "--finalize-existing" not in partial

    (geometry / "stage1" / "scene_manifest.json").write_text("{}")
    (geometry / "derived_ir_semantic_lod.blend").write_bytes(b"blend")
    published = controller._command(job, "geometry")
    assert "--finalize-existing" in published and "--resume" not in published


def test_view_plan_stage_writes_budgeted_qc_and_full_plans(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    graph_dir = controller.scene_root / "scene"; graph_dir.mkdir(parents=True)
    graph = {"nodes": [{"node_id": f"vp_{index:03d}", "position": [index, 0.0, 0.0],
                        "headings": [{"yaw_deg": 0.0}, {"yaw_deg": 90.0}]} for index in range(60)]}
    (graph_dir / "viewpoint_graph.json").write_text(json.dumps(graph))
    paths = {"render_plan": str(tmp_path / "render_plan.json"), "qc_render_plan": str(tmp_path / "qc_plan.json")}
    job = ControllerJob(job_id="plan", request={"scene_id": "scene", "pose_budget": 100, "paths": paths})
    controller._build_view_plan(job)
    full = json.loads(Path(paths["render_plan"]).read_text())
    qc = json.loads(Path(paths["qc_render_plan"]).read_text())
    assert full["actual_pose_count"] == 100
    assert [len(group["poses"]) for group in full["groups"]] == [25, 25, 25, 25]
    assert [len(group["poses"]) for group in qc["groups"]] == [2, 2, 2, 2]
    assert job.stage_results["view_plan"]["status"] == "succeeded"


def test_reference_subset_qc_keeps_each_sampled_variation_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller(tmp_path)
    graph_dir = controller.scene_root / "scene"; graph_dir.mkdir(parents=True)
    graph = {"nodes": [{"node_id": f"vp_{index:03d}", "position": [index, 0.0, 0.0],
                        "headings": [{"yaw_deg": 0.0}, {"yaw_deg": 90.0}]}
                       for index in range(60)]}
    (graph_dir / "viewpoint_graph.json").write_text(json.dumps(graph), encoding="utf-8")
    illumination = {
        "contract": "fixture", "manifest_digest": "fixture",
        "assets": {"overcast": {"path": "fixture.hdr", "sha256": "a" * 64}},
        "conditions": [
            {"id": "reference_neutral_v1", "external_asset": "overcast"},
            *[{"id": f"variation_{index}", "external_asset": "overcast"} for index in range(5)],
        ],
    }
    monkeypatch.setattr("apps.ir_dataset_viewer.backend.controller.load_bank", lambda _root: illumination)
    paths = {"render_plan": str(tmp_path / "render_plan.json"),
             "qc_render_plan": str(tmp_path / "qc_plan.json")}
    job = ControllerJob(job_id="paired-plan", request={
        "scene_id": "scene", "pose_budget": 100, "paths": paths,
        "illumination_diversity": True, "paired_fraction": .20,
        "illumination_pairing_policy": "reference_subset_v2",
    })
    controller._build_view_plan(job)
    full = json.loads(Path(paths["render_plan"]).read_text())
    qc = json.loads(Path(paths["qc_render_plan"]).read_text())
    assert sorted(len(group["poses"]) for group in full["groups"]) == [20, 20, 20, 20, 20, 100]
    assert sorted(len(group["poses"]) for group in qc["groups"]) == [2, 2, 2, 2, 2, 10]
    pair_counts: dict[str, int] = {}
    for group in qc["groups"]:
        for pose in group["poses"]:
            pair_counts[pose["pair_id"]] = pair_counts.get(pose["pair_id"], 0) + 1
    assert len(pair_counts) == 10
    assert set(pair_counts.values()) == {2}
    assert qc["illumination"]["expected_frame_count"] == 20


def test_recovery_inserts_missing_navigation_compile_without_discarding_import(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    source = controller.data_root / "kr_20260814_single_room_bedroom" / "full"
    source.mkdir(parents=True); (source / "scene.blend").write_bytes(b"fixture")
    scene = controller.scene_root / "bedroom"; scene.mkdir(parents=True)
    (scene / "material_slots.json").write_text("{}")
    (scene / "material_canonical.json").write_text("{}")
    import_dir = controller.repo_root / "out" / "infinigen_imports" / source.parent.name
    import_dir.mkdir(parents=True); (import_dir / "scene_manifest.json").write_text("{}")
    job = ControllerJob(job_id="recover", status="failed", request={"source_mode": "existing", "existing_output": str(source),
                        "scene_id": "bedroom", "dataset_name": "recover", "gpu_indices": [0], "pose_budget": 100,
                        "paths": {"pipeline": str(tmp_path / "pipe"), "geometry": str(tmp_path / "geo"), "prepared": str(tmp_path / "prepared"),
                                  "qc": str(tmp_path / "qc"), "dataset": str(tmp_path / "dataset"), "render_plan": str(tmp_path / "plan.json"),
                                  "qc_render_plan": str(tmp_path / "qc-plan.json")}},
                        stage_results={"import": {"status": "succeeded"}, "material_extract": {"status": "succeeded"}, "material_canonicalize": {"status": "succeeded"}})
    controller._jobs[job.job_id] = job
    audit = controller.recovery_plan(job.job_id)
    assert audit["recommended_rerun_from"] == "navigation_compile"
    with controller._lock:
        controller.resume(job.job_id)
        assert job.status == "queued"
        assert job.stage_results["import"]["status"] == "succeeded"
        assert "navigation_compile" not in job.stage_results


def test_gpu_reservation_only_for_running_gpu_stage(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    job = ControllerJob(job_id="gpu", request={"gpu_indices": [1, 3]})
    candidate = ControllerJob(job_id="candidate", request={"gpu_indices": [0]})
    overlap = ControllerJob(job_id="overlap", request={"gpu_indices": [3]})
    controller._jobs[job.job_id] = job
    controller._running[job.job_id] = threading.Thread()
    job.resource_class = "cpu_light"
    assert controller._can_start("gpu_render", candidate)
    job.resource_class = "gpu_render"
    job.resource_gpu_indices = [1, 3]
    assert controller._can_start("gpu_render", candidate)
    assert not controller._can_start("gpu_render", overlap)


def test_two_infinigen_generators_can_overlap_prepare_lane(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    first = ControllerJob(job_id="gen-a", request={}); first.resource_class = "infinigen_generate"
    second = ControllerJob(job_id="gen-b", request={}); second.resource_class = "infinigen_generate"
    blender = ControllerJob(job_id="blend", request={}); blender.resource_class = "blender_prepare"
    controller._jobs.update({job.job_id: job for job in (first, second, blender)})
    controller._running[first.job_id] = threading.Thread()
    assert controller._can_start("infinigen_generate")
    assert controller._can_start("blender_prepare", blender)
    controller._running[second.job_id] = threading.Thread()
    assert not controller._can_start("infinigen_generate")
    assert controller._can_start("blender_prepare", blender)
    controller._running[blender.job_id] = threading.Thread()
    assert controller._can_start("blender_prepare", blender)


def test_four_bootstrap_imports_overlap_without_blocking_gpu(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    imports = [ControllerJob(job_id=f"import-{i}", request={}, stage="import", status="running",
                             resource_class="blender_bootstrap") for i in range(4)]
    controller._jobs.update({job.job_id: job for job in imports})
    assert controller._resource_class("import") == "blender_bootstrap"
    for item in imports[:3]:
        controller._running[item.job_id] = threading.Thread()
    assert controller._can_start("blender_bootstrap", imports[3])
    render = ControllerJob(job_id="render", request={"gpu_indices": [0]})
    assert controller._can_start("gpu_render", render)
    controller._running[imports[3].job_id] = threading.Thread()
    assert not controller._can_start("blender_bootstrap", imports[3])
    assert controller._can_start("infinigen_generate")


def test_two_bakes_get_distinct_gpus_and_only_block_overlapping_render(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    first = ControllerJob(job_id="bake-a", request={"gpu_indices": [0, 1, 2]}, resource_class="blender_bake",
                          resource_gpu_indices=[0])
    second = ControllerJob(job_id="bake-b", request={"gpu_indices": [0, 1, 2]})
    controller._jobs[first.job_id] = first
    controller._running[first.job_id] = threading.Thread()
    assert controller._available_bake_gpu(second) == 1
    assert controller._can_start("blender_bake", second)
    second.resource_class = "blender_bake"; second.resource_gpu_indices = [1]
    controller._jobs[second.job_id] = second; controller._running[second.job_id] = threading.Thread()
    third = ControllerJob(job_id="bake-c", request={"gpu_indices": [0, 1, 2]})
    assert not controller._can_start("blender_bake", third)
    assert not controller._can_start("gpu_render", ControllerJob(job_id="r0", request={"gpu_indices": [0]}))
    assert controller._can_start("gpu_render", ControllerJob(job_id="r2", request={"gpu_indices": [2]}))


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (4, {"render-0": [0], "render-1": [1], "render-2": [2], "render-3": [3]}),
        (2, {"render-0": [0, 2], "render-1": [1, 3]}),
        (1, {"render-0": [0, 1, 2, 3]}),
    ],
)
def test_render_allocator_is_work_conserving_and_fair(
    tmp_path: Path, count: int, expected: dict[str, list[int]],
) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        jobs = [
            ControllerJob(job_id=f"render-{index}", request={"gpu_indices": [0, 1, 2, 3]}, created_at=f"2026-08-14T00:00:0{index}Z")
            for index in range(count)
        ]
        for job in jobs:
            job.eligible_gpu_indices = controller._eligible_gpus(job)
            controller._jobs[job.job_id] = job
        controller._rebalance_gpu_targets([(job, "qc_render") for job in jobs])
        assert {job.job_id: job.desired_gpu_indices for job in jobs} == expected


def test_two_bakes_leave_two_gpus_for_render_backlog(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        bakes = [
            ControllerJob(job_id=f"bake-{gpu}", request={"gpu_indices": [0, 1, 2, 3]}, status="running",
                          stage="geometry", resource_class="blender_bake", resource_gpu_indices=[gpu])
            for gpu in (0, 1)
        ]
        renders = [
            ControllerJob(job_id=f"render-{index}", request={"gpu_indices": [0, 1, 2, 3]}, created_at=f"2026-08-14T00:00:0{index}Z")
            for index in range(2)
        ]
        for job in [*bakes, *renders]:
            job.eligible_gpu_indices = controller._eligible_gpus(job)
            controller._jobs[job.job_id] = job
        for job in bakes:
            controller._running[job.job_id] = threading.Thread()
        controller._rebalance_gpu_targets([(job, "qc_render") for job in renders])
        assert {job.job_id: job.desired_gpu_indices for job in renders} == {
            "render-0": [2], "render-1": [3],
        }


def test_bake_reservation_uses_gpu_in_bake_eligible_subset(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with controller._lock:
        bake = ControllerJob(
            job_id="bake", request={"gpu_indices": [1, 2, 3]},
            created_at="2026-08-14T00:00:00Z",
        )
        render = ControllerJob(
            job_id="render", request={"gpu_indices": [1, 2, 3]},
            status="running", stage="full_render", resource_class="gpu_render",
            resource_gpu_indices=[1, 2, 3], desired_gpu_indices=[1, 2, 3],
            created_at="2026-08-14T00:00:01Z",
        )
        for job in (bake, render):
            job.eligible_gpu_indices = controller._eligible_gpus(job)
            controller._jobs[job.job_id] = job
        controller._running[render.job_id] = threading.Thread()
        controller._rebalance_gpu_targets([(bake, "geometry")])
        assert render.desired_gpu_indices == [2, 3]
        assert render.draining_gpu_indices == [1]


def test_live_render_lease_is_pinned_during_worker_state_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient empty worker report must not drain an active queue parent."""
    controller = _controller(tmp_path)
    with controller._lock:
        active = ControllerJob(
            job_id="active", request={"gpu_indices": [0, 1, 2, 3]},
            status="running", stage="full_render", resource_class="gpu_render",
            resource_gpu_indices=[2], desired_gpu_indices=[2], pid=123,
            created_at="2026-08-14T00:00:00Z",
        )
        waiting = ControllerJob(
            job_id="waiting", request={"gpu_indices": [0, 1, 2, 3]},
            created_at="2026-08-14T00:00:01Z",
        )
        for job in (active, waiting):
            job.eligible_gpu_indices = controller._eligible_gpus(job)
            controller._jobs[job.job_id] = job
        controller._running[active.job_id] = threading.Thread()
        monkeypatch.setattr(controller, "_pid_alive", lambda pid: bool(pid == 123))
        controller._rebalance_gpu_targets([(waiting, "qc_render")])
        assert 2 in active.desired_gpu_indices
        assert 2 not in waiting.desired_gpu_indices


def test_adopted_degraded_render_releases_failed_worker_gpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A surviving adopted worker must not reserve GPUs whose replacements died."""
    controller = _controller(tmp_path)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    _atomic_json(dataset / "gpu_worker_state.json", {
        "queue_pid": 123,
        "queue_state": "running",
        "workers": {
            "2": {"status": "busy"},
            "0": {"status": "failed"},
            "1": {"status": "failed"},
        },
    })
    with controller._lock:
        active = ControllerJob(
            job_id="adopted", request={"gpu_indices": [0, 1, 2, 3], "paths": {"dataset": str(dataset)}},
            status="running", stage="full_render", resource_class="gpu_render",
            resource_gpu_indices=[2], desired_gpu_indices=[0, 1, 2], pid=123,
            external_adopted=True, created_at="2026-08-14T00:00:00Z",
        )
        waiting = ControllerJob(
            job_id="waiting", request={"gpu_indices": [0, 1, 2, 3]},
            created_at="2026-08-14T00:00:01Z",
        )
        for job in (active, waiting):
            job.eligible_gpu_indices = controller._eligible_gpus(job)
            controller._jobs[job.job_id] = job
        monkeypatch.setattr(controller, "_pid_alive", lambda pid: bool(pid == 123))
        controller._sync_render_worker_state()
        assert active.degraded_worker_gpu_indices == [0, 1]
        assert active.desired_gpu_indices == [2]
        assert json.loads((dataset / "gpu_allocation.json").read_text())["desired_gpu_indices"] == [2]

        controller._rebalance_gpu_targets([(waiting, "qc_render")])
        assert active.desired_gpu_indices == [2]
        assert set(waiting.desired_gpu_indices) == {0, 1, 3}


def test_legacy_gpu_request_is_clamped_but_new_request_is_rejected(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    legacy = {"gpu_indices": list(range(8)), "paths": {}}
    controller._upgrade_request(legacy)
    assert legacy["gpu_indices"] == list(range(8))
    assert legacy["requested_gpu_indices"] == list(range(8))
    with pytest.raises(ValueError, match="outside ROBOMITUBA_IR_GPU_INDICES"):
        controller.submit({
            "source_mode": "generate", "dataset_name": "outside_pool", "gpu_indices": [0, 8],
            "scene_id": "outside_pool", "archetype": "single_room", "room_type": "office",
            "density": "normal_lived_in", "generation_stage": "full", "seed": "20260814",
        })


def test_infinigen_phase_and_local_annealing_progress(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    output = tmp_path / "generated" / "scene" / "full"
    job = ControllerJob(job_id="generate-progress", status="running", stage="generate", request={
        "source_mode": "generate", "existing_output": str(output), "paths": {},
    })
    controller._jobs[job.job_id] = job
    controller._log_path(job).parent.mkdir(parents=True, exist_ok=True)
    messages = [
        "[04:00:00] [logging] [INFO] | [solve_large]",
        "[04:01:00] [logging] [INFO] | [solve_large] finished in 0:01:00",
        "[04:01:00] [logging] [INFO] | [solve_medium]",
        "[04:01:10] [annealing] [INFO] | it=17/50 dt=0.1 n=14 loss=1",
    ]
    controller._log_path(job).write_text("".join(json.dumps({"event": "output", "line": line}) + "\n" for line in messages))
    progress = controller._stage_progress(job)["generate"]
    assert progress["phase"] == "solve_medium"
    assert progress["local_completed"] == 17 and progress["local_total"] == 50
    assert progress["object_count"] == 14
    assert progress["estimated"] is True
    assert progress["phase_percent"] == pytest.approx(34.0)
    # Only completed phases advance the durable generation milestone. The
    # current solver pass is intentionally reported separately.
    assert progress["percent"] == pytest.approx(22.0)


def test_infinigen_progress_resets_phase_history_on_safe_resume(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    job = ControllerJob(job_id="generate-resume-progress", status="running", stage="generate", request={
        "source_mode": "generate", "paths": {},
    })
    controller._jobs[job.job_id] = job
    controller._log_path(job).parent.mkdir(parents=True, exist_ok=True)
    events = [
        {"event": "stage_started", "stage": "generate"},
        {"event": "output", "stage": "generate", "line": "[logging] [INFO] | [solve_large]"},
        {"event": "output", "stage": "generate", "line": "[logging] [INFO] | [solve_large] finished in 0:01:00"},
        # A later safe resume starts a fresh deterministic generation attempt.
        {"event": "stage_started", "stage": "generate"},
        {"event": "output", "stage": "generate", "line": "[logging] [INFO] | [sky_lighting]"},
        {"event": "output", "stage": "generate", "line": "[logging] [INFO] | [sky_lighting] finished in 0:00:01"},
        {"event": "output", "stage": "generate", "line": "[logging] [INFO] | [solve_rooms]"},
        {"event": "output", "stage": "generate", "line": "[logging] [INFO] | [solve_rooms] finished in 0:00:01"},
        {"event": "output", "stage": "generate", "line": "[logging] [INFO] | [solve_large]"},
        {"event": "output", "stage": "generate", "line": "[annealing] [INFO] | it=150/300 dt=0.1 n=7 loss=1"},
    ]
    controller._log_path(job).write_text("".join(json.dumps(event) + "\n" for event in events))
    progress = controller._stage_progress(job)["generate"]
    assert progress["phase"] == "solve_large"
    assert progress["phase_percent"] == pytest.approx(50.0)
    assert progress["percent"] == pytest.approx(1.0)


def test_durable_process_log_is_tailed_once_across_controller_recovery(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    job = ControllerJob(job_id="durable-output", request={})
    controller._jobs[job.job_id] = job
    output = tmp_path / "durable-process.log"
    output.write_bytes(b"first\npartial")
    job.process_log_path, job.process_log_offset = str(output), 0

    controller._capture_process_output(job, "generate")
    assert job.process_log_offset == len(b"first\n")
    output.write_bytes(b"first\npartial tail\nsecond\n")
    controller._capture_process_output(job, "generate")
    controller._capture_process_output(job, "generate")  # idempotent polling

    events = [json.loads(line) for line in controller._log_path(job).read_text().splitlines()]
    assert [event["line"] for event in events if event.get("event") == "output"] == ["first", "partial tail", "second"]


def test_dataset_name_is_reserved_before_pipeline_directory_exists(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    request = {"source_mode": "generate", "dataset_name": "same", "gpu_indices": [0],
               "archetype": "single_room", "room_type": "kitchen", "seed": "20260814"}
    with controller._lock:
        first = controller.submit(request)
        with pytest.raises(FileExistsError, match="already reserved"):
            controller.submit(request)
        controller.cancel_job(first["job_id"])


def test_legacy_duplicate_pipeline_is_blocked_before_ir_artifacts(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    pipeline = str(tmp_path / "shared-pipeline")
    owner = ControllerJob(job_id="owner", created_at="2026-01-01T00:00:00Z", request={"paths": {"pipeline": pipeline}})
    duplicate = ControllerJob(job_id="duplicate", created_at="2026-01-02T00:00:00Z", request={"paths": {"pipeline": pipeline}})
    controller._jobs.update({owner.job_id: owner, duplicate.job_id: duplicate})
    controller._assert_pipeline_owner(owner)
    with pytest.raises(RuntimeError, match="generated scene is preserved"):
        controller._assert_pipeline_owner(duplicate)
