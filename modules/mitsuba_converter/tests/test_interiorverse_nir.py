from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2
import numpy as np
import pytest

from mitsuba_converter.interiorverse_nir import (
    FRAME_SCHEMA,
    FrameData,
    FramePaths,
    Light,
    atomic_write_exr,
    axial_depth_to_points,
    ccs_ldl_3bar_bank,
    ccs_ldl_3bar_direct,
    discover_frames,
    frame_is_complete,
    ggx_direct,
    load_frame,
    material_aware_passive_nir,
    render_ccs_active_nir_frame,
    output_paths,
    render_frame,
    screen_space_one_bounce_nir,
    passive_nir,
    TRANSPORT_MODEL_RGB_REUSED_V1,
    shadow_visibility,
    stable_random_light,
    write_frame,
)
from mitsuba_converter.nir_reflectance import pseudo_nir_albedo


def _light(position=(0.0, 0.0, 0.0)) -> Light:
    return Light(
        position=np.asarray(position, np.float32),
        direction=np.asarray([0.0, 0.0, -1.0], np.float32),
        beam_degrees=80.0,
        cutoff_degrees=89.0,
    )


def test_render_uses_existing_pseudo_nir_bitwise() -> None:
    rng = np.random.default_rng(4)
    h, w = 5, 7
    albedo = rng.random((h, w, 3), dtype=np.float32)
    data = FrameData(
        image_rgb=albedo.copy(),
        albedo_rgb=albedo,
        depth_mm=np.full((h, w), 2000.0, np.float32),
        normal=np.dstack((np.zeros((h, w)), np.zeros((h, w)), np.ones((h, w)))).astype(np.float32),
        roughness=np.full((h, w), 0.5, np.float32),
        metallic=np.zeros((h, w), np.float32),
        mask=np.ones((h, w), np.float32),
        valid=np.ones((h, w), bool),
    )
    outputs, _ = render_frame(data, seed=3, scene="scene", frame="000", shadow_map_size=16)
    assert np.array_equal(outputs["nir_albedo"], pseudo_nir_albedo(albedo))


def test_explicit_v1_transport_model_preserves_legacy_passive_output() -> None:
    h, w = 4, 5
    albedo = np.full((h, w, 3), [0.2, 0.4, 0.7], np.float32)
    data = FrameData(
        image_rgb=albedo * 0.6, albedo_rgb=albedo, depth_mm=np.full((h, w), 2000.0, np.float32),
        normal=np.dstack((np.zeros((h, w)), np.zeros((h, w)), np.ones((h, w)))).astype(np.float32),
        roughness=np.full((h, w), 0.5, np.float32), metallic=np.zeros((h, w), np.float32),
        mask=np.ones((h, w), np.float32), valid=np.ones((h, w), bool),
    )
    expected, _, _ = passive_nir(data.image_rgb, data.albedo_rgb, pseudo_nir_albedo(albedo), data.valid)
    outputs, metadata = render_frame(data, seed=5, scene="s", frame="f", shadow_map_size=16,
                                     transport_model=TRANSPORT_MODEL_RGB_REUSED_V1)
    np.testing.assert_array_equal(outputs["nir_passive"], expected)
    assert "nir_indirect_ss1" not in outputs
    assert metadata["transport_model"] == TRANSPORT_MODEL_RGB_REUSED_V1


def test_material_aware_passive_is_finite_and_does_not_divide_metallic_albedo() -> None:
    h = w = 12
    albedo = np.full((h, w, 3), 0.5, np.float32)
    image = albedo * 0.4
    metallic = np.zeros((h, w), np.float32)
    metallic[:, :3] = 1.0
    roughness = np.full((h, w), 0.7, np.float32)
    normal = np.zeros((h, w, 3), np.float32); normal[..., 2] = 1.0
    result, shading, confidence, metadata = material_aware_passive_nir(
        image, albedo, np.full((h, w), 0.7, np.float32), roughness, metallic,
        normal, np.full((h, w), 2000.0, np.float32), np.ones((h, w), bool),
    )
    assert np.isfinite(result).all() and np.isfinite(shading).all()
    assert np.all(result >= 0.0)
    assert confidence[:, :3].mean() < confidence[:, 3:].mean()
    assert metadata["diffuse_valid_fraction"] == pytest.approx(0.75)


def test_ccs_active_bundle_has_rgb_shading_and_nir_outputs() -> None:
    h = w = 8
    albedo = np.full((h, w, 3), [0.3, 0.5, 0.7], np.float32)
    normal = np.zeros_like(albedo); normal[..., 2] = 1.0
    data = FrameData(image_rgb=albedo * 0.4, albedo_rgb=albedo,
                     depth_mm=np.full((h, w), 1800.0, np.float32), normal=normal,
                     roughness=np.full((h, w), 0.7, np.float32), metallic=np.zeros((h, w), np.float32),
                     mask=np.ones((h, w), np.float32), valid=np.ones((h, w), bool))
    outputs, metadata = render_ccs_active_nir_frame(data, samples_per_bar=1, shadow_map_size=16)
    assert {"rgb_diffuse_shading", "rgb_diffuse_reconstruction", "nir_passive_diffuse",
            "nir_passive_confidence", "nir_active_direct_ccs_3bar", "nir_active_ccs_3bar"} <= set(outputs)
    assert outputs["rgb_diffuse_reconstruction"].shape == (h, w, 3)
    assert np.isfinite(np.concatenate([value.reshape(-1) for value in outputs.values()])).all()
    assert metadata["active_light"]["angular_model"] == "spot"


