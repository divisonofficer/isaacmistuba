from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

from mitsuba_converter.spatial_pbr import convert_spatial_pbr_textures
from mitsuba_converter.spatial_pbr_ab import (
    assert_scene_pair_invariants,
    build_scene_xml,
    resample_atlas_to_screen,
    rgb_roi_metrics,
    screen_space_maps,
)


def _rgb(path: Path, values: np.ndarray) -> None:
    Image.fromarray(np.asarray(values, dtype=np.uint8), mode="RGB").save(path)


def _table() -> dict:
    eta = np.asarray([[0.2, 0.3, 1.2], [1.4, 0.9, 0.5]], dtype=np.float32)
    k = np.asarray([[3.0, 2.0, 1.0], [1.8, 2.2, 2.5]], dtype=np.float32)
    f0 = ((eta - 1.0) ** 2 + k**2) / ((eta + 1.0) ** 2 + k**2)
    return {"names": ["metal_a", "metal_b"], "wavelengths_nm": [650, 550, 450],
            "eta": eta, "k": k, "f0": f0}


def test_f0_index_and_spatial_blend_xml_are_connected(tmp_path: Path) -> None:
    table = _table()
    base = tmp_path / "base.png"
    # Use the exact sRGB encoding of preset 1 F0 closely enough to select it.
    target = np.asarray(table["f0"][1], dtype=np.float32)
    srgb = np.where(target <= 0.0031308, 12.92 * target,
                    1.055 * np.power(target, 1 / 2.4) - 0.055)
    _rgb(base, np.rint(np.clip(srgb, 0, 1) * 255)[None, None, :])
    rough = tmp_path / "rough.png"; metal = tmp_path / "metal.png"
    _rgb(rough, np.full((1, 1, 3), 128, np.uint8))
    _rgb(metal, np.full((1, 1, 3), 191, np.uint8))
    record = convert_spatial_pbr_textures(
        object_id="sample", output_dir=tmp_path / "maps", base_color_path=base,
        roughness_path=rough, metallic_path=metal, conductor_table=table, write_exr=False,
    )
    maps = np.load(record["outputs"]["optical_maps_npz"])
    assert maps["conductor_index"][0, 0] == 2
    assert np.isclose(maps["metallic"][0, 0], 191 / 255)
    assert np.isclose(maps["alpha"][0, 0], (128 / 255) ** 2)

    obj = tmp_path / "mesh.obj"; obj.write_text("v -1 0 -1\nv 1 0 -1\nv 0 1 0\nf 1 2 3\n")
    eta = tmp_path / "eta.exr"; eta.touch(); k = tmp_path / "k.exr"; k.touch()
    material = {"base_color": base, "roughness_raw": rough, "normal": None,
                "metallic": Path(record["outputs"]["metallic"]),
                "alpha": Path(record["outputs"]["alpha"]), "eta": eta, "k": k,
                "optical_class": "diffuse"}
    xml = tmp_path / "B.xml"
    build_scene_xml(path=xml, branch="B", obj_path=obj, material=material,
                    camera_to_world=np.eye(4), light_to_world=np.eye(4),
                    bounds_min=np.asarray([-1, 0, -1]), bounds_max=np.asarray([1, 1, 1]),
                    resolution=8, spp=2, fov_deg=45, radiance=1, seed=0)
    root = ET.parse(xml).getroot()
    blend = root.find(".//shape[@id='experiment_object']//bsdf[@type='blendbsdf']")
    assert blend is not None
    assert blend.find("./texture[@name='weight']") is not None
    metal_bsdf = blend.find("./bsdf[@type='roughconductor']")
    assert metal_bsdf is not None
    assert metal_bsdf.find("./texture[@name='eta']/string").attrib["value"] == str(eta.resolve())
    assert metal_bsdf.find("./texture[@name='k']/string").attrib["value"] == str(k.resolve())
    assert metal_bsdf.find("./texture[@name='eta']/boolean[@name='raw']") is None
    assert metal_bsdf.find("./texture[@name='k']/boolean[@name='raw']") is None
    assert len(blend.findall(".//texture[@name='alpha']")) == 2


