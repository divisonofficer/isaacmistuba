"""Template instruction-generator tests (deterministic; no LLM).

Covers context extraction (rooms/objects/mirror-glass), the four generator levels,
node→room association, and graceful degradation when scene data is missing.
"""
from __future__ import annotations

from navigation_dataset.instruction_generators import (
    EpisodeCore,
    build_instruction_context,
    generate_instructions,
)


class _Node:
    def __init__(self, node_id, x, y):
        self.node_id = node_id
        self.position = [x, y, 0.0]


class _Graph:
    def __init__(self, nodes):
        self.nodes = nodes


class _Goal:
    def __init__(self, region_id, label, center):
        self.region_id = region_id
        self.label = label
        self.center = center


class _Hazard:
    def __init__(self, hazard_type):
        self.hazard_type = hazard_type
        self.geometry = {}


class _Annotation:
    def __init__(self, goals, hazards):
        self.goal_regions = goals
        self.hazard_regions = hazards


def _floor(name, cx, cy, w, d):
    return {
        "type": "landmark",
        "metadata": {"kind": "structure", "blender_name": f"{name}.floor"},
        "geometry": {"type": "point", "center": [cx, cy], "size_m": [w, 2.5, d], "yaw_deg": 0.0},
    }


def _obj(otype, cx, cy, factory=None):
    md = {"kind": "furniture"}
    if factory:
        md["factory"] = factory
    return {"type": otype, "metadata": md, "geometry": {"type": "point", "center": [cx, cy], "size_m": [0.5, 0.5, 0.5]}}


def _authoring_map():
    return {
        "objects": [
            _floor("living-room_0/0", 1.0, 1.0, 4.0, 4.0),   # x in [-1,3], y in [-1,3]
            _floor("kitchen_0/0", 7.0, 1.0, 4.0, 4.0),       # x in [5,9], y in [-1,3]
            _obj("chair", 1.2, 1.2),
            _obj("table", 6.8, 1.0, factory="TableDiningFactory"),
            _obj("landmark", 6.5, 0.5, factory="BedFactory"),   # bed via factory
            _obj("landmark", 2.0, 2.0, factory="BookStackFactory"),  # decorative -> dropped
            {"type": "mirror_wall", "metadata": {}, "geometry": {"type": "line", "start": [3.0, 0.5], "end": [3.0, 1.5]}},
        ],
        "regions": [],
    }


def _core(path_nodes, node_xy, scenario="goal_only", goal_label="the goal"):
    expanded = []
    for i, n in enumerate(path_nodes):
        if i == 0:
            expanded.append((n, "h_000", "turn_right_30", {"turn_deg": -30}))
            expanded.append((n, "h_000", "turn_right_30", {"turn_deg": -30}))
        if i < len(path_nodes) - 1:
            expanded.append((n, "h_000", "move_forward", {"forward_m": 1.0}))
        else:
            expanded.append((n, "h_000", "stop", {}))
    return EpisodeCore(
        episode_id="ep_test_000001", scenario=scenario, path_nodes=list(path_nodes),
        node_xy=node_xy, expanded_steps=expanded, goal_label=goal_label,
    )


def _ctx():
    nodes = [_Node("vp_1", 1.0, 1.0), _Node("vp_2", 2.5, 1.0), _Node("vp_3", 7.0, 1.0)]
    graph = _Graph(nodes)
    ann = _Annotation([_Goal("goal_corner", "the goal", [7.0, 1.0, 0.0])], [_Hazard("glass_door")])
    ctx = build_instruction_context(graph, ann, _authoring_map(), perturbation=None)
    node_xy = {n.node_id: (n.position[0], n.position[1]) for n in nodes}
    return ctx, node_xy


def test_context_extracts_rooms_objects_and_mirror():
    ctx, _ = _ctx()
    room_names = {name for name, _ in ctx.rooms}
    assert "living room" in room_names and "kitchen" in room_names
    nouns = {n for n, _, _ in ctx.objects}
    assert {"chair", "table", "bed"} <= nouns
    assert "book" not in " ".join(nouns)        # decorative BookStack dropped
    assert len(ctx.mirrors) == 1


def test_node_room_association():
    ctx, _ = _ctx()
    assert ctx.node_room(1.0, 1.0) == "living room"
    assert ctx.node_room(7.0, 1.0) == "kitchen"
    assert ctx.node_room(50.0, 50.0) is None


def test_generates_four_levels_with_grounding():
    ctx, node_xy = _ctx()
    core = _core(["vp_1", "vp_2", "vp_3"], node_xy, scenario="detour")
    ins = generate_instructions(core, ctx, use_llm=False)
    by_type = {i["type"]: i for i in ins}
    assert set(by_type) == {"goal", "turn_by_turn", "landmark", "perception"}
    assert all(i["lang"] == "en" and i["source"] == "template" and i["text"].strip() for i in ins)
    # landmark crosses living room -> kitchen
    assert "living room" in by_type["landmark"]["text"] and "kitchen" in by_type["landmark"]["text"]
    # turn-by-turn groups the two right turns into 60°
    assert "right 60°" in by_type["turn_by_turn"]["text"].lower()
    # perception references the mirror near the path (vp_2 at x=2.5, mirror at x=3.0)
    assert "mirror" in by_type["perception"]["text"]
    assert by_type["perception"]["grounding"]["mirror_side"] in ("left", "right")


def test_perception_skipped_when_no_hazard_near_path():
    ctx, node_xy = _ctx()
    # Path entirely in the kitchen, far from the mirror at x=3.0.
    core = _core(["vp_3"], {"vp_3": (7.0, 1.0)})
    ins = generate_instructions(core, ctx, use_llm=False)
    assert "perception" not in {i["type"] for i in ins}


def test_degrades_without_scene_data():
    # No authoring map / annotation: only the goal scenario instruction survives.
    ctx = build_instruction_context(_Graph([]), None, None, None)
    core = _core(["vp_1", "vp_2"], {"vp_1": (0.0, 0.0), "vp_2": (1.0, 0.0)})
    ins = generate_instructions(core, ctx, use_llm=False)
    types = {i["type"] for i in ins}
    assert "goal" in types and "turn_by_turn" in types
    assert "landmark" not in types and "perception" not in types
