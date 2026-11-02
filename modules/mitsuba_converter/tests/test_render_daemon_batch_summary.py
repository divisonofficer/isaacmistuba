from __future__ import annotations

import json
from types import SimpleNamespace

from robomituba_bridge import CameraSpec, RenderRequest, RobotState, SceneState

from mitsuba_converter.render_daemon import (
    RenderDaemon,
    _rewrite_resume_batch_child_routing,
    _is_render_queue_proxy_path,
    _snapshot_render_request_payload,
    _stokes_batch_window_policy,
)
from mitsuba_converter.versioned_artifacts import RenderLedger


def test_heading_batch_child_payload_is_detached_from_leader_extras():
    """A leader can safely retain a snapshot of itself as a batch child."""
    scene = SceneState(
        job_id="job-1", scene_id="scene-1", frame_id="frame-1",
        timestamp="2026-08-30T00:00:00Z", scene_snapshot_ref="scene.xml",
        mitsuba_scene_ref="scene.xml",
    )
    request = RenderRequest(
        request_id="request-1", job_id=scene.job_id, frame_id=scene.frame_id,
        timestamp=scene.timestamp, scene_state=scene,
        camera_specs=[CameraSpec(
            camera_id="polar", name="polar", fov_deg=75.0, resolution=[512, 512],
            camera_to_world=[
                1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
            ],
        )],
        modalities=["polar_rgb_preview", "s1", "s2", "dop", "aolp"],
        robot_state=RobotState(), extras={"polar_batch_key": "pose-1:0"},
    )

    child_payload = _snapshot_render_request_payload(request)
    request.extras["stokes_heading_batch_request_payloads"] = [child_payload]
    request.extras["run_id"] = "run-1"

    # This is where the former live payload formed extras -> payload -> extras.
    encoded = json.dumps(_snapshot_render_request_payload(request))
    decoded = json.loads(encoded)
    assert decoded["extras"]["run_id"] == "run-1"
    assert child_payload["extras"] is not request.extras
    assert "stokes_heading_batch_request_payloads" not in child_payload["extras"]


def test_resume_rewrites_version_routing_on_each_batch_child():
    payload = {
        "extras": {
            "run_id": "old-run",
            "render_version_id": "old-version",
            "stokes_heading_batch_request_payloads": [
                {"extras": {"opticalnav_vp_id": "vp-a", "opticalnav_heading_id": "h_000", "render_version_id": "old-version"}},
                {"extras": {"opticalnav_vp_id": "vp-b", "opticalnav_heading_id": "h_015", "render_version_id": "old-version"}},
            ],
        },
    }
    resumed = _rewrite_resume_batch_child_routing(
        payload,
        routing={
            "run_id": "resume-run", "scene_version_id": "scene-v1",
            "render_version_id": "resume-version", "scene_variant_key": "base",
            "task_key": "resume-task", "logical_task_key": "logical-task",
        },
        parent_task_key="resume-task",
    )
    children = resumed["extras"]["stokes_heading_batch_request_payloads"]
    assert [item["extras"]["render_version_id"] for item in children] == ["resume-version", "resume-version"]
    assert [item["extras"]["run_id"] for item in children] == ["resume-run", "resume-run"]
    assert [item["extras"]["opticalnav_vp_id"] for item in children] == ["vp-a", "vp-b"]
    assert [item["extras"]["opticalnav_heading_id"] for item in children] == ["h_000", "h_015"]


def test_resident_k_heading_batch_keeps_workers_and_legacy_mode_recycles(monkeypatch):
    passive = [SimpleNamespace(request=SimpleNamespace(extras={
        "stokes_heading_batch_execution": "ambient_stokes_heading_batch_v1",
    }))]
    # The resident K=4 scene uses fixed sensor slots, so a worker can retain
    # the single OptiX scene allocation for all subsequent strips.
    assert _stokes_batch_window_policy(
        passive, gpu_indices=[0, 1, 2, 3], default_window=32,
    ) == (32, False)

    monkeypatch.setenv("ROBOMITUBA_RESIDENT_STOKES_HEADING_BATCH", "0")
    assert _stokes_batch_window_policy(
        passive, gpu_indices=[0, 1, 2, 3], default_window=32,
    ) == (4, True)

    active = [SimpleNamespace(request=SimpleNamespace(extras={
        "stokes_heading_batch_execution": "active_stokes_heading_batch_v1",
    }))]
    assert _stokes_batch_window_policy(
        active, gpu_indices=[0, 1, 2, 3], default_window=32,
    ) == (32, False)


