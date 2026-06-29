from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from mitsuba_converter.multimodal import (
    _apply_measured_scope_policy,
    _convert_channel_split_measured_bsdfs_to_rgb_plugin,
    _pbrdf_band_policy_inventory,
    _substitute_measured_bsdfs_with_diffuse,
    _stage_measured_bsdfs_for_rgb,
)
from mitsuba_converter.render_daemon import (
    RenderDaemon,
    _append_bsdf_xml,
    _build_render_scene_material_policy,
    _generate_opticalnav_render_scene_xml,
    _select_part_render_material,
)


def _hpbrdf_material_index() -> dict[str, dict]:
    return {
        "sample_hpbrdf": {
            "render_binding": {
                "kind": "hpbrdf_2025",
                "material_id": "white_smooth_plastic",
                "bsdf_strategy": "measured_polarized",
                "channels_dir": "data/hpbrdf_2025/channels/white_smooth_plastic",
            }
        }
    }


def _measured_child(shape: ET.Element) -> ET.Element:
    bsdf = shape.find("./bsdf[@type='twosided']/bsdf[@type='measured_polarized']")
    assert bsdf is not None
    return bsdf


def test_hpbrdf_measured_bsdf_emits_albedo_scale_bitmap(tmp_path: Path) -> None:
    texture = tmp_path / "oak.png"
    texture.write_bytes(b"not-a-real-png-but-existing")
    shape = ET.Element("shape")

    _append_bsdf_xml(
        shape,
        "sample_hpbrdf",
        _hpbrdf_material_index(),
        repo_root=Path.cwd(),
        extracted_material={
            "source": "obj_mtl",
            "base_color_texture_ref": str(texture),
            "base_color_factor": [0.1, 0.2, 0.3],
        },
    )

    bsdf = _measured_child(shape)
    assert bsdf.find("./string[@name='filename']").get("value").endswith("/542.pbrdf")
    tex = bsdf.find("./texture[@name='albedo_scale'][@type='bitmap']")
    assert tex is not None
    assert tex.find("./string[@name='filename']").get("value") == str(texture)


def test_hpbrdf_measured_bsdf_emits_albedo_scale_factor_when_no_bitmap() -> None:
    shape = ET.Element("shape")

    _append_bsdf_xml(
        shape,
        "sample_hpbrdf",
        _hpbrdf_material_index(),
        repo_root=Path.cwd(),
        extracted_material={"base_color_factor": [1.2, 0.4, -0.5]},
    )

    bsdf = _measured_child(shape)
    rgb = bsdf.find("./rgb[@name='albedo_scale']")
    assert rgb is not None
    assert rgb.get("value") == "1 0.4 0"


def test_rgb_plugin_conversion_preserves_albedo_scale_texture() -> None:
    root = ET.fromstring(
        """
        <scene version="3.0.0">
          <shape type="obj">
            <bsdf type="measured_polarized">
              <string name="filename" value="data/hpbrdf_2025/channels/white_smooth_plastic/542.pbrdf"/>
              <texture name="albedo_scale" type="bitmap">
                <string name="filename" value="/tmp/oak.png"/>
              </texture>
              <float name="alpha_sample" value="0.08"/>
            </bsdf>
          </shape>
        </scene>
        """
    )

    assert _convert_channel_split_measured_bsdfs_to_rgb_plugin(root) == 1
    bsdf = root.find(".//bsdf")
    assert bsdf is not None
    assert bsdf.get("type") == "measured_polarized_rgb"
    assert bsdf.find("./string[@name='filename_r']") is not None
    assert bsdf.find("./string[@name='filename_g']") is not None
    assert bsdf.find("./string[@name='filename_b']") is not None
    tex = bsdf.find("./texture[@name='albedo_scale'][@type='bitmap']")
    assert tex is not None
    assert tex.find("./string[@name='filename']").get("value") == "/tmp/oak.png"


def test_single_band_rgb_staging_adds_542_wavelength_and_preserves_albedo_scale() -> None:
    root = ET.fromstring(
        """
        <scene version="3.0.0">
          <bsdf type="measured_polarized" id="wall_mat">
            <string name="filename" value="data/hpbrdf_2025/channels/white_smooth_plastic/614.pbrdf"/>
            <texture name="albedo_scale" type="bitmap">
              <string name="filename" value="/tmp/wall.png"/>
            </texture>
          </bsdf>
        </scene>
        """
    )

    counts = _stage_measured_bsdfs_for_rgb(root, band_mode="single")

    assert counts["three_band_converted"] == 0
    bsdf = root.find(".//bsdf")
    assert bsdf is not None
    assert bsdf.get("type") == "measured_polarized"
    assert bsdf.find("./string[@name='filename']").get("value").endswith("/542.pbrdf")
    assert bsdf.find("./float[@name='wavelength']").get("value") == "542"
    assert bsdf.find("./texture[@name='albedo_scale'][@type='bitmap']") is not None
    inventory = _pbrdf_band_policy_inventory(root)
    assert inventory["single_band_measured"] == 1
    assert inventory["three_band_measured"] == 0