def test_ss1_is_deterministic_finite_and_metallic_receivers_do_not_reemit() -> None:
    h = w = 18
    depth = np.full((h, w), 2000.0, np.float32)
    # A farther, visible back patch supplies a deterministic screen-space hit.
    depth[:, w // 2:] = 3000.0
    points = axial_depth_to_points(depth)
    normal = np.zeros((h, w, 3), np.float32)
    normal[..., 2] = -1.0
    valid = np.ones((h, w), bool)
    passive = np.ones((h, w), np.float32)
    albedo = np.full((h, w), 0.7, np.float32)
    correction_a, confidence_a = screen_space_one_bounce_nir(
        points, normal, passive, albedo, np.zeros((h, w), np.float32), valid, seed=17,
    )
    correction_b, confidence_b = screen_space_one_bounce_nir(
        points, normal, passive, albedo, np.zeros((h, w), np.float32), valid, seed=17,
    )
    np.testing.assert_array_equal(correction_a, correction_b)
    np.testing.assert_array_equal(confidence_a, confidence_b)
    assert np.isfinite(correction_a).all() and np.isfinite(confidence_a).all()
    assert np.all((0.0 <= confidence_a) & (confidence_a <= 1.0))
    metallic, _ = screen_space_one_bounce_nir(
        points, normal, passive, albedo, np.ones((h, w), np.float32), valid, seed=17,
    )
    assert np.count_nonzero(metallic) == 0


def test_axial_depth_restores_opengl_camera_plane_at_85_degrees() -> None:
    points = axial_depth_to_points(np.full((4, 6), 2000.0, np.float32))
    assert np.array_equal(points[..., 2], np.full((4, 6), -2.0, np.float32))
    assert points[1, 0, 0] < 0.0 < points[1, -1, 0]
    assert points[0, 2, 1] > 0.0 > points[-1, 2, 1]
    dx = points[1, 1] - points[1, 0]
    dy = points[1, 0] - points[0, 0]
    recovered_normal = np.cross(dy, dx)
    recovered_normal /= np.linalg.norm(recovered_normal)
    assert np.allclose(recovered_normal, [0.0, 0.0, 1.0], atol=1e-6)


@pytest.mark.parametrize("roughness", [0.0, 1.0])
@pytest.mark.parametrize("metallic", [0.0, 1.0])
@pytest.mark.parametrize("albedo", [0.0, 0.7])
def test_ggx_extremes_are_finite_nonnegative(roughness: float, metallic: float, albedo: float) -> None:
    points = np.asarray([[[0.0, 0.0, -2.0]]], np.float32)
    result = ggx_direct(
        points,
        np.asarray([[[0.0, 0.0, 1.0]]], np.float32),
        np.asarray([[roughness]], np.float32),
        np.asarray([[metallic]], np.float32),
        np.asarray([[albedo]], np.float32),
        np.asarray([[True]]),
        _light(),
    )
    assert np.isfinite(result).all()
    assert (result >= 0.0).all()


def test_ggx_inverse_square_and_left_right_symmetry() -> None:
    common = dict(
        normal=np.asarray([[[0.0, 0.0, 1.0]]], np.float32),
        roughness=np.asarray([[1.0]], np.float32),
        metallic=np.asarray([[0.0]], np.float32),
        nir_albedo=np.asarray([[0.6]], np.float32),
        valid=np.asarray([[True]]),
        light=_light(),
    )
    near = ggx_direct(np.asarray([[[0.0, 0.0, -1.0]]], np.float32), **common)[0, 0]
    far = ggx_direct(np.asarray([[[0.0, 0.0, -2.0]]], np.float32), **common)[0, 0]
    assert near / far == pytest.approx(4.0, rel=1e-5)

    points = np.asarray([[[-0.2, 0.0, -2.0], [0.2, 0.0, -2.0]]], np.float32)
    symmetric = ggx_direct(
        points,
        np.asarray([[[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]]], np.float32),
        np.ones((1, 2), np.float32),
        np.zeros((1, 2), np.float32),
        np.full((1, 2), 0.6, np.float32),
        np.ones((1, 2), bool),
        _light(),
    )
    assert symmetric[0, 0] == pytest.approx(symmetric[0, 1], rel=1e-6)


def test_three_bar_bank_is_front_only_and_stronger_than_one_legacy_light() -> None:
    points = np.asarray([[[0.0, 0.0, -2.0]]], np.float32)
    normal = np.asarray([[[0.0, 0.0, 1.0]]], np.float32)
    common = dict(roughness=np.ones((1, 1), np.float32), metallic=np.zeros((1, 1), np.float32),
                  nir_albedo=np.full((1, 1), 0.6, np.float32), valid=np.ones((1, 1), bool))
    bank = ccs_ldl_3bar_bank(points[0, 0], samples_per_bar=1)
    active, metadata = ccs_ldl_3bar_direct(points, normal, bank=bank, shadow_map_size=16, **common)
    legacy = ggx_direct(points, normal, light=_light(), **common)
    assert len(bank.samples) == 3
    assert np.isfinite(active).all() and active[0, 0] > legacy[0, 0]
    assert metadata["radiant_flux_prior_total_w"] == pytest.approx(2.07)
    assert metadata["direct_denoise"] == "depth_aware_log_9x9"
    assert metadata["angular_model"] == "spot"


def test_shadow_map_foreground_point_reduces_back_point_visibility() -> None:
    points = np.asarray([[[0.0, 0.0, -1.0], [0.0, 0.0, -2.0]]], np.float32)
    visibility = shadow_visibility(points, np.ones((1, 2), bool), _light(), map_size=32)
    assert visibility[0, 0] == pytest.approx(1.0)
    assert visibility[0, 1] < visibility[0, 0]


def test_random_light_is_stable_and_area_uniform_annulus_bounded() -> None:
    target = np.asarray([0.0, 0.0, -2.0], np.float32)
    first = stable_random_light(20260825, "s", "001", target)
    second = stable_random_light(20260825, "s", "001", target)
    assert first.seed == second.seed
    assert np.array_equal(first.position, second.position)
    radii = []
    for index in range(1000):
        light = stable_random_light(20260825, "s", str(index), target)
        radii.append(float(np.linalg.norm(light.position[:2])))
    assert min(radii) >= 0.5 - 1e-6
    assert max(radii) <= 1.5 + 1e-6
    # Area-uniform annulus has E[r^2] = (r_min^2 + r_max^2) / 2 = 1.25.
    assert np.mean(np.square(radii)) == pytest.approx(1.25, abs=0.06)


def _write_rgb_exr(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), np.asarray(rgb[..., ::-1], np.float32))


