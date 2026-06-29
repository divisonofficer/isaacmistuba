from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import random  # noqa: E402

from navigation_dataset.optical_perturbation import (  # noqa: E402
    _num_components,
    _rect_segments,
    disabled_edge_ids,
    place_glass_walls,
    place_mirrors,
)


def _grid_graph() -> dict:
    """A 3x3 grid of nodes connected to 4-neighbours (multiple detour paths)."""
    nodes, edges = [], []
    idx = {}
    k = 0
    for gy in range(3):
        for gx in range(3):
            nid = f"vp_{k:02d}"
            idx[(gx, gy)] = nid
            nodes.append({"node_id": nid, "position": [float(gx), float(gy), 0.0]})
            k += 1
    e = 0
    for gy in range(3):
        for gx in range(3):
            for dx, dy in ((1, 0), (0, 1)):
                nx, ny = gx + dx, gy + dy
                if (nx, ny) in idx:
                    edges.append({"edge_id": f"e{e}", "source": idx[(gx, gy)],
                                  "target": idx[(nx, ny)]})
                    e += 1
    return {"nodes": nodes, "edges": edges}


class TestOpticalPerturbation(unittest.TestCase):
    def test_mirrors_are_flush_and_varied(self):
        segs = _rect_segments([("room", 0.0, 0.0, 5.0, 4.0)])
        mirrors = place_mirrors(segs, [], [], rng=random.Random(1), density=2.0)
        self.assertTrue(mirrors, "expected some mirrors on a 5x4 room")
        for m in mirrors:
            self.assertEqual(m["type"], "mirror_wall")
            self.assertEqual(m["material"], "mirror")
            g = m["geometry"]
            # mounted (off the floor) and not full-height (not floor-to-ceiling)
            self.assertGreater(g["base_height_m"], 0.0)
            self.assertLess(g["height_m"], 2.0)
            # flush on a wall face: start/end share one coordinate that sits on a room edge
            sx, sy = g["start"]
            ex, ey = g["end"]
            on_x_edge = abs(sx - ex) < 1e-6 and abs(sx - round(sx)) < 1e-6 and round(sx) in (0, 5)
            on_y_edge = abs(sy - ey) < 1e-6 and abs(sy - round(sy)) < 1e-6 and round(sy) in (0, 4)
            self.assertTrue(on_x_edge or on_y_edge, f"mirror not flush on a wall: {g}")

    def test_mirrors_follow_a_diagonal_wall(self):
        # a single diagonal wall segment (45°). Mirrors must lie ON the diagonal,
        # i.e. start/end satisfy y == x (not snapped to an axis-aligned bbox edge).
        segs = [("room:diag", (0.0, 0.0), (6.0, 6.0))]
        mirrors = place_mirrors(segs, [], [], rng=random.Random(2), density=3.0)
        self.assertTrue(mirrors, "expected mirrors on the diagonal wall")
        for m in mirrors:
            g = m["geometry"]
            for px, py in (g["start"], g["end"]):
                self.assertAlmostEqual(px, py, places=4, msg=f"mirror off the diagonal wall: {g}")

    def test_mirrors_avoid_doors(self):
        segs = _rect_segments([("room", 0.0, 0.0, 6.0, 4.0)])
        openings = [(3.0, 0.0)]  # door on the south wall mid-span
        mirrors = place_mirrors(segs, openings, [], rng=random.Random(3), density=3.0)
        for m in mirrors:
            g = m["geometry"]
            if abs(g["start"][1]) < 1e-6 and abs(g["end"][1]) < 1e-6:  # on south wall
                mid_x = (g["start"][0] + g["end"][0]) / 2.0
                self.assertGreater(abs(mid_x - 3.0), 0.5, "mirror placed on top of the door")

    def test_mirrors_do_not_block_a_passage(self):
        # wall along y=0; a nav edge crosses it at x=3 (a doorway/passage). No mirror
        # may straddle x=3, or it would seal the route.
        segs = [("room:S", (0.0, 0.0), (6.0, 0.0))]
        edges = [((3.0, -0.6), (3.0, 0.6))]
        mirrors = place_mirrors(segs, [], edges, rng=random.Random(4), density=4.0)
        for m in mirrors:
            g = m["geometry"]
            lo, hi = sorted((g["start"][0], g["end"][0]))
            self.assertFalse(lo <= 3.0 <= hi, f"mirror straddles the passage at x=3: {g}")

    def test_glass_walls_preserve_connectivity(self):
        graph = _grid_graph()
        node_ids = {n["node_id"] for n in graph["nodes"]}
        all_edges = [(e["source"], e["target"]) for e in graph["edges"]]
        base = _num_components(node_ids, all_edges)
        self.assertEqual(base, 1)

        glass, disabled = place_glass_walls({"regions": []}, graph,
                                            rng=random.Random(5), max_walls=3)
        self.assertTrue(glass, "expected at least one glass wall on a connected grid")
        self.assertTrue(disabled, "glass walls should disable some edges")
        remaining = [(e["source"], e["target"]) for e in graph["edges"]
                     if e["edge_id"] not in set(disabled)]
        # detour guard: graph stays a single component after the glass walls
        self.assertEqual(_num_components(node_ids, remaining), base)


