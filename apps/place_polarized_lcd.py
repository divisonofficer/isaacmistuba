#!/usr/bin/env python3
"""Place a scene-fixed polarized LCD near an OpticalNav episode path.

The LCD is authored as a wall-mounted area emitter. The renderer expands the
``rgb_directional`` pattern into four colored quadrants and puts one linear
polarizer surface in front of the complete panel.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = REPO_ROOT / "out" / "opticalnav" / "opticalnav-v0.2"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.polarized_lcd.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _episode_files(dataset_root: Path) -> list[Path]:
    return sorted(dataset_root.glob("episodes/*/*.json"))


def _select_episode(dataset_root: Path, scene_id: str, episode_id: str | None) -> tuple[Path, dict[str, Any]]:
    candidates: list[tuple[int, Path, dict[str, Any]]] = []
    for path in _episode_files(dataset_root):
        if episode_id and path.stem != episode_id:
            continue
        payload = _read_json(path)
        if payload.get("scene_id") != scene_id:
            continue
        steps = len(payload.get("timesteps") or payload.get("trajectory") or [])
        candidates.append((steps, path, payload))
    if not candidates:
        requested = f" episode_id={episode_id!r}" if episode_id else ""
        raise FileNotFoundError(f"No episode found for scene_id={scene_id!r}{requested}")
    _, path, payload = min(candidates, key=lambda item: (item[0], item[1].as_posix()))
    return path, payload


def _path_target(scene_dir: Path, episode: dict[str, Any]) -> tuple[float, float]:
    graph = _read_json(scene_dir / "viewpoint_graph.json")
    by_id = {
        str(node.get("node_id")): node
        for node in graph.get("nodes") or []
        if isinstance(node, dict)
    }
    positions: list[tuple[float, float]] = []
    for node_id in episode.get("path_nodes") or []:
        position = (by_id.get(str(node_id)) or {}).get("position")
        if isinstance(position, list) and len(position) >= 2:
            positions.append((float(position[0]), float(position[1])))
    if not positions:
        for pose in episode.get("trajectory") or []:
            if isinstance(pose, list) and len(pose) >= 2:
                positions.append((float(pose[0]), float(pose[1])))
    if not positions:
        raise ValueError("Episode has no path positions")
    return (
        sum(item[0] for item in positions) / len(positions),
        sum(item[1] for item in positions) / len(positions),
    )


def _scene_bounds(authoring: dict[str, Any]) -> tuple[float, float, float, float]:
    centers: list[tuple[float, float]] = []
    for item in authoring.get("objects") or []:
        center = (item.get("geometry") or {}).get("center") if isinstance(item, dict) else None
        if isinstance(center, list) and len(center) >= 2:
            centers.append((float(center[0]), float(center[1])))
    if centers:
        return (
            min(item[0] for item in centers),
            max(item[0] for item in centers),
            min(item[1] for item in centers),
            max(item[1] for item in centers),
        )
    settings = authoring.get("settings") or {}
    return (0.0, float(settings.get("map_w") or 10.0), 0.0, float(settings.get("map_h") or 10.0))


def _auto_panel_pose(
    target: tuple[float, float],
    bounds: tuple[float, float, float, float],
    width_m: float,
) -> tuple[float, float, float, str]:
    tx, tz = target
    min_x, max_x, min_z, max_z = bounds
    distances = {
        "west": abs(tx - min_x),
        "east": abs(max_x - tx),
        "south": abs(tz - min_z),
        "north": abs(max_z - tz),
    }
    side = min(distances, key=distances.get)
    margin = 0.05
    half = width_m / 2.0
    if side in {"west", "east"}:
        x = min_x + margin if side == "west" else max_x - margin
        z = min(max(tz, min_z + half), max_z - half)
    else:
        x = min(max(tx, min_x + half), max_x - half)
        z = min_z + margin if side == "south" else max_z - margin
    yaw = math.degrees(math.atan2(tx - x, tz - z))
    return x, z, yaw, side


def _build_panel(
    *,
    panel_id: str,
    center: tuple[float, float],
    yaw_deg: float,
    width_m: float,
    height_m: float,
    base_height_m: float,
    radiance: float,
    intensity: float,
    polarizer_angle_deg: float,
    pattern: str,
    episode_id: str,
) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "landmark",
        "label": "light:polarized LCD display",
        "placement": "point",
        "geometry": {
            "type": "point",
            "center": [round(center[0], 6), round(center[1], 6)],
            "yaw_deg": round(yaw_deg, 6),
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
            "size_m": [width_m, height_m, 0.03],
            "base_height_m": base_height_m,
        },
        "material": None,
        "navigation": {
            "blocks_navigation": False,
            "hazard_type": None,
            "include_in_hazard_mask": False,
            "instruction_candidate": False,
            "goal_candidate": False,
        },
        "source_ref": None,
        "metadata": {
            "experiment": "polarized_lcd_episode_v1",
            "source_episode_id": episode_id,
            "display_model": "low_cost_lcd_idealized",
        },
        "is_emitter": True,
        "emitter_radiance": [radiance, radiance, radiance],
        "emitter_intensity": intensity,
        "emitter_shape": "wall_panel",
        "emitter_polarized": True,
        "emitter_polarizer_angle_deg": polarizer_angle_deg,
        "emitter_pattern": pattern,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Place a polarized LCD near an OpticalNav episode path.")
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--episode-id", default=None, help="Default: shortest episode for the scene")
    parser.add_argument("--panel-id", default="polarized_lcd_episode_v1")
    parser.add_argument("--position", type=float, nargs=2, metavar=("X", "Z"))
    parser.add_argument("--yaw-deg", type=float, default=None, help="Default: aim panel normal at episode path")
    parser.add_argument("--width-m", type=float, default=1.8)
    parser.add_argument("--height-m", type=float, default=1.0)
    parser.add_argument("--base-height-m", type=float, default=0.65)
    parser.add_argument("--radiance", type=float, default=10.0)
    parser.add_argument("--intensity", type=float, default=1.0)
    parser.add_argument("--polarizer-angle-deg", type=float, default=0.0)
    parser.add_argument("--pattern", choices=("white", "rgb_directional"), default="rgb_directional")
    parser.add_argument("--apply", action="store_true", help="Write authoring_map.json; default is dry-run")
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    scene_dir = dataset_root / "scenes" / args.scene_id
    authoring_path = scene_dir / "authoring_map.json"
    if not authoring_path.exists():
        raise FileNotFoundError(authoring_path)
    authoring = _read_json(authoring_path)
    episode_path, episode = _select_episode(dataset_root, args.scene_id, args.episode_id)
    target = _path_target(scene_dir, episode)
    bounds = _scene_bounds(authoring)
    if args.position:
        x, z = float(args.position[0]), float(args.position[1])
        side = "explicit"
        auto_yaw = math.degrees(math.atan2(target[0] - x, target[1] - z))
    else:
        x, z, auto_yaw, side = _auto_panel_pose(target, bounds, args.width_m)
    yaw = float(args.yaw_deg) if args.yaw_deg is not None else auto_yaw
    panel = _build_panel(
        panel_id=args.panel_id,
        center=(x, z),
        yaw_deg=yaw,
        width_m=max(0.1, args.width_m),
        height_m=max(0.1, args.height_m),
        base_height_m=max(0.0, args.base_height_m),
        radiance=max(0.0, args.radiance),
        intensity=max(0.0, args.intensity),
        polarizer_angle_deg=args.polarizer_angle_deg,
        pattern=args.pattern,
        episode_id=str(episode["episode_id"]),
    )
    objects = [item for item in authoring.get("objects") or [] if item.get("id") != args.panel_id]
    objects.append(panel)
    authoring["objects"] = objects
    result = {
        "scene_id": args.scene_id,
        "episode_id": episode["episode_id"],
        "episode_path": str(episode_path),
        "path_target": [round(target[0], 6), round(target[1], 6)],
        "scene_bounds": [round(value, 6) for value in bounds],
        "placement_side": side,
        "panel": panel,
        "applied": bool(args.apply),
    }
    if args.apply:
        backup = scene_dir / "authoring_map.before_polarized_lcd.json"
        if not backup.exists():
            shutil.copy2(authoring_path, backup)
        _atomic_write_json(authoring_path, authoring)
        result["backup"] = str(backup)
        result["installed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _atomic_write_json(scene_dir / "polarized_lcd_experiment.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
