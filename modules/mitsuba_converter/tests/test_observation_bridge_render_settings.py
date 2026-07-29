from robomituba_bridge import CameraSpec

from mitsuba_converter.observation_bridge import _camera_render_settings_payload, render_config_from_payload


def _camera(*, sensor_modality="rgb", extras=None):
    return CameraSpec(
        camera_id="cam",
        name="Camera",
        camera_to_world=[
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ],
        fov_deg=70.0,
        sensor_modality=sensor_modality,
        extras=dict(extras or {}),
    )


def test_polar_camera_does_not_inject_sensor_specific_material_settings():
    payload = _camera_render_settings_payload({}, _camera(sensor_modality="polarization"))

    assert payload == {}


def test_polar_camera_preserves_shared_analytic_only_scope():
    payload = _camera_render_settings_payload({"measured_scope": "analytic_only"}, _camera(extras={"sensor_type": "polar_camera"}))

    assert payload["measured_scope"] == "analytic_only"


def test_polar_camera_preserves_explicit_shared_measured_scope():
    payload = _camera_render_settings_payload(
        {"measured_scope": "measured_full", "max_measured_bsdfs": 9},
        _camera(extras={"render_modalities": ("dop",)}),
    )

    assert payload["measured_scope"] == "measured_full"
    assert payload["max_measured_bsdfs"] == 9


def test_rgb_camera_preserves_shared_material_settings():
    payload = _camera_render_settings_payload({"measured_scope": "analytic_only"}, _camera(sensor_modality="rgb"))

    assert payload == {"measured_scope": "analytic_only"}


def test_camera_render_overrides_are_applied_without_polar_defaults():
    payload = _camera_render_settings_payload(
        {"path_spp": 64},
        _camera(
            sensor_modality="polarization",
            extras={"render": {"polar_spp": 32, "measured_scope": "budgeted_measured"}},
        ),
    )

    assert payload["path_spp"] == 64
    assert payload["polar_spp"] == 32
    assert payload["measured_scope"] == "budgeted_measured"


def test_request_level_polar_modalities_do_not_change_material_settings():
    payload = _camera_render_settings_payload(
        {},
        _camera(sensor_modality="rgb"),
        ["polar_rgb_preview", "dop"],
    )

    assert payload == {}


def test_legacy_fallback_setting_is_ignored_when_loading_saved_requests():
    config = render_config_from_payload({"polar_fallback_mode": "invalid_only", "measured_scope": "analytic_only"})

    assert config.measured_scope == "analytic_only"
    assert not hasattr(config, "polar_fallback_mode")
