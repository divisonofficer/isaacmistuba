from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATHS = [
    REPO_ROOT / "modules" / "navigation_dataset" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
]
for module_path in reversed(MODULE_PATHS):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from navigation_dataset.edge_builder import build_viewpoint_edges  # noqa: E402
from navigation_dataset.graph_episode_sampler import plan_graph_episodes, shortest_graph_path, write_graph_episodes  # noqa: E402
from navigation_dataset.node_sampler import heading_sweep, sample_viewpoint_nodes  # noqa: E402
from navigation_dataset.scene_annotations import GoalRegion, HazardRegion, SceneAnnotation, TraversableRegion, write_scene_annotation  # noqa: E402
from navigation_dataset.sensor_sweep import build_custom_position_render_requests, build_sweep_render_requests, render_viewpoint_sweep_direct  # noqa: E402
from navigation_dataset.traversability import build_traversability_grid, save_traversability_grid  # noqa: E402
from navigation_dataset.validation import validate_dataset  # noqa: E402
from navigation_dataset.viewpoint_graph import (  # noqa: E402
    ViewpointEdge,
    ViewpointGraph,
    ViewpointHeading,
    ViewpointNode,
    find_object_overlapping_nodes,
    read_viewpoint_graph,
    remove_nodes,
    write_viewpoint_graph,
)
from navigation_dataset.traversability import build_traversability_grid, world_to_cell  # noqa: E402
from navigation_dataset.graph_episode_sampler import GraphPath, make_graph_episode  # noqa: E402
from navigation_dataset.episode_schema import DatasetProject, read_episode, write_project  # noqa: E402
from navigation_dataset.exporters.custom_json import write_dataset_index, write_split_files  # noqa: E402


