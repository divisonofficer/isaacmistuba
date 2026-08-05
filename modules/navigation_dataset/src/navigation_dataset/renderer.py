from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .episode_schema import EpisodeManifest, Pose2D, write_episode


def _mat4_from_pose_xy_yaw(pose: list[float]) -> list[float]:
    import math

    p = Pose2D.from_value(pose)
    c = math.cos(p.yaw)
    s = math.sin(p.yaw)
    return [
        c, 0.0, -s, 0.0,
        0.0, 1.0, 0.0, 0.0,
        s, 0.0, c, 0.0,
        p.x, 0.0, p.y, 1.0,
    ]


def build_episode_render_requests(
    episode: EpisodeManifest,
    *,
    scene_state_payload: dict,
    camera_spec_payload: dict,
    modalities: list[str],
    render_settings: dict | None = None,
    job_id_mode: str = "shared",
) -> list:
    """Build one RenderRequest per episode timestep.

    ``job_id_mode='per_timestep'`` is used by the daemon queue because the
    existing queue indexes jobs by ``job_id``. Direct rendering keeps the
    source scene job id unchanged for compatibility with the observation
    bridge's existing output layout.
    """
    from robomituba_bridge import (
        RenderRequest,
        RobotState,
    )
    from robomituba_bridge import scene_state_from_payload, camera_spec_from_payload

    scene_state = scene_state_from_payload(scene_state_payload)
    camera_template = camera_spec_from_payload(camera_spec_payload)
    requests = []
    for timestep in episode.timesteps:
        frame_id = f"{episode.episode_id}_frame_{timestep.timestep_index:04d}"
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        job_id = scene_state.job_id
        if job_id_mode == "per_timestep":
            job_id = f"{scene_state.job_id}-{episode.episode_id}-{timestep.timestep_index:04d}"
        elif job_id_mode != "shared":
            raise ValueError("job_id_mode must be 'shared' or 'per_timestep'.")
        timestep_scene_state = replace(scene_state, job_id=job_id, frame_id=frame_id, timestamp=timestamp)
        camera_spec = replace(
            camera_template,
            camera_to_world=_mat4_from_pose_xy_yaw(timestep.agent_pose),
            sensor_modality="multimodal",
        )
        request = RenderRequest(
            request_id=f"{episode.episode_id}-{timestep.timestep_index:04d}",
            job_id=timestep_scene_state.job_id,
            frame_id=frame_id,
            timestamp=timestamp,
            scene_state=timestep_scene_state,
            camera_specs=[camera_spec],
            modalities=list(modalities),
            robot_state=RobotState(base_pose=_mat4_from_pose_xy_yaw(timestep.agent_pose)),
            render_settings=dict(render_settings or {}),
            extras={"episode_id": episode.episode_id, "timestep_index": timestep.timestep_index},
        )
        requests.append(request)
    return requests


def render_episode_direct(
    episode: EpisodeManifest,
    *,
    dataset_root: str | Path,
    scene_state_payload: dict,
    camera_spec_payload: dict,
    modalities: list[str],
    render_settings: dict | None = None,
    render_fn: Callable | None = None,
    variant: str = "auto",
) -> EpisodeManifest:
    """Render an episode through the existing observation bridge.

    ``scene_state_payload`` and ``camera_spec_payload`` intentionally mirror
    robomituba_bridge payloads so this layer stays independent from Isaac.
    """
    if render_fn is None:
        from mitsuba_converter import render_timestep_bundle_split_lighting

        render_fn = render_timestep_bundle_split_lighting

    root = Path(dataset_root).resolve()
    updated_timesteps = []
    requests = build_episode_render_requests(
        episode,
        scene_state_payload=scene_state_payload,
        camera_spec_payload=camera_spec_payload,
        modalities=modalities,
        render_settings=render_settings,
        job_id_mode="shared",
    )
    for timestep, request in zip(episode.timesteps, requests):
        bundle = render_fn(request, repo_root=root, variant=variant)
        timestep.observation_bundle_ref = bundle.bundle_root.rstrip("/") + "/manifest.json"
        updated_timesteps.append(timestep)
    episode.timesteps = updated_timesteps
    return episode


def write_rendered_episode(dataset_root: str | Path, episode: EpisodeManifest) -> Path:
    return write_episode(Path(dataset_root) / "episodes" / episode.split / f"{episode.episode_id}.json", episode)