def test_variant_barrier_waits_for_unmaterialized_plan_total(tmp_path):
    """A finished admission window is not a finished predecessor run."""
    from mitsuba_converter.versioned_artifacts import new_render_version_id, scene_version_id

    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text("<scene/>", encoding="utf-8")
    scene_version, digest = scene_version_id(tmp_path, scene_ref=scene_xml)
    ledger = RenderLedger(tmp_path, scene_id="scene")
    ledger.create_scene_version(
        project_id="project", scene_id="scene", scene_version_id_value=scene_version,
        scene_digest=digest,
    )
    render_version = new_render_version_id(digest)
    ledger.create_render_run(
        run_id="base", project_id="project", scene_id="scene",
        scene_version_id_value=scene_version, render_version_id=render_version,
        metadata={"plan_total": 2},
    )
    ledger.put_tasks_batch([{
        "task_key": "first", "run_id": "base", "render_version_id": render_version,
        "variant": "base", "phase": "polar", "phase_index": 0, "ordinal": 0,
        "node_id": "vp-0", "heading_id": "h-000", "state": "succeeded",
        "metadata": {"scene_id": "scene"},
    }])

    daemon = RenderDaemon(repo_root=tmp_path)
    try:
        daemon._wait_for_graph_batch_terminal(tmp_path, "scene", "base", timeout_s=0.01)
    except TimeoutError:
        pass
    else:
        raise AssertionError("partial persisted plan must not pass the variant barrier")


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


def test_backend_keeps_multi_queue_scene_coverage_local_but_proxies_queue_control():
    prefix = "/api/opticalnav/projects/opticalnav-v0.2/scenes/infinigen_office_20260823"
    assert _is_render_queue_proxy_path("GET", f"{prefix}/graph-render-batches/batch-1")
    assert _is_render_queue_proxy_path("GET", f"{prefix}/render-runs/run-1")
    assert _is_render_queue_proxy_path("POST", f"{prefix}/render-runs/run-1/resume")
    assert _is_render_queue_proxy_path("GET", f"{prefix}/render-tasks/task-1/events")
    assert not _is_render_queue_proxy_path("GET", f"{prefix}/render-coverage")
    assert _is_render_queue_proxy_path("POST", f"{prefix}/graph/sweep")
    assert not _is_render_queue_proxy_path("GET", f"{prefix}/authoring-map")
    # Gallery is read-only scene-local I/O.  Its on-demand Stokes conversion
    # runs in the bounded 8765 control-plane preview executor, never in the
    # 8766 GPU queue process.
    assert not _is_render_queue_proxy_path("GET", f"{prefix}/render-versions/rv_123/gallery")
    assert not _is_render_queue_proxy_path("GET", "/api/opticalnav/projects/opticalnav-v0.2")


