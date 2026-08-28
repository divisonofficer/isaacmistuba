from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "audit_modern_office_graph.py"
    spec = importlib.util.spec_from_file_location("audit_modern_office_graph", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _segment(index: int):
    x = float(index * 5)
    return {
        "segment_id": f"office_glass_{index:02d}", "room": "meeting-room_0/0", "corridor": "hallway_0/0",
        "wall_endpoints_m": [[x, 0.0], [x, 2.0]], "door_opening_m": [[x, 0.75], [x, 1.25]],
        "frame": {"profile_m": 0.04, "top_clearance_m": 0.1},
    }


def test_structural_glass_audit_accepts_tags_door_crossings_and_room_viewpoints(tmp_path: Path):
    mod = _module()
    segments = [_segment(i) for i in range(1, 4)]
    source = {"office_style": "modern_glass_v1", "office_style_digest": "style", "structural_glass": {
        "requested_partition_count": 3, "eligible_segment_count": 3, "digest": "glass", "segments": segments}}
    (tmp_path / "office_layout_manifest.json").write_text(json.dumps(source))
    objects = []
    for segment in segments:
        objects.append({"type": "glass_wall", "metadata": {"source_custom_properties": {
            "transparent_partition": True, "office_wall_segment_id": segment["segment_id"]}}})
    for room, center in (("meeting-room_0/0.floor", [0.0, -1.0]), ("office_0/0.floor", [5.0, -1.0]), ("open-office_0/0.floor", [10.0, -1.0])):
        objects.append({"type": "landmark", "geometry": {"center": center, "size_m": [2.0, 0.1, 2.0]},
                        "metadata": {"blender_name": room}})
    (tmp_path / "authoring_map.json").write_text(json.dumps({"objects": objects}))
    nodes = [{"node_id": f"n{i}", "position": [float(i * 5), -1.0, 0.0]} for i in range(3)]
    edges = []
    for i, segment in enumerate(segments):
        x = float((i + 1) * 5)
        edges.append({"edge_id": f"e{i}", "path_polyline": [[x - 0.2, -1.0], [x + 0.2, -1.0]]})
    graph = {"nodes": nodes, "edges": edges, "metadata": {}}
    (tmp_path / "viewpoint_graph.json").write_text(json.dumps(graph))
    result = mod.audit(source_manifest=tmp_path / "office_layout_manifest.json", scene_dir=tmp_path)
    assert result["status"] == "passed"
    assert result["installed_partition_ids"] == ["office_glass_01", "office_glass_02", "office_glass_03"]
    assert set(result["room_types_with_viewpoints"]) == {"meeting-room", "office", "open-office"}


def test_wide_v2_audit_requires_twenty_panes_and_every_work_bay(tmp_path: Path):
    mod = _module()
    segments = [_segment(i) for i in range(1, 11)]
    for index, segment in enumerate(segments, 1):
        segment["segment_id"] = f"office_glass_v2_{index:02d}"
        segment["room"] = f"open-office_0/{(index - 1) % 3}" if index <= 3 else "meeting-room_0/0"
    source = {"office_style": "modern_glass_v2", "office_style_digest": "style", "work_bay_rooms": [
        "open-office_0/0", "open-office_0/1", "open-office_0/2",
    ], "structural_glass": {"requested_partition_count": 10, "requested_pane_count": 20,
        "eligible_segment_count": 10, "digest": "glass", "segments": segments}}
    (tmp_path / "office_layout_manifest.json").write_text(json.dumps(source))
    objects = []
    for segment in segments:
        for pane in range(2):
            objects.append({"type": "glass_wall", "metadata": {"source_custom_properties": {
                "transparent_partition": True, "glass_pane": True,
                "office_wall_segment_id": segment["segment_id"], "glass_pane_index": pane,
            }}})
    floors = [
        ("open-office_0/0.floor", [0.0, -1.0]), ("open-office_0/1.floor", [5.0, -1.0]),
        ("open-office_0/2.floor", [10.0, -1.0]), ("meeting-room_0/0.floor", [15.0, -1.0]),
        ("office_0/0.floor", [20.0, -1.0]),
    ]
    for room, center in floors:
        objects.append({"type": "landmark", "geometry": {"center": center, "size_m": [2.0, 0.1, 2.0]},
                        "metadata": {"blender_name": room}})
    (tmp_path / "authoring_map.json").write_text(json.dumps({"objects": objects}))
    nodes = [{"node_id": f"n{i}", "position": [float(i * 5), -1.0, 0.0]} for i in range(5)]
    edges = []
    for i, segment in enumerate(segments):
        x = float((i + 1) * 5)
        edges.append({"edge_id": f"e{i}", "path_polyline": [[x - 0.2, -1.0], [x + 0.2, -1.0]]})
    (tmp_path / "viewpoint_graph.json").write_text(json.dumps({"nodes": nodes, "edges": edges, "metadata": {}}))
    result = mod.audit(source_manifest=tmp_path / "office_layout_manifest.json", scene_dir=tmp_path)
    assert result["status"] == "passed"
    assert len(result["installed_partition_ids"]) == 10
    assert result["work_bays_with_viewpoints"] == source["work_bay_rooms"]
