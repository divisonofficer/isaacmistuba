from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from navigation_dataset.walkable_surface import _project_to_authoring_xy  # noqa: E402


class TestAuthoringTransform(unittest.TestCase):
    def test_bathroom_floor_maps_to_authoring_bbox(self):
        """Validated against the real bathroom_0_0.floor of indoor_seed3.

        world_bbox X[9.0,13.382] Y[10.118,13.382], origin_offset [-1.9804, 13.882, *]
        => authoring x[7.020, 11.402] y[0.500, 3.764] (Blender Z-up world; mesh Y-up
        local-centred; auth_x = X+dx, auth_y = -Y+dy with local Z -> world Y).
        """
        wbmin = [9.0, 10.117976, 0.117964]
        wbmax = [13.382024, 13.382024, 0.117976]
        offset = [-1.9804, 13.882, -0.1036]
        # Local Y-up floor: horizontal extent in local X and local Z, up=local Y~0.
        # AABB half-extents from the world bbox so center-alignment is exercised.
        hx = (wbmax[0] - wbmin[0]) / 2.0
        hz = (wbmax[1] - wbmin[1]) / 2.0
        local = np.array([
            [-hx, 0.0, -hz],
            [hx, 0.0, -hz],
            [hx, 0.0, hz],
            [-hx, 0.0, hz],
        ])
        xy = _project_to_authoring_xy(local, wbmin, wbmax, offset)
        self.assertAlmostEqual(float(xy[:, 0].min()), 7.020, places=2)
        self.assertAlmostEqual(float(xy[:, 0].max()), 11.402, places=2)
        self.assertAlmostEqual(float(xy[:, 1].min()), 0.500, places=2)
        self.assertAlmostEqual(float(xy[:, 1].max()), 3.764, places=2)

    def test_empty_input(self):
        out = _project_to_authoring_xy(np.zeros((0, 3)), [0, 0, 0], [1, 1, 1], [0, 0, 0])
        self.assertEqual(out.shape, (0, 2))


class TestWalkableSurfaceIntegration(unittest.TestCase):
    """End-to-end build on a real scene, skipped when dataset assets are absent."""

    SCENE_DIR = REPO_ROOT / "out" / "opticalnav" / "opticalnav-v0.2" / "scenes" / "infinigen_seed3"

    @unittest.skipUnless((SCENE_DIR / "authoring_map.json").is_file(), "infinigen_seed3 assets absent")
    def test_seed3_no_outside_or_wall_crossing(self):
        from navigation_dataset.graph_pipeline import build_viewpoint_graph_core
        from navigation_dataset.qa_walkable import graph_qa_report

        res = build_viewpoint_graph_core("infinigen_seed3", self.SCENE_DIR, graph_id="test", seed=0)
        self.assertIsNotNone(res.surface)
        qa = graph_qa_report(res.graph, res.surface)
        self.assertEqual(qa["outside_floor_nodes"], 0)
        self.assertEqual(qa["wall_crossing_edges"], 0)
        # The vast majority of nodes should be in a single connected component.
        self.assertGreater(qa["largest_component"], 0.9 * qa["node_count"])


if __name__ == "__main__":
    unittest.main()
