from __future__ import annotations

from mitsuba_converter.multimodal import RenderConfig, _polar_quality_summary


def _summary(*, s1: float = 1e-6, s2: float = 1e-6, finite_ratio: float = 1.0, invalid_pixels: int = 0) -> dict:
    return {
        "s1_scale_abs_p995": s1,
        "s2_scale_abs_p995": s2,
        "finite_ratio": finite_ratio,
        "invalid_pixel_count": invalid_pixels,
    }


def test_weak_valid_polarization_is_reported_without_material_substitution() -> None:
    cfg = RenderConfig(polar_scale_threshold=1e-4)

    decision = _polar_quality_summary(_summary(s1=1e-6, s2=1e-6), cfg)

    assert decision["weak_scales"] is True
    assert decision["invalid_polar"] is False

def test_excess_invalid_pixels_are_reported_as_invalid() -> None:
    cfg = RenderConfig(polar_scale_threshold=1e-4, polar_max_invalid_pixels=2000)

    quality = _polar_quality_summary(_summary(s1=1e-3, s2=1e-3, invalid_pixels=2001), cfg)

    assert quality["weak_scales"] is False
    assert quality["invalid_polar"] is True


def test_low_finite_ratio_is_reported_as_invalid() -> None:
    cfg = RenderConfig(polar_scale_threshold=1e-4)

    decision = _polar_quality_summary(_summary(s1=1e-3, s2=1e-3, finite_ratio=0.5), cfg)

    assert decision["weak_scales"] is False
    assert decision["invalid_polar"] is True


def test_mostly_finite_polarization_is_accepted() -> None:
    cfg = RenderConfig(polar_scale_threshold=1e-4)

    decision = _polar_quality_summary(_summary(s1=1e-3, s2=1e-3, finite_ratio=0.9948), cfg)

    assert decision["min_finite_ratio"] == 0.99
    assert decision["invalid_polar"] is False
