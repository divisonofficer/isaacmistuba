from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from mitsuba_converter.ir_render_plan import LIGHTING_PRESETS, _axis, _camera_key, _fps, build_render_plan


def _graph(nodes: int = 32) -> dict:
    return {
        "nodes": [
            {"node_id": f"vp_{index:03d}", "position": [index % 8, index // 8, 0.0],
             "headings": [{"yaw_deg": 0.0}, {"yaw_deg": 90.0}, {"yaw_deg": 180.0}]}
            for index in range(nodes)
        ]
    }


def test_render_plan_is_deterministic_unique_and_balanced() -> None:
    first = build_render_plan(_graph(), requested_pose_count=100, seed=41, scene_id="room")
    second = build_render_plan(_graph(), requested_pose_count=100, seed=41, scene_id="room")
    changed = build_render_plan(_graph(), requested_pose_count=100, seed=42, scene_id="room")
    assert first == second
    assert first["source_graph_digest"]
    assert first["render_plan_digest"] != changed["render_plan_digest"]
    assert len(first["groups"]) == len(LIGHTING_PRESETS) == 4
    counts = [len(group["poses"]) for group in first["groups"]]
    assert max(counts) - min(counts) <= 1
    poses = [(pose["viewpoint_id"], pose["heading_deg"]) for group in first["groups"] for pose in group["poses"]]
    assert len(poses) == len(set(poses)) == 96  # graph has 32 nodes x 3 headings
    assert first["clamped"] is True


def test_sparse_graph_is_clamped_and_keeps_recipe_contract() -> None:
    plan = build_render_plan(_graph(2), requested_pose_count=100, seed=1, scene_id="tiny")
    assert plan["actual_pose_count"] == 6
    assert plan["clamped"] and plan["clamp_reason"] == "candidate_pose_count"
    for group in plan["groups"]:
        lighting = group["lighting"]
        assert lighting["recipe_digest"]
        assert lighting["side_axis_xy"] == plan["side_key_axis_xy"]


def test_content_aware_plan_enforces_sparse_ceiling_and_is_deterministic() -> None:
    graph = _graph(100)
    visibility = {"probe_digest": "probe", "candidates": {}}
    classes = ("informative", "structural", "sparse_negative", "rejected")
    for node in graph["nodes"]:
        for heading in node["headings"]:
            index = int(node["node_id"].split("_")[-1])
            utility_class = classes[index % len(classes)]
            visibility["candidates"][f"{node['node_id']}@{heading['yaw_deg']:.6f}"] = {
                "utility_class": utility_class, "utility_score": 0.9 - index / 1000,
                "visible_categories": [f"c{index % 7}"], "nonstructural_fraction": 0.3,
            }
    first = build_render_plan(graph, requested_pose_count=200, seed=7, scene_id="room",
                              visibility=visibility, adaptive_budget=True)
    second = build_render_plan(graph, requested_pose_count=200, seed=7, scene_id="room",
                               visibility=visibility, adaptive_budget=True)
    assert first == second
    assert first["schema"].endswith(".v2")
    assert first["actual_pose_count"] <= 200
    counts = first["selection"]["class_counts"]
    assert counts["sparse_negative"] <= int(first["actual_pose_count"] * 0.15)
    assert first["reserve_poses"]


def test_queue_plan_tasks_keep_lighting_and_make_unique_frame_ids() -> None:
    path = Path(__file__).resolve().parents[3] / "apps" / "render_ir_principled_dataset_queue.py"
    spec = importlib.util.spec_from_file_location("ir_principled_queue_test", path)
    assert spec and spec.loader
    queue_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queue_module)
    graph = _graph(10)
    plan = build_render_plan(graph, requested_pose_count=20, seed=3, scene_id="room")
    specs = queue_module._plan_specs(graph, plan)
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    args = SimpleNamespace(eye_height=1.2, target_height=1.08, width=64, height=48, fov=60.0)
    tasks = [queue_module._task(nodes[node], yaw, lighting, args, (0.0, 0.0, 0.0), "fingerprint", "pbr", True) for node, yaw, lighting in specs]
    assert len(tasks) == 20 == len({task["frame_id"] for task in tasks})
    assert all("__l_" in task["frame_id"] for task in tasks)
    assert all(task["lighting"]["render_plan_digest"] == plan["render_plan_digest"] for task in tasks)


