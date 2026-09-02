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


def _illumination(condition_ids: list[str]) -> dict:
    return {
        "contract": "fixture", "manifest_digest": "fixture",
        "assets": {"overcast": {"path": "fixture.hdr", "sha256": "a" * 64}},
        "conditions": [{"id": ident, "external_asset": "overcast"} for ident in condition_ids],
    }


def test_legacy_plan_digests_are_frozen() -> None:
    """Pin the digests every published v1/v3/v4 dataset is resumed against.

    ``render_plan_digest`` reaches ``_stage_artifact_state``,
    ``_adopt_compatible_frames`` and ``plan_adoption_manifest.json``.  Any
    refactor of ``build_render_plan`` -- notably factoring the inlined pair-id
    expression into a helper -- must leave these values untouched.
    """
    coverage = build_render_plan(_graph(), requested_pose_count=100, seed=41, scene_id="room")
    assert coverage["render_plan_digest"] == (
        "15eaad52d3aac98f93cc7e574c51545a2c662bcb6aad615359d516fea36c2933"
    )
    assert coverage["groups"][0]["lighting"]["recipe_digest"] == (
        "048a4ddb61b58fcb22f1c6f7236b609d6f9c91167eeb4a4a80ecf13a7ca57a1a"
    )

    graph = _graph(100)
    for index, node in enumerate(graph["nodes"]):
        node["position"] = [index % 5, (index // 5) * .2, 0.0]
    legacy_six_way = build_render_plan(
        graph, requested_pose_count=400, seed=17, scene_id="room", adaptive_budget=True,
        illumination=_illumination([f"condition_{index}" for index in range(6)]),
        paired_fraction=.25,
    )
    assert legacy_six_way["schema"] == "robomituba.ir_principled_render_plan.v3"
    assert legacy_six_way["render_plan_digest"] == (
        "421ce6a2149a84daa0e967ca6450861ffc4a71cbf09c98fb935ad75e6b7ea092"
    )

    reference_subset = build_render_plan(
        _graph(40), requested_pose_count=100, seed=29, scene_id="room",
        illumination=_illumination(["reference_neutral_v1", *[f"variation_{i}" for i in range(5)]]),
        paired_fraction=.20, illumination_pairing_policy="reference_subset_v2",
    )
    assert reference_subset["schema"] == "robomituba.ir_principled_render_plan.v4"
    assert reference_subset["render_plan_digest"] == (
        "cc2f7aab05158ec5be0b9dffd6b460f5fd2ba1886846c7a4c3f6a30c7051a9a2"
    )
    assert reference_subset["groups"][0]["lighting"]["recipe_digest"] == (
        "1e0a4a7b3b2e44670a01a609f7aff5cdb2ba76f0192dfc86c8f3874892c4dc06"
    )


def test_legacy_pair_id_string_is_frozen() -> None:
    """The pair-id is an inlined f-string in two branches; freeze its exact shape.

    ``{scene_id}:{viewpoint_id}:{heading % 360:.3f}:{anchor_id}`` -- note the
    trailing colon with an empty anchor.  A helper extraction that drops the
    empty component would silently rewrite every published plan digest.
    """
    for policy, plan in (
        ("legacy_six_way_v1", build_render_plan(
            _graph(40), requested_pose_count=100, seed=29, scene_id="room",
            illumination=_illumination([f"condition_{index}" for index in range(6)]),
            paired_fraction=.20)),
        ("reference_subset_v2", build_render_plan(
            _graph(40), requested_pose_count=100, seed=29, scene_id="room",
            illumination=_illumination(["reference_neutral_v1",
                                        *[f"variation_{i}" for i in range(5)]]),
            paired_fraction=.20, illumination_pairing_policy="reference_subset_v2")),
    ):
        pair_ids = sorted({
            pose["pair_id"] for group in plan["groups"] for pose in group["poses"]
            if pose.get("pair_id")
        })
        assert pair_ids[0] == "room:vp_000:0.000:", policy
        assert all(ident.count(":") == 3 and ident.endswith(":") for ident in pair_ids), policy


def test_camera_key_is_unchanged_for_graph_poses() -> None:
    """v1-v4 poses never carry ``pose_id``; the 6-DoF dispatch must not reach them."""
    plan = build_render_plan(_graph(16), requested_pose_count=24, seed=5, scene_id="room")
    poses = [pose for group in plan["groups"] for pose in group["poses"]]
    assert poses and not any("pose_id" in pose for pose in poses)
    assert _camera_key(poses[0]) == (
        str(poses[0]["viewpoint_id"]), round(float(poses[0]["heading_deg"]) % 360.0, 6), "",
    )


def _free_poses(count: int = 60, anchors: int = 6) -> dict:
    """A 6-DoF sampler payload, shaped as the sampler emits it."""
    poses = []
    for index in range(count):
        anchor = f"obj:a{index % anchors}"
        orbit = f"orbit:{anchor}:00"
        poses.append({
            "pose_id": f"{anchor}|orbit|00|{index:03d}", "viewpoint_id": orbit,
            "orbit_id": orbit, "anchor_id": anchor, "capture_kind": "orbit",
            "sequence_index": index, "heading_deg": (index * 17.0) % 360.0,
            "position_xy": [math.cos(index) * 2.0, math.sin(index) * 2.0],
            "eye_mitsuba": [0.0, 1.2, 0.0], "target_mitsuba": [1.0, 0.5, 0.0],
            "up_mitsuba": [0.0, 1.0, 0.0], "roll_deg": 0.0,
            "elevation_deg": -20.0, "anchor_distance_m": 1.4,
        })
    return {"schema": "robomituba.ir_camera_6dof_poses.v1",
            "sampler_version": "object-orbit-6dof-v1", "poses": poses,
            "free_pose_digest": "deadbeef", "source_authoring_map_digest": "cafe",
            "anchor_count": anchors, "orbit_count": anchors, "tuple_count": 0,
            "radius_range_m": [1.0, 2.0], "camera_elevation_range_deg": [-30.0, 55.0],
            "orbits": [], "tuples": []}


def _bank(conditions: int = 6) -> dict:
    ids = ["reference_neutral_v1"] + [f"variation_{index}_v1" for index in range(conditions - 1)]
    return {
        "schema": "robomituba.ir_illumination_bank.v2",
        "contract": "illumination-fixture-diversity-v2",
        "manifest_digest": "bank-digest",
        "assets": {"overcast_day": {"path": "a.exr", "sha256": "0" * 64}},
        "conditions": [
            {"id": name, "external_asset": "overcast_day", "internal_energy_scale": 1.0,
             "fixtures": {"policy": "group_mask_v1", "subset_salt": name,
                          "groups": {"ceiling": {"on_probability": 1.0}}}}
            for name in ids
        ],
    }


def test_free_pose_plan_declares_its_own_universe() -> None:
    plan = build_render_plan({"nodes": [], "edges": []}, requested_pose_count=60, seed=7,
                             scene_id="room", free_poses=_free_poses(),
                             illumination=_bank(),
                             illumination_pairing_policy="variation_subset_v3")
    assert plan["schema"] == "robomituba.ir_principled_render_plan.v5"
    assert plan["pose_universe"] == "object_orbit_6dof_v1"
    assert plan["sampler_version"] == "object-orbit-6dof-v1"
    # The graph is not the pose universe, so provenance points at the sampler.
    assert plan["free_poses"]["free_pose_digest"] == "deadbeef"
    assert plan["free_poses"]["source_authoring_map_digest"] == "cafe"


def test_variation_subset_renders_every_base_pose_and_a_full_lighting_stack() -> None:
    """The rule: N base poses once, M of them under every variation."""
    plan = build_render_plan({"nodes": [], "edges": []}, requested_pose_count=60, seed=7,
                             scene_id="room", free_poses=_free_poses(60),
                             illumination=_bank(6), variation_pose_count=10,
                             illumination_pairing_policy="variation_subset_v3")
    groups = {group["lighting"]["id"]: group["poses"] for group in plan["groups"]}
    assert len(groups["reference_neutral_v1"]) == 60
    variations = [name for name in groups if name != "reference_neutral_v1"]
    assert len(variations) == 5
    for name in variations:
        assert len(groups[name]) == 10

    # Every variation condition covers the *same* ten poses, so lighting is
    # isolated for a fixed camera rather than confounded with viewpoint.
    stacks = [{pose["pose_id"] for pose in groups[name]} for name in variations]
    assert all(stack == stacks[0] for stack in stacks)
    assert stacks[0] <= {pose["pose_id"] for pose in groups["reference_neutral_v1"]}

    assert plan["illumination"]["expected_frame_count"] == 60 + 10 * 5
    assert plan["illumination"]["variation_pose_count"] == 10
    assert plan["illumination"]["variation_condition_count"] == 5


def test_only_the_variation_subset_carries_a_pair_id() -> None:
    """A pose seen under one lighting is not paired with anything.

    Tagging every base pose would advertise a lighting stack of size one.
    """
    plan = build_render_plan({"nodes": [], "edges": []}, requested_pose_count=60, seed=7,
                             scene_id="room", free_poses=_free_poses(),
                             illumination=_bank(), variation_pose_count=10,
                             illumination_pairing_policy="variation_subset_v3")
    by_pose: dict[str, set[str]] = {}
    appearances: dict[str, int] = {}
    for group in plan["groups"]:
        for pose in group["poses"]:
            appearances[pose["pose_id"]] = appearances.get(pose["pose_id"], 0) + 1
            if pose.get("pair_id"):
                by_pose.setdefault(pose["pose_id"], set()).add(pose["pair_id"])

    # Exactly the ten poses that appear under every condition are paired, and
    # each of them uses one pair_id across its whole stack.
    assert len(by_pose) == 10
    assert all(len(ids) == 1 for ids in by_pose.values())
    assert all(next(iter(ids)).startswith("room:") for ids in by_pose.values())
    assert all(appearances[pose_id] == 6 for pose_id in by_pose)
    assert all(appearances[pose_id] == 1 for pose_id in appearances if pose_id not in by_pose)


def test_variation_subset_spreads_the_lighting_stack_over_anchors() -> None:
    """Ten frames of one object teach less about lighting than ten objects."""
    plan = build_render_plan({"nodes": [], "edges": []}, requested_pose_count=60, seed=7,
                             scene_id="room", free_poses=_free_poses(60, anchors=6),
                             illumination=_bank(), variation_pose_count=6,
                             illumination_pairing_policy="variation_subset_v3")
    varied = [pose for group in plan["groups"]
              if group["lighting"]["id"] != "reference_neutral_v1" for pose in group["poses"]]
    assert len({pose["anchor_id"] for pose in varied}) == 6


def test_variation_subset_enforces_the_base_pose_band() -> None:
    with pytest.raises(ValueError, match="50-100 base poses"):
        build_render_plan({"nodes": [], "edges": []}, requested_pose_count=20, seed=7,
                          scene_id="room", free_poses=_free_poses(20), illumination=_bank(),
                          illumination_pairing_policy="variation_subset_v3")


def test_variation_subset_cannot_be_starved_of_conditions() -> None:
    """Five variations is the floor, and the bank rule already guarantees it.

    A v2 bank must carry 6-12 conditions and exactly one reference, so fewer
    than five variations is rejected before the policy is reached.  The policy
    keeps its own check as a guard, but this is the reachable failure.
    """
    with pytest.raises(ValueError, match="6-12 conditions"):
        build_render_plan({"nodes": [], "edges": []}, requested_pose_count=60, seed=7,
                          scene_id="room", free_poses=_free_poses(), illumination=_bank(5),
                          illumination_pairing_policy="variation_subset_v3")


def test_free_poses_are_keyed_by_pose_id_not_viewpoint() -> None:
    """Orbit members share a viewpoint id; the legacy key would collapse them."""
    first, second = _free_poses(2, anchors=1)["poses"]
    second["heading_deg"] = first["heading_deg"]
    assert first["viewpoint_id"] == second["viewpoint_id"]
    assert _camera_key(first) != _camera_key(second)
