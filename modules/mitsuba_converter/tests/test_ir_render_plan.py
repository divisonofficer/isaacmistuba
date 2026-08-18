from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from mitsuba_converter.ir_render_plan import LIGHTING_PRESETS, build_render_plan


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
    tasks = [queue_module._task(nodes[node], yaw, lighting, args, (0.0, 0.0, 0.0), "fingerprint") for node, yaw, lighting in specs]
    assert len(tasks) == 20 == len({task["frame_id"] for task in tasks})
    assert all("__l_" in task["frame_id"] for task in tasks)
    assert all(task["lighting"]["render_plan_digest"] == plan["render_plan_digest"] for task in tasks)
