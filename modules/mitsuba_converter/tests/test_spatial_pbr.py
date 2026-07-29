from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from mitsuba_converter.spatial_pbr import convert_spatial_pbr_textures


def _table() -> dict:
    eta = np.asarray([[0.2, 0.3, 1.2], [1.4, 0.9, 0.5]], dtype=np.float32)
    k = np.asarray([[3.0, 2.0, 1.0], [1.8, 2.2, 2.5]], dtype=np.float32)
    f0 = ((eta - 1.0) ** 2 + k**2) / ((eta + 1.0) ** 2 + k**2)
    return {
        "names": ["metal_a", "metal_b"],
        "wavelengths_nm": np.asarray([650.0, 550.0, 450.0], dtype=np.float32),
        "eta": eta,
        "k": k,
        "f0": f0,
    }


def _rgb(path: Path, values: np.ndarray) -> None:
    Image.fromarray(np.asarray(values, dtype=np.uint8), mode="RGB").save(path)


def test_packed_channels_apply_factors_and_square_roughness(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    packed = tmp_path / "mr.png"
    _rgb(base, np.full((2, 2, 3), 180, dtype=np.uint8))
    mr = np.zeros((2, 2, 3), dtype=np.uint8)
    mr[..., 1] = 128
    mr[..., 2] = 255
    _rgb(packed, mr)

    record = convert_spatial_pbr_textures(
        object_id="sample",
        output_dir=tmp_path / "out",
        base_color_path=base,
        roughness_path=packed,
        metallic_path=packed,
        roughness_channel=1,
        metallic_channel=2,
        roughness_factor=0.5,
        metallic_factor=0.0,
        conductor_table=_table(),
        write_exr=False,
    )

    maps = np.load(record["outputs"]["optical_maps_npz"])
    expected_roughness = (128.0 / 255.0) * 0.5
    assert np.allclose(maps["alpha"], expected_roughness**2)
    assert np.all(maps["metallic"] == 0.0)
    assert np.all(maps["conductor_index"] == 0)
    assert record["stats"]["conductor_fraction"] == 0.0


def test_continuous_metallic_weight_is_not_blurred_or_binarized(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    metal = tmp_path / "metal.png"
    _rgb(base, np.full((1, 3, 3), 200, dtype=np.uint8))
    values = np.asarray([0, 128, 255], dtype=np.uint8)
    _rgb(metal, np.repeat(values[None, :, None], 3, axis=2))

    record = convert_spatial_pbr_textures(
        object_id="sample",
        output_dir=tmp_path / "out",
        base_color_path=base,
        metallic_path=metal,
        conductor_table=_table(),
        conductor_threshold=0.5,
        write_exr=False,
    )

    maps = np.load(record["outputs"]["optical_maps_npz"])
    assert np.allclose(maps["metallic"], [[0.0, 128.0 / 255.0, 1.0]])
    assert np.array_equal(maps["conductor_index"] > 0, [[False, True, True]])
    weight = np.asarray(Image.open(record["outputs"]["bsdf_weight"]))
    assert np.array_equal(weight, values[None, :])
