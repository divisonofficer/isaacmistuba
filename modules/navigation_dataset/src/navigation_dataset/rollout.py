from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .episode_schema import EpisodeManifest, EpisodeTimestep, GENERATION_VERSION, write_episode
from .instruction_templates import make_instruction
from .planner import plan_path, sample_start_goal_pairs
from .scene_annotations import SceneAnnotation
from .traversability import TraversabilityGrid


def split_counts_from_spec(spec: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for part in spec.split(","):
        if not part.strip():
            continue
        name, value = part.split(":", 1)
        result[name.strip()] = int(value)
    return result


def split_for_index(split_counts: dict[str, int], index: int) -> str:
    cursor = 0
    for split, count in split_counts.items():
        cursor += int(count)
        if index < cursor:
            return split
    return next(reversed(split_counts)) if split_counts else "train"


def make_episode(
    *,
    episode_id: str,
    split: str,
    annotation: SceneAnnotation,
    grid: TraversabilityGrid,
    start_pose: list[float],
    goal_region_id: str,
    instruction_type: str,
    modalities: list[str],
) -> EpisodeManifest:
    goal_region = next((item for item in annotation.goal_regions if item.region_id == goal_region_id), None)
    if goal_region is None:
        raise ValueError(f"Unknown goal_region_id: {goal_region_id}")
    goal_pose = [float(goal_region.center[0]), float(goal_region.center[1]), 0.0]
    planned = plan_path(grid, start_pose, goal_pose)
    timesteps: list[EpisodeTimestep] = []
    for index, pose in enumerate(planned.poses):
        action = "stop" if index == len(planned.poses) - 1 else planned.actions[min(index, len(planned.actions) - 1)]
        cell = planned.cells[min(index, len(planned.cells) - 1)]
        timesteps.append(
            EpisodeTimestep(
                timestep_index=index,
                timestamp=float(index),
                agent_pose=pose,
                action=action,
                collision=False,
                hazard_collision=bool(grid.hazard[cell[1], cell[0]]),
            )
        )
    return EpisodeManifest(
        episode_id=episode_id,
        scene_id=annotation.scene_id,
        split=split,
        start_pose=planned.poses[0],
        goal_pose=goal_pose,
        goal_region=goal_region.region_id,
        natural_language_instruction=make_instruction(annotation, goal_region, instruction_type=instruction_type),
        trajectory=planned.poses,
        actions=planned.actions,
        timesteps=timesteps,
        metadata={
            "modalities": list(modalities),
            "hazards": sorted({item.hazard_type for item in annotation.hazard_regions}),
            "generation_version": GENERATION_VERSION,
            "instruction_type": instruction_type,
            "hazard_crossing": planned.hazard_crossing,
            "start_cell": list(planned.start_cell),
            "goal_cell": list(planned.goal_cell),
        },
    )


def plan_episodes(
    *,
    annotation: SceneAnnotation,
    grid: TraversabilityGrid,
    num_pairs: int,
    split_counts: dict[str, int],
    instruction_types: list[str],
    modalities: list[str],
    seed: int = 0,
) -> list[EpisodeManifest]:
    pairs = sample_start_goal_pairs(grid, annotation.goal_regions, count=num_pairs, seed=seed)
    episodes: list[EpisodeManifest] = []
    for index, (start_pose, goal_region) in enumerate(pairs):
        split = split_for_index(split_counts, index)
        instruction_type = instruction_types[index % len(instruction_types)]
        episode_id = f"{annotation.scene_id}_{split}_{index + 1:06d}"
        try:
            episodes.append(
                make_episode(
                    episode_id=episode_id,
                    split=split,
                    annotation=annotation,
                    grid=grid,
                    start_pose=start_pose,
                    goal_region_id=goal_region.region_id,
                    instruction_type=instruction_type,
                    modalities=modalities,
                )
            )
        except ValueError:
            continue
    return episodes


def write_episodes(root: str | Path, episodes: Iterable[EpisodeManifest]) -> list[Path]:
    dataset_root = Path(root)
    written: list[Path] = []
    for episode in episodes:
        path = dataset_root / "episodes" / episode.split / f"{episode.episode_id}.json"
        written.append(write_episode(path, episode))
    return written
