from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import threading
from typing import Any, Iterable

from .object_footprint import (
    ROOM_SHELL_OBJECT_TYPES as _ROOM_SHELL_OBJECT_TYPES,
    WALL_OBJECT_TYPES as _WALL_OBJECT_TYPES,
    object_blocks_at_height as _object_blocks_at_height,
    object_footprint as _object_footprint,
    point_in_footprint as _point_in_footprint,
)


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
    text = json.dumps(viewpoint_graph_to_payload(graph), ensure_ascii=False, indent=2) + "\n"
    tmp = output.with_name(f"{output.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, output)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return output


def _next_manual_node_id(graph: ViewpointGraph) -> str:
    existing = {node.node_id for node in graph.nodes}
    n = 1
    while True:
        candidate = f"vp_manual_{n:04d}"
        if candidate not in existing:
            return candidate
        n += 1


def append_manual_node(graph: ViewpointGraph, x: float, y: float, *, heading_count: int | None = None) -> ViewpointNode:
    """Add a manually-placed viewpoint node with N evenly spaced headings."""
    headings_n = int(heading_count or graph.node_heading_count or 8)
    if headings_n < 1:
        headings_n = 1
    headings = [
        ViewpointHeading(heading_id=f"h_{int(round(360 * i / headings_n)):03d}", yaw_deg=float(360 * i / headings_n))
        for i in range(headings_n)
    ]
    node = ViewpointNode(
        node_id=_next_manual_node_id(graph),
        position=[float(x), float(y), 0.0],
        clearance_m=0.0,
        tags=["manual"],
        headings=headings,
        extras={"manual": True},
    )
    graph.nodes.append(node)
    return node


def remove_node(graph: ViewpointGraph, node_id: str) -> bool:
    """Remove a node by id along with any edges that touch it."""
    before = len(graph.nodes)
    graph.nodes = [n for n in graph.nodes if n.node_id != node_id]
    if len(graph.nodes) == before:
        return False
    graph.edges = [e for e in graph.edges if e.source != node_id and e.target != node_id]
    return True


def remove_nodes(graph: ViewpointGraph, node_ids: Iterable[str]) -> list[str]:
    """Remove multiple nodes (and their incident edges) in one pass.

    Returns the list of node_ids that were actually present and removed, in the
    order they first appear in ``node_ids`` (unknown / duplicate ids are ignored).
    """
    present = {n.node_id for n in graph.nodes}
    removed: list[str] = []
    seen: set[str] = set()
    for nid in node_ids:
        if nid in present and nid not in seen:
            removed.append(nid)
            seen.add(nid)
    if not removed:
        return []
    graph.nodes = [n for n in graph.nodes if n.node_id not in seen]
    graph.edges = [e for e in graph.edges if e.source not in seen and e.target not in seen]
    return removed


def find_object_overlapping_nodes(
    graph: ViewpointGraph,
    objects: Iterable[JsonDict],
    *,
    margin_m: float = 0.0,
    include_walls: bool = False,
    robot_height_m: float = 1.2,
) -> list[str]:
    """node_ids whose (x, y) position falls inside any object footprint (+margin).

    ``objects`` are authoring/overlay object dicts (``{type, geometry, ...}``).
    Room-shell (floor/ceiling) is always skipped; walls/glass are skipped unless
    ``include_walls`` is True; objects mounted at/above ``robot_height_m`` (e.g.
    ceiling lights) are skipped because the robot passes under them. Point
    footprints respect ``yaw_deg`` exactly. Used to auto-flag grid vertices that
    landed on top of furniture so the user can review and remove them.
    """
    margin = float(margin_m)
    footprints: list[tuple] = []
    for obj in objects or []:
        otype = str(obj.get("type") or "")
        if otype in _ROOM_SHELL_OBJECT_TYPES:
            continue
        if not include_walls and otype in _WALL_OBJECT_TYPES:
            continue
        # Respect an explicit ``blocks_navigation: false``. Imported mesh scenes
        # carry floor/ceiling as non-blocking ``landmark`` objects (the authoring
        # schema has no floor/ceiling type) with whole-room footprints — flagging
        # every node. Unset/None keeps the legacy behaviour.
        nav = obj.get("navigation") or {}
        if nav.get("blocks_navigation") is False:
            continue
        geometry = obj.get("geometry") or {}
        if not _object_blocks_at_height(geometry, robot_height_m=robot_height_m):
            continue
        fp = _object_footprint(geometry, margin=margin)
        if fp is not None:
            footprints.append(fp)
    if not footprints:
        return []
    overlapping: list[str] = []
    for node in graph.nodes:
        pos = node.position or []
        if len(pos) < 2:
            continue
        x, y = float(pos[0]), float(pos[1])
        for fp in footprints:
            if _point_in_footprint(x, y, fp):
                overlapping.append(node.node_id)
                break
    return overlapping


def _next_manual_edge_id(graph: ViewpointGraph) -> str:
    existing = {edge.edge_id for edge in graph.edges}
    n = 1
    while True:
        candidate = f"edge_manual_{n:04d}"
        if candidate not in existing:
            return candidate
        n += 1


def find_node(graph: ViewpointGraph, node_id: str) -> ViewpointNode | None:
    for n in graph.nodes:
        if n.node_id == node_id:
            return n
    return None


def find_edge_by_endpoints(graph: ViewpointGraph, source: str, target: str) -> ViewpointEdge | None:
    for e in graph.edges:
        if (e.source == source and e.target == target) or (e.source == target and e.target == source):
            return e
    return None


def append_edge(
    graph: ViewpointGraph,
    source: str,
    target: str,
    *,
    edge_id: str | None = None,
    distance_m: float | None = None,
    weight: float | None = None,
) -> ViewpointEdge | None:
    """Add a (possibly manual) edge between two existing nodes.

    Returns the new (or pre-existing) edge, or ``None`` if either endpoint is unknown.
    """
    src_node = find_node(graph, source)
    tgt_node = find_node(graph, target)
    if src_node is None or tgt_node is None or source == target:
        return None
    existing = find_edge_by_endpoints(graph, source, target)
    if existing is not None:
        return existing
    import math as _math

    if distance_m is None:
        dx = float(src_node.position[0]) - float(tgt_node.position[0])
        dy = float(src_node.position[1]) - float(tgt_node.position[1])
        distance_m = _math.hypot(dx, dy)
    if weight is None:
        weight = float(distance_m)
    new_id = edge_id or _next_manual_edge_id(graph)
    edge = ViewpointEdge(
        edge_id=new_id,
        source=source,
        target=target,
        distance_m=float(distance_m),
        weight=float(weight),
        collision_free=True,
        hazard_crossing=False,
        path_polyline=[
            [float(src_node.position[0]), float(src_node.position[1])],
            [float(tgt_node.position[0]), float(tgt_node.position[1])],
        ],
        extras={"manual": True},
    )
    graph.edges.append(edge)
    return edge


def compute_connected_components(graph: ViewpointGraph) -> dict[str, Any]:
    """Compute connected components over the undirected edge set.

    Returns ``{"node_to_component": {node_id: idx}, "components": [{"index", "size", "node_ids"}]}``
    where component 0 is the largest. Isolated nodes (no edges) form singleton components.
    """
    adj: dict[str, list[str]] = {n.node_id: [] for n in graph.nodes}
    for e in graph.edges:
        if e.source in adj and e.target in adj:
            adj[e.source].append(e.target)
            adj[e.target].append(e.source)
    visited: set[str] = set()
    components_raw: list[list[str]] = []
    for start in adj:
        if start in visited:
            continue
        stack = [start]
        bucket: list[str] = []
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            bucket.append(nid)
            for nxt in adj.get(nid, ()):
                if nxt not in visited:
                    stack.append(nxt)
        components_raw.append(bucket)
    components_raw.sort(key=len, reverse=True)
    node_to_component: dict[str, int] = {}
    components: list[dict[str, Any]] = []
    for idx, bucket in enumerate(components_raw):
        for nid in bucket:
            node_to_component[nid] = idx
        components.append({
            "index": idx,
            "size": len(bucket),
            "node_ids": bucket,
        })
    return {
        "node_to_component": node_to_component,
        "components": components,
    }


def remove_edge(graph: ViewpointGraph, edge_id: str) -> bool:
    before = len(graph.edges)
    graph.edges = [e for e in graph.edges if e.edge_id != edge_id]
    return len(graph.edges) != before
