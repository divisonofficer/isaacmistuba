from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(MODULE_PATH) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH))

from navigation_dataset.authoring_map import (  # noqa: E402
    AuthoringMapValidationError,
    authoring_map_to_payload,
    load_authoring_map,
    save_authoring_map,
    starter_authoring_map,
    validate_authoring_map,
)


class AuthoringMapTests(unittest.TestCase):
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
                        "start": [1.0, 2.0],
                        "end": [4.0, 2.0],
                        "height_m": 2.4,
                        "thickness_m": 0.04,
                    },
                    "material": "clear_glass",
                    "navigation": {
                        "blocks_navigation": True,
                        "hazard_type": "transparent_obstacle",
                        "include_in_hazard_mask": True,
                        "instruction_candidate": True,
                        "goal_candidate": False,
                    },
                }
            ],
            "regions": [
                {
                    "id": "floor_001",
                    "type": "traversable",
                    "label": "floor",
                    "placement": "rectangle",
                    "geometry": {"type": "rectangle", "bounds": [0.0, 0.0, 5.0, 3.0]},
                    "navigation": {"blocks_navigation": False},
                },
                {
                    "id": "goal_001",
                    "type": "goal",
                    "label": "goal",
                    "placement": "rectangle",
                    "geometry": {"type": "rectangle", "bounds": [4.0, 1.0, 4.5, 1.5]},
                    "navigation": {"goal_candidate": True, "instruction_candidate": True},
                },
            ],
            "materials": [],
            "settings": {
                "grid_size_m": 0.25,
                "default_wall_height_m": 2.4,
                "default_wall_thickness_m": 0.08,
            },
            "metadata": {},
        }

    def test_starter_authoring_map_is_saveable(self) -> None:
        starter = starter_authoring_map("glass_corridor_001", "/api/scenes/glass_corridor_001/floorplan")
        validate_authoring_map(starter)
        payload = authoring_map_to_payload(starter)
        self.assertEqual(payload["scene_id"], "glass_corridor_001")
        self.assertEqual(payload["objects"], [])

    def test_minimum_authoring_map_roundtrip_and_compile_ready(self) -> None:
        payload = self.minimum_map()
        validate_authoring_map(payload, require_compile_ready=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "authoring_map.json"
            save_authoring_map(path, payload)
            restored = authoring_map_to_payload(load_authoring_map(path))
            self.assertEqual(restored["scene_id"], payload["scene_id"])
            self.assertEqual(restored["objects"][0]["id"], "glass_wall_001")
            self.assertEqual(restored["regions"][1]["type"], "goal")

    def test_validation_reports_object_id_field_and_reason(self) -> None:
        payload = self.minimum_map()
        payload["objects"][0]["geometry"]["end"] = [1.0, 2.0]
        with self.assertRaises(AuthoringMapValidationError) as ctx:
            validate_authoring_map(payload)
        body = ctx.exception.to_payload()
        self.assertEqual(body["status"], "blocked")
        first = body["errors"][0]
        self.assertEqual(first["id"], "glass_wall_001")
        self.assertEqual(first["field"], "geometry.end")
        self.assertIn("positive length", first["reason"])

    def test_compile_ready_requires_traversable_and_goal_regions(self) -> None:
        starter = authoring_map_to_payload(starter_authoring_map("empty_scene"))
        validate_authoring_map(starter)
        with self.assertRaises(AuthoringMapValidationError) as ctx:
            validate_authoring_map(starter, require_compile_ready=True)
        reasons = " ".join(item["reason"] for item in ctx.exception.to_payload()["errors"])
        self.assertIn("traversable", reasons)
        self.assertIn("goal", reasons)

    def test_render_ready_schema_roundtrip(self) -> None:
        payload = self.minimum_map()
        payload["environment"] = {"mode": "constant", "radiance": [0.7, 0.8, 0.9], "intensity": 1.2}
        payload["camera_rig"] = {
            "rig_id": "rig_test",
            "base_frame": "base_link",
            "sensors": [
                {
                    "sensor_id": "rgb_front",
                    "label": "RGB Front",
                    "modality": "rgb",
                    "mount": {"xyz_m": [0.2, 1.0, 0.0], "rpy_deg": [0, 0, 2]},
                    "fov_deg": 75,
                    "resolution": [800, 600],
                }
            ],
        }
        payload["objects"].append({
            "id": "box_001",
            "type": "chair",
            "label": "box",
            "placement": "point",
            "geometry": {"type": "point", "center": [1.0, 1.0], "size_m": [0.5, 0.8, 0.4], "base_height_m": 0.1, "yaw_deg": 15, "pitch_deg": 1, "roll_deg": 2, "scale": [1, 1, 1]},
            "material": "dataset:mat",
            "navigation": {"blocks_navigation": True},
        })
        payload["materials"] = [{
            "material_id": "dataset:mat",
            "category": "measured",
            "render_binding": {"kind": "measured", "dataset_id": "dataset", "material_id": "mat", "bsdf_strategy": "measured_polarized", "native_file": "materials/mat.pbsdf"},
        }]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "authoring_map.json"
            save_authoring_map(path, payload)
            restored = authoring_map_to_payload(load_authoring_map(path))
        self.assertEqual(restored["environment"]["radiance"], [0.7, 0.8, 0.9])
        self.assertEqual(restored["camera_rig"]["sensors"][0]["modality"], "rgb")
        self.assertEqual(restored["objects"][-1]["geometry"]["size_m"], [0.5, 0.8, 0.4])
        self.assertEqual(restored["materials"][0]["render_binding"]["bsdf_strategy"], "measured_polarized")


if __name__ == "__main__":
    unittest.main()

