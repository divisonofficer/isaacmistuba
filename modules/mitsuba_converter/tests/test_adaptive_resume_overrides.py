from __future__ import annotations

from mitsuba_converter.render_daemon import (
    _apply_resume_render_settings_overrides,
    _resume_render_settings_overrides,
)


def test_adaptive_resume_overrides_patch_camera_precedence() -> None:
    overrides = _resume_render_settings_overrides({
        "render_settings_overrides": {
            "polar_spp": 1024,
            "polar_adaptive_spp_min": 256,
            "polar_adaptive_spp_max": 1024,
            "polar_adaptive_noise_threshold": 0.035,
        }
    })
    payload = {
        "render_settings": {"polar_spp": 800},
        "camera_specs": [{
            "camera_id": "polar_cam",
            "sensor_modality": "polarization",
            "extras": {
                "canonical_sensor_type": "polar_camera",
                "render": {"polar_spp": 800},
            },
        }],
    }
    result = _apply_resume_render_settings_overrides(payload, overrides)
    assert result["render_settings"]["polar_spp"] == 1024
    assert result["camera_specs"][0]["extras"]["render"]["polar_adaptive_spp_min"] == 256
    assert payload["camera_specs"][0]["extras"]["render"]["polar_spp"] == 800


def test_adaptive_resume_requires_complete_pair() -> None:
    try:
        _resume_render_settings_overrides({
            "render_settings_overrides": {"polar_adaptive_spp_min": 256}
        })
    except ValueError as exc:
        assert "supplied together" in str(exc)
    else:
        raise AssertionError("partial adaptive override must be rejected")