class TestDisabledEdgeIds(unittest.TestCase):
    def _nodes_xy(self, graph):
        return {n["node_id"]: (float(n["position"][0]), float(n["position"][1]))
                for n in graph["nodes"]}

    def _edges(self, graph):
        return [(e["edge_id"], e["source"], e["target"]) for e in graph["edges"]]

    def test_disabled_empty_when_overlay_off(self):
        graph = _grid_graph()
        pert = {"enabled": False, "objects": [], "disabled_edge_ids": ["e0"]}
        self.assertEqual(disabled_edge_ids(pert, self._nodes_xy(graph), self._edges(graph)), set())
        self.assertEqual(disabled_edge_ids(None, self._nodes_xy(graph), self._edges(graph)), set())

    def test_glass_wall_cuts_crossed_edge(self):
        # Two nodes 2m apart on the x-axis; a glass wall perpendicular at the midpoint
        # cuts the edge between them.
        graph = {
            "nodes": [{"node_id": "a", "position": [0.0, 0.0, 0.0]},
                      {"node_id": "b", "position": [2.0, 0.0, 0.0]}],
            "edges": [{"edge_id": "e_ab", "source": "a", "target": "b"}],
        }
        pert = {
            "enabled": True,
            "objects": [{"type": "glass_wall", "geometry": {
                "type": "line", "start": [1.0, -0.7], "end": [1.0, 0.7], "thickness_m": 0.06}}],
            "disabled_edge_ids": [],
        }
        self.assertEqual(
            disabled_edge_ids(pert, self._nodes_xy(graph), self._edges(graph)), {"e_ab"})

    def test_parallel_edge_not_cut_by_wall_mirror(self):
        # An edge running PARALLEL to (and just off) a wall-mounted mirror must NOT be
        # flagged — only edges that pass THROUGH the mirror count.
        graph = {
            "nodes": [{"node_id": "a", "position": [0.0, 0.1, 0.0]},
                      {"node_id": "b", "position": [2.0, 0.1, 0.0]}],
            "edges": [{"edge_id": "e_par", "source": "a", "target": "b"}],
        }
        pert = {
            "enabled": True,
            "objects": [{"type": "mirror_wall", "geometry": {
                "type": "line", "start": [0.0, 0.0], "end": [2.0, 0.0], "thickness_m": 0.04}}],
            "disabled_edge_ids": [],
        }
        self.assertEqual(
            disabled_edge_ids(pert, self._nodes_xy(graph), self._edges(graph)), set())

    def test_stored_disabled_ids_honored_when_present(self):
        graph = _grid_graph()
        present = graph["edges"][0]["edge_id"]
        pert = {"enabled": True, "objects": [],
                "disabled_edge_ids": [present, "edge_no_longer_present"]}
        # Only the still-present id survives; stale stored ids are dropped.
        self.assertEqual(
            disabled_edge_ids(pert, self._nodes_xy(graph), self._edges(graph)), {present})


if __name__ == "__main__":
    unittest.main()
