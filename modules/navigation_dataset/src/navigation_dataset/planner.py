from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
import random
from typing import Iterable

import numpy as np

from .episode_schema import Pose2D
from .scene_annotations import GoalRegion
from .traversability import GridSpec, TraversabilityGrid, cell_to_world, world_to_cell


@dataclass(frozen=True)
class PlannedPath:
    start_cell: tuple[int, int]
    goal_cell: tuple[int, int]
    cells: list[tuple[int, int]]
    poses: list[list[float]]
    actions: list[str]
    hazard_crossing: bool


def _neighbors(grid: TraversabilityGrid, cell: tuple[int, int]) -> Iterable[tuple[int, int]]:
    x, y = cell
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
        if 0 <= nx < grid.spec.width and 0 <= ny < grid.spec.height and bool(grid.traversable[ny, nx]):
            yield nx, ny


def nearest_traversable_cell(grid: TraversabilityGrid, x: float, y: float) -> tuple[int, int]:
    start = world_to_cell(grid.spec, x, y)
    sx = max(0, min(grid.spec.width - 1, start[0]))
    sy = max(0, min(grid.spec.height - 1, start[1]))
    if bool(grid.traversable[sy, sx]):
        return sx, sy
    visited = {(sx, sy)}
    queue = [(sx, sy)]
    while queue:
        cx, cy = queue.pop(0)
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not (0 <= nx < grid.spec.width and 0 <= ny < grid.spec.height) or (nx, ny) in visited:
                continue
            if bool(grid.traversable[ny, nx]):
                return nx, ny
            visited.add((nx, ny))
            queue.append((nx, ny))
    raise ValueError("Grid has no traversable cells.")


def astar(grid: TraversabilityGrid, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    if not bool(grid.traversable[start[1], start[0]]):
        raise ValueError(f"start is not traversable: {start}")
    if not bool(grid.traversable[goal[1], goal[0]]):
        raise ValueError(f"goal is not traversable: {goal}")

    def h(cell: tuple[int, int]) -> float:
        return abs(cell[0] - goal[0]) + abs(cell[1] - goal[1])

    open_heap: list[tuple[float, tuple[int, int]]] = [(h(start), start)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score = {start: 0.0}

    while open_heap:
        _score, current = heapq.heappop(open_heap)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return list(reversed(path))
        for neighbor in _neighbors(grid, current):
            tentative = g_score[current] + 1.0
            if tentative < g_score.get(neighbor, math.inf):
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                heapq.heappush(open_heap, (tentative + h(neighbor), neighbor))
    raise ValueError(f"No path found from {start} to {goal}.")


def _yaw_for_delta(dx: int, dy: int) -> float:
    if dx > 0:
        return 0.0
    if dx < 0:
        return math.pi
    if dy > 0:
        return math.pi / 2.0
    if dy < 0:
        return -math.pi / 2.0
    return 0.0


def cells_to_poses(spec: GridSpec, cells: list[tuple[int, int]]) -> list[list[float]]:
    poses: list[list[float]] = []
    for index, cell in enumerate(cells):
        if index + 1 < len(cells):
            next_cell = cells[index + 1]
            yaw = _yaw_for_delta(next_cell[0] - cell[0], next_cell[1] - cell[1])
        elif poses:
            yaw = poses[-1][2]
        else:
            yaw = 0.0
        wx, wy = cell_to_world(spec, cell[0], cell[1])
        poses.append([wx, wy, yaw])
    return poses


def poses_to_actions(poses: list[list[float]]) -> list[str]:
    if len(poses) <= 1:
        return ["stop"]
    actions: list[str] = []
    current_yaw = Pose2D.from_value(poses[0]).yaw
    for pose in poses[1:]:
        target_yaw = Pose2D.from_value(pose).yaw
        delta = math.atan2(math.sin(target_yaw - current_yaw), math.cos(target_yaw - current_yaw))
        if delta > math.pi / 4:
            actions.append("turn_left")
        elif delta < -math.pi / 4:
            actions.append("turn_right")
        actions.append("move_forward")
        current_yaw = target_yaw
    actions.append("stop")
    return actions


def plan_path(grid: TraversabilityGrid, start_pose: list[float], goal_pose: list[float]) -> PlannedPath:
    start = nearest_traversable_cell(grid, start_pose[0], start_pose[1])
    goal = nearest_traversable_cell(grid, goal_pose[0], goal_pose[1])
    cells = astar(grid, start, goal)
    poses = cells_to_poses(grid.spec, cells)
    actions = poses_to_actions(poses)
    hazard_crossing = any(bool(grid.hazard[y, x]) for x, y in cells)
    return PlannedPath(start_cell=start, goal_cell=goal, cells=cells, poses=poses, actions=actions, hazard_crossing=hazard_crossing)


def sample_start_goal_pairs(
    grid: TraversabilityGrid,
    goal_regions: list[GoalRegion],
    *,
    count: int,
    seed: int = 0,
) -> list[tuple[list[float], GoalRegion]]:
    if count <= 0:
        raise ValueError("count must be positive.")
    traversable_cells = np.argwhere(grid.traversable)
    if traversable_cells.size == 0:
        raise ValueError("No traversable cells available.")
    rng = random.Random(seed)
    pairs: list[tuple[list[float], GoalRegion]] = []
    for _ in range(count):
        cell_y, cell_x = [int(item) for item in traversable_cells[rng.randrange(len(traversable_cells))]]
        wx, wy = cell_to_world(grid.spec, cell_x, cell_y)
        goal = goal_regions[rng.randrange(len(goal_regions))]
        pairs.append(([wx, wy, 0.0], goal))
    return pairs
