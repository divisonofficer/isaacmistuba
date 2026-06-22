"""Unit tests for apps/audit_graph_edit_history.py — the three metrics."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS = REPO_ROOT / "apps"
if str(APPS) not in sys.path:
    sys.path.insert(0, str(APPS))

import audit_graph_edit_history as A  # type: ignore  # noqa: E402


def _write(tmp_path, name, payload):
    p = tmp_path / name
    if isinstance(payload, list) and all(isinstance(x, dict) for x in payload):
        p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in payload), encoding="utf-8")
    else:
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_perfect_recall_with_baseline_graph(tmp_path):
    """If the new graph is the post-edit golden (mirrors human edits), every metric is 1.0."""
    history = [
        {"operation": "build_graph", "after": {"nodes": 5, "edges": 4}},
        {"operation": "delete_nodes",
         "params": {"requested": ["vp_0", "vp_1"]},
         "before": {"nodes": 5, "edges": 4}, "after": {"nodes": 3, "edges": 2}},
        {"operation": "add_node",
         "params": {"x": 10.0, "y": 10.0, "heading_count": 12},
         "added_node": {"id": "vp_manual_0", "position": [10.0, 10.0]},
         "after": {"nodes": 4, "edges": 2}},
        {"operation": "add_edge",
         "algo_context": {"reason": "blocked_by_obstacle"},
         "added_edge": {"id": "edge_m_0", "source": "a", "target": "b",
                        "source_pos": [10.0, 10.0], "target_pos": [10.8, 10.0]}},
    ]
    new_graph = {
        "scene_id": "s", "graph_id": "g",
        "nodes": [
            # vp_0, vp_1 are absent (matches deletion)
            {"node_id": "vp_2", "position": [0.0, 0.0]},
            {"node_id": "vp_3", "position": [1.0, 1.0]},
            {"node_id": "vp_4", "position": [2.0, 2.0]},
            {"node_id": "vp_manual_0", "position": [10.0, 10.0]},
            {"node_id": "vp_b", "position": [10.8, 10.0]},
        ],
        "edges": [
            {"source": "vp_manual_0", "target": "vp_b"},
        ],
    }
    hist_p = _write(tmp_path, "graph_edit_history.jsonl", history)
    graph_p = _write(tmp_path, "viewpoint_graph.json", new_graph)
    rep = A.audit(hist_p, graph_p)
    m = rep["metrics"]
    assert m["outdoor_pruning_recall"] == 1.0
    assert m["rug_fill_recall"] == 1.0
    assert m["carving_relaxation_rate"] == 1.0


def test_baseline_with_no_corrections_yields_zero(tmp_path):
    """If the new graph is the raw auto-built one (deletion ids present, manual additions missing,
    forced edges still absent), the three metrics should bottom out near 0."""
    history = [
        {"operation": "build_graph", "after": {"nodes": 3, "edges": 1}},
        {"operation": "delete_nodes",
         "params": {"requested": ["vp_0"]},
         "before": {"nodes": 3, "edges": 1}, "after": {"nodes": 2, "edges": 1}},
        {"operation": "add_node",
         "params": {"x": 99.0, "y": 99.0, "heading_count": 12},
         "added_node": {"id": "vp_manual_0", "position": [99.0, 99.0]},
         "after": {"nodes": 3, "edges": 1}},
        {"operation": "add_edge",
         "algo_context": {"reason": "blocked_by_obstacle"},
         "added_edge": {"id": "edge_m_0", "source": "x", "target": "y",
                        "source_pos": [50.0, 50.0], "target_pos": [60.0, 60.0]}},
    ]
    new_graph = {
        "scene_id": "s", "graph_id": "g",
        "nodes": [
            # vp_0 still present (auto graph didn't prune)
            {"node_id": "vp_0", "position": [0.0, 0.0]},
            {"node_id": "vp_1", "position": [1.0, 1.0]},
            # no node anywhere near (99, 99) → fill miss
            # no node anywhere near (50, 50) or (60, 60) → forced edge unresolved
        ],
        "edges": [],
    }
    hist_p = _write(tmp_path, "graph_edit_history.jsonl", history)
    graph_p = _write(tmp_path, "viewpoint_graph.json", new_graph)
    rep = A.audit(hist_p, graph_p)
    m = rep["metrics"]
    assert m["outdoor_pruning_recall"] == 0.0
    assert m["rug_fill_recall"] == 0.0
    assert m["carving_relaxation_rate"] == 0.0


def test_position_based_outdoor_survives_reimport(tmp_path):
    """A re-imported graph (entirely new ids) should still score on the
    position-based outdoor metric, while the id-based one trivially returns 1.0.
    """
    history = [
        {"operation": "build_graph", "after": {"nodes": 2, "edges": 0}},
        {"operation": "delete_nodes",
         "params": {"requested": ["vp_old_0", "vp_old_1"]},
         "deleted_nodes": [
             {"id": "vp_old_0", "position": [50.0, 50.0]},  # outdoor — should stay empty
             {"id": "vp_old_1", "position": [1.0, 1.0]},    # indoor — algorithm still places a node here
         ],
         "before": {"nodes": 2}, "after": {"nodes": 0}},
    ]
    # Re-imported graph: brand-new ids, only the indoor spot has a nearby node.
    new_graph = {
        "scene_id": "s", "graph_id": "g_v2",
        "nodes": [{"node_id": "vp_new_0", "position": [1.0, 1.0]}],
        "edges": [],
    }
    hist_p = _write(tmp_path, "graph_edit_history.jsonl", history)
    graph_p = _write(tmp_path, "viewpoint_graph.json", new_graph)
    rep = A.audit(hist_p, graph_p)
    m = rep["metrics"]
    # id-based: both old ids absent (new ids unrelated) → trivially 1.0 (false positive).
    assert m["outdoor_pruning_recall"] == 1.0
    # position-based: outdoor spot empty ✓, indoor spot still populated ✗ → 0.5.
    assert m["outdoor_pruning_recall_pos"] == 0.5


def test_partial_improvement(tmp_path):
    """Mixed outcome: 1 of 2 deletes pruned, 1 of 2 fills met, 0 of 1 forced edge resolved."""
    history = [
        {"operation": "build_graph", "after": {"nodes": 4, "edges": 2}},
        {"operation": "delete_nodes",
         "params": {"requested": ["vp_0", "vp_1"]},
         "before": {"nodes": 4}, "after": {"nodes": 2}},
        {"operation": "add_node",
         "params": {"x": 10.0, "y": 10.0, "heading_count": 12},
         "added_node": {"id": "vp_manual_0", "position": [10.0, 10.0]}},
        {"operation": "add_node",
         "params": {"x": 20.0, "y": 20.0, "heading_count": 12},
         "added_node": {"id": "vp_manual_1", "position": [20.0, 20.0]}},
        {"operation": "add_edge",
         "algo_context": {"reason": "blocked_by_obstacle"},
         "added_edge": {"source_pos": [5.0, 5.0], "target_pos": [6.0, 5.0]}},
    ]
    new_graph = {
        "scene_id": "s", "graph_id": "g",
        "nodes": [
            # vp_0 absent (pruned), vp_1 still present
            {"node_id": "vp_1", "position": [1.0, 1.0]},
            # vp_manual_0 met (within 0.25m), vp_manual_1 NOT
            {"node_id": "vp_a", "position": [10.05, 10.0]},
            # forced-edge endpoints exist as nodes but NOT connected by an edge
            {"node_id": "vp_b", "position": [5.0, 5.0]},
            {"node_id": "vp_c", "position": [6.0, 5.0]},
        ],
        "edges": [],
    }
    hist_p = _write(tmp_path, "graph_edit_history.jsonl", history)
    graph_p = _write(tmp_path, "viewpoint_graph.json", new_graph)
    rep = A.audit(hist_p, graph_p)
    m = rep["metrics"]
    assert m["outdoor_pruning_recall"] == 0.5
    assert m["rug_fill_recall"] == 0.5
    assert m["carving_relaxation_rate"] == 0.0
