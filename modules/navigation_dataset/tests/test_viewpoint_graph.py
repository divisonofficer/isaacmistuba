from __future__ import annotations

from pathlib import Path
import json
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
from navigation_dataset.sensor_sweep import build_custom_position_render_requests, build_sweep_render_requests, render_viewpoint_sweep_direct, split_sweep_requests_by_modality_phase  # noqa: E402
from navigation_dataset.traversability import build_traversability_grid, save_traversability_grid  # noqa: E402
from navigation_dataset.validation import validate_dataset  # noqa: E402
from navigation_dataset.viewpoint_graph import (  # noqa: E402
    ViewpointEdge,
    ViewpointGraph,
    ViewpointHeading,
    ViewpointNode,
    append_edge,
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

    def test_write_viewpoint_graph_atomic_roundtrip(self) -> None:
        _annotation, graph = self.make_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "viewpoint_graph.json"
            write_viewpoint_graph(path, graph)
            self.assertEqual(path.read_bytes()[-1:], b"\n")
            self.assertFalse(list(Path(tmpdir).glob("viewpoint_graph.json.tmp.*")))
            restored = read_viewpoint_graph(path)
            self.assertEqual(restored.graph_id, graph.graph_id)

    def test_read_legacy_graph_without_metadata_revision(self) -> None:
        _annotation, graph = self.make_graph()
        payload = {
            "scene_id": graph.scene_id,
            "graph_id": graph.graph_id,
            "node_heading_count": 1,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "position": node.position,
                    "headings": [{"heading_id": "h_000", "yaw_deg": 0.0}],
                }
                for node in graph.nodes
            ],
            "edges": [],
            "schema_version": "0.2",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "viewpoint_graph.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            restored = read_viewpoint_graph(path)
            self.assertEqual(restored.metadata, {})
            self.assertEqual(restored.graph_id, graph.graph_id)

    def test_append_edge_duplicate_endpoint_returns_existing_edge(self) -> None:
        nodes = [
            ViewpointNode(node_id="vp_a", position=[0.0, 0.0, 0.0]),
            ViewpointNode(node_id="vp_b", position=[1.0, 0.0, 0.0]),
        ]
        graph = ViewpointGraph(scene_id="s", graph_id="g", node_heading_count=4, nodes=nodes)
        first = append_edge(graph, "vp_a", "vp_b")
        second = append_edge(graph, "vp_b", "vp_a")
        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertEqual(len(graph.edges), 1)

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

    def test_multi_sensor_sweep_request_groups_rig_cameras_per_heading(self) -> None:
        graph = ViewpointGraph(
            scene_id="rig_room",
            graph_id="rig_graph",
            node_heading_count=1,
            nodes=[ViewpointNode(node_id="vp_000", position=[1.0, 2.0, 0.0], headings=[ViewpointHeading(heading_id="h_000", yaw_deg=0.0)])],
        )
        scene_state = {
            "job_id": "job-rig",
            "scene_id": "rig_room",
            "frame_id": "frame_0",
            "timestamp": "2026-05-27T00:00:00+00:00",
            "scene_snapshot_ref": "snapshot/scene.json",
            "mitsuba_scene_ref": "scene.xml",
        }
        base_camera = {
            "camera_id": "front",
            "name": "front",
            "camera_to_world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "fov_deg": 70.0,
        }
        camera_specs = [
            {
                **base_camera,
                "camera_id": "rgb_left",
                "resolution": [320, 256],
                "extras": {"robot_mount": {"xyz_m": [-0.2, 1.5, 0.0]}, "render_modalities": ["rgb"], "render": {"path_spp": 2048}},
            },
            {
                **base_camera,
                "camera_id": "polar_center",
                "resolution": [640, 512],
                "extras": {
                    "robot_mount": {"xyz_m": [0.0, 1.5, 0.0]},
                    "render_modalities": ["polar_rgb_preview"],
                    "render": {"path_spp": 4096, "polar_spp": 256},
                },
            },
        ]

        requests = build_sweep_render_requests(
            graph,
            scene_state_payload=scene_state,
            camera_spec_payload=base_camera,
            camera_specs_payload=camera_specs,
            sensor_scope="all_rig",
            modalities=["rgb"],
        )

        self.assertEqual(len(requests), 1)
        request = requests[0].request
        self.assertEqual([cam.camera_id for cam in request.camera_specs], ["rgb_left", "polar_center"])
        self.assertEqual(request.modalities, ["rgb", "polar_rgb_preview", "s1_over_s0", "s2_over_s0", "dop", "aolp", "s1", "s2"])
        self.assertEqual(request.extras["sensor_count"], 2)
        self.assertEqual(request.extras["modalities_by_sensor"]["rgb_left"], ["rgb"])
        self.assertEqual(request.extras["modalities_by_sensor"]["polar_center"], ["polar_rgb_preview", "s1_over_s0", "s2_over_s0", "dop", "aolp", "s1", "s2"])
        self.assertIn("vp_000-h_000", request.job_id)
        self.assertNotIn("rgb_left", request.job_id)

    def test_mixed_rgb_polar_sweep_can_split_into_modality_phases(self) -> None:
        graph = ViewpointGraph(
            scene_id="rig_room",
            graph_id="rig_graph",
            node_heading_count=1,
            nodes=[ViewpointNode(node_id="vp_000", position=[1.0, 2.0, 0.0], headings=[ViewpointHeading(heading_id="h_000", yaw_deg=0.0)])],
        )
        scene_state = {
            "job_id": "job-rig",
            "scene_id": "rig_room",
            "frame_id": "frame_0",
            "timestamp": "2026-05-27T00:00:00+00:00",
            "scene_snapshot_ref": "snapshot/scene.json",
            "mitsuba_scene_ref": "scene.xml",
        }
        base_camera = {
            "camera_id": "front",
            "name": "front",
            "camera_to_world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "fov_deg": 70.0,
        }
        camera_specs = [
            {**base_camera, "camera_id": "rgb_left", "extras": {"render_modalities": ["rgb"]}},
            {**base_camera, "camera_id": "rgb_right", "extras": {"render_modalities": ["rgb"]}},
            {**base_camera, "camera_id": "polar_center", "sensor_modality": "polarization", "extras": {"render_modalities": ["polar_rgb_preview"]}},
        ]

        requests = build_sweep_render_requests(
            graph,
            scene_state_payload=scene_state,
            camera_spec_payload=base_camera,
            camera_specs_payload=camera_specs,
            sensor_scope="all_rig",
            modalities=["rgb"],
        )
        phases = split_sweep_requests_by_modality_phase(requests, sweep_execution_policy="modality_phases")

        self.assertEqual([phase.phase for phase in phases], ["rgb", "polar"])
        rgb_request = phases[0].requests[0].request
        polar_request = phases[1].requests[0].request
        self.assertEqual([cam.camera_id for cam in rgb_request.camera_specs], ["rgb_left", "rgb_right"])
        self.assertEqual([cam.camera_id for cam in polar_request.camera_specs], ["polar_center"])
        self.assertEqual(rgb_request.frame_id, polar_request.frame_id)
        self.assertTrue(rgb_request.job_id.endswith("-rgb"))
        self.assertTrue(polar_request.job_id.endswith("-polar"))
        self.assertNotEqual(rgb_request.job_id, polar_request.job_id)
        self.assertEqual(rgb_request.modalities, ["rgb"])
        self.assertIn("s1_over_s0", polar_request.modalities)
        self.assertEqual(polar_request.extras["phase_sensor_ids"], ["polar_center"])

    def test_auto_sweep_policy_keeps_rgb_only_rig_per_view(self) -> None:
        graph = ViewpointGraph(
            scene_id="rig_room",
            graph_id="rig_graph",
            node_heading_count=1,
            nodes=[ViewpointNode(node_id="vp_000", position=[1.0, 2.0, 0.0], headings=[ViewpointHeading(heading_id="h_000", yaw_deg=0.0)])],
        )
        scene_state = {
            "job_id": "job-rig",
            "scene_id": "rig_room",
            "frame_id": "frame_0",
            "timestamp": "2026-05-27T00:00:00+00:00",
            "scene_snapshot_ref": "snapshot/scene.json",
            "mitsuba_scene_ref": "scene.xml",
        }
        base_camera = {
            "camera_id": "front",
            "name": "front",
            "camera_to_world": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            "fov_deg": 70.0,
        }
        requests = build_sweep_render_requests(
            graph,
            scene_state_payload=scene_state,
            camera_spec_payload=base_camera,
            camera_specs_payload=[
                {**base_camera, "camera_id": "rgb_left", "extras": {"render_modalities": ["rgb"]}},
                {**base_camera, "camera_id": "rgb_right", "extras": {"render_modalities": ["rgb"]}},
            ],
            sensor_scope="all_rig",
            modalities=["rgb"],
        )
        phases = split_sweep_requests_by_modality_phase(requests, sweep_execution_policy="auto")

        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0].phase, "per_view")
        self.assertEqual([cam.camera_id for cam in phases[0].requests[0].request.camera_specs], ["rgb_left", "rgb_right"])

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


