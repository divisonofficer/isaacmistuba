from pathlib import Path

import pytest

from mitsuba_converter.multimodal import (
    RenderConfig,
    _polar_variant,
    extract_stokes_channels,
    save_polarization_products,
    materialize_stokes_visualizations,
    stokes_rgb_component_preview,
)
from mitsuba_converter.observation_bridge import _camera_assist_light


def test_rgb_stokes_v2_forces_rgb_polarized_variant():
    assert _polar_variant("auto", color_mode="rgb_stokes_12") == "cuda_ad_rgb_polarized"
    assert RenderConfig().polar_color_mode == "rgb_stokes_12"
    with pytest.raises(ValueError, match="polar_color_mode"):
        RenderConfig(polar_color_mode="spectral")


def test_rgb_stokes_v2_extracts_twelve_scalar_channels():
    import numpy as np

    image = np.zeros((2, 3, 15), dtype=np.float64)
    image[:, :, 3:6] = 1.0
    rgb, s0, s1, s2, s3 = extract_stokes_channels(image)
    assert rgb.shape == s0.shape == s1.shape == s2.shape == s3.shape == (2, 3, 3)
    assert sum(value.shape[2] for value in (s0, s1, s2, s3)) == 12
    assert {value.dtype for value in (s0, s1, s2, s3)} == {np.dtype(np.float32)}


def test_active_polar_assist_is_scoped_to_polar_camera_in_a_mixed_rig():
    from robomituba_bridge import AssistLightSpec, CameraSpec, RenderRequest, SceneState

    request = RenderRequest(
        request_id="request", job_id="job", frame_id="frame", timestamp="2026-08-24T00:00:00Z",
        scene_state=SceneState("job", "scene", "frame", "2026-08-24T00:00:00Z", "snapshot", "scene.xml"),
        assist_light=AssistLightSpec(spectrum_mode="rgb_white"), extras={"polar_active": True},
    )
    polar = CameraSpec("polar", "polar", [1.0] * 16, 90.0, extras={"render_modalities": ["polar_rgb_preview"]})
    rgb = CameraSpec("rgb", "rgb", [1.0] * 16, 90.0, extras={"render_modalities": ["rgb"]})
    assert _camera_assist_light(request, polar, ["polar_rgb_preview"]) is request.assist_light
    assert _camera_assist_light(request, rgb, ["rgb"]) is None


def test_stokes_fixture_preserves_malus_sign_and_derived_dolp_aolp(tmp_path):
    import numpy as np

    # Fully linearly polarized 0° and 90° fixtures: S1 changes sign while
    # DoLP remains one and AoLP rotates by 90°.  This is the CPU counterpart
    # of the renderer-level Malus/Fresnel fixture gate.
    image = np.zeros((1, 2, 15), dtype=np.float32)
    image[:, :, :3] = 1.0
    image[:, :, 3:6] = 1.0  # S0 RGB
    image[0, 0, 6:9] = 1.0  # S1: horizontal
    image[0, 1, 6:9] = -1.0  # S1: vertical
    save_polarization_products(image, tmp_path, {"dop", "aolp"})
    with np.load(tmp_path / "stokes_data.npz") as data:
        assert np.allclose(data["dop"], 1.0)
        assert np.isclose(data["aolp"][0, 0], 0.0)
        assert np.isclose(data["aolp"][0, 1], np.pi / 2)
        assert np.all(data["s1"][0, 0] > 0)
        assert np.all(data["s1"][0, 1] < 0)
    # New renders have direct gallery assets for every component; the same
    # rendering is synthesized from legacy NPZs by the daemon when absent.
    for component in ("s0", "s1", "s2", "s3"):
        assert (tmp_path / f"{component}_rgb_preview.png").is_file()


def test_signed_stokes_rgb_preview_keeps_channel_signs_around_mid_grey():
    import numpy as np

    component = np.array([[[1.0, 0.0, -1.0]]], dtype=np.float32)
    preview, summary = stokes_rgb_component_preview(component, component_name="s1")
    assert summary["signed"] is True
    assert preview[0, 0, 0] > 0.5
    assert np.isclose(preview[0, 0, 1], 0.5)
    assert preview[0, 0, 2] < 0.5


def test_core_preview_policy_keeps_only_raw_stokes_and_one_preview(tmp_path):
    import numpy as np

    image = np.zeros((4, 5, 15), dtype=np.float32)
    image[:, :, :3] = 0.4
    image[:, :, 3:6] = 1.0
    image[:, :, 6:9] = 0.2
    summary, _ = save_polarization_products(
        image, tmp_path, {"polar_rgb_preview", "dop", "aolp", "s1"},
        visualization_policy="core_preview_v1",
    )
    assert set(summary["outputs"]) == {"stokes_npz", "rgb_preview"}
    assert (tmp_path / "stokes_data.npz").is_file()
    assert (tmp_path / "polar_rgb_preview.png").is_file()
    assert not (tmp_path / "dop_red_black_colorbar.png").exists()
    assert {"dop", "aolp", "s1"}.issubset(set(summary["derived_on_demand"]))


def test_raw_stokes_aolp_policy_keeps_twelve_channel_npz_with_rgb_and_aolp_png(tmp_path):
    import numpy as np

    image = np.zeros((4, 5, 15), dtype=np.float32)
    image[:, :, :3] = 0.4
    image[:, :, 3:6] = 1.0
    image[:, :, 6:9] = 0.2
    summary, _ = save_polarization_products(
        image,
        tmp_path,
        {"polar_rgb_preview", "dop", "aolp", "s1", "s2"},
        visualization_policy="raw_stokes_aolp_v1",
    )
    assert set(summary["outputs"]) == {"stokes_npz", "rgb_preview", "aolp"}
    assert (tmp_path / "polar_rgb_preview.png").is_file()
    assert {path.name for path in tmp_path.iterdir()} == {
        "stokes_data.npz",
        "polar_rgb_preview.png",
        "aolp_rainbow_colorbar.png",
    }
    with np.load(tmp_path / "stokes_data.npz") as data:
        assert all(data[key].shape == (4, 5, 3) for key in ("s0", "s1", "s2", "s3"))
    assert {"rgb_preview", "dop", "s1", "s2"}.issubset(set(summary["derived_on_demand"]))


def test_stokes_visualization_materialization_reuses_full_recipe(tmp_path):
    import numpy as np

    image = np.zeros((4, 5, 15), dtype=np.float32)
    image[:, :, :3] = 0.4
    image[:, :, 3:6] = 1.0
    image[:, :, 6:9] = 0.25
    full = tmp_path / "full"
    core = tmp_path / "core"
    full.mkdir()
    core.mkdir()
    save_polarization_products(image, full, {"dop"}, visualization_policy="full_v1")
    save_polarization_products(image, core, {"polar_rgb_preview", "dop"}, visualization_policy="core_preview_v1")
    regenerated = tmp_path / "regenerated"
    outputs = materialize_stokes_visualizations(core / "stokes_data.npz", regenerated, {"dop"})
    assert np.array_equal(
        np.frombuffer((full / "dop_red_black_colorbar.png").read_bytes(), dtype=np.uint8),
        np.frombuffer(Path(outputs["dop"]).read_bytes(), dtype=np.uint8),
    )