class ViewpointGraphTests(unittest.TestCase):
    def make_annotation(self) -> SceneAnnotation:
        return SceneAnnotation(
            scene_id="graph_room_001",
            goal_regions=[GoalRegion(region_id="goal_east", center=[2.5, 0.5], radius=0.25, label="the east marker")],
            hazard_regions=[
                HazardRegion(
                    region_id="hazard_mid",
                    hazard_type="transparent_wall",
                    geometry={"type": "box", "bounds": [0.75, 0.2, 1.25, 0.8]},
                )
            ],
            traversable_regions=[TraversableRegion(region_id="floor", geometry={"type": "box", "bounds": [0.0, 0.0, 3.0, 1.0]})],
        )

    def make_graph(self, heading_count: int = 4) -> tuple[SceneAnnotation, ViewpointGraph]:
        annotation = self.make_annotation()
        grid = build_traversability_grid(annotation, resolution=0.25, margin=0.0)
        nodes = sample_viewpoint_nodes(
            grid,
            max_nodes=8,
            heading_count=heading_count,
            min_node_spacing_m=0.45,
            min_clearance_m=0.0,
            seed=3,
        )
        edges = build_viewpoint_edges(grid, nodes, robot_radius_m=0.0, k_neighbors=4, max_edge_length_m=1.0)
        graph = ViewpointGraph(
            scene_id=annotation.scene_id,
            graph_id=f"{annotation.scene_id}_vg_test",
            node_heading_count=heading_count,
            nodes=nodes,
            edges=edges,
        )
        return annotation, graph

    def test_viewpoint_graph_roundtrip_and_shortest_path(self) -> None:
        _annotation, graph = self.make_graph()
        self.assertTrue(graph.edges)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "viewpoint_graph.json"
            write_viewpoint_graph(path, graph)
            restored = read_viewpoint_graph(path)
            self.assertEqual(restored.graph_id, graph.graph_id)
            path_result = shortest_graph_path(restored, restored.edges[0].source, restored.edges[0].target)
            self.assertEqual(path_result.nodes[0], restored.edges[0].source)
            self.assertEqual(path_result.nodes[-1], restored.edges[0].target)

    def test_hazard_crossing_edge_is_flagged_but_retained(self) -> None:
        annotation = self.make_annotation()
        grid = build_traversability_grid(annotation, resolution=0.25, margin=0.0)
        nodes = [
            ViewpointNode(node_id="vp_left", position=[0.25, 0.5, 0.0], headings=heading_sweep(4)),
            ViewpointNode(node_id="vp_right", position=[1.75, 0.5, 0.0], headings=heading_sweep(4)),
        ]
        edges = build_viewpoint_edges(grid, nodes, robot_radius_m=0.0, k_neighbors=1, max_edge_length_m=2.0)
        self.assertTrue(edges)
        self.assertTrue(any(edge.hazard_crossing for edge in edges))

    def test_graph_episode_and_fake_sweep_refs(self) -> None:
        annotation, graph = self.make_graph(heading_count=2)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scene_dir = root / "scenes" / annotation.scene_id
            write_project(root / "dataset.json", DatasetProject(project_name="OpticalNav-v0.2"))
            write_scene_annotation(scene_dir / "scene_annotation.json", annotation)
            grid = build_traversability_grid(annotation, resolution=0.25, margin=0.0)
            save_traversability_grid(scene_dir / "traversable_grid.npy", grid)
            graph_path = write_viewpoint_graph(scene_dir / "viewpoint_graph.json", graph)

            def fake_render(request, repo_root, variant="auto"):
                bundle_root = f"viewpoint_observations/{annotation.scene_id}/{request.extras['node_id']}/{request.extras['heading_id']}"
                manifest = root / bundle_root / "manifest.json"
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text("{}", encoding="utf-8")
                return SimpleNamespace(bundle_root=bundle_root)

            scene_state = {
                "job_id": "job-graph-test",
                "scene_id": annotation.scene_id,
                "frame_id": "frame_0",
                "timestamp": "2026-05-27T00:00:00+00:00",
                "scene_snapshot_ref": "snapshot/scene.json",
                "mitsuba_scene_ref": "scene.xml",
            }
            camera_spec = {
                "camera_id": "front",
                "name": "front",
                "camera_to_world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                "fov_deg": 70.0,
            }
            requests = build_sweep_render_requests(
                graph,
                scene_state_payload=scene_state,
                camera_spec_payload=camera_spec,
                modalities=["rgb", "depth"],
            )
            job_ids = [item.request.job_id for item in requests]
            self.assertEqual(len(job_ids), len(set(job_ids)))
            rendered = render_viewpoint_sweep_direct(
                graph,
                dataset_root=root,
                graph_path=graph_path,
                scene_state_payload=scene_state,
                camera_spec_payload=camera_spec,
                modalities=["rgb", "depth"],
                render_fn=fake_render,
            )
            self.assertTrue(rendered.nodes[0].headings[0].sensor_observations)

            episodes = plan_graph_episodes(
                graph=rendered,
                num_pairs=2,
                split_counts={"train": 2},
                scenarios=["goal_only"],
                modalities=["rgb", "depth"],
                annotation=annotation,
                seed=5,
            )
            written = write_graph_episodes(root, episodes)
            write_dataset_index(root)
            write_split_files(root)
            restored = read_episode(written[0])
            self.assertEqual(restored.navigation_mode, "viewpoint_graph")
            self.assertEqual(restored.actions[-1], "stop")
            self.assertTrue(restored.path_nodes)
            report = validate_dataset(root, require_observations=True)
            self.assertTrue(report.ok, report.errors)

    def test_custom_position_preview_metadata_is_preserved(self) -> None:
        scene_state = {
            "job_id": "job-preview-test",
            "scene_id": "preview_room_001",
            "frame_id": "frame_0",
            "timestamp": "2026-05-27T00:00:00+00:00",
            "scene_snapshot_ref": "snapshot/scene.json",
            "mitsuba_scene_ref": "scene.xml",
        }
        camera_spec = {
            "camera_id": "rig_front",
            "name": "Rig Front",
            "camera_to_world": [1, 0, 0, 0, 0, 1, 0, 0.8, 0, 0, 1, 0, 0, 0, 0, 1],
            "fov_deg": 75.0,
        }
        requests = build_custom_position_render_requests(
            [{
                "node_id": "probe_123",
                "heading_id": "h0",
                "preview_id": "probe_123",
                "render_mode": "preview_probe",
                "x": 1.25,
                "y": 2.5,
                "yaw_deg": 35,
            }],
            scene_state_payload=scene_state,
            camera_spec_payload=camera_spec,
            modalities=["rgb"],
            scene_id="preview_room_001",
            camera_height_m=0.8,
        )
        self.assertEqual(len(requests), 1)
        request = requests[0].request
        self.assertEqual(requests[0].node_id, "probe_123")
        self.assertEqual(requests[0].heading_id, "h0")
        self.assertEqual(request.extras["render_mode"], "preview_probe")
        self.assertEqual(request.extras["preview_id"], "probe_123")
        self.assertEqual(request.camera_specs[0].camera_id, "rig_front")


