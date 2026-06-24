"""Read-only QA for mesh-derived viewpoint graphs.

Measures the defects the manual editing was fixing (outside-room nodes,
wall-crossing edges, disconnected components) so a build can be scored against
the manual-final baselines.
"""

from __future__ import annotations

from typing import Any

from .edge_builder import line_cells
from .traversability import world_to_cell
from .viewpoint_graph import ViewpointGraph, compute_connected_components
from .walkable_surface import WalkableSurface


def graph_qa_report(
    graph: ViewpointGraph,
    surface: WalkableSurface,
    *,
    robot_radius_m: float = 0.25,
) -> dict[str, Any]:
    spec = surface.grid.spec
    floor = surface.floor_mask
    eroded = surface.clearance_m >= float(robot_radius_m)

    def _in(mask, x: float, y: float) -> bool:
        cx, cy = world_to_cell(spec, x, y)
        return 0 <= cx < spec.width and 0 <= cy < spec.height and bool(mask[cy, cx])

    outside_floor = [n.node_id for n in graph.nodes if not _in(floor, n.position[0], n.position[1])]

    wall_crossing = []
    for e in graph.edges:
        ex = e.extras or {}
        if ex.get("portal") or ex.get("bridge"):
            continue  # portal/bridge edges intentionally thread eroded doorways
        a = e.path_polyline[0] if e.path_polyline else e.path_polyline
        b = e.path_polyline[1] if e.path_polyline and len(e.path_polyline) > 1 else None
        if b is None:
            continue
        for cx, cy in line_cells(surface.grid, a, b):
            if not (0 <= cx < spec.width and 0 <= cy < spec.height and bool(eroded[cy, cx])):
                wall_crossing.append(e.edge_id)
                break

    comps = compute_connected_components(graph).get("components", [])
    clearances = [float(n.clearance_m) for n in graph.nodes if n.clearance_m]

    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "portal_nodes": sum(1 for n in graph.nodes if "portal" in (n.tags or [])),
        "outside_floor_nodes": len(outside_floor),
        "outside_floor_node_ids": outside_floor[:20],
        "wall_crossing_edges": len(wall_crossing),
        "wall_crossing_edge_ids": wall_crossing[:20],
        "connected_components": len(comps),
        "largest_component": comps[0]["size"] if comps else 0,
        "isolated_fragment_nodes": sum(c["size"] for c in comps[1:]) if len(comps) > 1 else 0,
        "clearance_min_m": round(min(clearances), 3) if clearances else None,
        "clearance_median_m": round(sorted(clearances)[len(clearances) // 2], 3) if clearances else None,
        "portals_unresolved": sum(1 for p in surface.portals if not getattr(p, "resolved", True)),
    }
