from __future__ import annotations

import numpy as np

from robomituba_bridge import AssistLightSpec, CameraSpec, RenderRequest, RobotState, SceneState

from mitsuba_converter.multimodal import ModalityResult, MultimodalRenderResult, RenderConfig
from mitsuba_converter import observation_bridge


def _matrix() -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _request(index: int) -> RenderRequest:
    scene = SceneState(
        job_id=f"job_{index}", scene_id="scene", frame_id=f"frame_{index}",
        timestamp="2026-08-29T00:00:00Z", scene_snapshot_ref="scene.xml", mitsuba_scene_ref="scene.xml",
    )
    camera = CameraSpec(
        camera_id="polar", name="Passive polar", camera_to_world=_matrix(), fov_deg=90.0,
        resolution=[4, 3], extras={"render_modalities": ["polar_rgb_preview", "dop"]},
    )
    return RenderRequest(
        request_id=f"request_{index}", job_id=scene.job_id, frame_id=scene.frame_id,
        timestamp=scene.timestamp, scene_state=scene, camera_specs=[camera],
        modalities=["polar_rgb_preview", "dop"], robot_state=RobotState(),
        extras={
            "available_heading_ids": ["h_000", "h_015", "h_345", "h_180"],
            "polar_batch_key": "motion_0001:TRACK_4:00",
        },
    )


def test_stokes_heading_batch_fans_one_render_result_into_ordinary_bundles(tmp_path, monkeypatch):
    (tmp_path / "scene.xml").write_text("<scene version='3.0.0'/>", encoding="utf-8")

    def fake_batch(_scene, poses, _fov, modalities, *, out_dirs, config, **_kwargs):
        assert len(poses) == len(out_dirs) == 2
        assert modalities == ["polar_rgb_preview", "dop"]
        assert config.width == 4 and config.height == 3
        output = []
        for index, out_dir in enumerate(out_dirs):
            out_dir.mkdir(parents=True, exist_ok=True)
            stokes = out_dir / "stokes_data.npz"
            png = out_dir / "polar_rgb_preview.png"
            stokes.write_bytes(b"npz")
            png.write_bytes(b"png")
            array = np.zeros((3, 4, 3), dtype=np.float32)
            results = {
                "polar_rgb_preview": ModalityResult(
                    name="polar_rgb_preview", array=array,
                    artifacts={"stokes_npz": str(stokes), "png": str(png)},
                ),
                "dop": ModalityResult(
                    name="dop", array=np.zeros((3, 4), dtype=np.float32),
                    artifacts={"stokes_npz": str(stokes)},
                ),
            }
            output.append(MultimodalRenderResult(
                scene={"source_scene": str(_scene)}, camera={"batch_index": index},
                config=RenderConfig(width=4, height=3), definitions={}, results=results,
                pass_records={"polarization": {"batch_size": 2, "batch_index": index}},
            ))
        return output

    monkeypatch.setattr(observation_bridge, "render_ambient_stokes_heading_batch", fake_batch)
    bundles = observation_bridge.render_timestep_bundle_stokes_heading_batch(
        [_request(0), _request(1)], repo_root=tmp_path, variant="cuda_ad_rgb_polarized",
    )

    assert [bundle.frame_id for bundle in bundles] == ["frame_0", "frame_1"]
    for index, bundle in enumerate(bundles):
        assert bundle.extras["stokes_heading_batch"] == {
            "batch_index": index, "batch_size": 2, "camera_id": "polar",
        }
        assert bundle.extras["available_heading_ids"] == ["h_000", "h_015", "h_345", "h_180"]
        assert {artifact.modality for artifact in bundle.artifacts} == {"polar_rgb_preview", "dop"}
        assert (tmp_path / "out" / "bridge_jobs" / f"job_{index}" / "observations" / f"frame_{index}" / "manifest.json").is_file()


def test_active_stokes_heading_batch_keeps_one_camera_local_light_per_strip(tmp_path, monkeypatch):
    (tmp_path / "scene.xml").write_text("<scene version='3.0.0'/>", encoding="utf-8")
    requests = [_request(0), _request(1)]
    for request in requests:
        request.assist_light = AssistLightSpec(
            mode="camera_aligned_rect", distance_m=0.12, size_world=[2.2, 1.6],
            spectrum_mode="rgb_white", polarized=True, polarizer_angle_deg=0.0,
        )
        request.extras["polar_active"] = True

    def fake_batch(_scene, poses, _fov, modalities, *, out_dirs, config, assist_lights, batch_mode, **_kwargs):
        assert len(poses) == len(out_dirs) == len(assist_lights) == 2
        assert all(light.mode == "camera_aligned_rect" and light.polarized for light in assist_lights)
        assert batch_mode == "active_stokes_heading_spatial_batch_v1"
        output = []
        for index, out_dir in enumerate(out_dirs):
            out_dir.mkdir(parents=True, exist_ok=True)
            stokes = out_dir / "stokes_data.npz"
            png = out_dir / "polar_rgb_preview.png"
            stokes.write_bytes(b"npz")
            png.write_bytes(b"png")
            array = np.zeros((3, 4, 3), dtype=np.float32)
            output.append(MultimodalRenderResult(
                scene={"source_scene": str(_scene)}, camera={"batch_index": index},
                config=RenderConfig(width=4, height=3), definitions={},
                results={
                    "polar_rgb_preview": ModalityResult(name="polar_rgb_preview", array=array, artifacts={"stokes_npz": str(stokes), "png": str(png)}),
                    "dop": ModalityResult(name="dop", array=np.zeros((3, 4), dtype=np.float32), artifacts={"stokes_npz": str(stokes)}),
                },
                pass_records={"polarization": {"batch_size": 2, "batch_index": index}},
            ))
        return output

    monkeypatch.setattr(observation_bridge, "render_ambient_stokes_heading_batch", fake_batch)
    bundles = observation_bridge.render_timestep_bundle_active_stokes_heading_batch(
        requests, repo_root=tmp_path, variant="cuda_ad_rgb_polarized",
    )

    for index, bundle in enumerate(bundles):
        assert bundle.extras["branch_policy"] == "active_stokes_heading_spatial_batch_v1"
        assert bundle.extras["stokes_heading_batch"] == {
            "batch_index": index,
            "batch_size": 2,
            "camera_id": "polar",
            "mode": "active_stokes_heading_spatial_batch_v1",
            "camera_aligned_light": True,
            "spatial_noninterference_required": True,
        }
