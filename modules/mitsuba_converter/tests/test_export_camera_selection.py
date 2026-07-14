from __future__ import annotations

from types import SimpleNamespace

import pytest

from mitsuba_converter.render_daemon import (
    RenderDaemon,
    _normalize_export_camera_ids,
)


def _write_sensor(root, tree: str, camera_id: str, filename: str) -> None:
    sensor_dir = root / "scenes" / "scene_a" / tree / "vp_1" / "h_000" / "sensors" / camera_id
    sensor_dir.mkdir(parents=True, exist_ok=True)
    (sensor_dir / filename).write_bytes(b"render")


def test_export_camera_ids_normalization() -> None:
    assert _normalize_export_camera_ids(None) is None
    assert _normalize_export_camera_ids(["cam_b", "cam_a", "cam_b"]) == ["cam_b", "cam_a"]
    with pytest.raises(ValueError, match="at least one"):
        _normalize_export_camera_ids([])
    with pytest.raises(ValueError, match="array or null"):
        _normalize_export_camera_ids("cam_a")


def test_observation_scan_builds_base_and_perturbed_sensor_inventory(tmp_path) -> None:
    _write_sensor(tmp_path, "observations", "rgb_cam", "rgb.png")
    _write_sensor(tmp_path, "observations", "polar_cam", "polar_rgb_preview.png")
    _write_sensor(tmp_path, "observations_perturbed", "polar_cam", "dop_red_black_colorbar.png")

    daemon = SimpleNamespace(_OPTICALNAV_OBS_PNG_FILENAMES=RenderDaemon._OPTICALNAV_OBS_PNG_FILENAMES)
    result = RenderDaemon._opticalnav_scan_observations(daemon, tmp_path, "scene_a")
    inventory = {item["sensor_id"]: item for item in result["sensor_inventory"]}

    assert inventory["rgb_cam"] == {
        "sensor_id": "rgb_cam",
        "modalities": ["rgb"],
        "observation_count": 1,
        "base_count": 1,
        "perturbed_count": 0,
    }
    assert inventory["polar_cam"] == {
        "sensor_id": "polar_cam",
        "modalities": ["dop", "polar_rgb_preview"],
        "observation_count": 2,
        "base_count": 1,
        "perturbed_count": 1,
    }