class GraphNodeRemovalTests(unittest.TestCase):
    def _graph(self) -> ViewpointGraph:
        nodes = [
            ViewpointNode(node_id="vp_001", position=[0.0, 0.0, 0.0]),
            ViewpointNode(node_id="vp_002", position=[1.0, 0.0, 0.0]),
            ViewpointNode(node_id="vp_003", position=[2.0, 0.0, 0.0]),
        ]
        edges = [
            ViewpointEdge(edge_id="e12", source="vp_001", target="vp_002", distance_m=1.0, weight=1.0),
            ViewpointEdge(edge_id="e23", source="vp_002", target="vp_003", distance_m=1.0, weight=1.0),
        ]
        return ViewpointGraph(scene_id="s", graph_id="g", node_heading_count=4, nodes=nodes, edges=edges)

    def test_remove_nodes_drops_nodes_and_incident_edges(self) -> None:
        graph = self._graph()
        removed = remove_nodes(graph, ["vp_002", "vp_002", "vp_999"])
        self.assertEqual(removed, ["vp_002"])  # dedup + ignore unknown
        self.assertEqual({n.node_id for n in graph.nodes}, {"vp_001", "vp_003"})
        # both edges touched vp_002 → both gone
        self.assertEqual(graph.edges, [])

    def test_remove_nodes_empty_or_unknown_is_noop(self) -> None:
        graph = self._graph()
        self.assertEqual(remove_nodes(graph, []), [])
        self.assertEqual(remove_nodes(graph, ["nope"]), [])
        self.assertEqual(len(graph.nodes), 3)
        self.assertEqual(len(graph.edges), 2)


class OverlapDetectionTests(unittest.TestCase):
    def _graph(self) -> ViewpointGraph:
        nodes = [
            ViewpointNode(node_id="inside_box", position=[5.0, 5.0, 0.0]),
            ViewpointNode(node_id="far_away", position=[0.5, 0.5, 0.0]),
            ViewpointNode(node_id="near_edge", position=[5.9, 5.0, 0.0]),
        ]
        return ViewpointGraph(scene_id="s", graph_id="g", node_heading_count=4, nodes=nodes)

    def test_point_footprint_overlap(self) -> None:
        # 2x1 m table centred at (5,5): footprint x[4,6] y[4.5,5.5].
        objects = [{"type": "table", "geometry": {"type": "point", "center": [5.0, 5.0], "size_m": [2.0, 0.7, 1.0], "yaw_deg": 0.0}}]
        ids = find_object_overlapping_nodes(self._graph(), objects)
        self.assertIn("inside_box", ids)
        self.assertNotIn("far_away", ids)
        # near_edge at x=5.9 is inside [4,6]
        self.assertIn("near_edge", ids)

    def test_margin_expands_footprint(self) -> None:
        objects = [{"type": "chair", "geometry": {"type": "point", "center": [5.0, 5.0], "size_m": [0.4, 0.9, 0.4], "yaw_deg": 0.0}}]
        graph = self._graph()
        self.assertNotIn("near_edge", find_object_overlapping_nodes(graph, objects))  # 0.4 box too small
        self.assertIn("near_edge", find_object_overlapping_nodes(graph, objects, margin_m=1.0))

    def test_walls_excluded_by_default(self) -> None:
        # A wall line passing through (5,5).
        objects = [{"type": "wall", "geometry": {"type": "line", "start": [0.0, 5.0], "end": [10.0, 5.0], "thickness_m": 0.5}}]
        graph = self._graph()
        self.assertEqual(find_object_overlapping_nodes(graph, objects), [])
        self.assertIn("inside_box", find_object_overlapping_nodes(graph, objects, include_walls=True))

    def test_room_shell_always_skipped(self) -> None:
        objects = [{"type": "ceiling", "geometry": {"type": "rectangle", "bounds": [0.0, 0.0, 12.0, 7.0]}}]
        self.assertEqual(find_object_overlapping_nodes(self._graph(), objects, include_walls=True), [])

    def test_rotated_rectangle_respects_yaw(self) -> None:
        # Long-thin object (2 m along local x, 0.4 m along local z) rotated 90° at (5,5).
        # After rotation its long axis runs along authoring-y (world z).
        obj = {"type": "table", "geometry": {"type": "point", "center": [5.0, 5.0], "size_m": [2.0, 0.74, 0.4], "yaw_deg": 90.0}}
        nodes = [
            ViewpointNode(node_id="along_rotated_long", position=[5.0, 5.8, 0.0]),  # 0.8 along z → inside (len 1.0)
            ViewpointNode(node_id="along_rotated_short", position=[5.8, 5.0, 0.0]),  # 0.8 along x → outside (width 0.2)
        ]
        graph = ViewpointGraph(scene_id="s", graph_id="g", node_heading_count=4, nodes=nodes)
        ids = find_object_overlapping_nodes(graph, [obj])
        self.assertIn("along_rotated_long", ids)
        self.assertNotIn("along_rotated_short", ids)

    def test_high_mounted_objects_skipped(self) -> None:
        # Ceiling light at base 2.65 m → robot passes underneath → not an obstacle.
        light = {"type": "landmark", "geometry": {"type": "point", "center": [5.0, 5.0], "size_m": [1.6, 0.06, 0.18], "yaw_deg": 0.0, "base_height_m": 2.65}}
        graph = self._graph()
        self.assertEqual(find_object_overlapping_nodes(graph, [light]), [])
        # A low desk at the same spot (base 0) still blocks.
        desk = {"type": "table", "geometry": {"type": "point", "center": [5.0, 5.0], "size_m": [2.0, 0.74, 1.0], "yaw_deg": 0.0, "base_height_m": 0.0}}
        self.assertIn("inside_box", find_object_overlapping_nodes(graph, [desk]))
        # Raising the pass-under threshold above the light makes it block again.
        self.assertIn("inside_box", find_object_overlapping_nodes(graph, [light], robot_height_m=3.0))