def _fixture_frame(root: Path, scene: str = "scene", frame: str = "000") -> FramePaths:
    h, w = 8, 10
    rgb = np.zeros((h, w, 3), np.float32)
    rgb[..., 0] = 0.2
    rgb[..., 1] = 0.4
    rgb[..., 2] = 0.8
    normal = np.zeros_like(rgb)
    normal[..., 2] = 1.0
    material = np.zeros_like(rgb)
    material[..., 0] = 0.6
    material[..., 1] = 0.2
    scene_dir = root / scene
    for name, value in (("im", rgb * 0.7), ("albedo", rgb), ("normal", normal), ("material", material)):
        _write_rgb_exr(scene_dir / f"{frame}_{name}.exr", value)
    assert cv2.imwrite(str(scene_dir / f"{frame}_depth.exr"), np.full((h, w), 2000.0, np.float32))
    mask = np.ones((h, w), np.float32)
    mask[0, 0] = 0.0
    assert cv2.imwrite(str(scene_dir / f"{frame}_mask.exr"), mask)
    return discover_frames(root)[0]


def test_exr_channel_mask_atomic_completion_and_corruption_recovery(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    output = tmp_path / "nir"
    frame = _fixture_frame(source)
    data = load_frame(frame)
    assert np.allclose(data.albedo_rgb[1, 1], [0.2, 0.4, 0.8])
    assert not data.valid[0, 0]
    outputs, metadata = render_frame(data, seed=7, scene=frame.scene, frame=frame.frame, shadow_map_size=16)
    payload = write_frame(frame, output, outputs, metadata, source)
    assert payload["schema"] == FRAME_SCHEMA
    assert frame_is_complete(output, frame.scene, frame.frame)
    for name, path in output_paths(output, frame.scene, frame.frame).items():
        assert path.is_file(), name
    assert not list(output.rglob(".*.exr"))

    broken = output_paths(output, frame.scene, frame.frame)["nir_passive"]
    broken.write_bytes(b"not an exr")
    assert not frame_is_complete(output, frame.scene, frame.frame)
    atomic_write_exr(broken, outputs["nir_passive"])
    assert frame_is_complete(output, frame.scene, frame.frame)
    decoded = cv2.imread(str(broken), cv2.IMREAD_UNCHANGED)
    assert decoded.ndim == 2
    assert decoded.dtype == np.float32
    assert np.allclose(decoded, outputs["nir_passive"], atol=2e-3)

    meta = json.loads(output_paths(output, frame.scene, frame.frame)["metadata"].read_text())
    assert meta["complete"] is True
    assert meta["source"]["im"] == "scene/000_im.exr"
    assert np.all(outputs["nir_active_colocated"] >= outputs["nir_passive"])
    assert not np.array_equal(outputs["nir_active_colocated"], outputs["nir_active_random"])
