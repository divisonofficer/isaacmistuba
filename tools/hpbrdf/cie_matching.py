"""CIE 1931 2° standard observer + sRGB conversion helpers.

Used by the channel-split renderer to fold a stack of monochromatic
spectral renders down into a viewable sRGB image. Two flavours:

    cie_xyz_weights(wavelengths)        -> (N, 3) X/Y/Z weights
    xyz_to_srgb_linear(xyz)             -> linear sRGB
    srgb_linear_to_gamma(rgb)           -> gamma-encoded sRGB (display-ready)
    spectrum_to_srgb(spectrum, wls)     -> convenience: spectrum (..., N)
                                           + N wavelengths → (..., 3) sRGB

Pure-numpy. Tabulated CIE 1931 2° colour-matching functions at 5 nm
steps from 380 to 780 nm (the standard published range — values outside
this are clipped to zero so NIR channels in the hpBRDF dataset
contribute nothing to perceived colour).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import numpy as np


# CIE 1931 2° colour-matching functions, 5 nm intervals 380…780 nm.
# Source: CIE Publication 15:2004, Table 1. Each row is (λ_nm, x̄, ȳ, z̄).
# Verified against https://cvrl.ucl.ac.uk/cmfs.htm (CIE 1931 2-deg).
_CIE_1931_2DEG: Final[np.ndarray] = np.array([
    (380, 0.001368, 0.000039, 0.006450),
    (385, 0.002236, 0.000064, 0.010550),
    (390, 0.004243, 0.000120, 0.020050),
    (395, 0.007650, 0.000217, 0.036210),
    (400, 0.014310, 0.000396, 0.067850),
    (405, 0.023190, 0.000640, 0.110200),
    (410, 0.043510, 0.001210, 0.207400),
    (415, 0.077630, 0.002180, 0.371300),
    (420, 0.134380, 0.004000, 0.645600),
    (425, 0.214770, 0.007300, 1.039050),
    (430, 0.283900, 0.011600, 1.385600),
    (435, 0.328500, 0.016840, 1.622960),
    (440, 0.348280, 0.023000, 1.747060),
    (445, 0.348060, 0.029800, 1.782600),
    (450, 0.336200, 0.038000, 1.772110),
    (455, 0.318700, 0.048000, 1.744100),
    (460, 0.290800, 0.060000, 1.669200),
    (465, 0.251100, 0.073900, 1.528100),
    (470, 0.195360, 0.090980, 1.287640),
    (475, 0.142100, 0.112600, 1.041900),
    (480, 0.095640, 0.139020, 0.812950),
    (485, 0.057950, 0.169300, 0.616200),
    (490, 0.032010, 0.208020, 0.465180),
    (495, 0.014700, 0.258600, 0.353300),
    (500, 0.004900, 0.323000, 0.272000),
    (505, 0.002400, 0.407300, 0.212300),
    (510, 0.009300, 0.503000, 0.158200),
    (515, 0.029100, 0.608200, 0.111700),
    (520, 0.063270, 0.710000, 0.078250),
    (525, 0.109600, 0.793200, 0.057250),
    (530, 0.165500, 0.862000, 0.042160),
    (535, 0.225750, 0.914850, 0.029840),
    (540, 0.290400, 0.954000, 0.020300),
    (545, 0.359700, 0.980300, 0.013400),
    (550, 0.433450, 0.994950, 0.008750),
    (555, 0.512050, 1.000000, 0.005750),
    (560, 0.594500, 0.995000, 0.003900),
    (565, 0.678400, 0.978600, 0.002750),
    (570, 0.762100, 0.952000, 0.002100),
    (575, 0.842500, 0.915400, 0.001800),
    (580, 0.916300, 0.870000, 0.001650),
    (585, 0.978600, 0.816300, 0.001400),
    (590, 1.026300, 0.757000, 0.001100),
    (595, 1.056700, 0.694900, 0.001000),
    (600, 1.062200, 0.631000, 0.000800),
    (605, 1.045600, 0.566800, 0.000600),
    (610, 1.002600, 0.503000, 0.000340),
    (615, 0.938400, 0.441200, 0.000240),
    (620, 0.854450, 0.381000, 0.000190),
    (625, 0.751400, 0.321000, 0.000100),
    (630, 0.642400, 0.265000, 0.000050),
    (635, 0.541900, 0.217000, 0.000030),
    (640, 0.447900, 0.175000, 0.000020),
    (645, 0.360800, 0.138200, 0.000010),
    (650, 0.283500, 0.107000, 0.000000),
    (655, 0.218700, 0.081600, 0.000000),
    (660, 0.164900, 0.061000, 0.000000),
    (665, 0.121200, 0.044580, 0.000000),
    (670, 0.087400, 0.032000, 0.000000),
    (675, 0.063600, 0.023200, 0.000000),
    (680, 0.046770, 0.017000, 0.000000),
    (685, 0.032900, 0.011920, 0.000000),
    (690, 0.022700, 0.008210, 0.000000),
    (695, 0.015840, 0.005723, 0.000000),
    (700, 0.011359, 0.004102, 0.000000),
    (705, 0.008111, 0.002929, 0.000000),
    (710, 0.005790, 0.002091, 0.000000),
    (715, 0.004109, 0.001484, 0.000000),
    (720, 0.002899, 0.001047, 0.000000),
    (725, 0.002049, 0.000740, 0.000000),
    (730, 0.001440, 0.000520, 0.000000),
    (735, 0.001000, 0.000361, 0.000000),
    (740, 0.000690, 0.000249, 0.000000),
    (745, 0.000476, 0.000172, 0.000000),
    (750, 0.000332, 0.000120, 0.000000),
    (755, 0.000235, 0.000085, 0.000000),
    (760, 0.000166, 0.000060, 0.000000),
    (765, 0.000117, 0.000042, 0.000000),
    (770, 0.000083, 0.000030, 0.000000),
    (775, 0.000059, 0.000021, 0.000000),
    (780, 0.000042, 0.000015, 0.000000),
], dtype=np.float64)

_CMF_LAMBDAS: Final[np.ndarray] = _CIE_1931_2DEG[:, 0]
_CMF_VALUES: Final[np.ndarray] = _CIE_1931_2DEG[:, 1:]  # (N, 3) X/Y/Z


def cie_xyz_weights(wavelengths_nm: Sequence[float]) -> np.ndarray:
    """Linearly-interpolated CIE 1931 2° X/Y/Z weights for arbitrary λ.

    Wavelengths outside the published 380–780 nm range come back as zero
    — that's the right thing for our NIR channels (≥ 830 nm), which
    carry no perceived colour.

    Returns
        np.ndarray of shape ``(N, 3)`` with rows X, Y, Z.
    """
    wls = np.asarray(wavelengths_nm, dtype=np.float64)
    out = np.zeros((wls.size, 3), dtype=np.float64)
    in_range = (wls >= _CMF_LAMBDAS[0]) & (wls <= _CMF_LAMBDAS[-1])
    if np.any(in_range):
        for k in range(3):
            out[in_range, k] = np.interp(wls[in_range], _CMF_LAMBDAS, _CMF_VALUES[:, k])
    return out


# Linear sRGB primaries (Rec. 709) → CIE XYZ (D65 white). The inverse
# below converts XYZ back into linear sRGB. Standard reference: IEC 61966.
_XYZ_TO_SRGB_LINEAR: Final[np.ndarray] = np.array([
    [ 3.2404542, -1.5371385, -0.4985314],
    [-0.9692660,  1.8760108,  0.0415560],
    [ 0.0556434, -0.2040259,  1.0572252],
], dtype=np.float64)


def xyz_to_srgb_linear(xyz: np.ndarray) -> np.ndarray:
    """Convert CIE XYZ to linear sRGB. Output is unclamped — caller
    decides whether to clip negative values (out-of-gamut) or to gamut-map.
    Last axis must be size 3."""
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.shape[-1] != 3:
        raise ValueError(f"xyz: last axis must be 3, got {xyz.shape}")
    return xyz @ _XYZ_TO_SRGB_LINEAR.T


def srgb_linear_to_gamma(linear_rgb: np.ndarray) -> np.ndarray:
    """Apply the sRGB transfer function (gamma encoding). Input clipped
    to [0, ∞), output clipped to [0, 1]. Standard piecewise function with
    a linear segment for very small values."""
    rgb = np.maximum(np.asarray(linear_rgb, dtype=np.float64), 0.0)
    threshold = 0.0031308
    low = 12.92 * rgb
    high = 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055
    out = np.where(rgb <= threshold, low, high)
    return np.clip(out, 0.0, 1.0)


def spectrum_to_srgb(spectrum: np.ndarray, wavelengths_nm: Sequence[float]) -> np.ndarray:
    """Combine: spectral radiance → CIE XYZ → linear sRGB → gamma sRGB.

    Args
        spectrum: array shape ``(..., N)`` with the spectrum at each
            wavelength along the last axis. Typical usage: an image
            stacked as ``(H, W, N)`` of monochromatic intensities from
            channel-split renders.
        wavelengths_nm: length-N sequence of band centres.

    Returns
        ``(..., 3)`` gamma-encoded sRGB in [0, 1].

    Note
        The integral is approximated as a *sum* — i.e. each channel
        carries weight 1, no Δλ rescaling. For 4-channel RGB+NIR mode
        this matches the user's "직접 채널 매핑" intent. For dense
        spectral sampling (≥ 16 channels) you may want to multiply the
        weights by the channel spacing in nm before summing for more
        accurate luminance.
    """
    spectrum = np.asarray(spectrum, dtype=np.float64)
    weights = cie_xyz_weights(wavelengths_nm)  # (N, 3)
    if spectrum.shape[-1] != weights.shape[0]:
        raise ValueError(
            f"channel mismatch: spectrum has {spectrum.shape[-1]} channels "
            f"but {weights.shape[0]} wavelengths were given"
        )
    xyz = spectrum @ weights  # (..., 3)
    linear = xyz_to_srgb_linear(xyz)
    return srgb_linear_to_gamma(linear)


def stack_rgbnir_to_image(
    channels: dict[int, np.ndarray],
    band_assignment: dict[str, int] | None = None,
) -> np.ndarray:
    """Direct band → channel mapping (no CIE weighting), used for the
    fast 4-band default tier.

    Args
        channels: ``{wavelength_nm: (H, W) intensity}`` for at least the
            wavelengths referenced in ``band_assignment``.
        band_assignment: ``{"R": λ_red, "G": λ_green, "B": λ_blue,
            "NIR": λ_nir}``. Defaults to the project canon
            (R=614, G=542, B=446, NIR=854).

    Returns
        ``(H, W, 4)`` float64 in linear-light units; channels ordered
        ``[R, G, B, NIR]``. The renderer does its own tone-mapping after
        this — we deliberately don't gamma-encode here so downstream
        Reinhard / etc. can operate on linear values.
    """
    if band_assignment is None:
        band_assignment = {"R": 614, "G": 542, "B": 446, "NIR": 854}
    out_planes: list[np.ndarray] = []
    for key in ("R", "G", "B", "NIR"):
        wl = band_assignment[key]
        if wl not in channels:
            raise KeyError(f"missing channel for {key}={wl} nm")
        plane = np.asarray(channels[wl], dtype=np.float64)
        if plane.ndim != 2:
            raise ValueError(f"channel {wl} nm must be 2-D, got shape {plane.shape}")
        out_planes.append(plane)
    return np.stack(out_planes, axis=-1)  # (H, W, 4)
