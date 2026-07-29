"""Optional mitransient integration boundary.

The production renderer keeps transient rendering optional because the custom
OptiX7 build may not contain the plugin variant required by mitransient.  This
module provides a small, explicit capability check and a deterministic
transient-histogram-to-ToF conversion utility.  Callers must opt in; no
geometric depth fallback is performed silently.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def availability() -> dict[str, Any]:
    try:
        import mitransient as mitr  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"available": True, "version": getattr(mitr, "__version__", "unknown")}


def require_available() -> Any:
    try:
        import mitransient as mitr  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "depth_transient requires the optional 'mitransient' package and a compatible Mitsuba variant; "
            "install/compile it explicitly instead of falling back to geometric depth."
        ) from exc
    return mitr


def tof_depth_from_histogram(
    histogram: np.ndarray,
    *,
    bin_width_s: float,
    c_m_per_s: float = 299_792_458.0,
    threshold: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract first-return ToF depth and confidence from a time histogram."""
    values = np.asarray(histogram, dtype=np.float32)
    if values.ndim < 1:
        raise ValueError("histogram must have a time-bin dimension")
    if bin_width_s <= 0:
        raise ValueError("bin_width_s must be positive")
    peak = np.argmax(values, axis=-1)
    amplitude = np.take_along_axis(values, peak[..., None], axis=-1)[..., 0]
    valid = np.isfinite(amplitude) & (amplitude > float(threshold))
    depth = peak.astype(np.float32) * float(bin_width_s) * float(c_m_per_s) * 0.5
    depth[~valid] = np.nan
    confidence = np.zeros(depth.shape, dtype=np.float32)
    finite = np.isfinite(values)
    max_value = np.max(np.where(finite, values, 0.0), axis=-1)
    confidence[valid] = np.clip(amplitude[valid] / np.maximum(max_value[valid], 1e-6), 0.0, 1.0)
    return depth, confidence, valid
