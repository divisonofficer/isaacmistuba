"""Ouster lidar metadata and range-image helpers.

The bridge deliberately keeps this module dependency free.  Ouster metadata is
JSON, so the parser accepts either a mapping or a path and normalises the small
set of fields needed by the renderer.  Rendering code can then use the same
profile for synthetic defaults and real sensor metadata without importing the
Ouster SDK.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional


def _matrix16(value: Any, *, default: list[float]) -> list[float]:
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple)):
        flat: list[float] = []
        for item in value:
            if isinstance(item, (list, tuple)):
                flat.extend(float(v) for v in item)
            else:
                flat.append(float(item))
        if len(flat) == 16:
            return flat
    raise ValueError("Ouster transform must contain 16 numeric values")


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _beam_array(mapping: Mapping[str, Any], name: str) -> list[float] | None:
    value = _first(mapping, name)
    if value is None and isinstance(mapping.get("beam_intrinsics"), Mapping):
        value = mapping["beam_intrinsics"].get(name)
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"Ouster {name} must be a non-empty array")
    return [float(item) for item in value]


def _parse_lidar_mode(value: Any) -> tuple[int | None, float | None]:
    if not isinstance(value, str):
        return None, None
    match = re.match(r"^(\d+)x([0-9]+(?:\.[0-9]+)?)$", value.strip())
    if not match:
        return None, None
    return int(match.group(1)), float(match.group(2))


@dataclass(frozen=True)
class OusterLidarMetadata:
    """Normalised metadata used by the Ouster forward sensor model."""

    product_line: str = "OS1"
    model: str = "OS1-128"
    serial: Optional[str] = None
    firmware: Optional[str] = None
    lidar_mode: str = "1024x10"
    columns: int = 1024
    scan_rate_hz: float = 10.0
    n_rings: int = 128
    beam_altitude_angles_deg: list[float] = field(default_factory=list)
    beam_azimuth_angles_deg: list[float] = field(default_factory=list)
    pixel_shift_by_row: list[int] = field(default_factory=list)
    beam_to_lidar_transform: list[float] = field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    lidar_to_sensor_transform: list[float] = field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    azimuth_window_deg: list[float] = field(default_factory=lambda: [-180.0, 180.0])
    min_range_m: float = 0.3
    max_range_m: float = 90.0
    wavelength_nm: float = 865.0
    beam_divergence_deg: float = 0.09
    return_mode: str = "single"
    metadata_source: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_os1_128_metadata() -> OusterLidarMetadata:
    # This is a synthetic calibration fallback, not a claim that all OS1
    # revisions share exactly these angles.  Real metadata should override it.
    angles = [(-22.5 + 45.0 * i / 127.0) for i in range(128)]
    return OusterLidarMetadata(
        beam_altitude_angles_deg=angles,
        beam_azimuth_angles_deg=[0.0] * 128,
        pixel_shift_by_row=[0] * 128,
    )


def ouster_metadata_from_mapping(payload: Mapping[str, Any], *, source: str | None = None) -> OusterLidarMetadata:
    columns, scan_rate = _parse_lidar_mode(payload.get("lidar_mode"))
    columns = int(_first(payload, "columns", "columns_per_frame") or columns or 1024)
    scan_rate = float(_first(payload, "scan_rate_hz", "frequency") or scan_rate or 10.0)
    altitude = _beam_array(payload, "beam_altitude_angles")
    azimuth = _beam_array(payload, "beam_azimuth_angles")
    n_rings = int(_first(payload, "n_rings", "channels", "pixels_per_column") or len(altitude or azimuth or []) or 128)
    if not altitude:
        base_altitude = default_os1_128_metadata().beam_altitude_angles_deg
        if n_rings == len(base_altitude):
            altitude = list(base_altitude)
        else:
            lo, hi = float(min(base_altitude)), float(max(base_altitude))
            altitude = [lo + (hi - lo) * i / max(n_rings - 1, 1) for i in range(n_rings)]
    if not azimuth:
        azimuth = [0.0] * n_rings
    if len(altitude) != n_rings or len(azimuth) != n_rings:
        raise ValueError("Ouster beam angle arrays must have n_rings entries")
    shifts = _first(payload, "pixel_shift_by_row", "pixel_shift_by_row_idx")
    if shifts is None:
        shifts = [0] * n_rings
    shifts = [int(round(float(item))) for item in shifts]
    if len(shifts) != n_rings:
        raise ValueError("Ouster pixel_shift_by_row must have n_rings entries")
    defaults = default_os1_128_metadata()
    raw_window = _first(payload, "azimuth_window_deg", "azimuth_window") or [-180.0, 180.0]
    if not isinstance(raw_window, (list, tuple)) or len(raw_window) != 2:
        raise ValueError("Ouster azimuth_window must contain two values")
    # Ouster JSON revisions commonly encode this field in 1/1000 degree
    # encoder ticks (e.g. [0, 360000]); accept plain degree values too.
    azimuth_window = [float(v) for v in raw_window]
    if max(abs(v) for v in azimuth_window) > 720.0:
        azimuth_window = [v / 1000.0 for v in azimuth_window]
    lidar_intrinsics = payload.get("lidar_intrinsics") if isinstance(payload.get("lidar_intrinsics"), Mapping) else {}
    beam_to_lidar = _first(payload, "beam_to_lidar_transform", "beam_to_lidar") or lidar_intrinsics.get("beam_to_lidar_transform")
    lidar_to_sensor = _first(payload, "lidar_to_sensor_transform", "lidar_to_sensor") or lidar_intrinsics.get("lidar_to_sensor_transform")
    return OusterLidarMetadata(
        product_line=str(payload.get("product_line") or payload.get("prod_line") or "OS1"),
        model=str(payload.get("model") or payload.get("prod_sn") or "OS1-128"),
        serial=str(payload.get("serial") or payload.get("serial_no")) if payload.get("serial") or payload.get("serial_no") else None,
        firmware=str(payload.get("firmware") or payload.get("fw_rev")) if payload.get("firmware") or payload.get("fw_rev") else None,
        lidar_mode=str(payload.get("lidar_mode") or "1024x10"),
        columns=columns,
        scan_rate_hz=scan_rate,
        n_rings=n_rings,
        beam_altitude_angles_deg=altitude,
        beam_azimuth_angles_deg=azimuth,
        pixel_shift_by_row=shifts,
        beam_to_lidar_transform=_matrix16(beam_to_lidar, default=defaults.beam_to_lidar_transform),
        lidar_to_sensor_transform=_matrix16(lidar_to_sensor, default=defaults.lidar_to_sensor_transform),
        azimuth_window_deg=azimuth_window,
        min_range_m=float(_first(payload, "min_range_m", "min_range") or 0.3),
        max_range_m=float(_first(payload, "max_range_m", "max_range") or 90.0),
        wavelength_nm=float(payload.get("wavelength_nm") or 865.0),
        beam_divergence_deg=float(payload.get("beam_divergence_deg") or 0.09),
        return_mode=str(payload.get("return_mode") or payload.get("return_profile") or "single"),
        metadata_source=source,
    )


def load_ouster_metadata(value: str | Path | Mapping[str, Any] | None) -> OusterLidarMetadata:
    if value is None:
        return default_os1_128_metadata()
    if isinstance(value, Mapping):
        return ouster_metadata_from_mapping(value)
    path = Path(value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Ouster metadata must be a JSON object: {path}")
    return ouster_metadata_from_mapping(payload, source=str(path))
