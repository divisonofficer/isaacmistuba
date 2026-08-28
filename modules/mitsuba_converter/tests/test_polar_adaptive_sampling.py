from __future__ import annotations

import numpy as np

from mitsuba_converter.multimodal import _polar_adaptive_noise_score


def _stokes(value: float) -> np.ndarray:
    # rgb_stokes_12 carrier: use an illuminated S0 and quiet S1/S2/S3.
    image = np.zeros((12, 10, 12), dtype=np.float32)
    image[..., :3] = value
    return image


def test_polar_adaptive_noise_score_is_low_for_matching_stokes() -> None:
    image = _stokes(1.0)
    assert _polar_adaptive_noise_score(image, image.copy()) == 0.0


def test_polar_adaptive_noise_score_tracks_stokes_disagreement() -> None:
    reference = _stokes(1.0)
    small_delta = reference.copy()
    small_delta[..., 3:6] += 0.01
    large_delta = reference.copy()
    large_delta[..., 3:6] += 0.10

    assert _polar_adaptive_noise_score(reference, small_delta) < _polar_adaptive_noise_score(reference, large_delta)


def test_polar_adaptive_noise_ignores_unlit_background() -> None:
    reference = _stokes(1.0)
    estimate = reference.copy()
    # A handful of effectively black pixels must not demand the full budget.
    reference[:2, :2] = 0.0
    estimate[:2, :2, 3:6] = 1000.0
    assert _polar_adaptive_noise_score(reference, estimate) == 0.0
