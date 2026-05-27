from __future__ import annotations

from pathlib import Path
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

from navigation_dataset.episode_schema import DatasetProject, read_episode, write_project  # noqa: E402
from navigation_dataset.evaluator import evaluate_dataset  # noqa: E402
from navigation_dataset.exporters.custom_json import build_dataset_index, write_dataset_index, write_split_files  # noqa: E402
from navigation_dataset.rollout import plan_episodes, split_counts_from_spec, write_episodes  # noqa: E402
from navigation_dataset.scene_annotations import (  # noqa: E402
    AnnotatedObject,
    GoalRegion,
    HazardRegion,
    SceneAnnotation,
    TraversableRegion,
    write_scene_annotation,
)
from navigation_dataset.traversability import build_traversability_grid, save_traversability_grid, write_nav_graph  # noqa: E402
from navigation_dataset.validation import validate_dataset  # noqa: E402
from mitsuba_converter.multimodal import MODALITY_DEFINITIONS, SUPPORTED_MODALITIES  # noqa: E402
from mitsuba_converter.observation_bridge import AMBIENT_MODALITIES  # noqa: E402


class NavigationDatasetTests(unittest.TestCase):
    def make_annotation(self) -> SceneAnnotation:
        return SceneAnnotation(
            scene_id="glass_corridor_001",
            usd_ref="scenes/glass_corridor_001/scene.usd",
            objects=[
                AnnotatedObject(
                    object_id="glass_wall_01",
                    category="transparent_surface",
                    hazard_type="transparent_wall",
                    geometry={"type": "box", "bounds": [2.0, 0.8, 2.2, 2.2]},
                    mask_export=True,
                )
            ],
            transparent_surfaces=["glass_wall_01"],
            hazard_regions=[
                HazardRegion(
                    region_id="hazard_glass_wall",
                    hazard_type="transparent_wall",
                    geometry={"type": "box", "bounds": [2.0, 0.8, 2.2, 2.2]},
                    object_refs=["glass_wall_01"],
                )
            ],
            goal_regions=[
                GoalRegion(
                    region_id="goal_near_chair",
                    center=[3.5, 0.5],
                    radius=0.25,
                    label="the chair",
                )
            ],
            traversable_regions=[
                TraversableRegion(
                    region_id="corridor_floor",
                    geometry={"type": "box", "bounds": [0.0, 0.0, 4.0, 1.0]},
                )
            ],
        )

    def test_schema_planner_export_and_evaluator_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_project(root / "dataset.json", DatasetProject(project_name="OpticalNav-v0.1"))
            annotation = self.make_annotation()
            scene_dir = root / "scenes" / annotation.scene_id
            write_scene_annotation(scene_dir / "scene_annotation.json", annotation)

            grid = build_traversability_grid(annotation, resolution=0.25, margin=0.0)
            save_traversability_grid(scene_dir / "traversable_grid.npy", grid)
            write_nav_graph(scene_dir / "nav_graph.json", grid)

            episodes = plan_episodes(
                annotation=annotation,
                grid=grid,
                num_pairs=4,
                split_counts=split_counts_from_spec("train:2,val_seen:1,val_unseen:1"),
                instruction_types=["goal_only", "hazard_aware"],
                modalities=["rgb", "depth", "active_nir_intensity", "hazard_mask"],
                seed=7,
            )
            self.assertGreaterEqual(len(episodes), 1)
            written = write_episodes(root, episodes)
            restored = read_episode(written[0])
            self.assertEqual(restored.scene_id, "glass_corridor_001")
            self.assertEqual(restored.actions[-1], "stop")
            self.assertEqual(restored.timesteps[-1].action, "stop")

            write_dataset_index(root)
            write_split_files(root)
            index = build_dataset_index(root)
            self.assertEqual(index["format"], "custom_json")
            self.assertEqual(index["episode_count"], len(episodes))

            report = validate_dataset(root)
            self.assertTrue(report.ok, report.errors)
            metrics = evaluate_dataset(root)
            self.assertEqual(metrics["episode_count"], len(episodes))
            self.assertIn("success_rate", metrics["metrics"])

    def test_hazard_mask_is_public_render_modality(self) -> None:
        self.assertIn("hazard_mask", SUPPORTED_MODALITIES)
        self.assertIn("hazard_mask", MODALITY_DEFINITIONS)
        self.assertIn("hazard_mask", AMBIENT_MODALITIES)


if __name__ == "__main__":
    unittest.main()