class TestEdgeBuilderWallGate(unittest.TestCase):
    def test_regular_edges_skip_walls_but_keep_doorways(self):
        import numpy as np
        from navigation_dataset.traversability import GridSpec, TraversabilityGrid

        spec = GridSpec(width=40, height=20, resolution=0.1, origin=(0.0, 0.0), scene_id="t")
        grid = TraversabilityGrid(spec=spec, traversable=np.ones((20, 40), bool),
                                  hazard=np.zeros((20, 40), bool))
        wall = np.zeros((20, 40), dtype=bool)
        wall[:, 15] = True            # wall at x≈1.5 ...
        wall[13:18, 15] = False       # ... with a doorway gap at y∈[1.3,1.7]
        nodes = [
            ViewpointNode(node_id="L1", position=[1.0, 0.5, 0.0], headings=heading_sweep(1)),
            ViewpointNode(node_id="R1", position=[2.0, 0.5, 0.0], headings=heading_sweep(1)),  # across wall
            ViewpointNode(node_id="L2", position=[1.0, 1.5, 0.0], headings=heading_sweep(1)),
            ViewpointNode(node_id="R2", position=[2.0, 1.5, 0.0], headings=heading_sweep(1)),  # across doorway
        ]
        edges = build_viewpoint_edges(grid, nodes, max_edge_length_m=1.5, wall_mask=wall)
        pairs = {tuple(sorted((e.source, e.target))) for e in edges}
        self.assertIn(("L2", "R2"), pairs, "doorway edge should be kept")
        self.assertNotIn(("L1", "R1"), pairs, "through-wall edge must be dropped")
        # Same nodes WITHOUT a wall mask: the through-wall edge is created (legacy).
        legacy = {tuple(sorted((e.source, e.target)))
                  for e in build_viewpoint_edges(grid, nodes, max_edge_length_m=1.5)}
        self.assertIn(("L1", "R1"), legacy)


