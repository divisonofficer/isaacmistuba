from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import mean

from .episode_schema import EpisodeManifest, Pose2D, read_episode
from .exporters.custom_json import find_episode_files
from .scene_dataset import SceneDatasetPaths


@dataclass
class EpisodeMetrics:
    episode_id: str
    success: bool
    spl: float
    goal_distance: float
    collision: bool
    hazard_collision: bool
    stop_accuracy: bool
    path_length: float
    shortest_path_length: float


def _distance(a: list[float], b: list[float]) -> float:
    pa = Pose2D.from_value(a)
    pb = Pose2D.from_value(b)
    return float(math.hypot(pa.x - pb.x, pa.y - pb.y))


def _path_length(trajectory: list[list[float]]) -> float:
    return sum(_distance(a, b) for a, b in zip(trajectory, trajectory[1:]))


def evaluate_episode(episode: EpisodeManifest, *, success_radius: float = 0.5) -> EpisodeMetrics:
    final_pose = episode.timesteps[-1].agent_pose if episode.timesteps else episode.trajectory[-1]
    goal_distance = _distance(final_pose, episode.goal_pose)
    collision = any(item.collision for item in episode.timesteps)
    hazard_collision = any(item.hazard_collision for item in episode.timesteps)
    success = goal_distance <= success_radius and not collision
    path_length = _path_length([item.agent_pose for item in episode.timesteps] or episode.trajectory)
    shortest = max(_path_length(episode.trajectory), 1e-9)
    spl = (shortest / max(path_length, shortest)) if success else 0.0
    stop_accuracy = bool(episode.actions and episode.actions[-1] == "stop" and (not episode.timesteps or episode.timesteps[-1].action == "stop"))
    return EpisodeMetrics(
        episode_id=episode.episode_id,
        success=success,
        spl=float(spl),
        goal_distance=float(goal_distance),
        collision=collision,
        hazard_collision=hazard_collision,
        stop_accuracy=stop_accuracy,
        path_length=float(path_length),
        shortest_path_length=float(shortest),
    )


def evaluate_dataset(
    dataset_root: str | Path,
    *,
    success_radius: float = 0.5,
    scene_id: str | None = None,
) -> dict:
    paths = (SceneDatasetPaths.from_project(dataset_root, scene_id).episode_paths()
             if scene_id is not None else find_episode_files(dataset_root))
    episode_metrics = [evaluate_episode(read_episode(path), success_radius=success_radius) for path in paths]
    if not episode_metrics:
        return {"episode_count": 0, "metrics": {}, "episodes": []}
    payloads = [vars(item) for item in episode_metrics]
    return {
        "episode_count": len(episode_metrics),
        "metrics": {
            "success_rate": mean(1.0 if item.success else 0.0 for item in episode_metrics),
            "spl": mean(item.spl for item in episode_metrics),
            "goal_distance": mean(item.goal_distance for item in episode_metrics),
            "collision_rate": mean(1.0 if item.collision else 0.0 for item in episode_metrics),
            "hazard_collision_rate": mean(1.0 if item.hazard_collision else 0.0 for item in episode_metrics),
            "stop_accuracy": mean(1.0 if item.stop_accuracy else 0.0 for item in episode_metrics),
        },
        "episodes": payloads,
    }


def write_evaluation(
    path: str | Path,
    dataset_root: str | Path,
    *,
    success_radius: float = 0.5,
    scene_id: str | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evaluate_dataset(dataset_root, success_radius=success_radius, scene_id=scene_id), indent=2),
        encoding="utf-8",
    )
    return output
