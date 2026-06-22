import json
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from navigation_dataset.graph_edit_log import (  # noqa: E402
    HISTORY_FILENAME,
    append_graph_edit,
    edge_record,
    graph_size,
    nearest_node_distance,
    node_record,
)
from navigation_dataset.viewpoint_graph import (  # noqa: E402
    ViewpointEdge,
    ViewpointGraph,
    ViewpointNode,
)


def _graph():
    return ViewpointGraph(
        scene_id="s",
        graph_id="g",
        node_heading_count=8,
        nodes=[
            ViewpointNode(node_id="vp_1", position=[1.0, 2.0, 0.0], clearance_m=0.4, tags=["auto"]),
            ViewpointNode(node_id="vp_2", position=[3.0, 2.0, 0.0], clearance_m=0.2,
                          tags=["manual"], extras={"manual": True}),
        ],
        edges=[
            ViewpointEdge(edge_id="edge_1", source="vp_1", target="vp_2",
                          distance_m=2.0, weight=2.0, hazard_crossing=True),
        ],
    )


class GraphEditLogTest(unittest.TestCase):
    def test_graph_size(self):
        self.assertEqual(graph_size(_graph()), {"nodes": 2, "edges": 1})

    def test_node_record_resolves_position(self):
        rec = node_record(_graph(), "vp_2")
        self.assertEqual(rec["position"], [3.0, 2.0])
        self.assertEqual(rec["clearance_m"], 0.2)
        self.assertTrue(rec["extras"].get("manual"))
        self.assertIsNone(node_record(_graph(), "missing"))

    def test_edge_record_has_endpoint_positions(self):
        rec = edge_record(_graph(), "edge_1")
        self.assertEqual(rec["source_pos"], [1.0, 2.0])
        self.assertEqual(rec["target_pos"], [3.0, 2.0])
        self.assertTrue(rec["hazard_crossing"])
        self.assertIsNone(edge_record(_graph(), "missing"))

    def test_nearest_node_distance(self):
        # closest node to (1.2, 2.0) is vp_1 at distance 0.2
        self.assertAlmostEqual(nearest_node_distance(_graph(), 1.2, 2.0), 0.2, places=6)
        # excluding vp_1 -> nearest is vp_2 at distance 1.8
        self.assertAlmostEqual(
            nearest_node_distance(_graph(), 1.2, 2.0, exclude=["vp_1"]), 1.8, places=6
        )

    def test_append_writes_one_json_line(self):
        with tempfile.TemporaryDirectory() as d:
            scene = Path(d)
            ok = append_graph_edit(scene, {
                "operation": "delete_node",
                "scene_id": "s",
                "before": {"nodes": 2, "edges": 1},
                "after": {"nodes": 1, "edges": 0},
                "deleted_nodes": [node_record(_graph(), "vp_2")],
            }, ts="2026-06-19T00:00:00+00:00")
            self.assertTrue(ok)
            lines = (scene / HISTORY_FILENAME).read_text().strip().splitlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["kind"], "graph_edit")
            self.assertEqual(rec["operation"], "delete_node")
            self.assertTrue(rec["edit_id"].startswith("gedit_"))
            self.assertEqual(rec["timestamp"], "2026-06-19T00:00:00+00:00")
            self.assertEqual(rec["deleted_nodes"][0]["position"], [3.0, 2.0])

            # second append -> two lines (append-only)
            append_graph_edit(scene, {"operation": "add_node"}, ts="2026-06-19T00:00:01+00:00")
            self.assertEqual(len((scene / HISTORY_FILENAME).read_text().strip().splitlines()), 2)

    def test_append_never_raises(self):
        # a non-serializable value falls back to str(); still must not raise
        self.assertTrue(append_graph_edit.__doc__ is not None)
        with tempfile.TemporaryDirectory() as d:
            ok = append_graph_edit(Path(d), {"operation": "x", "weird": object()})
            self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