def test_coverage_illumination_honours_adaptive_cap_and_is_legacy_subset() -> None:
    graph = _graph(100)  # 300 candidate node-heading poses; force the small-room cap of 240.
    for index, node in enumerate(graph["nodes"]):
        node["position"] = [index % 5, (index // 5) * .2, 0.0]
    illumination = {
        "contract": "fixture", "manifest_digest": "fixture",
        "assets": {"overcast": {"path": "fixture.hdr", "sha256": "a" * 64}},
        "conditions": [
            {"id": f"condition_{index}", "external_asset": "overcast"}
            for index in range(6)
        ],
    }
    plan = build_render_plan(graph, requested_pose_count=400, seed=17, scene_id="room",
                             adaptive_budget=True, illumination=illumination, paired_fraction=.25)
    assert plan["sampler_version"].endswith("v2")
    assert plan["actual_pose_count"] == 240
    assert plan["illumination"]["paired_pose_count"] == 60
    assert plan["illumination"]["single_pose_count"] == 180
    assert plan["illumination"]["expected_frame_count"] == 540
    assert [len(group["poses"]) for group in plan["groups"]] == [90] * 6
    paired = [pose for group in plan["groups"] for pose in group["poses"] if pose["capture_kind"] == "paired"]
    assert len({pose["pair_id"] for pose in paired}) == 60
    assert all(sum(pose["pair_id"] == pair_id for pose in paired) == 6 for pair_id in {pose["pair_id"] for pose in paired})

    # The corrected task set must be re-attestable from the old v1 expansion.
    candidates = [
        {"viewpoint_id": node["node_id"], "heading_deg": heading["yaw_deg"], "position_xy": node["position"][:2]}
        for node in graph["nodes"] for heading in node["headings"]
    ]
    candidates.sort(key=lambda item: (item["viewpoint_id"], item["heading_deg"]))
    center, _ = _axis([tuple(item["position_xy"]) for item in candidates])
    span = max(math.hypot(x - center[0], y - center[1]) for x, y in (item["position_xy"] for item in candidates)) * 2.0
    rng = random.Random(17)
    paired_legacy = _fps(candidates, 60, rng, span)
    paired_keys = {(item["viewpoint_id"], item["heading_deg"]) for item in paired_legacy}
    legacy_singles = [item for item in candidates if (item["viewpoint_id"], item["heading_deg"]) not in paired_keys]
    legacy_tasks = {
        (pose["viewpoint_id"], pose["heading_deg"], condition["id"])
        for index, condition in enumerate(illumination["conditions"])
        for pose in paired_legacy + [single for ordinal, single in enumerate(legacy_singles) if ordinal % 6 == index]
    }
    corrected_tasks = {
        (pose["viewpoint_id"], pose["heading_deg"], group["lighting"]["id"])
        for group in plan["groups"] for pose in group["poses"]
    }
    assert corrected_tasks <= legacy_tasks


def test_reference_subset_v2_renders_every_base_pose_and_partitions_variations() -> None:
    illumination = {
        "contract": "fixture", "manifest_digest": "fixture",
        "assets": {"overcast": {"path": "fixture.hdr", "sha256": "a" * 64}},
        "conditions": [
            {"id": "reference_neutral_v1", "external_asset": "overcast"},
            *[
                {"id": f"variation_{index}", "external_asset": "overcast"}
                for index in range(5)
            ],
        ],
    }
    plan = build_render_plan(
        _graph(40), requested_pose_count=100, seed=29, scene_id="room",
        illumination=illumination, paired_fraction=.20,
        illumination_pairing_policy="reference_subset_v2",
    )
    groups = {group["lighting"]["id"]: group for group in plan["groups"]}
    reference = groups.pop("reference_neutral_v1")["poses"]
    reference_keys = {_camera_key(pose) for pose in reference}
    variation_key_sets = [{_camera_key(pose) for pose in group["poses"]} for group in groups.values()]

    assert plan["schema"] == "robomituba.ir_principled_render_plan.v4"
    assert plan["actual_pose_count"] == plan["unique_pose_count"] == 100
    assert plan["illumination"]["base_pose_count"] == 100
    assert plan["illumination"]["expected_frame_count"] == 200
    assert len(reference) == 100
    assert [len(keys) for keys in variation_key_sets] == [20] * 5
    assert set().union(*variation_key_sets) == reference_keys
    assert sum(len(keys) for keys in variation_key_sets) == len(set().union(*variation_key_sets))

    pair_counts: dict[str, int] = {}
    for group in plan["groups"]:
        for pose in group["poses"]:
            pair_counts[pose["pair_id"]] = pair_counts.get(pose["pair_id"], 0) + 1
    assert set(pair_counts.values()) == {2}


def test_queue_accepts_reference_subset_v2_plan_schema() -> None:
    """The v4 plan producer and rolling queue must advance in lockstep."""
    path = Path(__file__).resolve().parents[3] / "apps" / "render_ir_principled_dataset_queue.py"
    spec = importlib.util.spec_from_file_location("ir_principled_queue_reference_plan_test", path)
    assert spec and spec.loader
    queue_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queue_module)
    illumination = {
        "contract": "fixture", "manifest_digest": "fixture",
        "assets": {"overcast": {"path": "fixture.hdr", "sha256": "a" * 64}},
        "conditions": [
            {"id": "reference_neutral_v1", "external_asset": "overcast"},
            *[{"id": f"variation_{index}", "external_asset": "overcast"} for index in range(5)],
        ],
    }
    graph = _graph(12)
    plan = build_render_plan(
        graph, requested_pose_count=20, seed=41, scene_id="room", illumination=illumination,
        paired_fraction=.20, illumination_pairing_policy="reference_subset_v2",
    )
    assert plan["schema"] == "robomituba.ir_principled_render_plan.v4"
    assert len(queue_module._plan_specs(graph, plan)) == plan["illumination"]["expected_frame_count"]


def test_showcase_independent_pose_floor_rejects_sparse_camera_set() -> None:
    graph = _graph(2)
    camera_sets = {
        "poses": [
            {"viewpoint_id": "n0", "heading_deg": 0.0, "position_xy": [0.0, 0.0]},
            {"viewpoint_id": "n1", "heading_deg": 90.0, "position_xy": [1.0, 0.0]},
        ],
        "camera_sets": [],
    }
    with pytest.raises(ValueError, match="independent camera pose minimum"):
        build_render_plan(graph, requested_pose_count=10, seed=1, scene_id="showcase",
                          camera_sets=camera_sets, min_unique_pose_count=3)