def test_v4_place_graph_edits_target_place_sidecar_and_reset_derived_support(tmp_path, monkeypatch):
    """Manual place edits must not silently mutate the legacy viewpoint graph."""
    import numpy as np
    from navigation_dataset.navigation_support import (
        BLUEPRINTS_FILE,
        DEFAULT_CONFIG,
        MOTION_GRID_FILE,
        OBSERVATION_PLAN_FILE,
        PLACE_GRAPH_FILE,
        RENDER_GRAPH_FILE,
        SUPPORT_ARCHIVE_DIR,
        SUPPORT_GRAPH_FILE,
        read_route_blueprints,
        write_place_graph,
        write_route_blueprints,
    )
    from navigation_dataset.traversability import GridSpec, TraversabilityGrid, save_traversability_grid
    from navigation_dataset.viewpoint_graph import (
        ViewpointEdge,
        ViewpointGraph,
        ViewpointHeading,
        ViewpointNode,
        read_viewpoint_graph,
    )

    project_dir = tmp_path / "opticalnav-v0.2"
    scene_dir = project_dir / "scenes" / "scene-v4"
    scene_dir.mkdir(parents=True)
    headings = [ViewpointHeading(f"h_{angle:03d}", float(angle)) for angle in range(0, 360, 30)]
    graph = ViewpointGraph(
        scene_id="scene-v4", graph_id="place-v4", node_heading_count=12,
        nodes=[
            ViewpointNode("a", [0.0, 0.0, 0.0], headings=headings),
            ViewpointNode("b", [1.0, 0.0, 0.0], headings=headings),
        ],
        edges=[ViewpointEdge("ab", "a", "b", 1.0, 1.0)],
    )
    write_place_graph(scene_dir, graph, config=DEFAULT_CONFIG)
    # This is the clearance-eroded v4 placement domain, not the legacy grid.
    spec = GridSpec(origin=[-2.0, -2.0], resolution=0.05, width=100, height=100, scene_id="scene-v4")
    save_traversability_grid(
        scene_dir / MOTION_GRID_FILE,
        TraversabilityGrid(spec=spec, traversable=np.ones((100, 100), dtype=bool), hazard=np.zeros((100, 100), dtype=bool)),
    )
    write_route_blueprints(scene_dir / BLUEPRINTS_FILE, {
        "profile_id": "adaptive_navigation_support_v4", "place_graph_id": "place-v4",
        "config": dict(DEFAULT_CONFIG), "blueprints": [], "coverage": {}, "blueprint_digest": "old",
    })
    digest = "d" * 40
    (scene_dir / SUPPORT_GRAPH_FILE).write_text(json.dumps({
        "profile_id": "adaptive_navigation_support_v4",
        "profile_digest": digest,
        "validation": {"digest": digest},
    }), encoding="utf-8")
    (scene_dir / OBSERVATION_PLAN_FILE).write_text(json.dumps({
        "profile_id": "adaptive_navigation_support_v4",
        "profile_digest": digest,
        "validation_digest": digest,
        "place_graph_id": "place-v4",
        "render_entries": [],
        "summary": {"support_pose_count": 2, "polar_observation_count": 0},
    }), encoding="utf-8")
    (scene_dir / RENDER_GRAPH_FILE).write_text("{}", encoding="utf-8")

    daemon = RenderDaemon(repo_root=tmp_path)
    handler = SimpleNamespace(headers={}, client_address=("127.0.0.1", 0))
    status, response = daemon._apply_opticalnav_graph_edits(handler, project_dir, "scene-v4", {
        "graph_scope": "navigation_place",
        "ops": [{"client_op_id": "add-1", "type": "add_node", "x": 0.5, "y": 0.5}],
    })

    assert status.value == 409
    assert response["error"] == "navigation_support_locked"
    assert (scene_dir / SUPPORT_GRAPH_FILE).is_file()
    status, response = daemon._apply_opticalnav_graph_edits(handler, project_dir, "scene-v4", {
        "graph_scope": "navigation_place",
        "confirm_support_invalidation": True,
        "ops": [{"client_op_id": "add-1", "type": "add_node", "x": 0.5, "y": 0.5}],
    })

    assert status.value == 200
    assert response["graph_scope"] == "navigation_place"
    assert response["support_invalidated"] is True
    assert response["archived_support"]["profile_digest"] == digest
    assert (scene_dir / SUPPORT_ARCHIVE_DIR / digest / SUPPORT_GRAPH_FILE).is_file()
    edited = read_viewpoint_graph(scene_dir / PLACE_GRAPH_FILE)
    assert len(edited.nodes) == 3
    assert len(edited.nodes[-1].headings) == 12
    # A v4 manual place node is subject to the support grid and the explicit
    # 0.15 m editing floor, rather than accidentally consulting legacy grid.npy.
    status, response = daemon._apply_opticalnav_graph_edits(handler, project_dir, "scene-v4", {
        "graph_scope": "navigation_place",
        "ops": [{"client_op_id": "add-too-close", "type": "add_node", "x": 0.58, "y": 0.5}],
    })
    assert status.value == 400
    assert response["results"][0]["reason"] == "too_close_to_place_node"
    assert read_route_blueprints(scene_dir / BLUEPRINTS_FILE)["blueprint_digest"] != "old"
    assert not any((scene_dir / name).exists() for name in (SUPPORT_GRAPH_FILE, OBSERVATION_PLAN_FILE, RENDER_GRAPH_FILE))

    # A visible threshold that the automatic portal catalogue missed is not an
    # arbitrary force-add: only an explicit confirmation may persist the
    # bounded wall-free/raw-gap exception, and it becomes an open portal for
    # subsequent support-grid materialisation.
    from navigation_dataset.edge_builder import EdgeValidation
    import navigation_dataset.graph_pipeline as graph_pipeline

    monkeypatch.setattr(
        graph_pipeline,
        "validate_scene_graph_edge",
        lambda *args, **kwargs: (
            EdgeValidation(False, "rejected", "not_certified_doorway", 1.25, 0, 19, False, raw_gap_run_cells=8),
            {},
        ),
    )
    target_id = edited.nodes[-1].node_id
    status, response = daemon._apply_opticalnav_graph_edits(handler, project_dir, "scene-v4", {
        "graph_scope": "navigation_place",
        "ops": [{"client_op_id": "certify-1", "type": "add_edge", "source": "a", "target": target_id, "certify_opening": True}],
    })
    assert status.value == 200
    certified = read_viewpoint_graph(scene_dir / PLACE_GRAPH_FILE).edges[-1]
    assert certified.extras["portal_source"] == "user_certified"
    assert certified.extras["manual_opening"]["certified"] is True
    from navigation_dataset.route_motion import _portal_is_open
    assert _portal_is_open(certified)


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