def test_measured_scope_policy_injects_budgeted_candidates_after_analytic_source(tmp_path: Path) -> None:
    scene_path = tmp_path / "render_scene.xml"
    scene_path.write_text(
        """
        <scene version="3.0.0">
          <integrator type="path"/>
          <shape type="obj" id="metal_shape">
            <string name="filename" value="metal.obj"/>
            <bsdf type="twosided"><bsdf type="roughconductor"/></bsdf>
          </shape>
          <shape type="obj" id="wall_shape">
            <string name="filename" value="wall.obj"/>
            <bsdf type="twosided"><bsdf type="pplastic"/></bsdf>
          </shape>
        </scene>
        """,
        encoding="utf-8",
    )
    policy = _build_render_scene_material_policy(
        scene_id="unit",
        material_policy_records=[
            {
                "shape_id": "metal_shape",
                "material_id": "metal",
                "analytic_strategy": "roughconductor",
                "analytic_capabilities": {"rgb": True, "polarization": True},
                "analytic_polar_rgb": True,
                "invalid_analytic_fallback": False,
                "measured_role": "anchor",
                "measured_candidate": {
                    "kind": "hpbrdf_2025",
                    "material_id": "aluminum",
                    "bsdf_strategy": "measured_polarized",
                    "channels_dir": "data/hpbrdf_2025/channels/aluminum",
                    "base_color_factor": [0.8, 0.7, 0.6],
                },
            },
            {
                "shape_id": "wall_shape",
                "material_id": "wall",
                "analytic_strategy": "pplastic",
                "analytic_capabilities": {"rgb": True, "polarization": True},
                "analytic_polar_rgb": True,
                "invalid_analytic_fallback": False,
                "measured_role": "candidate",
                "measured_candidate": {
                    "kind": "hpbrdf_2025",
                    "material_id": "white_smooth_plastic",
                    "bsdf_strategy": "measured_polarized",
                    "channels_dir": "data/hpbrdf_2025/channels/white_smooth_plastic",
                },
            },
        ],
    )
    (tmp_path / "render_scene_material_policy.json").write_text(
        json.dumps(policy),
        encoding="utf-8",
    )

    root = ET.parse(scene_path).getroot()
    counts = _apply_measured_scope_policy(
        root,
        source_scene=scene_path,
        measured_scope="analytic_priority",
        max_measured_bsdfs=1,
    )
    assert counts["measured_candidates"] == 2
    assert counts["measured_enabled"] == 1
    assert counts["measured_suppressed"] == 1
    _stage_measured_bsdfs_for_rgb(root, band_mode="single")
    assert root.find(".//shape[@id='metal_shape']//bsdf[@type='measured_polarized']") is not None
    assert root.find(".//shape[@id='wall_shape']//bsdf[@type='measured_polarized']") is None
    measured = root.find(".//shape[@id='metal_shape']//bsdf[@type='measured_polarized']")
    assert measured.find("./string[@name='filename']").get("value").endswith("/542.pbrdf")
    assert measured.find("./float[@name='wavelength']").get("value") == "542"
    assert measured.find("./rgb[@name='albedo_scale']").get("value") == "0.8 0.7 0.6"
    assert measured.find("./string[@name='material_id']") is None


def test_measured_scope_analytic_only_keeps_policy_scene_fully_analytic(tmp_path: Path) -> None:
    scene_path = tmp_path / "render_scene.xml"
    scene_path.write_text(
        """
        <scene version="3.0.0">
          <shape type="obj" id="metal_shape">
            <string name="filename" value="metal.obj"/>
            <bsdf type="twosided"><bsdf type="roughconductor"/></bsdf>
          </shape>
        </scene>
        """,
        encoding="utf-8",
    )
    policy = _build_render_scene_material_policy(
        scene_id="unit",
        material_policy_records=[
            {
                "shape_id": "metal_shape",
                "material_id": "metal",
                "analytic_strategy": "roughconductor",
                "analytic_capabilities": {"rgb": True, "polarization": True},
                "analytic_polar_rgb": True,
                "invalid_analytic_fallback": False,
                "measured_role": "anchor",
                "measured_candidate": {
                    "kind": "hpbrdf_2025",
                    "material_id": "aluminum",
                    "bsdf_strategy": "measured_polarized",
                    "channels_dir": "data/hpbrdf_2025/channels/aluminum",
                },
            }
        ],
    )
    (tmp_path / "render_scene_material_policy.json").write_text(
        json.dumps(policy),
        encoding="utf-8",
    )

    root = ET.parse(scene_path).getroot()
    counts = _apply_measured_scope_policy(
        root,
        source_scene=scene_path,
        measured_scope="analytic_only",
        max_measured_bsdfs=3,
    )

    assert counts["measured_candidates"] == 1
    assert counts["measured_enabled"] == 0
    assert counts["measured_suppressed"] == 1
    assert root.find(".//bsdf[@type='measured_polarized']") is None
    assert root.find(".//bsdf[@type='roughconductor']") is not None