class TraversabilityFootprintMaskingTests(unittest.TestCase):
    def _floor(self) -> SceneAnnotation:
        return SceneAnnotation(
            scene_id="t",
            traversable_regions=[TraversableRegion(region_id="floor", geometry={"type": "box", "bounds": [0.0, 0.0, 4.0, 4.0]})],
        )

    def test_furniture_footprint_carves_grid(self) -> None:
        objs = [{"type": "table", "geometry": {"type": "point", "center": [2.0, 2.0], "size_m": [2.0, 0.74, 1.0], "yaw_deg": 0.0, "base_height_m": 0.0}}]
        grid = build_traversability_grid(self._floor(), resolution=0.1, objects=objs)
        cx, cy = world_to_cell(grid.spec, 2.0, 2.0)
        self.assertFalse(bool(grid.traversable[cy, cx]))  # under the table → obstacle
        ox, oy = world_to_cell(grid.spec, 0.5, 0.5)
        self.assertTrue(bool(grid.traversable[oy, ox]))   # corner stays walkable

    def test_glass_line_is_masked(self) -> None:
        glass = [{"type": "glass_wall", "geometry": {"type": "line", "start": [1.0, 2.0], "end": [3.0, 2.0], "thickness_m": 0.2}}]
        grid = build_traversability_grid(self._floor(), resolution=0.1, objects=glass)
        cx, cy = world_to_cell(grid.spec, 2.0, 2.0)
        self.assertFalse(bool(grid.traversable[cy, cx]))

    def test_ceiling_mounted_object_not_masked(self) -> None:
        light = [{"type": "landmark", "geometry": {"type": "point", "center": [2.0, 2.0], "size_m": [1.6, 0.06, 0.18], "yaw_deg": 0.0, "base_height_m": 2.65}}]
        grid = build_traversability_grid(self._floor(), resolution=0.1, objects=light)
        cx, cy = world_to_cell(grid.spec, 2.0, 2.0)
        self.assertTrue(bool(grid.traversable[cy, cx]))  # robot passes underneath


