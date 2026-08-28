from mitsuba_converter.render_daemon import _render_profile_identity
from mitsuba_converter.render_daemon import RenderDaemon


def _profile(*, polar_spp: int, policy: str):
    return _render_profile_identity(
        scene_variant_key="base",
        sensor_ids=["polar_cam"],
        camera_specs_payload=None,
        sensor_specs_payload=[{
            "sensor_id": "polar_cam",
            "sensor_type": "polar_camera",
            "modalities": ["polar_rgb_preview", "dop"],
            "render": {"polar_spp": polar_spp, "polar_visualization_policy": policy},
        }],
        modalities=["polar_rgb_preview", "dop"],
        render_settings={"path_spp": 4096},
        active_lights=[],
    )


def test_render_profile_is_stable_for_same_capture_contract():
    first, payload = _profile(polar_spp=768, policy="core_preview_v1")
    second, _ = _profile(polar_spp=768, policy="core_preview_v1")
    assert first == second
    assert payload["schema"] == "opticalnav.render_profile.v1"


def test_render_profile_changes_for_spp_or_visualization_policy():
    baseline, _ = _profile(polar_spp=768, policy="core_preview_v1")
    changed_spp, _ = _profile(polar_spp=1024, policy="core_preview_v1")
    changed_policy, _ = _profile(polar_spp=768, policy="full_v1")
    assert baseline != changed_spp
    assert baseline != changed_policy


def test_default_polar_rig_uses_768_core_preview_only_for_polar_sensor(tmp_path):
    rig = RenderDaemon(repo_root=tmp_path)._default_camera_rig()
    by_id = {sensor["sensor_id"]: sensor for sensor in rig["sensors"]}
    assert by_id["opticalnav_right_polar"]["render"]["polar_spp"] == 768
    assert by_id["opticalnav_right_polar"]["render"]["polar_visualization_policy"] == "core_preview_v1"
    assert by_id["opticalnav_left_nir"]["render"]["polar_spp"] == 256