def test_render_scene_stats_reads_material_policy_sidecar(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    scene_dir = project_dir / "scenes" / "unit"
    scene_dir.mkdir(parents=True)
    (scene_dir / "render_scene.xml").write_text(
        """
        <scene version="3.0.0">
          <shape type="obj" id="metal_shape">
            <string name="filename" value="metal.obj"/>
            <bsdf type="twosided"><bsdf type="roughconductor"/></bsdf>
          </shape>
        </scene>
        """,
        encoding="utf-8",
    )
    policy = _build_render_scene_material_policy(
        scene_id="unit",
        material_policy_records=[
            {
                "shape_id": "metal_shape",
                "material_id": "metal",
                "analytic_strategy": "roughconductor",
                "analytic_capabilities": {"rgb": True, "polarization": True},
                "analytic_polar_rgb": True,
                "invalid_analytic_fallback": False,
                "measured_role": "anchor",
                "measured_candidate": {
                    "kind": "hpbrdf_2025",
                    "material_id": "aluminum",
                    "bsdf_strategy": "measured_polarized",
                    "channels_dir": "data/hpbrdf_2025/channels/aluminum",
                },
            }
        ],
    )
    (scene_dir / "render_scene_material_policy.json").write_text(
        json.dumps(policy),
        encoding="utf-8",
    )
    daemon = object.__new__(RenderDaemon)
    daemon.repo_root = tmp_path

    stats = RenderDaemon._opticalnav_render_scene_stats(daemon, project_dir, "unit")

    assert stats["exists"] is True
    assert stats["shape_count"] == 1
    assert stats["measured_candidates"] == 1
    assert stats["measured_enabled_default"] == 1
    assert stats["material_policy_ref"] == "project/scenes/unit/render_scene_material_policy.json"


def test_hybrid_rgb_staging_keeps_achromatic_single_and_converts_coloured() -> None:
    root = ET.fromstring(
        """
        <scene version="3.0.0">
          <bsdf type="measured_polarized" id="plastic">
            <string name="filename" value="data/hpbrdf_2025/channels/white_smooth_plastic/542.pbrdf"/>
            <rgb name="albedo_scale" value="0.8 0.8 0.8"/>
          </bsdf>
          <bsdf type="measured_polarized" id="gold">
            <string name="filename" value="data/hpbrdf_2025/channels/fake_gold/542.pbrdf"/>
            <rgb name="albedo_scale" value="1 0.7 0.2"/>
          </bsdf>
        </scene>
        """
    )

    counts = _stage_measured_bsdfs_for_rgb(root, band_mode="hybrid")

    assert counts["three_band_converted"] == 1
    plastic = root.find(".//bsdf[@id='plastic']")
    gold = root.find(".//bsdf[@id='gold']")
    assert plastic is not None and gold is not None
    assert plastic.get("type") == "measured_polarized"
    assert plastic.find("./float[@name='wavelength']").get("value") == "542"
    assert gold.get("type") == "measured_polarized_rgb"
    assert gold.find("./string[@name='filename_r']") is not None
    inventory = _pbrdf_band_policy_inventory(root)
    assert inventory["single_band_measured"] == 1
    assert inventory["three_band_measured"] == 1


def test_aov_measured_substitution_replaces_nested_twosided_measured_bsdfs() -> None:
    root = ET.fromstring(
        """
        <scene version="3.0.0">
          <bsdf type="twosided" id="shared_mat">
            <bsdf type="measured_polarized">
              <string name="filename" value="data/hpbrdf_2025/channels/aluminum/542.pbrdf"/>
            </bsdf>
          </bsdf>
        </scene>
        """
    )

    assert _substitute_measured_bsdfs_with_diffuse(root) == 1
    assert root.find(".//bsdf[@type='measured_polarized']") is None
    assert root.find(".//bsdf[@type='diffuse']/rgb[@name='reflectance']") is not None


def test_pbrdf_fallback_measured_bsdf_emits_albedo_scale_bitmap(tmp_path: Path) -> None:
    texture = tmp_path / "leather.png"
    texture.write_bytes(b"not-a-real-png-but-existing")
    material_id, material_class = _select_part_render_material(
        None,
        {
            "mesh_name": "Chair_Leather",
            "mesh_prim_path": "/World/barChairs/Chair_Leather",
        },
        {"base_color_texture_ref": str(texture)},
        {},
        repo_root=tmp_path,
    )
    assert material_class == "leather"
    assert material_id == "pbrdf_2020:black_billiard"

    shape = ET.Element("shape")
    _append_bsdf_xml(
        shape,
        material_id,
        {},
        repo_root=Path.cwd(),
        extracted_material={"base_color_texture_ref": str(texture)},
    )

    bsdf = _measured_child(shape)
    assert bsdf.find("./string[@name='filename']").get("value").endswith("4_black_billiard_inpainted.pbsdf")
    tex = bsdf.find("./texture[@name='albedo_scale'][@type='bitmap']")
    assert tex is not None
    assert tex.find("./string[@name='filename']").get("value") == str(texture)


def test_usd_prim_mesh_parts_emit_multiple_shapes_with_part_materials(tmp_path: Path) -> None:
    leather_texture = tmp_path / "leather.png"
    wood_texture = tmp_path / "wood.png"
    leather_texture.write_bytes(b"not-a-real-png-but-existing")
    wood_texture.write_bytes(b"not-a-real-png-but-existing")
    for name in ("leather.obj", "metal.obj", "wood.obj"):
        (tmp_path / name).write_text("# empty test obj\n", encoding="utf-8")

    def mesh_resolver(_usd_ref: str, _prim_path: str):
        return tmp_path / "combined.obj", {
            "mesh_parts": [
                {
                    "part_id": "part_000_Chair_Leather",
                    "obj_ref": str(leather_texture.with_name("leather.obj")),
                    "mesh_prim_path": "/World/barChairs/Chair_Leather",
                    "mesh_name": "Chair_Leather",
                    "triangle_count": 10,
                    "extracted_material": {"base_color_texture_ref": str(leather_texture)},
                },
                {
                    "part_id": "part_001_Chair_Metal",
                    "obj_ref": str(leather_texture.with_name("metal.obj")),
                    "mesh_prim_path": "/World/barChairs/Chair_Metal",
                    "mesh_name": "Chair_Metal",
                    "triangle_count": 20,
                    "extracted_material": {"metallic_factor": 1.0},
                },
                {
                    "part_id": "part_002_Chair_wood",
                    "obj_ref": str(leather_texture.with_name("wood.obj")),
                    "mesh_prim_path": "/World/barChairs/Chair_wood",
                    "mesh_name": "Chair_wood",
                    "triangle_count": 30,
                    "extracted_material": {"base_color_texture_ref": str(wood_texture)},
                },
            ]
        }

    records: list[dict] = []
    out_xml = tmp_path / "render_scene.xml"
    added = _generate_opticalnav_render_scene_xml(
        {
            "scene_id": "unit",
            "settings": {
                "auto_floor_enabled": False,
                "wall_shell_enabled": False,
            },
            "materials": [],
        },
        {
            "objects": [
                {
                    "id": "chair_test",
                    "label": "chair",
                    "type": "chair",
                    "material": None,
                    "source_ref": "asset.usd#/World/barChairs",
                    "geometry": {
                        "type": "box",
                        "center": [1.0, 2.0],
                        "size_m": [1.0, 1.0, 1.0],
                    },
                }
            ]
        },
        out_xml,
        repo_root=tmp_path,
        mesh_resolver=mesh_resolver,
        materialization_records=records,
    )

    assert added == 3
    root = ET.parse(out_xml).getroot()
    assert root.find(".//shape[@id='chair_test']") is not None
    assert root.find(".//shape[@id='chair_test__part_000_Chair_Leather']") is not None
    assert root.find(".//shape[@id='chair_test__part_001_Chair_Metal']") is not None
    assert len(root.findall(".//texture[@name='albedo_scale'][@type='bitmap']")) == 2
    metal_shape = root.find(".//shape[@id='chair_test__part_001_Chair_Metal']")
    assert metal_shape is not None
    assert metal_shape.find("./ref") is not None
    assert root.find(".//bsdf[@type='conductor']") is not None

    part_records = [rec for rec in records if rec.get("source_type") == "usd_prim_part"]
    assert len(part_records) == 3
    by_mesh = {rec["extras"]["mesh_name"]: rec["extras"] for rec in part_records}
    assert by_mesh["Chair_Leather"]["material_class"] == "leather"
    assert by_mesh["Chair_Metal"]["material_class"] == "metal"
    assert by_mesh["Chair_wood"]["material_class"] == "wood"
