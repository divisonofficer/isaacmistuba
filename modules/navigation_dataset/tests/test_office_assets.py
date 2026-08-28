from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(MODULE_PATH) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH))

from navigation_dataset.authoring_compile import compile_authoring_map  # noqa: E402
from navigation_dataset.authoring_map import validate_authoring_map  # noqa: E402
from navigation_dataset.office_assets import (  # noqa: E402
    build_office_asset_coverage,
    classify_office_asset_text,
    default_office_material_hint,
)
from navigation_dataset.office_sample import install_shared_office_sample  # noqa: E402


class OfficeAssetCoverageTests(unittest.TestCase):
    def test_classifies_shared_office_taxonomy(self) -> None:
        self.assertIn("desk", classify_office_asset_text("LiteOffice_Desk_A"))
        self.assertIn("keyboard_mouse", classify_office_asset_text("Keyboard_B08SBG4JG7_Black"))
        self.assertIn("fire_safety", classify_office_asset_text("FireAlarm"))
        self.assertIn("reflective_surface", classify_office_asset_text("polished aluminum mirror wall"))

    def test_office_default_materials_are_render_ready_refs(self) -> None:
        self.assertEqual(default_office_material_hint("glass_partition", "glass wall"), "clear_glass")
        self.assertEqual(default_office_material_hint("reflective_surface", "mirror wall"), "mirror")
        self.assertEqual(default_office_material_hint("monitor_computer", "keyboard"), "pbrdf_2020:black_billiard")
        self.assertEqual(default_office_material_hint("fire_safety", "fire extinguisher"), "pbrdf_2020:red_billiard")

    def test_coverage_report_merges_available_and_download_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            builtins = root / "apps" / "webui" / "src" / "lib"
            builtins.mkdir(parents=True)
            (builtins / "opticalnavBuiltInAssets.ts").write_text(
                "moorelaneAsset('glass_panel', 'Glass Panel', '/ROOT/glass', 'glass', 'Reflective Surfaces', [1,2,0.1], 'clear_glass', ['glass']);",
                encoding="utf-8",
            )
            dtc_index = root / "assets" / "dtc_object"
            dtc_index.mkdir(parents=True)
            (dtc_index / "DTC_objects_all_download_urls.json").write_text(
                json.dumps({
                    "objects": {
                        "LiteOffice_Desk_A": {
                            "asset": {"filename": "DTC_1_1_LiteOffice_Desk_A_3d-asset.glb"}
                        },
                        "Keyboard_B08SBG4JG7_Black": {
                            "asset": {"filename": "DTC_1_1_Keyboard_B08SBG4JG7_Black_3d-asset.glb"}
                        },
                    }
                }),
                encoding="utf-8",
            )
            report = build_office_asset_coverage(root)
        self.assertEqual(report["summary"]["glass_partition"]["status"], "available")
        self.assertEqual(report["summary"]["desk"]["status"], "download_candidate")
        self.assertEqual(report["summary"]["keyboard_mouse"]["download_candidate_count"], 1)

    def test_shared_office_seed_scene_validates_and_compiles(self) -> None:
        payload = json.loads((REPO_ROOT / "tests" / "fixtures" / "opticalnav" / "shared_office_authoring_map.json").read_text(encoding="utf-8"))
        validate_authoring_map(payload, require_compile_ready=True)
        result = compile_authoring_map(payload, usd_ref="scenes/shared_office_floor_001/scene.usd")
        self.assertIn("meeting_glass_front", result.annotation.transparent_surfaces)
        self.assertIn("reflective_lobby_wall", result.annotation.reflective_hazards)
        object_ids = {item.object_id for item in result.annotation.objects}
        self.assertIn("printer_placeholder", object_ids)
        self.assertIn("fire_safety_placeholder", object_ids)
        self.assertTrue(any(item.region_id == "goal_desk" for item in result.annotation.goal_regions))

    def test_install_shared_office_sample_writes_editor_scene_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = install_shared_office_sample(
                root,
                fixture_path=REPO_ROOT / "tests" / "fixtures" / "opticalnav" / "shared_office_authoring_map.json",
            )
            scene_dir = root / "out" / "opticalnav" / result.project_id / "scenes" / result.scene_id
            for filename in (
                "authoring_map.json",
                "scene_annotation.json",
                "scene_variant.json",
                "render_scene_overlays.json",
                "sample_map_summary.json",
                "render_readiness.json",
            ):
                self.assertTrue((scene_dir / filename).exists(), filename)
            readiness = json.loads((scene_dir / "render_readiness.json").read_text(encoding="utf-8"))
            # In the temporary test root, MooreLane/DTC assets and measured
            # material data are intentionally absent. The installer should still
            # produce editor/render sidecars; readiness may be blocked because
            # those external sources cannot be resolved in the fixture root.
            self.assertIn(readiness["status"], {"ready", "pending", "blocked"})
            if (scene_dir / "xml_scene_index.json").exists():
                xml_index = json.loads((scene_dir / "xml_scene_index.json").read_text(encoding="utf-8"))
                for shape in xml_index.get("shapes", []):
                    mesh_ref = shape.get("mesh_ref")
                    if mesh_ref:
                        self.assertTrue((scene_dir / "mesh_cache" / mesh_ref).exists(), mesh_ref)
                        continue
                    mesh_path = shape.get("mesh_path")
                    if not mesh_path:
                        continue
                    self.assertTrue((scene_dir / "mesh_cache" / Path(mesh_path).name).exists(), mesh_path)
            annotation = json.loads((scene_dir / "scene_annotation.json").read_text(encoding="utf-8"))
            self.assertIsNone(annotation.get("usd_ref"))
            self.assertEqual(result.compile_summary["transparent_surface_count"], 3)
            self.assertIn("printer_copier", result.asset_gap_categories)


if __name__ == "__main__":
    unittest.main()