class RotationPathExpansionTests(unittest.TestCase):
    def _graph(self) -> ViewpointGraph:
        def mk(nid: str, x: float, y: float) -> ViewpointNode:
            hs = [ViewpointHeading(heading_id=f"h_{int(round(i * 30)):03d}", yaw_deg=float(i * 30),
                                   sensor_observations={"bundle": f"obs/{nid}/h_{int(round(i*30)):03d}"}) for i in range(12)]
            return ViewpointNode(node_id=nid, position=[x, y, 0.0], headings=hs)
        nodes = [mk("A", 0.0, 0.0), mk("B", 0.0, 1.0), mk("C", 1.0, 1.0)]
        edges = [
            ViewpointEdge(edge_id="ab", source="A", target="B", distance_m=1.0, weight=1.0),
            ViewpointEdge(edge_id="bc", source="B", target="C", distance_m=1.0, weight=1.0),
        ]
        return ViewpointGraph(scene_id="s", graph_id="g", node_heading_count=12, nodes=nodes, edges=edges)

    def test_primitive_action_sequence(self) -> None:
        graph = self._graph()
        path = GraphPath(nodes=["A", "B", "C"], edges=list(graph.edges), distance_m=2.0, hazard_crossing=False)
        ep = make_graph_episode(episode_id="e1", split="train", graph=graph, path=path, scenario="goal_only", modalities=["rgb"])
        # Aligned lengths, primitive action space only, ends with stop.
        self.assertEqual(len(ep.actions), len(ep.timesteps))
        self.assertEqual(len(ep.trajectory), len(ep.timesteps))
        self.assertEqual(ep.actions[-1], "stop")
        self.assertNotIn("move_to_neighbor", ep.actions)  # forward/rotation primitives only
        self.assertEqual(set(ep.actions) - {"move_forward", "turn_left_30", "turn_right_30", "stop"}, set())
        # Node-level summary preserved.
        self.assertEqual(ep.path_nodes, ["A", "B", "C"])
        # Two edges → two move_forward steps, each carrying forward_m = edge distance.
        moves = [t for t in ep.timesteps if t.action == "move_forward"]
        self.assertEqual(len(moves), 2)
        self.assertTrue(all(abs(t.extras.get("forward_m", 0.0) - 1.0) < 1e-6 for t in moves))
        # Rotation steps carry turn_deg = ±30.
        for t in ep.timesteps:
            if t.action in ("turn_left_30", "turn_right_30"):
                self.assertIn(abs(t.extras.get("turn_deg", 0.0)), (30.0,))
        # Each step records node/heading + has an observation ref (graph has sweeps).
        self.assertTrue(all(t.extras.get("node_id") and t.extras.get("heading_id") for t in ep.timesteps))
        self.assertTrue(all(t.observation_bundle_ref for t in ep.timesteps))

    def test_spawn_heading_is_deterministic_and_drives_start_pose(self) -> None:
        graph = self._graph()
        path = GraphPath(nodes=["A", "B", "C"], edges=list(graph.edges), distance_m=2.0, hazard_crossing=False)
        ep1 = make_graph_episode(episode_id="ep_fixed", split="train", graph=graph, path=path, scenario="goal_only", modalities=["rgb"])
        ep2 = make_graph_episode(episode_id="ep_fixed", split="train", graph=graph, path=path, scenario="goal_only", modalities=["rgb"])
        # Reproducible spawn → identical start pose for the same episode_id.
        self.assertEqual(ep1.start_pose, ep2.start_pose)
        # First timestep is at the start node, facing the spawn heading.
        self.assertAlmostEqual(ep1.trajectory[0][0], 0.0)
        self.assertAlmostEqual(ep1.trajectory[0][1], 0.0)
        self.assertEqual(ep1.timesteps[0].extras.get("node_id"), "A")

    def test_observation_ref_disk_fallback(self) -> None:
        # Graph headings with EMPTY sensor_observations → must resolve from disk.
        def mk(nid: str, x: float, y: float) -> ViewpointNode:
            hs = [ViewpointHeading(heading_id=f"h_{int(round(i * 30)):03d}", yaw_deg=float(i * 30)) for i in range(12)]
            return ViewpointNode(node_id=nid, position=[x, y, 0.0], headings=hs)
        graph = ViewpointGraph(scene_id="scn", graph_id="g", node_heading_count=12,
                               nodes=[mk("A", 0.0, 0.0), mk("B", 0.0, 1.0)],
                               edges=[ViewpointEdge(edge_id="ab", source="A", target="B", distance_m=1.0, weight=1.0)])
        path = GraphPath(nodes=["A", "B"], edges=list(graph.edges), distance_m=1.0, hazard_crossing=False)
        with tempfile.TemporaryDirectory() as tmp:
            obs_root = Path(tmp) / "observations"
            # Materialize on-disk observation dirs for a couple of (vp, heading) pairs.
            for vp, hd in (("A", "h_000"), ("B", "h_000")):
                (obs_root / vp / hd).mkdir(parents=True, exist_ok=True)
                (obs_root / vp / hd / "_sensor_index.json").write_text("{}", encoding="utf-8")
            ep = make_graph_episode(episode_id="e1", split="train", graph=graph, path=path,
                                    scenario="goal_only", modalities=["rgb"], observations_root=obs_root)
            refs = [t.observation_bundle_ref for t in ep.timesteps if t.extras.get("heading_id") == "h_000"]
            self.assertTrue(refs and all(r and "scenes/scn/observations/" in r for r in refs))


if __name__ == "__main__":
    unittest.main()
