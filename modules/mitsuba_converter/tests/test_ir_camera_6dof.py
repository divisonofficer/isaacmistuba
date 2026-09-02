"""Behaviour the 6-DoF camera sampler exists to guarantee."""
from __future__ import annotations

import math

import pytest

from mitsuba_converter.ir_camera_6dof import (
    EYE_HEIGHT_RANGE_M,
    MIN_BASELINE_M,
    MIN_FITTED_RADIUS_M,
    RADIUS_RANGE_M,
    build_free_camera_poses,
    room_bounds,
)


def _floor(width=8.0, depth=8.0):
    return {"id": "room_0_0.floor", "type": "floor",
            "geometry": {"center": [0.0, 0.0], "size_m": [width, 0.02, depth],
                         "base_height_m": 0.0}}


def _prop(oid, x, y, *, base=0.0, height=0.5, extent=0.4, depth=None):
    return {"id": oid, "type": "prop",
            "geometry": {"center": [x, y],
                         "size_m": [extent, height, depth if depth is not None else extent],
                         "base_height_m": base}}


def _anchor(aid, x, y_up, z, *, half=0.2, object_id=None):
    return {"anchor_id": aid, "object_id": object_id or aid,
            "center_mitsuba": [x, y_up, z], "center_xy": [x, z],
            "half_extent_xy": [half, half], "height_m": half * 2,
            "target_height_m": y_up}


def _map(objects):
    return {"objects": objects, "regions": []}


def test_room_bounds_prefer_the_floor_over_traversable_regions():
    """Regions are inset by the robot radius; a camera has no body.

    On the bathroom scene the traversable inset excluded four of six anchors.
    """
    authoring = {
        "objects": [_floor(width=3.254, depth=2.877)],
        "regions": [{"id": "traversable_room_00", "bounds": [1.0, 1.0, 2.0, 2.0]}],
    }
    assert room_bounds(authoring) == pytest.approx((-1.627, -1.4385, 1.627, 1.4385))

    # Only with no floor at all does it fall back to the regions.
    assert room_bounds({"objects": [], "regions": authoring["regions"]}) == (1.0, 1.0, 2.0, 2.0)


def test_poses_look_both_down_and_up():
    """The point of the rewrite: pitch follows geometry, it is not a constant.

    The graph sampler emitted one near-horizontal pitch for every frame.
    """
    objects = [_floor(), _prop("low", 0.0, 0.0, base=0.0, height=0.1),
               _prop("high", 2.5, 0.0, base=2.45, height=0.3)]
    anchors = [_anchor("obj:low", 0.0, 0.05, 0.0, object_id="low"),
               _anchor("obj:high", 2.5, 2.6, 0.0, object_id="high")]
    result = build_free_camera_poses(anchors, _map(objects), scene_id="s", seed=7)

    elevations = [p["elevation_deg"] for p in result["poses"]]
    assert min(elevations) < -15.0, "no downward views"
    assert max(elevations) > 15.0, "no upward views"


def test_every_pose_holds_the_working_distance_band():
    """Active NIR irradiance falls as 1/r^2, so standoff is the whole point."""
    objects = [_floor(), _prop("t", 0.0, 0.0, height=0.6)]
    anchors = [_anchor("obj:t", 0.0, 0.3, 0.0, object_id="t")]
    result = build_free_camera_poses(anchors, _map(objects), scene_id="s", seed=3)

    assert result["poses"]
    for pose in result["poses"]:
        radius = math.dist(pose["eye_mitsuba"], anchors[0]["center_mitsuba"])
        assert MIN_FITTED_RADIUS_M <= radius <= RADIUS_RANGE_M[1] + 1e-6
        assert EYE_HEIGHT_RANGE_M[0] <= pose["eye_height_m"] <= EYE_HEIGHT_RANGE_M[1]


def test_the_room_shell_is_not_an_occluder():
    """A room-sized wall box would place every camera 'inside an object'.

    Walls are enforced through the floor bounds instead.
    """
    objects = [_floor(),
               {"id": "room_0_0.wall", "type": "wall",
                "geometry": {"center": [0.0, 0.0], "size_m": [8.0, 2.6, 8.0],
                             "base_height_m": 0.0}},
               _prop("t", 0.0, 0.0, height=0.6)]
    result = build_free_camera_poses([_anchor("obj:t", 0.0, 0.3, 0.0, object_id="t")],
                                     _map(objects), scene_id="s", seed=3)
    assert result["poses"], "room shell swallowed every candidate"


def test_a_pose_above_a_table_is_admitted():
    """A robot-height traversability grid cannot express this.

    The table blocks the floor, but 1.6 m is clear above it.
    """
    from mitsuba_converter.ir_camera_6dof import _inside

    table = {"cx": 1.0, "cy": 0.0, "hx": 0.6, "hy": 0.6, "z0": 0.0, "z1": 0.75}
    assert _inside(table, 1.0, 0.0, 0.40) is True     # inside the table itself
    assert _inside(table, 1.0, 0.0, 1.60) is False    # clear above it


