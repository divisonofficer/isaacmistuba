from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable

from .episode_schema import EpisodeManifest, EpisodeTimestep, GENERATION_VERSION, write_episode
from .scene_dataset import SceneDatasetPaths
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


def scale_split_counts(split_counts: dict[str, int], total: int) -> dict[str, int]:
    """Rescale a split spec (interpreted as weights/ratios) to ``total`` items.

    The CLI spec (e.g. ``train:60,val_seen:10,val_unseen:10``) describes *proportions*,
    not absolute counts. When ``num_pairs`` exceeds ``sum(split_counts)`` the raw counts
    would dump every overflow episode into the last split. Rescaling preserves the ratio
    regardless of how many episodes are generated, using largest-remainder rounding so
    the result sums to exactly ``total``.
    """
    weights = {name: max(0, int(count)) for name, count in split_counts.items()}
    weight_sum = sum(weights.values())
    if total <= 0 or weight_sum <= 0:
        return dict(split_counts)
    exact = {name: total * w / weight_sum for name, w in weights.items()}
    scaled = {name: int(value) for name, value in exact.items()}
    remainder = total - sum(scaled.values())
    # Hand out the leftover (from flooring) to the largest fractional parts first.
    order = sorted(exact, key=lambda name: exact[name] - scaled[name], reverse=True)
    for name in order[:remainder]:
        scaled[name] += 1
    return scaled


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
    on_progress: "Callable[[int, int, int], None] | None" = None,
) -> list[EpisodeManifest]:
    pairs = sample_start_goal_pairs(grid, annotation.goal_regions, count=num_pairs, seed=seed)
    split_counts = scale_split_counts(split_counts, len(pairs))
    episodes: list[EpisodeManifest] = []
    total = len(pairs)
    for index, (start_pose, goal_region) in enumerate(pairs):
        if on_progress is not None:
            on_progress(len(episodes), total, index + 1)
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
    rows = list(episodes)
    if not rows:
        return []
    scene_ids = {episode.scene_id for episode in rows}
    if len(scene_ids) != 1:
        raise ValueError("write_episodes requires one scene; use explicit multi-scene orchestration")
    return write_scene_episodes(SceneDatasetPaths.from_project(root, scene_ids.pop()), rows)


def write_scene_episodes(paths: SceneDatasetPaths, episodes: Iterable[EpisodeManifest]) -> list[Path]:
    """Write episodes to one scene workspace without a project-wide path."""
    return [paths.write_episode(episode) for episode in episodes]
