from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from mitsuba_converter.material_pipeline.dataset_render import _axial_depth, _stage_readout_xml
from mitsuba_converter.nir_reflectance import nir_reflectance


def test_opaque_readout_uses_raw_roughness_not_squared_alpha(tmp_path: Path) -> None:
    scene = tmp_path / "render_scene.xml"
    scene.write_text(
        """<scene version="3.0.0"><bsdf type="blendbsdf" id="opaque_1">
<texture type="bitmap" name="weight"><string name="filename" value="weight.png"/></texture>
<bsdf type="pplastic"><texture type="bitmap" name="diffuse_reflectance"><string name="filename" value="base.png"/></texture><texture type="bitmap" name="alpha"><string name="filename" value="alpha.png"/></texture></bsdf>
<bsdf type="roughconductor"/></bsdf><shape type="obj" id="shape"><string name="filename" value="mesh.obj"/><ref id="opaque_1"/></shape></scene>"""
    )
    for name in ("base.png", "rough.png", "metal.png", "alpha.png", "weight.png"):
        Image.fromarray(np.full((2, 2, 3), 128, np.uint8)).save(tmp_path / name)
    record = {
        "object_id": "unit",
        "inputs": {"roughness": str(tmp_path / "rough.png"), "roughness_constant": 0.4,
                   "metallic_constant": 0.0},
        "outputs": {"base_color": str(tmp_path / "base.png"),
                    "metallic": str(tmp_path / "metal.png")},
    }
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(record))
    (tmp_path / "opaque_scene_assembly.json").write_text(json.dumps({"replacements": [
        {"bsdf_id": "opaque_1", "spatial_record": str(record_path)}
    ]}))
    (tmp_path / "xml_scene_index.json").write_text(json.dumps({"shapes": [
        {"shape_id": "shape", "bsdf_ref": "opaque_1", "material_id": "mat"}
    ]}))
    (tmp_path / "render_scene_material_policy.json").write_text(json.dumps({"shape_policies": [
        {"shape_id": "shape", "material_id": "mat"}
    ]}))
    canonical = {"materials": [{
        "material_id": "mat", "optical_class": "diffuse", "parameters": {}
    }]}

    rough_xml = _stage_readout_xml(scene, canonical, "roughness")
    root = ET.parse(rough_xml).getroot()
    filename = root.find("./bsdf[@id='opaque_1']/texture/string").get("value")
    assert filename == str((tmp_path / "rough.png").resolve())
    assert "alpha.png" not in filename

    albedo_xml = _stage_readout_xml(scene, canonical, "albedo")
    albedo = ET.parse(albedo_xml).getroot().find("./bsdf[@id='opaque_1']/texture/string")
    assert albedo.get("value") == str((tmp_path / "base.png").resolve())

    nir_xml = _stage_readout_xml(scene, canonical, "nir_albedo", nir_dir=tmp_path / "nir")
    nir_texture = ET.parse(nir_xml).getroot().find("./bsdf[@id='opaque_1']/texture/string")
    assert nir_texture is not None
    assert ".nir854_hybrid.png" in nir_texture.get("value")


def test_axial_depth_makes_a_frontoparallel_plane_constant() -> None:
    directions = np.asarray([
        [0.0, 0.0, 1.0],
        [0.6, 0.0, 0.8],
        [0.0, 0.8, 0.6],
    ], dtype=np.float32)
    plane_z = 2.0
    ray_ranges = plane_z / directions[:, 2]

    result = _axial_depth(ray_ranges, directions, np.asarray([0.0, 0.0, 1.0]))

    assert result.tolist() == pytest.approx([plane_z, plane_z, plane_z])


def test_nir_albedo_readout_uses_material_band_prior(tmp_path: Path) -> None:
    scene = tmp_path / "render_scene.xml"
    scene.write_text(
        '<scene version="3.0.0"><bsdf type="diffuse" id="mat">'
        '<rgb name="reflectance" value="0.2 0.3 0.4"/></bsdf>'
        '<shape type="rectangle" id="shape"><ref id="mat"/></shape></scene>'
    )
    (tmp_path / "xml_scene_index.json").write_text(json.dumps({"shapes": [
        {"shape_id": "shape", "bsdf_ref": "mat", "material_id": "wall_plaster"}
    ]}))
    (tmp_path / "render_scene_material_policy.json").write_text(json.dumps({"shape_policies": [
        {"shape_id": "shape", "material_id": "wall_plaster"}
    ]}))
    canonical = {"materials": [{
        "material_id": "wall_plaster", "optical_class": "diffuse", "parameters": {}
    }]}

    nir_xml = _stage_readout_xml(
        scene, canonical, "nir_albedo", nir_band=854, nir_dir=tmp_path / "nir"
    )

    value = ET.parse(nir_xml).getroot().find("./bsdf[@id='mat']/rgb").get("value")
    expected = nir_reflectance("plaster", 854)["mean"]
    assert [float(v) for v in value.split()] == pytest.approx([expected] * 3)