def test_scene_pair_shares_geometry_uv_normal_camera_light_and_sampler(tmp_path: Path) -> None:
    obj = tmp_path / "mesh.obj"; obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    paths = {}
    for name in ("base", "rough", "metal", "alpha", "normal"):
        paths[name] = tmp_path / f"{name}.png"
        _rgb(paths[name], np.full((2, 2, 3), 127, np.uint8))
    paths["eta"] = tmp_path / "eta.exr"; paths["eta"].touch()
    paths["k"] = tmp_path / "k.exr"; paths["k"].touch()
    material = {"base_color": paths["base"], "roughness_raw": paths["rough"],
                "metallic": paths["metal"], "alpha": paths["alpha"], "normal": paths["normal"],
                "eta": paths["eta"], "k": paths["k"], "optical_class": "diffuse"}
    for branch in ("A", "B"):
        build_scene_xml(path=tmp_path / f"{branch}.xml", branch=branch, obj_path=obj,
                        material=material, camera_to_world=np.eye(4), light_to_world=np.eye(4),
                        bounds_min=np.zeros(3), bounds_max=np.ones(3), resolution=16, spp=4,
                        fov_deg=45, radiance=2, seed=0)
    invariant = assert_scene_pair_invariants(tmp_path / "A.xml", tmp_path / "B.xml")
    assert invariant["geometry"] == [str(obj.resolve())]
    assert invariant["normal"] == str(paths["normal"].resolve())
    assert invariant["sample_count"] == "4"


def test_glass_transmission_is_not_nested_under_twosided(tmp_path: Path) -> None:
    obj = tmp_path / "glass.obj"
    obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    rough = tmp_path / "rough.png"
    normal = tmp_path / "normal.png"
    _rgb(rough, np.full((2, 2, 3), 127, np.uint8))
    _rgb(normal, np.full((2, 2, 3), 127, np.uint8))
    material = {
        "base_color": rough, "roughness_raw": rough, "normal": normal,
        "optical_class": "glass", "obj_parts": [obj],
    }
    xml = tmp_path / "glass.xml"
    build_scene_xml(path=xml, branch="A", obj_path=obj, material=material,
                    camera_to_world=np.eye(4), light_to_world=np.eye(4),
                    bounds_min=np.zeros(3), bounds_max=np.ones(3), resolution=8,
                    spp=1, fov_deg=45, radiance=1, seed=0)
    shape = ET.parse(xml).getroot().find("./shape[@id='experiment_object']")
    assert shape is not None
    assert shape.find("./bsdf[@type='twosided']") is None
    normalmap = shape.find("./bsdf[@type='normalmap']")
    assert normalmap is not None
    assert normalmap.find("./bsdf[@type='roughdielectric']") is not None


def test_uv_resampling_rois_never_leak_outside_object() -> None:
    uv = np.asarray([[[0.1, 0.1], [0.9, 0.9]], [[0.2, 0.8], [0.8, 0.2]]], np.float32)
    mask = np.asarray([[True, False], [False, True]])
    atlas = np.asarray([[0.0, 1.0], [1.0, 0.0]], np.float32)
    sampled = resample_atlas_to_screen(uv, mask, atlas)
    assert np.all(sampled[~mask] == 0)
    maps = screen_space_maps(uv, mask, {"metallic": atlas, "alpha": atlas,
                                             "conductor_index": atlas.astype(np.uint8),
                                             "eta": np.repeat(atlas[..., None], 3, axis=2),
                                             "k": np.repeat(atlas[..., None], 3, axis=2)})
    assert not np.any(maps["metal_mask"] & ~mask)
    assert not np.any(maps["dielectric_mask"] & ~mask)


def test_rgb_roi_metrics_are_linear_and_masked() -> None:
    a = np.asarray([[[0.2, 0.4, 0.6], [9.0, 9.0, 9.0]]], np.float32)
    b = np.asarray([[[0.4, 0.4, 0.3], [1.0, 1.0, 1.0]]], np.float32)
    roi = np.asarray([[True, False]])
    metrics = rgb_roi_metrics(a, b, roi)
    assert metrics["pixels"] == 1
    assert np.isclose(metrics["linear_rgb_mae"], (0.2 + 0.0 + 0.3) / 3)
    assert metrics["coverage"] == 0.5


def test_fixed_config_contains_the_eight_planned_assets() -> None:
    config = json.loads((Path(__file__).resolve().parents[3] / "configs/experiments/spatial_pbr_ab_2026-07-13.json").read_text())
    assert len(config["assets"]) == 8
    assert {row["group"] for row in config["assets"]} == {"positive", "negative"}
    assert sum(row["group"] == "positive" for row in config["assets"]) == 4
    assert "NatureShelfTrinketsFactory_7695705_.spawn_asset_742423" in {row["id"] for row in config["assets"]}
    assert "PlantContainerFactory_8288363_.spawn_asset_1688329" in {row["id"] for row in config["assets"]}
    assert config["rgb_variant"] == "cuda_ad_spectral"
