from __future__ import annotations

import numpy as np

from mitsuba_converter.multimodal import (
    _reject_firefly_outliers,
    _sanitize_radiance,
    _tonemap_reinhard,
    compute_global_tone_params,
    luminance,
    read_exr_rgb,
    save_rgb_radiance_preview,
)


def test_sanitize_inpaints_nan_and_clamps() -> None:
    img = np.full((8, 8, 3), 0.5, dtype=np.float32)
    img[3, 3, :] = np.nan
    img[5, 5, 0] = np.inf
    img[1, 1, :] = -2.0  # negative radiance
    img[6, 6, :] = 1e6  # firefly above the cap
    out = _sanitize_radiance(img, max_value=1e4)
    assert np.isfinite(out).all()
    assert out.min() >= 0.0
    assert out.max() <= 1e4
    # the NaN pixel is inpainted from its 0.5 neighbours, not left at 0/black
    assert out[3, 3, 0] > 0.3


def test_sanitize_noop_when_finite() -> None:
    img = np.abs(np.random.default_rng(3).standard_normal((4, 4, 3))).astype(np.float32)
    out = _sanitize_radiance(img)
    assert np.allclose(out, np.clip(img, 0.0, 1e4))


def test_firefly_clamp_removes_isolated_speck() -> None:
    img = np.full((9, 9, 3), 0.5, dtype=np.float32)
    img[4, 4, :] = 200.0  # lone firefly, ~400x the local median
    out = _reject_firefly_outliers(img, factor=10.0)
    # speck pulled down toward ~median*factor (= 0.5*10 = 5), far below 200
    assert out[4, 4, 0] < 10.0
    # neighbours untouched
    assert np.allclose(out[0, 0], 0.5, atol=1e-3)


def test_firefly_clamp_preserves_large_bright_region() -> None:
    # A genuine light source spans many pixels → its neighbourhood median is
    # also high → it must NOT be clamped.
    img = np.full((16, 16, 3), 0.3, dtype=np.float32)
    img[4:12, 4:12, :] = 150.0  # 8x8 bright panel
    out = _reject_firefly_outliers(img, factor=10.0)
    assert np.allclose(out[7, 7], 150.0, rtol=1e-3)  # interior preserved


def test_firefly_clamp_noop_on_smooth() -> None:
    rng = np.random.default_rng(7)
    img = 0.5 + 0.02 * rng.standard_normal((12, 12, 3)).astype(np.float32)
    img = np.clip(img, 0.0, None)
    out = _reject_firefly_outliers(img, factor=10.0)
    assert np.allclose(out, img, atol=1e-3)  # no outliers → unchanged


def test_tonemap_handles_nan_without_black_holes() -> None:
    img = np.full((6, 6, 3), 0.4, dtype=np.float32)
    img[2, 2, :] = np.nan
    out = _tonemap_reinhard(img, exposure=2.0, white=10.0)
    assert np.isfinite(out).all()
    assert out[2, 2, 0] > 0.2  # inpainted, not a black square


def test_reinhard_monotonic_and_bounded() -> None:
    arr = np.array([[[0.0, 0.5, 2.0]]], dtype=np.float32).repeat(4, axis=0).repeat(4, axis=1)
    out = _tonemap_reinhard(arr, exposure=1.0, white=10.0)
    assert out.shape == arr.shape
    assert out.dtype == np.float32
    assert np.all(out >= 0.0) and np.all(out <= 1.0)
    # brighter linear input → brighter (or equal) sRGB output, per channel
    ramp = np.linspace(0.0, 50.0, 64, dtype=np.float32)[None, :, None].repeat(3, axis=2)
    enc = _tonemap_reinhard(ramp, exposure=1.0, white=20.0)[0, :, 0]
    assert np.all(np.diff(enc) >= -1e-6)


def test_reinhard_highlight_rolloff_recovers_midtones() -> None:
    # A scene with a tiny very-bright emitter pixel and a dim background. The old
    # percentile-divide would latch onto the emitter and crush the background to
    # ~0; extended Reinhard keeps the midtone visible.
    img = np.full((8, 8, 3), 0.4, dtype=np.float32)
    img[0, 0, :] = 500.0  # emitter
    out = _tonemap_reinhard(img, exposure=1.0, white=10.0)
    assert out[4, 4, 0] > 0.3  # background is still well exposed
    assert out[0, 0, 0] > 0.95  # emitter rolls off toward white, not clipped to nonsense


def test_compute_global_tone_params_basic() -> None:
    rng = np.random.default_rng(0)
    lum = rng.gamma(shape=2.0, scale=0.3, size=20000).astype(np.float32)
    tone = compute_global_tone_params([lum], exposure_percentile=0.90, white_percentile=0.999)
    assert tone["tone_exposure"] > 0.0
    assert tone["tone_white"] >= 1.0


def test_compute_global_tone_params_empty() -> None:
    tone = compute_global_tone_params([np.zeros(0, dtype=np.float32)])
    assert tone["tone_exposure"] == 1.0


def test_luminance_weights() -> None:
    white = np.ones((2, 2, 3), dtype=np.float32)
    assert np.allclose(luminance(white), 1.0)


def test_read_exr_roundtrip(tmp_path) -> None:
    try:
        import mitsuba  # noqa: F401
    except Exception:
        import pytest

        pytest.skip("mitsuba runtime not available for EXR write")
    import mitsuba as mi

    mi.set_variant(next(iter(mi.variants())))
    arr = np.abs(np.random.default_rng(1).standard_normal((6, 8, 3))).astype(np.float32)
    path = tmp_path / "x.exr"
    mi.util.write_bitmap(str(path), arr)
    back = read_exr_rgb(path)
    assert back.shape == arr.shape
    assert np.allclose(back, arr, atol=1e-3)


def test_save_rgb_radiance_preview_writes_png(tmp_path) -> None:
    img = np.abs(np.random.default_rng(2).standard_normal((4, 5, 3))).astype(np.float32)
    png = tmp_path / "p.png"
    summary = save_rgb_radiance_preview(img, png, exposure=1.5, white=8.0)
    assert png.is_file()
    assert summary["tone_operator"] == "reinhard_ext"
    assert summary["tone_exposure"] == 1.5
