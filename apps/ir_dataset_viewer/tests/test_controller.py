from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from apps.ir_dataset_viewer.backend.controller import ROOM_TYPES, ControllerJob, IRDatasetController, _atomic_json


def _controller(tmp_path: Path) -> IRDatasetController:
    controller = IRDatasetController(
        repo_root=tmp_path / "repo", work_root=tmp_path / "work", bean_root=tmp_path / "bean"
    )
    controller.data_root = tmp_path / "generated"
    controller.scene_root = tmp_path / "scenes"
    return controller


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
        assert current.request["gpu_indices"] == [0, 1, 2, 3]
        assert current.request["requested_gpu_indices"] == [0, 2]
        assert current.request["pipeline_revision"] == "ir-content-aware-v2"
        assert current.request["import_profile"] == "ir-bootstrap-v1"
        assert "scene_content_audit" in controller._pipeline(current)
        assert "view_probe" in controller._pipeline(current)
        assert "dataset_utility_audit" in controller._pipeline(current)
        assert controller._command(current, "view_probe")[1] == "apps/probe_ir_candidate_visibility.py"
        assert "today" not in controller._command(current, "generate")
        graph_command = controller._command(current, "navigation_compile")
        assert graph_command[graph_command.index("--max-nodes") + 1] == "70"
        assert graph_command[graph_command.index("--heading-count") + 1] == "24"
        assert str(controller.data_root) in current.request["existing_output"]
        assert controller._command(current, "geometry")[:2] == ["python3", "apps/build_ir_geometry_profile.py"]
        controller.cancel_job(current.job_id)


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
    with restarted._lock:
        retried = restarted.retry("running")
        assert retried["status"] == "queued"
        assert restarted.priority("running", 4)["priority"] == 4
        restarted.cancel_job("running")


def test_prepared_v1_or_missing_effective_audit_is_rejected(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    prepared = tmp_path / "prepared"; prepared.mkdir()
    request = {"dataset_name": "audit", "gpu_indices": [0], "paths": {"prepared": str(prepared)}}
    job = ControllerJob(job_id="audit", request=request)
    (prepared / "principled_material_contract.json").write_text(json.dumps({"schema": "robomituba.ir_principled_material_contract.v1"}))
    with pytest.raises(RuntimeError, match="v2"):
        controller._assert_prepared_v2(job)
    (prepared / "principled_material_contract.json").write_text(json.dumps({
        "schema": "robomituba.ir_principled_material_contract.v2",
        "contract_version": "blender42-principled-metallic-roughness-v2", "materials": [{}],
    }))
    with pytest.raises(RuntimeError, match="effective-input"):
        controller._assert_prepared_v2(job)


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


def test_legacy_gpu_request_is_clamped_but_new_request_is_rejected(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    legacy = {"gpu_indices": list(range(8)), "paths": {}}
    controller._upgrade_request(legacy)
    assert legacy["gpu_indices"] == [0, 1, 2, 3]
    assert legacy["requested_gpu_indices"] == list(range(8))
    with pytest.raises(ValueError, match="outside ROBOMITUBA_IR_GPU_INDICES"):
        controller.submit({
            "source_mode": "generate", "dataset_name": "outside_pool", "gpu_indices": [0, 4],
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
    assert progress["estimated"] is True and progress["percent"] > 0


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
