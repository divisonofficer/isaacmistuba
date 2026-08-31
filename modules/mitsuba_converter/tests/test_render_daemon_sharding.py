from types import SimpleNamespace

import mitsuba_converter.render_daemon as render_daemon
from mitsuba_converter.render_daemon import (
    _bind_graph_sweep_task_record,
    _interleaved_gpu_shard_assignments,
)


def test_interleaved_gpu_shard_assignments_feed_all_gpus_from_start():
    assignments = _interleaved_gpu_shard_assignments(10, [0, 1, 2, 3])

    assert [item["target_gpu_index"] for item in assignments] == [
        0, 1, 2, 3, 0, 1, 2, 3, 0, 1
    ]
    assert [item["shard_index"] for item in assignments] == [
        0, 1, 2, 3, 0, 1, 2, 3, 0, 1
    ]
    assert [item["shard_item_index"] for item in assignments] == [
        0, 0, 0, 0, 1, 1, 1, 1, 2, 2
    ]
    assert [item["shard_size"] for item in assignments] == [
        3, 3, 2, 2, 3, 3, 2, 2, 3, 3
    ]


def test_interleaved_gpu_shard_assignments_limit_gpus_to_item_count():
    assignments = _interleaved_gpu_shard_assignments(2, [0, 1, 2, 3])

    assert [item["target_gpu_index"] for item in assignments] == [0, 1]
    assert [item["shard_count"] for item in assignments] == [2, 2]
    assert [item["shard_size"] for item in assignments] == [1, 1]


def test_graph_sweep_task_records_bind_each_phase_request(monkeypatch):
    monkeypatch.setattr(
        render_daemon,
        "render_request_to_payload",
        lambda request: {"request_id": request.request_id},
    )
    rgb_request = SimpleNamespace(request_id="vp-1-rgb", extras={})
    polar_request = SimpleNamespace(request_id="vp-1-polar", extras={})
    sweep_requests = [
        SimpleNamespace(node_id="vp-1", heading_id="h-000", request=rgb_request),
        SimpleNamespace(node_id="vp-1", heading_id="h-000", request=polar_request),
    ]
    payloads = [
        {"phase": "rgb", "phase_index": 0},
        {"phase": "polar", "phase_index": 1},
    ]

    records = {}
    for ordinal, (sweep_request, payload) in enumerate(zip(sweep_requests, payloads)):
        request_key, record = _bind_graph_sweep_task_record(
            sweep_request,
            payload,
            logical_key=f"logical-{ordinal}",
            task_id=f"task-{ordinal}",
            ordinal=ordinal,
            project_id="opticalnav-v0.2",
            scene_id="scene-1",
            run_id="run-1",
            scene_version_id_value="scene-version-1",
            render_version_id="render-version-1",
            scene_variant_key="base",
            render_variant="auto",
            submission_group_id="group-1",
            variant_sequence_index=0,
            variant_sequence_total=2,
            previous_variant_batch_id=None,
        )
        records[request_key] = record

    assert len(records) == 2
    assert [record["phase"] for record in records.values()] == ["rgb", "polar"]
    assert rgb_request.extras["task_key"] == "task-0"
    assert rgb_request.extras["phase"] == "rgb"
    assert polar_request.extras["task_key"] == "task-1"
    assert polar_request.extras["phase"] == "polar"
    assert [record["request_payload"]["request_id"] for record in records.values()] == [
        "vp-1-rgb",
        "vp-1-polar",
    ]


def test_heading_batch_children_receive_versioned_output_identity(monkeypatch):
    """Worker child snapshots must not fall back to legacy bridge_jobs paths."""
    monkeypatch.setattr(
        render_daemon,
        "render_request_to_payload",
        lambda request: {"extras": dict(request.extras)},
    )
    children = [
        {"request_id": "child-0", "extras": {"unrelated": "keep"}},
        {"request_id": "child-1", "extras": {"unrelated": "keep"}},
    ]
    request = SimpleNamespace(
        request_id="leader",
        extras={
            "stokes_heading_batch_request_payloads": children,
            "stokes_heading_batch_view_keys": [
                {"node_id": "vp-1", "heading_id": "h-000"},
                {"node_id": "vp-2", "heading_id": "h-015"},
            ],
        },
    )
    sweep_request = SimpleNamespace(node_id="vp-1", heading_id="h-000", request=request)

    _bind_graph_sweep_task_record(
        sweep_request,
        {"phase": "polar", "phase_index": 1, "render_profile_id": "profile-1"},
        logical_key="logical-1", task_id="task-1", ordinal=0,
        project_id="opticalnav-v0.2", scene_id="scene-1", run_id="run-1",
        scene_version_id_value="scene-version-1", render_version_id="render-version-1",
        scene_variant_key="base", render_variant="auto", submission_group_id="group-1",
        variant_sequence_index=0, variant_sequence_total=1, previous_variant_batch_id=None,
    )

    payloads = request.extras["stokes_heading_batch_request_payloads"]
    assert [payload["extras"]["opticalnav_vp_id"] for payload in payloads] == ["vp-1", "vp-2"]
    assert [payload["extras"]["opticalnav_heading_id"] for payload in payloads] == ["h-000", "h-015"]
    for index, payload in enumerate(payloads):
        extras = payload["extras"]
        assert extras["render_version_id"] == "render-version-1"
        assert extras["opticalnav_project_id"] == "opticalnav-v0.2"
        assert extras["scene_variant_key"] == "base"
        assert extras["stokes_heading_batch_parent_task_key"] == "task-1"
        assert extras["stokes_heading_batch_child_index"] == index
        assert extras["unrelated"] == "keep"
