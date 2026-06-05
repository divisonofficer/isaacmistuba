from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(MODULE_PATH) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH))

from navigation_dataset.authoring_compile import AuthoringMapCompileError, compile_authoring_map  # noqa: E402
from navigation_dataset.scene_annotations import write_scene_annotation, validate_scene_annotation  # noqa: E402
from navigation_dataset.scene_sync import build_render_scene_sync_payload, write_render_scene_sync  # noqa: E402
from navigation_dataset.validation import validate_dataset  # noqa: E402
from navigation_dataset.traversability import build_traversability_grid  # noqa: E402


class AuthoringCompileTests(unittest.TestCase):
    def minimum_map(self) -> dict:
        return {
            "version": "opticalnav-authoring-map-v0.2",
            "scene_id": "glass_corridor_001",
            "unit": "meter",
            "floorplan_ref": "/api/scenes/glass_corridor_001/floorplan",
            "objects": [
                {
                    "id": "glass_wall_001",
                    "type": "glass_wall",
                    "label": "glass wall",
                    "placement": "line",
                    "geometry": {
                        "type": "line",
                        "start": [1.0, 0.5],
                        "end": [3.0, 0.5],
                        "height_m": 2.4,
                        "thickness_m": 0.1,
                    },
                    "material": "clear_glass",
                    "navigation": {
                        "blocks_navigation": True,
                        "hazard_type": "transparent_obstacle",
                        "include_in_hazard_mask": True,
                        "instruction_candidate": True,
                    },
                }
            ],
            "regions": [
                {
                    "id": "floor_001",
                    "type": "traversable",
                    "label": "floor",
                    "placement": "rectangle",
                    "geometry": {"type": "rectangle", "bounds": [0.0, 0.0, 4.0, 2.0]},
                    "navigation": {"blocks_navigation": False},
                },
                {
                    "id": "goal_001",
                    "type": "goal",
                    "label": "chair",
                    "placement": "rectangle",
                    "geometry": {"type": "rectangle", "bounds": [3.2, 1.2, 3.8, 1.8]},
                    "navigation": {"goal_candidate": True, "instruction_candidate": True},
                },
            ],
            "materials": [],
            "settings": {},
            "metadata": {},
        }

    def test_compile_minimum_map_to_valid_scene_annotation(self) -> None:
        result = compile_authoring_map(self.minimum_map(), usd_ref="scenes/glass_corridor_001/scene.usd")
        annotation = result.annotation
        validate_scene_annotation(annotation)
        self.assertEqual(annotation.scene_id, "glass_corridor_001")
        self.assertEqual(annotation.usd_ref, "scenes/glass_corridor_001/scene.usd")
        self.assertIn("glass_wall_001", annotation.transparent_surfaces)
        self.assertEqual(annotation.objects[0].object_id, "glass_wall_001")
        self.assertTrue(annotation.objects[0].mask_export)
        self.assertTrue(any(item.region_id == "hazard_glass_wall_001" for item in annotation.hazard_regions))
        self.assertTrue(any(item.region_id == "obstacle_glass_wall_001" and not item.traversable for item in annotation.traversable_regions))
        self.assertTrue(any(item.region_id == "floor_001" and item.traversable for item in annotation.traversable_regions))
        self.assertEqual(annotation.goal_regions[0].region_id, "goal_001")
        self.assertEqual(result.sync["dataset"], "synced")
        self.assertEqual(result.sync["render_scene"], "pending")

    def test_compiled_annotation_can_build_traversability_grid(self) -> None:
        annotation = compile_authoring_map(self.minimum_map()).annotation
        grid = build_traversability_grid(annotation, resolution=0.05, margin=0.0)
        self.assertGreater(grid.spec.width, 1)
        self.assertTrue(grid.traversable.any())
        self.assertTrue(grid.hazard.any())

    def test_compile_mirror_wall_sets_reflective_hazard(self) -> None:
        payload = self.minimum_map()
        payload["objects"][0]["id"] = "mirror_wall_001"
        payload["objects"][0]["type"] = "mirror_wall"
        payload["objects"][0]["material"] = "mirror"
        payload["objects"][0]["navigation"]["hazard_type"] = "reflective_obstacle"
        result = compile_authoring_map(payload)
        self.assertIn("mirror_wall_001", result.annotation.reflective_hazards)
        self.assertTrue(any(item.hazard_type == "reflective_obstacle" for item in result.annotation.hazard_regions))

    def test_compile_error_payload_identifies_authoring_item(self) -> None:
        payload = self.minimum_map()
        payload["regions"][1]["geometry"]["bounds"] = [1.0, 1.0, 1.0, 2.0]
        with self.assertRaises(AuthoringMapCompileError) as ctx:
            compile_authoring_map(payload)
        body = ctx.exception.to_payload()
        self.assertEqual(body["stage"], "compile_annotation")
        first = body["errors"][0]
        self.assertEqual(first["id"], "goal_001")
        self.assertIn("bounds", first["field"])

    def test_render_scene_sync_payload_materializes_overlay_manifest(self) -> None:
        payload = self.minimum_map()
        result = compile_authoring_map(payload, usd_ref="scenes/glass_corridor_001/scene.usd")
        scene_variant, overlay, sync = build_render_scene_sync_payload(payload, result.annotation)
        self.assertEqual(sync["render_scene"], "synced")
        self.assertEqual(sync["isaac_stage"], "pending")
        self.assertEqual(scene_variant["render_sync_mode"], "editor_generated_xml")
        self.assertEqual(scene_variant["base_usd_ref"], "scenes/glass_corridor_001/scene.usd")
        self.assertEqual(overlay["hazard_mask_targets"][0]["object_id"], "glass_wall_001")
        self.assertEqual(overlay["material_bindings"][0]["material"], "clear_glass")

    def test_validation_requires_synced_render_scene_artifacts(self) -> None:
        payload = self.minimum_map()
        result = compile_authoring_map(payload, usd_ref="scenes/glass_corridor_001/scene.usd")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scene_dir = root / "scenes" / result.annotation.scene_id
            sync_result = write_render_scene_sync(scene_dir, payload, result.annotation, project_dir=root)
            render_scene = scene_dir / "render_scene.xml"
            render_scene.write_text("<scene version=\"3.0.0\" />", encoding="utf-8")
            readiness = scene_dir / "render_readiness.json"
            readiness.write_text('{"ok": true}', encoding="utf-8")
            result.annotation.metadata["sync"] = {
                **sync_result.sync,
                "scene_variant_ref": sync_result.scene_variant_ref,
                "render_scene_overlay_ref": sync_result.overlay_ref,
                "render_scene_xml_ref": render_scene.relative_to(root).as_posix(),
                "render_readiness_ref": readiness.relative_to(root).as_posix(),
            }
            write_scene_annotation(scene_dir / "scene_annotation.json", result.annotation)
            report = validate_dataset(root)
            self.assertTrue(report.ok, report.errors)
            (root / sync_result.overlay_ref).unlink()
            report = validate_dataset(root)
            self.assertFalse(report.ok)
            self.assertTrue(any("missing synced render-scene artifact" in item for item in report.errors))


if __name__ == "__main__":
    unittest.main()
