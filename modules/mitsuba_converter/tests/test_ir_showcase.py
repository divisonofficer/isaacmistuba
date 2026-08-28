from __future__ import annotations

import json
from pathlib import Path

from mitsuba_converter.ir_render_plan import build_render_plan
from mitsuba_converter.ir_showcase import (
    CAMERA_SET_MAX,
    CAMERA_SET_MIN,
    MIN_ACCEPTED_POSES,
    acceptance_report,
    build_camera_sets,
    composition_contract,
    registry_digest,
)


def _registry() -> dict:
    path = Path(__file__).resolve().parents[3] / "configs" / "infinigen" / "prop_pbr_registry_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _graph() -> dict:
    nodes = []
    # A dense walkable lattice lets each local anchor choose a real multi-view
    # baseline. Headings intentionally contain an irrelevant 360° sweep.
    for x in range(-2, 15):
        for y in range(-2, 11):
            nodes.append({"node_id": f"vp_{x + 2:02d}_{y + 2:02d}", "position": [float(x), float(y), 0.0],
                          "clearance_m": 1.0, "camera_height_m": 1.2,
                          "headings": [{"yaw_deg": value} for value in range(0, 360, 30)]})
    return {"nodes": nodes, "edges": []}


def _anchors() -> list[dict]:
    return [{"anchor_id": f"anchor:{index:02d}", "center_xy": [float(index % 8) * 1.7, float(index // 8) * 3.2],
             "target_height_m": .82} for index in range(16)]


def _metric() -> dict:
    return {"utility_score": .9, "camera_clearance_m": 1.0, "forward_clearance_m": 2.0,
            "visible_pbr_object_count": 13, "material_id_count": 9, "specular_eligible_object_count": 9,
            "object_pixel_fraction": .02, "specular_pixel_fraction": .20, "roughness_bin_count": 4,
            "structural_or_empty_fraction": .3, "wall_only": False, "severe_occlusion": False,
            "visible_object_ids": [f"object:{index}" for index in range(14)],
            "target_object_ids": ["target"]}


def _probe(graph: dict, anchors: list[dict]) -> dict:
    return {"anchor_candidates": {
        f"{anchor['anchor_id']}:{node['node_id']}": _metric()
        for anchor in anchors for node in graph["nodes"]
    }}


def test_registry_sampling_is_deterministic_and_balanced() -> None:
    registry = _registry()
    first = composition_contract(registry, seed=31, target_count=20)
    second = composition_contract(registry, seed=31, target_count=20)
    assert first == second
    assert first["registry_digest"] == registry_digest(registry)
    assert len(first["props"]) == 20
    assert len(first["category_counts"]) >= 8
    assert all(value <= 2 for value in first["factory_counts"].values())
    assert first["class_counts"]["polished_metallic"] >= 3
    assert first["class_counts"]["glossy_dielectric"] >= 4
    assert first["class_counts"]["coated"] >= 3
    assert first["class_counts"]["rough_textured"] >= 3


def test_anchor_camera_sets_keep_four_to_twelve_views_and_never_expand_headings() -> None:
    graph, anchors = _graph(), _anchors()
    cameras = build_camera_sets(graph, anchors, seed=9, pose_budget=120, probe=_probe(graph, anchors))
    assert cameras["actual_pose_count"] >= MIN_ACCEPTED_POSES
    assert cameras == build_camera_sets(graph, anchors, seed=9, pose_budget=120, probe=_probe(graph, anchors))
    assert all(CAMERA_SET_MIN <= row["member_count"] <= CAMERA_SET_MAX for row in cameras["camera_sets"])
    assert all(row["azimuth_span_deg"] >= 90.0 for row in cameras["camera_sets"])
    assert all(pose["capture_kind"] == "anchor_multiview" for pose in cameras["poses"])
    assert all(pose["camera_set_ids"] and pose["anchor_id"] for pose in cameras["poses"])
    # Graph headings are deliberately ignored: every showcase yaw looks at its anchor.
    assert any(pose["heading_deg"] not in {row["yaw_deg"] for row in graph["nodes"][0]["headings"]} for pose in cameras["poses"])


def test_showcase_illumination_uses_selected_pose_set_and_keeps_pair_contract() -> None:
    graph, anchors = _graph(), _anchors()
    cameras = build_camera_sets(graph, anchors, seed=9, pose_budget=120, probe=_probe(graph, anchors))
    illumination = {"contract": "fixture", "manifest_digest": "fixture", "assets": {"hdr": {"path": "fixture.hdr", "sha256": "a" * 64}},
                    "conditions": [{"id": f"light_{index}", "external_asset": "hdr"} for index in range(6)]}
    plan = build_render_plan(graph, requested_pose_count=120, seed=9, scene_id="showcase", camera_sets=cameras,
                             illumination=illumination, paired_fraction=.25,
                             showcase_provenance={"composition_digest": "composition"})
    assert plan["actual_pose_count"] == cameras["actual_pose_count"]
    assert plan["candidate_pose_count"] == cameras["actual_pose_count"]
    assert plan["camera_sets"]["camera_set_digest"] == cameras["camera_set_digest"]
    pairs = [pose for group in plan["groups"] for pose in group["poses"] if pose["capture_kind"] == "paired"]
    assert all(sum(pose["pair_id"] == pair_id for pose in pairs) == 6 for pair_id in {pose["pair_id"] for pose in pairs})
    assert plan["illumination"]["expected_frame_count"] == len(pairs) + plan["illumination"]["single_pose_count"]


def test_showcase_can_fill_independent_pose_floor_without_fake_lighting_views() -> None:
    graph, anchors = _graph(), _anchors()
    cameras = build_camera_sets(graph, anchors, seed=9, pose_budget=120, probe=_probe(graph, anchors),
                                 min_independent_pose_count=50)
    assert cameras["independent_pose_count"] >= 50
    assert cameras["supplemental_pose_count"] >= 0
    assert len({(p["viewpoint_id"], round(p["heading_deg"] % 360.0, 5)) for p in cameras["poses"]}) >= 50
    supplemental = [p for p in cameras["poses"] if p["capture_kind"] == "coverage_supplement"]
    assert all(not p["camera_set_ids"] for p in supplemental)


def test_acceptance_rejects_insufficient_shared_view_contract() -> None:
    graph, anchors = _graph(), _anchors()
    cameras = build_camera_sets(graph, anchors, seed=9, pose_budget=100, probe=_probe(graph, anchors))
    report = acceptance_report(cameras, probe=_probe(graph, anchors))
    assert report["status"] == "passed"
    bad = {**cameras, "poses": cameras["poses"][:3]}
    rejected = acceptance_report(bad, probe=_probe(graph, anchors))
    assert rejected["status"] == "failed"
    assert "insufficient_anchor_multiview_poses" in rejected["failures"]