class TestConnectivityRepairWallGate(unittest.TestCase):
    def test_repair_bridges_through_doorway_not_wall(self):
        """A wall between two rooms with a doorway gap: repair must connect the pair
        whose straight line threads the doorway, never the pair that crosses the wall."""
        import numpy as np
        from navigation_dataset.traversability import GridSpec, TraversabilityGrid
        from navigation_dataset.graph_pipeline import _repair_connectivity, _max_wall_run_cells

        spec = GridSpec(width=40, height=20, resolution=0.1, origin=(0.0, 0.0), scene_id="t")
        traversable = np.ones((20, 40), dtype=bool)          # open floor (no grid gap)
        grid = TraversabilityGrid(spec=spec, traversable=traversable,
                                  hazard=np.zeros((20, 40), bool))
        # Vertical wall at x≈1.5 (col 15) with a doorway gap at y∈[1.3,1.7] (rows 13-17).
        wall = np.zeros((20, 40), dtype=bool)
        wall[:, 15] = True
        wall[13:18, 15] = False

        def node(nid, x, y):
            return ViewpointNode(node_id=nid, position=[x, y, 0.0],
                                 headings=heading_sweep(1))
        # Left room {L1,L2} and right room {R1,R2}; L1↔R1 cross the solid wall (y=0.5),
        # L2↔R2 cross the doorway (y=1.5). Both cross-pairs are 1.0 m apart.
        graph = ViewpointGraph(
            scene_id="t", graph_id="g", node_heading_count=1,
            nodes=[node("L1", 1.0, 0.5), node("L2", 1.0, 1.5),
                   node("R1", 2.0, 0.5), node("R2", 2.0, 1.5)],
            edges=[ViewpointEdge(edge_id="L", source="L1", target="L2", distance_m=1.0, weight=1.0),
                   ViewpointEdge(edge_id="R", source="R1", target="R2", distance_m=1.0, weight=1.0)],
        )
        # Sanity: the discriminator sees the wall on L1-R1 and a clear doorway on L2-R2.
        self.assertGreater(_max_wall_run_cells(wall, spec, [1.0, 0.5], [2.0, 0.5]), 0)
        self.assertEqual(_max_wall_run_cells(wall, spec, [1.0, 1.5], [2.0, 1.5]), 0)

        _repair_connectivity(graph, grid, wall_mask=wall, heading_count=1)
        pairs = {tuple(sorted((e.source, e.target))) for e in graph.edges}
        self.assertIn(("L2", "R2"), pairs, "should bridge through the doorway")
        self.assertNotIn(("L1", "R1"), pairs, "must not bridge through the wall")
        # Whatever bridges were added, none may cross body-height wall.
        pos = {n.node_id: n.position for n in graph.nodes}
        for e in graph.edges:
            self.assertEqual(
                _max_wall_run_cells(wall, spec, list(pos[e.source][:2]), list(pos[e.target][:2])), 0,
                f"edge {e.edge_id} crosses a wall")

    def test_no_wall_mask_keeps_legacy_behaviour(self):
        """Without a wall mask (e.g. non-Infinigen scenes) repair still bridges."""
        import numpy as np
        from navigation_dataset.traversability import GridSpec, TraversabilityGrid
        from navigation_dataset.graph_pipeline import _repair_connectivity

        spec = GridSpec(width=40, height=20, resolution=0.1, origin=(0.0, 0.0), scene_id="t")
        grid = TraversabilityGrid(spec=spec, traversable=np.ones((20, 40), bool),
                                  hazard=np.zeros((20, 40), bool))
        graph = ViewpointGraph(
            scene_id="t", graph_id="g", node_heading_count=1,
            nodes=[ViewpointNode(node_id="A", position=[1.0, 1.0, 0.0], headings=heading_sweep(1)),
                   ViewpointNode(node_id="B", position=[2.0, 1.0, 0.0], headings=heading_sweep(1))],
            edges=[],
        )
        s, _ = _repair_connectivity(graph, grid, wall_mask=None, heading_count=1)
        self.assertTrue(graph.edges, "repair should still connect the two nodes")


