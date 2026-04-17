"""Helpers for spawning and controlling Ranger Mini robots from the Isaac panel."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

_APPS_DIR = Path(__file__).resolve().parent.parent


def _log_debug(message: str) -> None:
    line = f"[RangerMiniStage] {message}"
    try:
        import carb  # type: ignore

        carb.log_info(line)
    except Exception:
        pass
    print(line)


def _require_pxr():
    from pxr import Gf, Sdf, Usd, UsdGeom  # type: ignore

    return Gf, Sdf, Usd, UsdGeom


def _attr_value(prim: Any, name: str, default: Any = None) -> Any:
    attr = prim.GetAttribute(name)
    if not attr:
        return default
    value = attr.Get()
    return default if value is None else value


def _robot_root_prim(stage: Any, prim_path: str) -> Any:
    prim = stage.GetPrimAtPath(prim_path)
    if prim and prim.IsValid():
        return prim
    return None


def _default_spawn_path(stage: Any) -> str:
    index = 1
    while True:
        candidate = f"/World/RangerMini_{index:02d}"
        prim = stage.GetPrimAtPath(candidate)
        if not prim or not prim.IsValid():
            return candidate
        index += 1


def _viewport_based_spawn_translation(stage: Any, *, robot_index: int = 0) -> tuple[float, float, float]:
    try:
        import omni.usd  # type: ignore
        from omni.kit.viewport.utility import get_active_viewport  # type: ignore
        from pxr import Gf, Usd, UsdGeom  # type: ignore
    except Exception:
        return (float(robot_index) * 1.2, 0.0, 0.0)

    try:
        viewport = get_active_viewport()
        if viewport is None:
            return (float(robot_index) * 1.2, 0.0, 0.0)
        camera_path = viewport.camera_path
        camera_path_str = camera_path.pathString if hasattr(camera_path, "pathString") else str(camera_path)
        camera_prim = stage.GetPrimAtPath(camera_path_str)
        if not camera_prim or not camera_prim.IsValid():
            return (float(robot_index) * 1.2, 0.0, 0.0)
        matrix = UsdGeom.Xformable(camera_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        origin = matrix.Transform(Gf.Vec3d(0.0, 0.0, 0.0))
        target = matrix.Transform(Gf.Vec3d(0.0, 0.0, -1.0))
        forward = Gf.Vec3d(target[0] - origin[0], target[1] - origin[1], target[2] - origin[2])
        length = math.sqrt(float(forward[0] ** 2 + forward[1] ** 2 + forward[2] ** 2))
        if length <= 1e-6:
            return (float(robot_index) * 1.2, 0.0, 0.0)
        forward = Gf.Vec3d(forward[0] / length, forward[1] / length, forward[2] / length)

        spawn_x = float(origin[0])
        spawn_y = float(origin[1])
        spawn_z = 0.0

        # Prefer the point where the camera view ray meets the ground plane (Z=0).
        if abs(float(forward[2])) > 1e-4:
            t_ground = -float(origin[2]) / float(forward[2])
            if t_ground > 0.25:
                spawn_x = float(origin[0] + forward[0] * t_ground)
                spawn_y = float(origin[1] + forward[1] * t_ground)
            else:
                raise ValueError("Viewport ray does not intersect ground in front of the camera.")
        else:
            raise ValueError("Viewport ray is parallel to the ground plane.")

        flat_len = math.sqrt(float(forward[0] ** 2 + forward[1] ** 2))
        if flat_len > 1e-6:
            left_x = -float(forward[1]) / flat_len
            left_y = float(forward[0]) / flat_len
        else:
            left_x, left_y = 0.0, 1.0
        lateral_offset = float(robot_index) * 0.9
        spawn_x += left_x * lateral_offset
        spawn_y += left_y * lateral_offset
        return (spawn_x, spawn_y, spawn_z)
    except Exception as exc:
        _log_debug(f"viewport-based spawn fallback engaged error={exc}")
        return (float(robot_index) * 1.2, 0.0, 0.0)


def list_ranger_mini_robots(stage: Any) -> list[dict[str, Any]]:
    _, _, _, UsdGeom = _require_pxr()

    xform_cache = UsdGeom.XformCache()
    robots: list[dict[str, Any]] = []
    for prim in stage.Traverse():
        if str(_attr_value(prim, "robomituba:robotName", "")) != "ranger_mini_v3":
            continue
        transform = xform_cache.GetLocalToWorldTransform(prim)
        translation = transform.ExtractTranslation()
        robots.append(
            {
                "prim_path": str(prim.GetPath()),
                "name": prim.GetName(),
                "translation": [float(translation[0]), float(translation[1]), float(translation[2])],
                "motion_mode": int(_attr_value(prim, "robomituba:motionMode", 0)),
                "battery_voltage": float(_attr_value(prim, "robomituba:batteryVoltage", 48.0)),
                "battery_soc": float(_attr_value(prim, "robomituba:batterySoc", 1.0)),
                "estop": bool(_attr_value(prim, "robomituba:estop", False)),
                "has_error": bool(_attr_value(prim, "robomituba:hasError", False)),
                "joint_positions": [float(v) for v in (_attr_value(prim, "robomituba:jointPositions", []) or [])],
            }
        )
    robots.sort(key=lambda item: item["prim_path"])
    return robots


def spawn_ranger_mini(stage: Any, *, prim_path: str | None = None, translation: tuple[float, float, float] | None = None) -> dict[str, Any]:
    from isaac_standalone.ranger_mini import RangerMiniRobot

    resolved_prim_path = prim_path or _default_spawn_path(stage)
    resolved_translation = translation
    if resolved_translation is None:
        resolved_translation = _viewport_based_spawn_translation(stage, robot_index=len(list_ranger_mini_robots(stage)))
    _log_debug(f"spawn requested prim_path={resolved_prim_path} translation={resolved_translation}")
    robot = RangerMiniRobot.spawn(
        stage=stage,
        prim_path=resolved_prim_path,
        translation=resolved_translation,
        use_reference=True,
    )
    state = robot.get_state()
    _log_debug(
        "spawn completed "
        f"prim_path={resolved_prim_path} motion_mode={int(state.motion_mode)} "
        f"base_pose={state.base_pose}"
    )
    return {
        "prim_path": resolved_prim_path,
        "translation": list(resolved_translation),
        "motion_mode": int(state.motion_mode),
    }


def _bound_robot(stage: Any, prim_path: str):
    from isaac_standalone.ranger_mini import RangerMiniRobot

    prim = _robot_root_prim(stage, prim_path)
    if prim is None:
        raise RuntimeError(f"Robot not found at {prim_path}")

    robot = RangerMiniRobot(prim_path=prim_path)
    _, _, _, UsdGeom = _require_pxr()
    xform_cache = UsdGeom.XformCache()
    transform = xform_cache.GetLocalToWorldTransform(prim)
    translation = transform.ExtractTranslation()
    robot.state.base_pose = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        float(translation[0]), float(translation[1]), float(translation[2]), 1.0,
    ]
    robot.heading_rad = float(_attr_value(prim, "robomituba:headingRad", 0.0))
    motion_mode = int(_attr_value(prim, "robomituba:motionMode", 0))
    joint_positions = [float(v) for v in (_attr_value(prim, "robomituba:jointPositions", []) or [])]
    steering_angles = [float(v) for v in (_attr_value(prim, "robomituba:steeringAngles", []) or [])]
    wheel_speeds = [float(v) for v in (_attr_value(prim, "robomituba:wheelSpeeds", []) or [])]
    robot.state.motion_mode = motion_mode
    if joint_positions:
        robot.state.joint_positions = joint_positions
    if steering_angles:
        robot.state.steering_angles = steering_angles
    if wheel_speeds:
        robot.state.wheel_speeds = wheel_speeds
    robot.state.battery_voltage = float(_attr_value(prim, "robomituba:batteryVoltage", 48.0))
    robot.state.battery_soc = float(_attr_value(prim, "robomituba:batterySoc", 1.0))
    robot.state.estop = bool(_attr_value(prim, "robomituba:estop", False))
    robot.state.has_error = bool(_attr_value(prim, "robomituba:hasError", False))
    _log_debug(
        "bound robot "
        f"prim_path={prim_path} translation={robot.state.base_pose[12:15]} "
        f"motion_mode={motion_mode}"
    )
    return robot


def command_robot(stage: Any, prim_path: str, action: str) -> dict[str, Any]:
    from isaac_standalone.ranger_mini import RangerMiniMotionMode

    _log_debug(f"command requested prim_path={prim_path} action={action}")
    robot = _bound_robot(stage, prim_path)
    if action == "forward":
        robot.set_motion_mode(int(RangerMiniMotionMode.ACKERMANN))
        robot.move(linear_speed=0.8, steering_angle=0.0)
    elif action == "backward":
        robot.set_motion_mode(int(RangerMiniMotionMode.ACKERMANN))
        robot.move(linear_speed=-0.6, steering_angle=0.0)
    elif action == "left":
        robot.turn_left(speed=0.5)
    elif action == "right":
        robot.turn_right(speed=0.5)
    elif action == "strafe_left":
        robot.set_motion_mode(int(RangerMiniMotionMode.OBLIQUE))
        robot.move(linear_speed=0.5, steering_angle=1.57079632679 / 2.0)
    elif action == "strafe_right":
        robot.set_motion_mode(int(RangerMiniMotionMode.OBLIQUE))
        robot.move(linear_speed=0.5, steering_angle=-1.57079632679 / 2.0)
    elif action == "spin_left":
        robot.spin(0.8)
    elif action == "spin_right":
        robot.spin(-0.8)
    elif action == "park":
        robot.park()
    elif action == "stop":
        robot.stop()
    else:
        raise RuntimeError(f"Unsupported RangerMini action: {action}")

    state = robot.update(1.0 / 60.0, stage=stage)
    _log_debug(
        "command completed "
        f"prim_path={prim_path} action={action} motion_mode={int(state.motion_mode)} "
        f"translation={state.base_pose[12:15] if state.base_pose else None}"
    )
    return {
        "prim_path": prim_path,
        "action": action,
        "motion_mode": int(state.motion_mode),
        "joint_positions": list(state.joint_positions),
    }
