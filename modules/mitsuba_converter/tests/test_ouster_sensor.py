from __future__ import annotations

import numpy as np

from robomituba_bridge import (
    IsaacSensorSpec,
    RenderRequest,
    OUSTER_OS1_128,
    default_os1_128_metadata,
    render_request_from_payload,
    render_request_to_payload,
)
from mitsuba_converter.multimodal import _build_sensor_depth, _destagger_lidar_field


def _matrix():
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def test_os1_profile_and_default_shape():
    metadata = default_os1_128_metadata()
    assert OUSTER_OS1_128.resolution_wh == (1024, 128)
    assert metadata.columns == 1024
    assert metadata.n_rings == 128
    assert len(metadata.beam_altitude_angles_deg) == 128


def test_destagger_applies_per_ring_pixel_shift():
    field = np.arange(2 * 5, dtype=np.float32).reshape(2, 5)
    out = _destagger_lidar_field(field, [0, 2])
    assert np.array_equal(out[0], field[0])
    assert np.array_equal(out[1], np.roll(field[1], -2))


def test_depth_sensor_quantizes_and_masks_dropout():
    depth = np.full((4, 4), 1.2346, dtype=np.float32)
    depth[0, 0] = np.nan
    sensor, valid, confidence = _build_sensor_depth(
        depth, quantization_m=0.001, noise_std_m=0.0, dropout_probability=0.0, seed=3
    )
    assert np.isclose(sensor[1, 1], 1.235)
    assert not valid[0, 0]
    assert confidence[1, 1] == 1.0
    assert np.isnan(sensor[0, 0])


def test_render_request_sensor_round_trip():
    from robomituba_bridge import SceneState, RobotState

    scene = SceneState(
        job_id="job", scene_id="scene", frame_id="frame", timestamp="2026-01-01T00:00:00Z",
        scene_snapshot_ref="snapshot.json", mitsuba_scene_ref="scene.xml",
    )
    request = RenderRequest(
        request_id="request", job_id="job", frame_id="frame", timestamp=scene.timestamp,
        scene_state=scene, camera_specs=[], sensor_specs=[IsaacSensorSpec(
            sensor_id="ouster", name="OS1", sensor_type="ouster_lidar", profile="os1-128",
            modalities=["lidar_point_cloud"], camera_to_world=_matrix(), resolution=[1024, 128],
            metadata_ref="calibration/ouster.json",
        )], modalities=["lidar_point_cloud"], robot_state=RobotState(),
    )
    payload = render_request_to_payload(request)
    restored = render_request_from_payload(payload)
    assert restored.sensor_specs[0].sensor_type == "ouster_lidar"
    assert restored.sensor_specs[0].resolution == [1024, 128]


def test_transient_histogram_to_tof_depth():
    from mitsuba_converter.mitransient_adapter import tof_depth_from_histogram

    hist = np.zeros((2, 4), dtype=np.float32)
    hist[0, 1] = 2.0
    hist[1, 3] = 4.0
    depth, confidence, valid = tof_depth_from_histogram(hist, bin_width_s=1e-9)
    assert valid.tolist() == [True, True]
    assert np.isclose(depth[0], 0.149896229)
    assert np.isclose(depth[1], 0.449688687)
    assert np.allclose(confidence, 1.0)
