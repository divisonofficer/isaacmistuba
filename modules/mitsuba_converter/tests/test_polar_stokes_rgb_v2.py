from pathlib import Path

import pytest

from mitsuba_converter.multimodal import (
    RenderConfig,
    _polar_variant,
    extract_stokes_channels,
    load_stokes_rgb_channels,
    save_polarization_products,
    stokes_rgb_tensor_for_polanalyser,
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


def test_active_k1_uses_the_resident_scene_with_camera_and_light_pose_updates(tmp_path, monkeypatch):
    """Fixed-SPP active K=1 must not drop its dynamic scene arguments."""
    import numpy as np
    from robomituba_bridge import AssistLightSpec
    import mitsuba_converter.mitsuba_runtime as runtime
    import mitsuba_converter.multimodal as multimodal

    source = tmp_path / "scene.xml"
    source.write_text("<scene version='3.0.0'/>", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(runtime, "resolve_variant", lambda *args, **kwargs: "cuda_ad_rgb_polarized")
    monkeypatch.setattr(multimodal, "_stage_base_stokes_scene", lambda *_args, **_kwargs: source)

    def fake_render_scene(_scene, **kwargs):
        captured.update(kwargs)
        image = np.zeros((2, 2, 15), dtype=np.float32)
        image[:, :, :6] = 1.0
        return image, {
            "variant": "cuda_ad_rgb_polarized",
            "load_scene_s": 0.0,
            "scene_cache_hit": True,
            "sensor_build_s": 0.0,
            "requested_spp": 4,
            "sensor_sampler_spp": 1,
            "render_s": 0.01,
            "total_s": 0.01,
            "resident_allocator_flush_s": 0.0,
        }

    monkeypatch.setattr(multimodal, "_render_scene", fake_render_scene)
    light = AssistLightSpec(
        mode="camera_aligned_rect", distance_m=0.12, size_world=[2.2, 1.6],
        spectrum_mode="rgb_white", polarized=True, polarizer_angle_deg=0.0,
    )
    result = multimodal.render_modalities(
        source,
        np.eye(4, dtype=np.float32),
        75.0,
        ["polar_rgb_preview"],
        out_dir=tmp_path / "out",
        config=RenderConfig(width=2, height=2, polar_spp=4),
        assist_light=light,
        variant="cuda_ad_rgb_polarized",
    )

    assert captured["scene_viewpoint"] is not None
    assert captured["dynamic_assist_light"] is light
    assert captured["resident_cache_limit"] == 1
    polar = result.pass_records["polarization"]
    assert polar["batch_size"] == 1
    assert polar["batch_mode"] == "active_stokes_heading_k1_resident_v1"
    assert polar["stokes_basis"] == "world_gravity_y_v1"
    assert polar["stokes_reference_axis"] == [0.0, 1.0, 0.0]


def test_resident_render_flushes_allocator_before_and_after_each_strip(tmp_path, monkeypatch):
    """K=4 keeps the scene resident, not transient Dr.Jit frame buffers."""
    import sys
    from types import SimpleNamespace
    import numpy as np
    import mitsuba_converter.multimodal as multimodal

    calls: list[str] = []

    class FakeMitsuba:
        @staticmethod
        def render(_scene, **_kwargs):
            calls.append("render")
            return np.ones((1, 1, 15), dtype=np.float32)

    fake_dr = SimpleNamespace(
        eval=lambda _image: calls.append("eval"),
        sync_thread=lambda: calls.append("sync"),
        flush_malloc_cache=lambda: calls.append("flush"),
    )
    monkeypatch.setitem(sys.modules, "drjit", fake_dr)
    monkeypatch.setattr(multimodal, "_import_mitsuba", lambda: FakeMitsuba())
    monkeypatch.setattr(
        multimodal, "_load_resident_scene", lambda *_args, **_kwargs: (object(), 0.0, True),
    )

    _image, timing = multimodal._render_scene(
        tmp_path / "stable_batch.xml", variant="cuda_ad_rgb_polarized", spp=4,
        resident_cache_limit=1,
    )

    # The pre-render sync/flush releases scratch left by a prior strip; the
    # post-render pair releases this strip's image tensor once NumPy owns it.
    assert calls == ["sync", "flush", "render", "eval", "sync", "sync", "flush"]
    assert timing["resident_allocator_prepare_s"] >= 0.0
    assert timing["resident_allocator_flush_s"] >= 0.0


def test_resident_scene_evicts_before_loading_a_different_batch_shape(tmp_path, monkeypatch):
    """A K=2 tail must not coexist with a new K=4 OptiX scene during load."""
    import sys
    from types import SimpleNamespace
    import mitsuba_converter.mitsuba_runtime as runtime
    import mitsuba_converter.multimodal as multimodal

    calls: list[str] = []
    old_key = ("old", 1, 1, "cuda_ad_rgb_polarized")
    new_key = ("new", 1, 1, "cuda_ad_rgb_polarized")
    old_scene = object()
    new_scene = object()

    class FakeMitsuba:
        @staticmethod
        def load_file(_path):
            # This assertion captures the OOM-prevention invariant: no stale
            # scene or ParamMap sidecar survives while the next XML is loaded.
            assert old_key not in multimodal._RESIDENT_SCENE_CACHE
            assert old_key not in multimodal._RESIDENT_BATCH_BINDINGS
            calls.append("load")
            return new_scene

    fake_dr = SimpleNamespace(
        sync_thread=lambda: calls.append("sync"),
        flush_malloc_cache=lambda: calls.append("flush"),
    )
    monkeypatch.setitem(sys.modules, "drjit", fake_dr)
    monkeypatch.setattr(runtime, "ensure_mitsuba_variant", lambda variant: variant)
    monkeypatch.setattr(multimodal, "_import_mitsuba", lambda: FakeMitsuba())
    monkeypatch.setattr(
        multimodal, "_resident_scene_cache_key",
        lambda path, *, variant: old_key if path.name == "old.xml" else new_key,
    )
    multimodal._clear_scene_caches()
    try:
        with multimodal._SCENE_CACHE_LOCK:
            multimodal._RESIDENT_SCENE_CACHE[old_key] = old_scene
            multimodal._RESIDENT_BATCH_BINDINGS[old_key] = (object(), ("sensor.slot_0.to_world",))
        scene, _load_s, hit = multimodal._load_resident_scene(
            tmp_path / "new.xml", variant="cuda_ad_rgb_polarized", cache_limit=1,
        )
        assert scene is new_scene
        assert hit is False
        assert calls == ["sync", "flush", "load"]
        with multimodal._SCENE_CACHE_LOCK:
            assert list(multimodal._RESIDENT_SCENE_CACHE) == [new_key]
            assert old_key not in multimodal._RESIDENT_BATCH_BINDINGS
    finally:
        multimodal._clear_scene_caches()


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
    arrays = load_stokes_rgb_channels(tmp_path / "stokes_data.npz")
    s0_l = np.tensordot(arrays["s0"], [0.2126, 0.7152, 0.0722], axes=([2], [0]))
    s1_l = np.tensordot(arrays["s1"], [0.2126, 0.7152, 0.0722], axes=([2], [0]))
    s2_l = np.tensordot(arrays["s2"], [0.2126, 0.7152, 0.0722], axes=([2], [0]))
    assert np.allclose(np.sqrt(s1_l * s1_l + s2_l * s2_l) / s0_l, 1.0)
    aolp = np.mod(0.5 * np.arctan2(s2_l, s1_l), np.pi)
    assert np.isclose(aolp[0, 0], 0.0)
    assert np.isclose(aolp[0, 1], np.pi / 2)
    assert np.all(arrays["s1"][0, 0] > 0)
    assert np.all(arrays["s1"][0, 1] < 0)
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
        assert set(data.files) == {"s0", "s1", "s2", "s3"}
        assert all(data[key].shape == (4, 5, 3) and data[key].dtype == np.float16 for key in ("s0", "s1", "s2", "s3"))
    tensor = stokes_rgb_tensor_for_polanalyser(tmp_path / "stokes_data.npz")
    assert tensor.shape == (4, 5, 3, 4)
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
