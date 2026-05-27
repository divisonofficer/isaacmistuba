from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path, PurePosixPath
from typing import Any


JsonDict = dict[str, Any]


@dataclass
class ViewpointHeading:
    heading_id: str
    yaw_deg: float
    sensor_observations: dict[str, str] = field(default_factory=dict)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class ViewpointNode:
    node_id: str
    position: list[float]
    clearance_m: float = 0.0
    tags: list[str] = field(default_factory=list)
    headings: list[ViewpointHeading] = field(default_factory=list)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class ViewpointEdge:
    edge_id: str
    source: str
    target: str
    distance_m: float
    weight: float
    collision_free: bool = True
    hazard_crossing: bool = False
    path_polyline: list[list[float]] = field(default_factory=list)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class ViewpointGraph:
    scene_id: str
    graph_id: str
    node_heading_count: int
    nodes: list[ViewpointNode] = field(default_factory=list)
    edges: list[ViewpointEdge] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)
    schema_version: str = "0.2"


def _validate_relative_ref(value: str, *, field_name: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{field_name} must be package-relative: {value}")


def validate_viewpoint_graph(graph: ViewpointGraph) -> None:
    if not graph.scene_id:
        raise ValueError("scene_id must not be empty.")
    if not graph.graph_id:
        raise ValueError("graph_id must not be empty.")
    if graph.node_heading_count <= 0:
        raise ValueError("node_heading_count must be positive.")
    node_ids = {node.node_id for node in graph.nodes}
    if len(node_ids) != len(graph.nodes):
        raise ValueError("nodes must have unique node_id values.")
    if not graph.nodes:
        raise ValueError("at least one viewpoint node is required.")
    for node in graph.nodes:
        if not node.node_id:
            raise ValueError("node_id must not be empty.")
        if len(node.position) != 3:
            raise ValueError(f"{node.node_id}.position must be [x, y, yaw].")
        heading_ids = {heading.heading_id for heading in node.headings}
        if len(heading_ids) != len(node.headings):
            raise ValueError(f"{node.node_id}.headings must have unique heading_id values.")
        if len(node.headings) != graph.node_heading_count:
            raise ValueError(f"{node.node_id} must have {graph.node_heading_count} headings.")
        for heading in node.headings:
            if not heading.heading_id:
                raise ValueError("heading_id must not be empty.")
            float(heading.yaw_deg)
            for key, ref in heading.sensor_observations.items():
                if not key:
                    raise ValueError("sensor_observations keys must not be empty.")
                _validate_relative_ref(ref, field_name=f"{node.node_id}.{heading.heading_id}.{key}")
    edge_ids = {edge.edge_id for edge in graph.edges}
    if len(edge_ids) != len(graph.edges):
        raise ValueError("edges must have unique edge_id values.")
    for edge in graph.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            raise ValueError(f"edge {edge.edge_id} references unknown node.")
        if edge.source == edge.target:
            raise ValueError(f"edge {edge.edge_id} source and target must differ.")
        if edge.distance_m <= 0 or edge.weight <= 0:
            raise ValueError(f"edge {edge.edge_id} distance_m and weight must be positive.")
        if not edge.collision_free:
            raise ValueError(f"edge {edge.edge_id} is not collision_free and should not be in the graph.")
    json.dumps(graph.metadata)


def viewpoint_graph_to_payload(graph: ViewpointGraph) -> JsonDict:
    return asdict(graph)


def viewpoint_graph_from_payload(payload: JsonDict) -> ViewpointGraph:
    graph = ViewpointGraph(
        scene_id=str(payload["scene_id"]),
        graph_id=str(payload["graph_id"]),
        node_heading_count=int(payload.get("node_heading_count", 12)),
        nodes=[
            ViewpointNode(
                node_id=str(node["node_id"]),
                position=[float(item) for item in node["position"]],
                clearance_m=float(node.get("clearance_m", 0.0)),
                tags=[str(item) for item in node.get("tags", [])],
                headings=[
                    ViewpointHeading(
                        heading_id=str(heading["heading_id"]),
                        yaw_deg=float(heading["yaw_deg"]),
                        sensor_observations={str(k): str(v) for k, v in dict(heading.get("sensor_observations", {})).items()},
                        extras=dict(heading.get("extras", {})),
                    )
                    for heading in node.get("headings", [])
                ],
                extras=dict(node.get("extras", {})),
            )
            for node in payload.get("nodes", [])
        ],
        edges=[
            ViewpointEdge(
                edge_id=str(edge["edge_id"]),
                source=str(edge.get("source", edge.get("from"))),
                target=str(edge.get("target", edge.get("to"))),
                distance_m=float(edge["distance_m"]),
                weight=float(edge.get("weight", edge["distance_m"])),
                collision_free=bool(edge.get("collision_free", True)),
                hazard_crossing=bool(edge.get("hazard_crossing", False)),
                path_polyline=[[float(value) for value in point] for point in edge.get("path_polyline", [])],
                extras=dict(edge.get("extras", {})),
            )
            for edge in payload.get("edges", [])
        ],
        metadata=dict(payload.get("metadata", {})),
        schema_version=str(payload.get("schema_version", "0.2")),
    )
    validate_viewpoint_graph(graph)
    return graph


def read_viewpoint_graph(path: str | Path) -> ViewpointGraph:
    return viewpoint_graph_from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def write_viewpoint_graph(path: str | Path, graph: ViewpointGraph) -> Path:
    validate_viewpoint_graph(graph)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(viewpoint_graph_to_payload(graph), ensure_ascii=False, indent=2), encoding="utf-8")
    return output
