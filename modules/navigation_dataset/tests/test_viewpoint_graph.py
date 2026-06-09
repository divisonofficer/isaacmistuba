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
from navigation_dataset.viewpoint_graph import ViewpointGraph, ViewpointNode, read_viewpoint_graph, write_viewpoint_graph  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
