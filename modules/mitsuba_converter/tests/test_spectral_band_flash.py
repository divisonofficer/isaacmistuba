import json
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mitsuba_converter.material_pipeline import build_band_scene


_APP_PATH = Path(__file__).resolve().parents[3] / "apps" / "render_ir_dataset.py"
_APP_SPEC = importlib.util.spec_from_file_location("render_ir_dataset", _APP_PATH)
_APP = importlib.util.module_from_spec(_APP_SPEC)
assert _APP_SPEC.loader is not None
_APP_SPEC.loader.exec_module(_APP)


def _minimal_scene(tmp_path):
    scene = tmp_path / "render_scene.xml"
    scene.write_text(
        '<scene version="3.0.0">'
        '<integrator type="path"/>'
        '<bsdf type="diffuse" id="mat"><rgb name="reflectance" value="0.5"/></bsdf>'
        '<shape type="rectangle" id="shape"><ref id="mat"/></shape>'
        '</scene>'
    )
    (tmp_path / "xml_scene_index.json").write_text(json.dumps({
        "shapes": [{"shape_id": "shape", "bsdf_ref": "mat"}],
    }))
    (tmp_path / "render_scene_material_policy.json").write_text(json.dumps({
        "shape_policies": [{"shape_id": "shape", "material_id": "mat"}],
    }))
    return scene, {"materials": [{"material_id": "mat", "optical_class": "diffuse"}]}


def test_build_band_scene_can_stage_microbrite_spot(tmp_path):
    scene, canonical = _minimal_scene(tmp_path)
    output = tmp_path / "band.xml"

    summary = build_band_scene(
        scene,
        canonical,
        output,
        nir_flash=True,
        nir_flash_model="spot",
        nir_flash_beam_width_deg=22.0,
        nir_flash_cutoff_angle_deg=30.0,
        nir_flash_initial_radiance=400.0,
        force_analytic=False,
        polarized=False,
        enforce_bsdf_contract=False,
    )

    root = ET.parse(output).getroot()
    emitter = root.find("emitter[@id='nir_flash']")
    assert emitter is not None
    assert emitter.get("type") == "spot"
    assert root.find("shape[@id='nir_flash']") is None
    assert emitter.find("transform[@name='to_world']") is not None
    assert emitter.find("rgb[@name='intensity']").get("value") == "400 400 400"
    assert emitter.find("float[@name='beam_width']").get("value") == "22"
    assert emitter.find("float[@name='cutoff_angle']").get("value") == "30"
    assert summary["nir_flash_model"] == "spot"


def test_build_band_scene_rejects_unknown_flash_model(tmp_path):
    scene, canonical = _minimal_scene(tmp_path)
    with pytest.raises(ValueError, match="nir_flash_model"):
        build_band_scene(
            scene,
            canonical,
            tmp_path / "band.xml",
            nir_flash=True,
            nir_flash_model="laser",
            force_analytic=False,
            polarized=False,
            enforce_bsdf_contract=False,
        )


def test_flash_only_scene_removes_ambient_emitters(tmp_path):
    scene, canonical = _minimal_scene(tmp_path)
    tree = ET.parse(scene)
    root = tree.getroot()
    ET.SubElement(root, "emitter", {"type": "constant", "id": "ambient"})
    lit_shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": "ceiling_light"})
    ET.SubElement(lit_shape, "emitter", {"type": "area"})
    tree.write(scene, encoding="unicode")

    output = tmp_path / "flash.xml"
    summary = build_band_scene(
        scene,
        canonical,
        output,
        integrator="direct",
        nir_flash=True,
        flash_only=True,
        nir_flash_model="spot",
        force_analytic=False,
        polarized=False,
        enforce_bsdf_contract=False,
    )

    root = ET.parse(output).getroot()
    assert [e.get("id") for e in root.findall("emitter")] == ["nir_flash"]
    assert root.find("shape[@id='ceiling_light']/emitter") is None
    assert summary["ambient_emitters_removed"] == 2


def test_rig_light_offset_is_camera_local_and_does_not_scale_translation():
    camera = pytest.importorskip("numpy").eye(4, dtype="float32")
    camera[:3, 3] = [3.0, 1.2, 2.0]

    spot = _APP._rig_light_to_world(camera, offset_y_m=-0.1, area_half_m=None)
    area = _APP._rig_light_to_world(camera, offset_y_m=-0.1, area_half_m=0.015)

    assert spot[:3, 3].tolist() == pytest.approx([3.0, 1.1, 2.0])
    assert area[:3, 3].tolist() == pytest.approx([3.0, 1.1, 2.0])
    assert area[0, 0] == pytest.approx(0.015)


def test_render_sensor_and_spot_share_the_same_forward_axis():
    camera = _APP._camera({"position": [2.5, 2.2, 0.0]}, 180.0)

    sensor, spot = _APP._render_rig_transforms(
        camera,
        offset_y_m=-0.1,
        area_half_m=None,
    )

    assert spot[:3, 2].tolist() == pytest.approx(sensor[:3, 2].tolist())
    assert spot[:3, 3].tolist() == pytest.approx(
        (sensor[:3, 3] - 0.1 * sensor[:3, 1]).tolist()
    )