def test_line_of_sight_is_blocked_by_a_tall_slab():
    """A wall between the camera and the anchor rejects that side of the ring."""
    objects = [_floor(), _prop("t", 0.0, 0.0, height=0.6),
               _prop("blocker", 0.0, 1.2, base=0.0, height=2.4, extent=6.0, depth=0.2)]
    result = build_free_camera_poses([_anchor("obj:t", 0.0, 0.3, 0.0, object_id="t")],
                                     _map(objects), scene_id="s", seed=3)

    assert result["rejected"].get("occluded", 0) > 0
    # Nothing survives on the far side of the slab.
    assert all(p["position_xy"][1] < 1.2 for p in result["poses"])


def test_framing_rejects_anchors_that_are_too_small_or_too_large():
    objects = [_floor(width=20.0, depth=20.0)]
    tiny = build_free_camera_poses([_anchor("obj:tiny", 0.0, 0.5, 0.0, half=0.005)],
                                   _map(objects), scene_id="s", seed=3)
    huge = build_free_camera_poses([_anchor("obj:huge", 0.0, 0.5, 0.0, half=4.0)],
                                   _map(objects), scene_id="s", seed=3)
    assert tiny["actual_pose_count"] == 0
    assert huge["actual_pose_count"] == 0
    assert tiny["rejected"].get("frame_fill", 0) > 0


def test_orbit_members_are_contiguous_and_close_together():
    objects = [_floor(), _prop("t", 0.0, 0.0, height=0.6)]
    result = build_free_camera_poses([_anchor("obj:t", 0.0, 0.3, 0.0, object_id="t")],
                                     _map(objects), scene_id="s", seed=11)
    orbits = [o["orbit_id"] for o in result["orbits"]]
    assert orbits, "expected at least one orbit in an open room"
    for orbit_id in orbits:
        members = sorted((p for p in result["poses"] if p.get("orbit_id") == orbit_id),
                         key=lambda p: p["sequence_index"])
        assert [p["sequence_index"] for p in members] == list(range(len(members)))
        for a, b in zip(members, members[1:]):
            assert math.dist(a["position_xy"], b["position_xy"]) < 1.0


def test_sparse_tuples_keep_baseline_and_azimuth_span():
    objects = [_floor(), _prop("t", 0.0, 0.0, height=0.6)]
    result = build_free_camera_poses([_anchor("obj:t", 0.0, 0.3, 0.0, object_id="t")],
                                     _map(objects), scene_id="s", seed=11)
    for spec in result["tuples"]:
        members = [p for p in result["poses"] if p.get("tuple_id") == spec["tuple_id"]]
        assert spec["azimuth_span_deg"] >= 90.0
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                assert math.dist(a["position_xy"], b["position_xy"]) >= MIN_BASELINE_M


def test_adding_an_anchor_does_not_disturb_the_others():
    """Seeds are digest-derived, not drawn from one shared RNG stream."""
    objects = [_floor(), _prop("a", 0.0, 0.0, height=0.6), _prop("b", 3.0, 0.0, height=0.6)]
    first = _anchor("obj:a", 0.0, 0.3, 0.0, object_id="a")
    second = _anchor("obj:b", 3.0, 0.3, 0.0, object_id="b")

    alone = build_free_camera_poses([first], _map(objects), scene_id="s", seed=5)
    together = build_free_camera_poses([first, second], _map(objects), scene_id="s", seed=5)

    def only_a(result):
        return [p for p in result["poses"] if p["anchor_id"] == "obj:a"]

    assert only_a(alone) == only_a(together)


def test_output_is_deterministic_and_seed_sensitive():
    objects = [_floor(), _prop("t", 0.0, 0.0, height=0.6)]
    anchors = [_anchor("obj:t", 0.0, 0.3, 0.0, object_id="t")]
    args = (anchors, _map(objects))
    a = build_free_camera_poses(*args, scene_id="s", seed=5)
    b = build_free_camera_poses(*args, scene_id="s", seed=5)
    c = build_free_camera_poses(*args, scene_id="s", seed=6)
    assert a["free_pose_digest"] == b["free_pose_digest"]
    assert a["free_pose_digest"] != c["free_pose_digest"]


def test_pose_ids_are_unique_and_carry_a_capture_kind():
    objects = [_floor(), _prop("t", 0.0, 0.0, height=0.6)]
    result = build_free_camera_poses([_anchor("obj:t", 0.0, 0.3, 0.0, object_id="t")],
                                     _map(objects), scene_id="s", seed=11)
    ids = [p["pose_id"] for p in result["poses"]]
    assert len(ids) == len(set(ids))
    assert {p["capture_kind"] for p in result["poses"]} <= {"orbit", "sparse_tuple"}
    # viewpoint_id must stay populated: downstream consumers hard-index it.
    assert all(p["viewpoint_id"] for p in result["poses"])