def test_v3_catalog_includes_ready_apartment_and_office_workspaces_but_not_single_room_ir(tmp_path):
    project_dir = tmp_path / "opticalnav-v0.2"
    project_dir.mkdir(parents=True)
    (project_dir / "dataset.json").write_text(json.dumps({
        "layout_version": "opticalnav_project_catalog_v3",
        "project_name": "opticalnav-v0.2",
        "scenes": [{
            "scene_id": "infinigen_office_20260823",
            "episode_count": 12,
            "split_counts": {"train": 12},
        }],
    }), encoding="utf-8")
    scene_root = project_dir / "scenes"
    (scene_root / "infinigen_office_20260823").mkdir(parents=True)
    apartment = scene_root / "infinigen_apartment_natural_v1_20260828"
    apartment.mkdir()
    (apartment / "authoring_map.json").write_text("{}", encoding="utf-8")
    office = scene_root / "infinigen_office_20260822"
    office.mkdir()
    (office / "scene_annotation.json").write_text("{}", encoding="utf-8")
    single_room = scene_root / "infinigen_single_room_office_20260829_v02"
    single_room.mkdir()
    (single_room / "authoring_map.json").write_text("{}", encoding="utf-8")
    # A directory name is not enough: abandoned workspace names must not be
    # selectable before import has produced authoring input.
    (scene_root / "infinigen_kr_29927241_office").mkdir()

    summary = RenderDaemon(repo_root=tmp_path)._opticalnav_project_summary(project_dir)

    assert [row["scene_id"] for row in summary["scenes"]] == [
        "infinigen_apartment_natural_v1_20260828",
        "infinigen_office_20260822",
        "infinigen_office_20260823",
    ]
    assert summary["split_counts"] == {"train": 12}
    apartment_row = summary["scenes"][0]
    assert apartment_row["status"] == "workspace_unregistered"
    assert apartment_row["catalog_source"] == "editor_workspace"
    assert apartment_row["authoring_map_ref"] == (
        "scenes/infinigen_apartment_natural_v1_20260828/authoring_map.json"
    )


def test_v3_catalog_cache_refreshes_when_candidate_authoring_input_appears(tmp_path):
    project_dir = tmp_path / "opticalnav-v0.2"
    project_dir.mkdir(parents=True)
    (project_dir / "dataset.json").write_text(json.dumps({
        "layout_version": "opticalnav_project_catalog_v3",
        "project_name": "opticalnav-v0.2",
        "scenes": [],
    }), encoding="utf-8")
    office = project_dir / "scenes" / "infinigen_office_20260822"
    office.mkdir(parents=True)
    daemon = RenderDaemon(repo_root=tmp_path)

    assert daemon._opticalnav_project_summary(project_dir)["scenes"] == []
    (office / "authoring_map.json").write_text("{}", encoding="utf-8")

    assert [row["scene_id"] for row in daemon._opticalnav_project_summary(project_dir)["scenes"]] == [
        "infinigen_office_20260822",
    ]


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
