#!/usr/bin/env python3
"""Audit auto-graph-build quality against a scene's human edit history.

Reads ``<scene_dir>/graph_edit_history.jsonl`` and compares it against a
viewpoint graph (the current ``viewpoint_graph.json`` by default, or a baseline
candidate via ``--graph PATH``). Reports three metrics:

  - outdoor_pruning_recall:  fraction of nodes the human deleted that the new
                             algorithm did NOT generate. ↑ is better.
  - rug_fill_recall:          fraction of human-added nodes that the new
                             algorithm DID generate within ε of the manual
                             position. ↑ is better.
  - carving_relaxation_rate:  fraction of human-forced add_edges (those marked
                             ``blocked_by_obstacle`` in algo_context) whose
                             both endpoints exist in the new graph AND are
                             connected by an edge. ↑ is better.

The history is treated as a golden set: every human edit is one place where
auto generation was wrong. The metrics measure how many of those corrections
the new algorithm makes redundant.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _src in ("modules/navigation_dataset/src",):
    p = REPO_ROOT / _src
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ── history parsing ───────────────────────────────────────────────────────────


def _events(history_path: Path) -> list[dict]:
    return [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]


def _baseline_counts(events: list[dict]) -> dict[str, int]:
    """Initial (auto-generated) node/edge counts from the first build_graph event."""
    for ev in events:
        if ev.get("operation") == "build_graph":
            after = ev.get("after") or {}
            return {"nodes": int(after.get("nodes") or 0), "edges": int(after.get("edges") or 0)}
    return {"nodes": 0, "edges": 0}


def _deleted_node_ids(events: list[dict]) -> set[str]:
    """All node ids the human deleted across the session."""
    deleted: set[str] = set()
    for ev in events:
        if ev.get("operation") != "delete_nodes":
            continue
        params = ev.get("params") or {}
        for nid in params.get("requested") or []:
            deleted.add(str(nid))
    return deleted


def _deleted_node_positions(events: list[dict]) -> list[tuple[str, float, float]]:
    """Human-deleted nodes resolved to (id, x, y) using the event's deleted_nodes snapshot.

    The render_daemon's DELETE handler resolves each requested id to a record
    (id + position + extras) BEFORE removal and records it under
    ``event.deleted_nodes``. Events written before that schema (or events that
    failed to resolve an id) are skipped from the position list — they still
    contribute to the id-based recall via ``_deleted_node_ids``.
    """
    out: list[tuple[str, float, float]] = []
    seen: set[str] = set()
    for ev in events:
        if ev.get("operation") != "delete_nodes":
            continue
        for rec in ev.get("deleted_nodes") or []:
            nid = str(rec.get("id") or "")
            pos = rec.get("position") or []
            if len(pos) < 2 or nid in seen:
                continue
            seen.add(nid)
            out.append((nid, float(pos[0]), float(pos[1])))
    return out


def _added_node_positions(events: list[dict]) -> list[tuple[str, float, float]]:
    """Human-added nodes: (added_id, x, y)."""
    out: list[tuple[str, float, float]] = []
    for ev in events:
        if ev.get("operation") != "add_node":
            continue
        added = ev.get("added_node") or {}
        pos = added.get("position") or []
        if len(pos) < 2:
            params = ev.get("params") or {}
            x = params.get("x")
            y = params.get("y")
        else:
            x, y = pos[0], pos[1]
        if x is None or y is None:
            continue
        out.append((str(added.get("id") or ""), float(x), float(y)))
    return out


def _forced_edges(events: list[dict]) -> list[dict]:
    """Human add_edges that the algorithm had flagged as blocked_by_obstacle.

    Returns dicts with source_pos / target_pos (2D) so we can match endpoints
    against a new graph even when node ids changed.
    """
    out: list[dict] = []
    for ev in events:
        if ev.get("operation") != "add_edge":
            continue
        algo = ev.get("algo_context") or {}
        if str(algo.get("reason") or "") != "blocked_by_obstacle":
            continue
        added = ev.get("added_edge") or {}
        sp = added.get("source_pos") or []
        tp = added.get("target_pos") or []
        if len(sp) < 2 or len(tp) < 2:
            continue
        out.append({
            "source_pos": [float(sp[0]), float(sp[1])],
            "target_pos": [float(tp[0]), float(tp[1])],
            "distance_m": float(algo.get("distance_m") or added.get("distance_m") or 0.0),
            "hazard_crossing": bool(algo.get("hazard_crossing") or False),
        })
    return out


# ── graph loading ─────────────────────────────────────────────────────────────


def _load_graph(graph_path: Path) -> dict:
    return json.loads(graph_path.read_text())


def _graph_node_positions(graph: dict) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for n in graph.get("nodes") or []:
        pos = n.get("position") or []
        if len(pos) < 2:
            continue
        out[str(n.get("node_id") or n.get("id") or "")] = (float(pos[0]), float(pos[1]))
    return out


def _graph_edge_pairs(graph: dict) -> set[tuple[str, str]]:
    """Undirected (sorted) (source, target) pairs."""
    out: set[tuple[str, str]] = set()
    for e in graph.get("edges") or []:
        s = str(e.get("source") or "")
        t = str(e.get("target") or "")
        if not s or not t:
            continue
        out.add(tuple(sorted([s, t])))
    return out


def _nearest_node_within(
    positions: dict[str, tuple[float, float]], x: float, y: float, eps_m: float
) -> str | None:
    best_id, best_d2 = None, eps_m * eps_m + 1e-9
    for nid, (nx, ny) in positions.items():
        d2 = (nx - x) ** 2 + (ny - y) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_id = nid
    return best_id


# ── metrics ───────────────────────────────────────────────────────────────────


def _audit_graph(
    events: list[dict],
    graph: dict,
    *,
    fill_eps_m: float = 0.25,
    endpoint_eps_m: float = 0.30,
    prune_eps_m: float = 0.25,
) -> dict:
    baseline = _baseline_counts(events)
    deleted_ids = _deleted_node_ids(events)
    deleted_pos = _deleted_node_positions(events)
    added = _added_node_positions(events)
    forced = _forced_edges(events)

    node_pos = _graph_node_positions(graph)
    edge_pairs = _graph_edge_pairs(graph)
    node_ids = set(node_pos.keys())

    # 1a) outdoor_pruning_recall (id-based): deleted ids the new graph doesn't carry.
    #     Honest only when the new graph reuses the OLD id scheme. After a re-import
    #     the id space changes and this trivially hits 1.0 — use the position-based
    #     variant below for that case.
    pruned = sum(1 for nid in deleted_ids if nid not in node_ids)
    outdoor_recall = pruned / len(deleted_ids) if deleted_ids else None

    # 1b) outdoor_pruning_recall_pos (position-based): for each deleted position
    #     (resolved from the event's deleted_nodes snapshot), does the new graph
    #     have NO node within prune_eps_m? "Yes" = algorithm correctly pruned the
    #     spot. This survives a re-import (new ids) and is the metric to use when
    #     comparing OLD vs NEW algorithm.
    pruned_pos = sum(
        1 for (_id, x, y) in deleted_pos
        if _nearest_node_within(node_pos, x, y, prune_eps_m) is None
    )
    outdoor_recall_pos = pruned_pos / len(deleted_pos) if deleted_pos else None

    # 2) rug_fill_recall: human-added positions that the new graph fills with a
    #    node within fill_eps_m.
    filled = sum(1 for (_id, x, y) in added if _nearest_node_within(node_pos, x, y, fill_eps_m))
    fill_recall = filled / len(added) if added else None

    # 3) carving_relaxation_rate: forced edges whose endpoints both have a
    #    nearby node AND are connected in the new graph.
    relaxed = 0
    matched_endpoints = 0
    for fe in forced:
        sx, sy = fe["source_pos"]
        tx, ty = fe["target_pos"]
        s_id = _nearest_node_within(node_pos, sx, sy, endpoint_eps_m)
        t_id = _nearest_node_within(node_pos, tx, ty, endpoint_eps_m)
        if s_id and t_id and s_id != t_id:
            matched_endpoints += 1
            if tuple(sorted([s_id, t_id])) in edge_pairs:
                relaxed += 1
    relaxation_rate = relaxed / len(forced) if forced else None

    return {
        "scene_id": graph.get("scene_id"),
        "graph_id": graph.get("graph_id"),
        "history_events": len(events),
        "baseline_build": baseline,
        "new_graph_counts": {"nodes": len(node_ids), "edges": len(edge_pairs)},
        "summary": {
            "deleted_nodes": len(deleted_ids),
            "deleted_nodes_with_positions": len(deleted_pos),
            "added_nodes": len(added),
            "forced_edges_blocked": len(forced),
        },
        "metrics": {
            "outdoor_pruning_recall": _round(outdoor_recall),
            "outdoor_pruning_recall_pos": _round(outdoor_recall_pos),
            "rug_fill_recall": _round(fill_recall),
            "carving_relaxation_rate": _round(relaxation_rate),
        },
        "details": {
            "outdoor_pruned": pruned,
            "outdoor_pruned_pos": pruned_pos,
            "rug_filled": filled,
            "carving_relaxed": relaxed,
            "carving_endpoints_matched": matched_endpoints,
        },
        "params": {
            "fill_eps_m": fill_eps_m,
            "endpoint_eps_m": endpoint_eps_m,
            "prune_eps_m": prune_eps_m,
        },
    }


def audit(
    history_path: Path,
    graph_path: Path,
    *,
    fill_eps_m: float = 0.25,
    endpoint_eps_m: float = 0.30,
    prune_eps_m: float = 0.25,
) -> dict:
    """Audit a persisted candidate graph without modifying any scene artifact."""
    return _audit_graph(
        _events(history_path), _load_graph(graph_path),
        fill_eps_m=fill_eps_m, endpoint_eps_m=endpoint_eps_m, prune_eps_m=prune_eps_m,
    )


_FRESH_BUILD_DEFAULTS = {
    "resolution": 0.05,
    "robot_radius_m": 0.25,
    "robot_height_m": 1.2,
    "heading_count": 12,
    "min_node_spacing_m": 0.5,
    "min_clearance_m": 0.10,
    "camera_margin_m": 0.10,
    "doorway_gap_m": 0.45,
    "max_nodes": 300,
    "k_neighbors": 8,
    "max_edge_length_m": 1.5,
    "seed": 0,
}


def _latest_build_config(events: list[dict], overrides: dict[str, object | None]) -> dict[str, object]:
    """Use the latest build request when available; explicit CLI values win."""
    config: dict[str, object] = dict(_FRESH_BUILD_DEFAULTS)
    for event in reversed(events):
        if event.get("operation") != "build_graph":
            continue
        params = event.get("params") or {}
        for key in config:
            if params.get(key) is not None:
                config[key] = params[key]
        break
    for key, value in overrides.items():
        if value is not None:
            config[key] = value
    for key in ("max_nodes", "heading_count", "k_neighbors", "seed"):
        config[key] = int(config[key])
    for key in set(config) - {"max_nodes", "heading_count", "k_neighbors", "seed"}:
        config[key] = float(config[key])
    return config


def fresh_build_audit(
    history_path: Path,
    scene_dir: Path,
    *,
    overrides: dict[str, object | None] | None = None,
    fill_eps_m: float = 0.75,
    endpoint_eps_m: float = 0.30,
    prune_eps_m: float = 0.25,
) -> dict:
    """Build a disposable auto-only candidate and audit it against edit history.

    ``persist_grid=False`` and ``existing_graph=None`` are intentional: this is the
    regression path for the generator, not a request to alter manual corrections.
    """
    from navigation_dataset.graph_pipeline import _max_wall_run_cells, build_viewpoint_graph_core
    from navigation_dataset.viewpoint_graph import compute_connected_components

    events = _events(history_path)
    config = _latest_build_config(events, overrides or {})
    result = build_viewpoint_graph_core(
        str(scene_dir.name), scene_dir,
        graph_id=f"{scene_dir.name}_fresh_audit",
        persist_grid=False,
        existing_graph=None,
        **config,
    )
    graph_payload = {
        "scene_id": result.graph.scene_id,
        "graph_id": result.graph.graph_id,
        "nodes": [{"node_id": n.node_id, "position": list(n.position)} for n in result.graph.nodes],
        "edges": [{"edge_id": e.edge_id, "source": e.source, "target": e.target,
                   "distance_m": e.distance_m} for e in result.graph.edges],
    }
    report = _audit_graph(
        events, graph_payload,
        fill_eps_m=fill_eps_m, endpoint_eps_m=endpoint_eps_m, prune_eps_m=prune_eps_m,
    )
    positions = {n.node_id: n.position for n in result.graph.nodes}
    wall_crossings = 0
    if result.surface is not None and result.surface.wall_band_mask is not None:
        for edge in result.graph.edges:
            src, tgt = positions.get(edge.source), positions.get(edge.target)
            if src is not None and tgt is not None and _max_wall_run_cells(
                result.surface.wall_band_mask, result.grid.spec, src, tgt,
            ) > 0:
                wall_crossings += 1
    report["fresh_build"] = {
        "non_mutating": True,
        "config": config,
        "summary": result.summary,
        "edge_quality": {
            "max_edge_length_m": _round(max((e.distance_m for e in result.graph.edges), default=0.0), 4),
            "wall_crossing_edges": wall_crossings,
        },
        "connected_components": len(compute_connected_components(result.graph).get("components", [])),
    }
    return report


def _round(x: float | None, digits: int = 3) -> float | None:
    if x is None:
        return None
    return round(float(x), digits)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _print_table(report: dict) -> None:
    m = report["metrics"]
    d = report["details"]
    s = report["summary"]
    print(f"scene_id={report['scene_id']}  graph_id={report['graph_id']}")
    print(f"history events: {report['history_events']}  baseline build: {report['baseline_build']}")
    print(f"new graph: nodes={report['new_graph_counts']['nodes']}  edges={report['new_graph_counts']['edges']}")
    print()
    print(f"{'metric':<32} {'value':>8}  detail")
    print(f"{'-' * 32} {'-' * 8}  {'-' * 40}")
    print(f"{'outdoor_pruning_recall (id)':<32} {str(m['outdoor_pruning_recall']):>8}  {d['outdoor_pruned']}/{s['deleted_nodes']} deleted ids absent (same-id-scheme only)")
    print(f"{'outdoor_pruning_recall_pos':<32} {str(m['outdoor_pruning_recall_pos']):>8}  {d['outdoor_pruned_pos']}/{s['deleted_nodes_with_positions']} deleted positions empty within {report['params']['prune_eps_m']}m (re-import safe)")
    print(f"{'rug_fill_recall':<32} {str(m['rug_fill_recall']):>8}  {d['rug_filled']}/{s['added_nodes']} manual adds met by auto node within {report['params']['fill_eps_m']}m")
    print(f"{'carving_relaxation_rate':<32} {str(m['carving_relaxation_rate']):>8}  {d['carving_relaxed']}/{s['forced_edges_blocked']} blocked-edges now auto-connected ({d['carving_endpoints_matched']} endpoint-pairs matched)")
    if report.get("fresh_build"):
        fresh = report["fresh_build"]
        quality = fresh["edge_quality"]
        print()
        print(f"fresh build (non-mutating): components={fresh['connected_components']}  "
              f"max_edge={quality['max_edge_length_m']}m  wall_crossings={quality['wall_crossing_edges']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", required=True, help="OpticalNav scene id (under out/opticalnav/<project>/scenes/<id>/)")
    ap.add_argument("--project", default="opticalnav-v0.2", help="OpticalNav project id (default: opticalnav-v0.2)")
    ap.add_argument("--graph", default=None, help="Path to viewpoint_graph.json to audit (default: scene's current).")
    ap.add_argument("--history", default=None, help="Path to graph_edit_history.jsonl (default: scene's current).")
    ap.add_argument("--fresh-build", action="store_true", help="Build an in-memory auto-only candidate; never writes graph/grid/history.")
    ap.add_argument("--fill-eps-m", type=float, default=None)
    ap.add_argument("--endpoint-eps-m", type=float, default=0.30)
    ap.add_argument("--prune-eps-m", type=float, default=0.25,
                    help="position-based outdoor: a deleted spot counts as pruned when no node within this radius.")
    ap.add_argument("--json", action="store_true", help="Emit JSON to stdout instead of the human table.")
    for flag, key, cast in (
        ("--resolution", "resolution", float),
        ("--robot-radius-m", "robot_radius_m", float),
        ("--robot-height-m", "robot_height_m", float),
        ("--heading-count", "heading_count", int),
        ("--min-node-spacing-m", "min_node_spacing_m", float),
        ("--min-clearance-m", "min_clearance_m", float),
        ("--camera-margin-m", "camera_margin_m", float),
        ("--doorway-gap-m", "doorway_gap_m", float),
        ("--max-nodes", "max_nodes", int),
        ("--k-neighbors", "k_neighbors", int),
        ("--max-edge-length-m", "max_edge_length_m", float),
        ("--seed", "seed", int),
    ):
        ap.add_argument(flag, dest=key, type=cast, default=None)
    args = ap.parse_args()

    scene_dir = REPO_ROOT / "out" / "opticalnav" / args.project / "scenes" / args.scene
    history_path = Path(args.history) if args.history else scene_dir / "graph_edit_history.jsonl"
    graph_path = Path(args.graph) if args.graph else scene_dir / "viewpoint_graph.json"

    if not history_path.is_file():
        print(f"[error] history not found: {history_path}", file=sys.stderr)
        return 2
    if not args.fresh_build and not graph_path.is_file():
        print(f"[error] graph not found: {graph_path}", file=sys.stderr)
        return 2

    fill_eps_m = args.fill_eps_m if args.fill_eps_m is not None else (0.75 if args.fresh_build else 0.25)
    if args.fresh_build:
        overrides = {key: getattr(args, key) for key in _FRESH_BUILD_DEFAULTS}
        report = fresh_build_audit(
            history_path, scene_dir,
            overrides=overrides,
            fill_eps_m=fill_eps_m, endpoint_eps_m=args.endpoint_eps_m,
            prune_eps_m=args.prune_eps_m,
        )
    else:
        report = audit(
            history_path, graph_path,
            fill_eps_m=fill_eps_m, endpoint_eps_m=args.endpoint_eps_m,
            prune_eps_m=args.prune_eps_m,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