class TestGraphEpisodeStaleRefs(unittest.TestCase):
    def _graph(self):
        def mk(nid, x, y):
            hs = [ViewpointHeading(heading_id=f"h_{int(round(i * 30)):03d}", yaw_deg=float(i * 30)) for i in range(12)]
            return ViewpointNode(node_id=nid, position=[x, y, 0.0], headings=hs)
        # A-B-C chain.
        return ViewpointGraph(
            scene_id="scn", graph_id="g", node_heading_count=12,
            nodes=[mk("A", 0.0, 0.0), mk("B", 0.0, 1.0), mk("C", 0.0, 2.0)],
            edges=[ViewpointEdge(edge_id="ab", source="A", target="B", distance_m=1.0, weight=1.0),
                   ViewpointEdge(edge_id="bc", source="B", target="C", distance_m=1.0, weight=1.0)],
        )

    def test_plan_excludes_disabled_edges(self):
        # Disabling B-C leaves the planner unable to reach C — no episode may traverse it.
        graph = self._graph()
        eps = plan_graph_episodes(
            graph=graph, num_pairs=3, split_counts={"train": 3}, scenarios=["goal_only"],
            modalities=["rgb"], seed=1, excluded_edge_ids={"bc"},
        )
        for ep in eps:
            self.assertNotIn("C", ep.path_nodes, "episode routed through the disabled B-C edge")

    def test_stale_refs_detects_missing_and_disabled(self):
        from navigation_dataset.graph_episode_sampler import graph_episode_stale_refs
        node_ids = {"A", "B", "C"}
        edge_pairs = {("A", "B"), ("B", "C")}
        r = graph_episode_stale_refs(
            {"navigation_mode": "viewpoint_graph", "path_nodes": ["A", "Z"]},
            node_ids=node_ids, edge_pairs=edge_pairs)
        self.assertTrue(r["stale"])
        self.assertEqual(r["missing_nodes"], ["Z"])
        r = graph_episode_stale_refs(
            {"navigation_mode": "viewpoint_graph", "path_nodes": ["A", "C"]},
            node_ids=node_ids, edge_pairs=edge_pairs)
        self.assertEqual(r["missing_edges"], [["A", "C"]])
        r = graph_episode_stale_refs(
            {"navigation_mode": "viewpoint_graph", "path_nodes": ["B", "C"]},
            node_ids=node_ids, edge_pairs=edge_pairs, disabled_pairs={("B", "C")})
        self.assertEqual(r["disabled_edges"], [["B", "C"]])
        self.assertFalse(graph_episode_stale_refs(
            {"navigation_mode": "viewpoint_graph", "path_nodes": ["A", "B", "C"]},
            node_ids=node_ids, edge_pairs=edge_pairs)["stale"])
        self.assertFalse(graph_episode_stale_refs(
            {"navigation_mode": "grid", "path_nodes": ["Z"]},
            node_ids=node_ids, edge_pairs=edge_pairs)["stale"])


if __name__ == "__main__":
    unittest.main()
