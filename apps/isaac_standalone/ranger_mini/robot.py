from __future__ import annotations

from dataclasses import replace
from math import cos, degrees, sin, tan
from pathlib import Path
from typing import Any

from .constants import JOINT_ORDER, RangerMiniMotionMode, RangerMiniParams
from .kinematics import compute_joint_targets, saturate_command
from .ros_adapter import RangerMiniRosAdapter
from .types import JointTargets, RangerMiniCommand, RangerMiniState


def _log_debug(message: str) -> None:
    line = f"[RangerMiniRobot] {message}"
    try:
        import carb  # type: ignore

        carb.log_info(line)
    except Exception:
        pass
    print(line)


def _identity_pose(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        float(x), float(y), float(z), 1.0,
    ]


class RangerMiniRobot:
    def __init__(
        self,
        *,
        prim_path: str | None = None,
        asset_path: str | None = None,
        params: RangerMiniParams | None = None,
    ) -> None:
        self.params = params or RangerMiniParams()
        self.prim_path = prim_path or self.params.prim_path
        self.asset_path = asset_path or self.params.asset_repo_path
        self.command = RangerMiniCommand()
        self.targets = compute_joint_targets(self.command, self.params)
        self.heading_rad = 0.0
        self._wheel_rotation_rad = {
            "fr_wheel_link": 0.0,
            "fl_wheel_link": 0.0,
            "rr_wheel_link": 0.0,
            "rl_wheel_link": 0.0,
        }
        self.state = RangerMiniState(
            joint_names=list(JOINT_ORDER),
            joint_positions=self._joint_targets_to_positions(self.targets),
            steering_angles=self._steering_angles_from_targets(self.targets),
            wheel_speeds=self._wheel_speeds_from_targets(self.targets),
            base_pose=_identity_pose(0.0, 0.0, self.params.wheel_radius_m),
        )
        self.ros = RangerMiniRosAdapter()

    @classmethod
    def spawn(
        cls,
        *,
        stage: Any | None = None,
        prim_path: str | None = None,
        asset_path: str | None = None,
        translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        params: RangerMiniParams | None = None,
        use_reference: bool | None = None,
    ) -> "RangerMiniRobot":
        robot = cls(prim_path=prim_path, asset_path=asset_path, params=params)
        robot.state.base_pose = _identity_pose(*translation)
        _log_debug(
            f"spawn start prim_path={robot.prim_path} translation={translation} "
            f"use_reference={use_reference} asset_path={robot.asset_path}"
        )
        if stage is not None:
            robot._spawn_robot(stage, translation=translation, use_reference=use_reference)
            robot._write_state_to_stage(stage)
        _log_debug(f"spawn done prim_path={robot.prim_path}")
        return robot

    def set_motion_mode(self, motion_mode: int) -> None:
        self.command.motion_mode = int(motion_mode)

    def set_speed(self, speed_mps: float, *, steering_angle_rad: float | None = None) -> None:
        self.command.linear_speed_mps = float(speed_mps)
        if steering_angle_rad is not None:
            self.command.steering_angle_rad = float(steering_angle_rad)

    def move(self, speed: float | None = None, *, linear_speed: float | None = None, steering_angle: float | None = None) -> None:
        if linear_speed is None and speed is not None:
            linear_speed = speed
        if linear_speed is not None:
            self.command.linear_speed_mps = float(linear_speed)
        if steering_angle is not None:
            self.command.steering_angle_rad = float(steering_angle)

    def stop(self) -> None:
        self.command.linear_speed_mps = 0.0
        self.command.spin_speed_radps = 0.0

    def turn_left(self, speed: float = 0.5, steering_angle: float | None = None) -> None:
        self.command.motion_mode = int(RangerMiniMotionMode.ACKERMANN)
        self.command.linear_speed_mps = float(speed)
        self.command.steering_angle_rad = float(
            steering_angle if steering_angle is not None else self.params.max_ackermann_steer_rad * 0.5
        )

    def turn_right(self, speed: float = 0.5, steering_angle: float | None = None) -> None:
        self.command.motion_mode = int(RangerMiniMotionMode.ACKERMANN)
        self.command.linear_speed_mps = float(speed)
        self.command.steering_angle_rad = -float(
            steering_angle if steering_angle is not None else self.params.max_ackermann_steer_rad * 0.5
        )

    def spin(self, spin_speed: float) -> None:
        self.command.motion_mode = int(RangerMiniMotionMode.SPIN)
        self.command.spin_speed_radps = float(spin_speed)
        self.command.linear_speed_mps = 0.0

    def park(self) -> None:
        self.command.motion_mode = int(RangerMiniMotionMode.PARKING)
        self.command.linear_speed_mps = 0.0
        self.command.spin_speed_radps = 0.0

    def update(self, dt: float, *, stage: Any | None = None) -> RangerMiniState:
        self.command = saturate_command(self.command, self.params)
        self.targets = compute_joint_targets(self.command, self.params)
        self._integrate_base_motion(dt)
        self._integrate_wheel_rotation(dt)
        self.state = replace(
            self.state,
            motion_mode=int(self.command.motion_mode),
            linear_speed_mps=float(self.command.linear_speed_mps),
            steering_angle_rad=float(self.command.steering_angle_rad),
            spin_speed_radps=float(self.command.spin_speed_radps),
            joint_positions=self._joint_targets_to_positions(self.targets),
            steering_angles=self._steering_angles_from_targets(self.targets),
            wheel_speeds=self._wheel_speeds_from_targets(self.targets),
        )
        if stage is not None:
            self._write_state_to_stage(stage)
        return self.state

    def get_state(self) -> RangerMiniState:
        return self.state

    def robot_state_payload(self) -> dict[str, Any]:
        return {
            "base_pose": list(self.state.base_pose) if self.state.base_pose else None,
            "joint_names": list(self.state.joint_names),
            "joint_positions": list(self.state.joint_positions),
            "extras": {
                "ranger_mini": {
                    "motion_mode": int(self.state.motion_mode),
                    "steering_angles": list(self.state.steering_angles),
                    "wheel_speeds": list(self.state.wheel_speeds),
                    "battery": {
                        "voltage": float(self.state.battery_voltage),
                        "soc": float(self.state.battery_soc),
                    },
                    "estop": bool(self.state.estop),
                    "has_error": bool(self.state.has_error),
                }
            },
        }

    def ros_messages(self, *, base_frame: str = "base_link", odom_frame: str = "odom") -> dict[str, dict[str, Any]]:
        return self.ros.state_messages(self.state, base_frame=base_frame, odom_frame=odom_frame)

    def apply_cmd_vel(self, twist: Any) -> None:
        converted = self.ros.command_from_twist(twist, current_mode=int(self.command.motion_mode))
        self.command.motion_mode = int(converted.motion_mode)
        self.command.linear_speed_mps = float(converted.linear_speed_mps)
        self.command.steering_angle_rad = float(converted.steering_angle_rad)
        self.command.spin_speed_radps = float(converted.spin_speed_radps)

    def _spawn_robot(
        self,
        stage: Any,
        *,
        translation: tuple[float, float, float],
        use_reference: bool | None,
    ) -> None:
        resolved_use_reference = True if use_reference is None else bool(use_reference)
        _log_debug(
            f"_spawn_robot prim_path={self.prim_path} translation={translation} "
            f"use_reference={resolved_use_reference}"
        )
        if resolved_use_reference:
            if self._spawn_reference(stage, translation=translation):
                _log_debug(f"_spawn_robot succeeded via USD reference prim_path={self.prim_path}")
                return
            _log_debug(f"_spawn_robot reference fallback engaged prim_path={self.prim_path}")
        self._spawn_placeholder(stage, translation=translation)
        _log_debug(f"_spawn_robot procedural spawn finished prim_path={self.prim_path}")

    def _spawn_reference(self, stage: Any, *, translation: tuple[float, float, float]) -> bool:
        try:
            from pxr import Gf, UsdGeom
        except Exception:
            _log_debug("_spawn_reference pxr import unavailable")
            return False

        root_prim = stage.GetPrimAtPath(self.prim_path)
        if not root_prim or not root_prim.IsValid():
            root_prim = stage.DefinePrim(self.prim_path, "Xform")
            asset_abs = (Path(__file__).resolve().parents[3] / self.asset_path).resolve()
            if not asset_abs.exists():
                _log_debug(f"_spawn_reference asset missing path={asset_abs}")
                return False
            refs = root_prim.GetReferences()
            _log_debug(f"_spawn_reference adding reference asset={asset_abs}")
            refs.AddReference(assetPath=str(asset_abs))

        xformable = UsdGeom.Xformable(root_prim)
        if xformable:
            translate_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeTranslate]
            op = translate_ops[0] if translate_ops else xformable.AddTranslateOp()
            op.Set(Gf.Vec3d(*translation))
        _log_debug(f"_spawn_reference success prim_path={self.prim_path}")
        return True

    def _spawn_placeholder(self, stage: Any, *, translation: tuple[float, float, float]) -> None:
        try:
            from pxr import Gf, Sdf, UsdGeom
        except Exception:
            _log_debug("_spawn_placeholder pxr import unavailable")
            return

        root = stage.GetPrimAtPath(self.prim_path)
        if not root or not root.IsValid():
            root = stage.DefinePrim(self.prim_path, "Xform")
            _log_debug(f"_spawn_placeholder defined root prim_path={self.prim_path}")
        else:
            _log_debug(f"_spawn_placeholder reusing root prim_path={self.prim_path}")
        self._ensure_root_metadata(root, stage)
        self._set_root_transform(root, translation=translation)

        base_path = f"{self.prim_path}/base_link"
        base_link = stage.GetPrimAtPath(base_path)
        if not base_link or not base_link.IsValid():
            base_link = stage.DefinePrim(base_path, "Xform")

        mounts = {
            "imu_link": (0.0, 0.0, 0.33),
            "lidar_link": (0.20, 0.0, 0.35),
            "camera_front_link": (0.31, 0.0, 0.30),
        }
        for mount_name, mount_translation in mounts.items():
            mount = stage.GetPrimAtPath(f"{base_path}/{mount_name}")
            if not mount or not mount.IsValid():
                mount = stage.DefinePrim(f"{base_path}/{mount_name}", "Xform")
            self._set_xform_translation(mount, mount_translation)

        visuals = stage.GetPrimAtPath(f"{base_path}/visuals")
        if not visuals or not visuals.IsValid():
            visuals = stage.DefinePrim(f"{base_path}/visuals", "Scope")
        self._ensure_cube(
            stage,
            f"{base_path}/visuals/deck_mesh",
            translation=(0.0, 0.0, 0.255),
            scale=(0.62, 0.42, 0.10),
            color=(0.17, 0.18, 0.20),
        )
        self._ensure_cube(
            stage,
            f"{base_path}/visuals/battery_box_mesh",
            translation=(0.0, 0.0, 0.155),
            scale=(0.50, 0.36, 0.10),
            color=(0.11, 0.11, 0.12),
        )
        self._ensure_cube(
            stage,
            f"{base_path}/visuals/rear_panel_mesh",
            translation=(-0.325, 0.0, 0.20),
            scale=(0.03, 0.40, 0.11),
            color=(0.28, 0.29, 0.31),
        )

        wheel_positions = {
            "fr": (self.params.wheelbase_m / 2.0, -self.params.track_width_m / 2.0, self.params.wheel_radius_m),
            "fl": (self.params.wheelbase_m / 2.0, self.params.track_width_m / 2.0, self.params.wheel_radius_m),
            "rr": (-self.params.wheelbase_m / 2.0, -self.params.track_width_m / 2.0, self.params.wheel_radius_m),
            "rl": (-self.params.wheelbase_m / 2.0, self.params.track_width_m / 2.0, self.params.wheel_radius_m),
        }
        for corner, position in wheel_positions.items():
            steer_path = f"{base_path}/{corner}_steer_link"
            wheel_path = f"{steer_path}/{corner}_wheel_link"
            steer = stage.GetPrimAtPath(steer_path)
            if not steer or not steer.IsValid():
                steer = stage.DefinePrim(steer_path, "Xform")
            self._set_xform_translation(steer, position)
            self._ensure_rotate_op(steer, "Z", 0.0)
            self._ensure_cube(
                stage,
                f"{steer_path}/{corner}_steer_visual",
                translation=(0.0, 0.0, 0.015),
                scale=(0.06, 0.06, 0.06),
                color=(0.26, 0.27, 0.29),
            )

            wheel = stage.GetPrimAtPath(wheel_path)
            if not wheel or not wheel.IsValid():
                wheel = stage.DefinePrim(wheel_path, "Xform")
            self._ensure_rotate_op(wheel, "Y", 0.0)
            self._ensure_cylinder(
                stage,
                f"{wheel_path}/{corner}_wheel_visual",
                radius=self.params.wheel_radius_m,
                height=self.params.wheel_width_m,
                axis="Y",
                color=(0.08, 0.08, 0.08),
            )

        for joint_name in (
            "fr_steer_joint",
            "fl_steer_joint",
            "rr_steer_joint",
            "rl_steer_joint",
            "fr_wheel_joint",
            "fl_wheel_joint",
            "rr_wheel_joint",
            "rl_wheel_joint",
        ):
            joint_prim = stage.GetPrimAtPath(f"{self.prim_path}/{joint_name}")
            if not joint_prim or not joint_prim.IsValid():
                joint_prim = stage.DefinePrim(f"{self.prim_path}/{joint_name}", "Xform")
            attr_name = "drive:angular:targetPosition" if "steer" in joint_name else "drive:angular:targetVelocity"
            self._ensure_attr(joint_prim, attr_name, Sdf.ValueTypeNames.Double, 0.0)
        _log_debug(f"_spawn_placeholder completed prim_path={self.prim_path}")

    def _write_state_to_stage(self, stage: Any) -> None:
        root = stage.GetPrimAtPath(self.prim_path)
        if not root or not root.IsValid():
            return
        translation = self._pose_translation()
        self._set_root_transform(root, translation=translation)
        self._set_attr(root, "robomituba:robotName", "ranger_mini_v3")
        self._set_attr(root, "robomituba:jointNames", list(self.state.joint_names))
        self._set_attr(root, "robomituba:jointPositions", list(self.state.joint_positions))
        self._set_attr(root, "robomituba:steeringAngles", list(self.state.steering_angles))
        self._set_attr(root, "robomituba:wheelSpeeds", list(self.state.wheel_speeds))
        self._set_attr(root, "robomituba:motionMode", int(self.state.motion_mode))
        self._set_attr(root, "robomituba:batteryVoltage", float(self.state.battery_voltage))
        self._set_attr(root, "robomituba:batterySoc", float(self.state.battery_soc))
        self._set_attr(root, "robomituba:estop", bool(self.state.estop))
        self._set_attr(root, "robomituba:hasError", bool(self.state.has_error))
        self._set_attr(root, "robomituba:headingRad", float(self.heading_rad))

        for joint_name in ("fr_steer_joint", "fl_steer_joint", "rr_steer_joint", "rl_steer_joint"):
            joint = stage.GetPrimAtPath(f"{self.prim_path}/{joint_name}")
            if joint and joint.IsValid():
                target = getattr(self.targets, joint_name.replace("_joint", ""))
                self._set_attr(joint, "drive:angular:targetPosition", float(target))
        for joint_name in ("fr_wheel_joint", "fl_wheel_joint", "rr_wheel_joint", "rl_wheel_joint"):
            joint = stage.GetPrimAtPath(f"{self.prim_path}/{joint_name}")
            if joint and joint.IsValid():
                target = getattr(self.targets, joint_name.replace("_joint", ""))
                self._set_attr(joint, "drive:angular:targetVelocity", float(target))
        self._apply_visual_pose(stage)

    def _set_attr(self, prim: Any, name: str, value: Any) -> None:
        attr = prim.GetAttribute(name)
        if not attr:
            return
        attr.Set(value)

    def _pose_translation(self) -> tuple[float, float, float]:
        base_pose = self.state.base_pose or _identity_pose(0.0, 0.0, self.params.wheel_radius_m)
        return (float(base_pose[12]), float(base_pose[13]), float(base_pose[14]))

    def _integrate_base_motion(self, dt: float) -> None:
        if dt <= 0:
            return
        x, y, z = self._pose_translation()
        mode = int(self.command.motion_mode)
        if mode == int(RangerMiniMotionMode.SPIN):
            self.heading_rad += float(self.command.spin_speed_radps) * dt
        elif mode == int(RangerMiniMotionMode.OBLIQUE):
            travel_heading = self.heading_rad + float(self.command.steering_angle_rad)
            speed = float(self.command.linear_speed_mps)
            x += speed * dt * cos(travel_heading)
            y += speed * dt * sin(travel_heading)
        elif mode == int(RangerMiniMotionMode.ACKERMANN):
            speed = float(self.command.linear_speed_mps)
            steer = float(self.command.steering_angle_rad)
            if abs(steer) > 1e-6:
                self.heading_rad += (2.0 * speed * tan(steer) / max(self.params.wheelbase_m, 1e-6)) * dt
            x += speed * dt * cos(self.heading_rad)
            y += speed * dt * sin(self.heading_rad)
        self.state.base_pose = _identity_pose(x, y, z)

    def _integrate_wheel_rotation(self, dt: float) -> None:
        if dt <= 0:
            return
        for link_name, wheel_speed in zip(
            ("fr_wheel_link", "fl_wheel_link", "rr_wheel_link", "rl_wheel_link"),
            self._wheel_speeds_from_targets(self.targets),
            strict=False,
        ):
            self._wheel_rotation_rad[link_name] += float(wheel_speed) * dt

    def _apply_visual_pose(self, stage: Any) -> None:
        try:
            from pxr import UsdGeom
        except Exception:
            return

        steer_values = {
            "fr_steer_link": self.targets.fr_steer,
            "fl_steer_link": self.targets.fl_steer,
            "rr_steer_link": self.targets.rr_steer,
            "rl_steer_link": self.targets.rl_steer,
        }
        for link_name, angle in steer_values.items():
            prim = stage.GetPrimAtPath(f"{self.prim_path}/base_link/{link_name}")
            if prim and prim.IsValid():
                self._set_rotate_op(UsdGeom.Xformable(prim), "Z", degrees(float(angle)))

        for link_name, angle in self._wheel_rotation_rad.items():
            prim = stage.GetPrimAtPath(f"{self.prim_path}/base_link/{link_name[:2]}_steer_link/{link_name}")
            if prim and prim.IsValid():
                self._set_rotate_op(UsdGeom.Xformable(prim), "Y", degrees(float(angle)))

    def _set_root_transform(self, root: Any, *, translation: tuple[float, float, float]) -> None:
        try:
            from pxr import Gf, UsdGeom
        except Exception:
            return
        xformable = UsdGeom.Xformable(root)
        translate_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeTranslate]
        translate_op = translate_ops[0] if translate_ops else xformable.AddTranslateOp()
        translate_op.Set(Gf.Vec3d(*translation))
        self._set_rotate_op(xformable, "Z", degrees(self.heading_rad))

    def _ensure_root_metadata(self, root: Any, stage: Any) -> None:
        try:
            from pxr import Sdf
        except Exception:
            return
        self._ensure_attr(root, "robomituba:robotName", Sdf.ValueTypeNames.String, "ranger_mini_v3")
        self._ensure_attr(root, "robomituba:jointNames", Sdf.ValueTypeNames.StringArray, list(JOINT_ORDER))
        self._ensure_attr(root, "robomituba:jointPositions", Sdf.ValueTypeNames.DoubleArray, [0.0] * 8)
        self._ensure_attr(root, "robomituba:steeringAngles", Sdf.ValueTypeNames.DoubleArray, [0.0] * 4)
        self._ensure_attr(root, "robomituba:wheelSpeeds", Sdf.ValueTypeNames.DoubleArray, [0.0] * 4)
        self._ensure_attr(root, "robomituba:motionMode", Sdf.ValueTypeNames.Int, int(RangerMiniMotionMode.ACKERMANN))
        self._ensure_attr(root, "robomituba:batteryVoltage", Sdf.ValueTypeNames.Double, 48.0)
        self._ensure_attr(root, "robomituba:batterySoc", Sdf.ValueTypeNames.Double, 1.0)
        self._ensure_attr(root, "robomituba:estop", Sdf.ValueTypeNames.Bool, False)
        self._ensure_attr(root, "robomituba:hasError", Sdf.ValueTypeNames.Bool, False)
        self._ensure_attr(root, "robomituba:headingRad", Sdf.ValueTypeNames.Double, 0.0)
        self._ensure_attr(root, "robomituba:spawnBackend", Sdf.ValueTypeNames.String, "procedural")

    def _ensure_attr(self, prim: Any, name: str, value_type: Any, default: Any) -> None:
        attr = prim.GetAttribute(name)
        if not attr:
            attr = prim.CreateAttribute(name, value_type, custom=True)
        if attr.Get() is None:
            attr.Set(default)

    def _ensure_cube(
        self,
        stage: Any,
        prim_path: str,
        *,
        translation: tuple[float, float, float],
        scale: tuple[float, float, float],
        color: tuple[float, float, float],
    ) -> None:
        try:
            from pxr import Gf, UsdGeom
        except Exception:
            return
        cube = UsdGeom.Cube.Define(stage, prim_path)
        xformable = UsdGeom.Xformable(cube.GetPrim())
        translate_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeTranslate]
        translate_op = translate_ops[0] if translate_ops else xformable.AddTranslateOp()
        translate_op.Set(Gf.Vec3d(*translation))
        scale_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeScale]
        scale_op = scale_ops[0] if scale_ops else xformable.AddScaleOp()
        scale_op.Set(Gf.Vec3f(*scale))
        cube.CreateDisplayColorAttr().Set([Gf.Vec3f(*color)])

    def _ensure_cylinder(
        self,
        stage: Any,
        prim_path: str,
        *,
        radius: float,
        height: float,
        axis: str,
        color: tuple[float, float, float],
    ) -> None:
        try:
            from pxr import Gf, UsdGeom
        except Exception:
            return
        cylinder = UsdGeom.Cylinder.Define(stage, prim_path)
        cylinder.CreateRadiusAttr(float(radius))
        cylinder.CreateHeightAttr(float(height))
        cylinder.CreateAxisAttr(str(axis))
        cylinder.CreateDisplayColorAttr().Set([Gf.Vec3f(*color)])

    def _set_xform_translation(self, prim: Any, translation: tuple[float, float, float]) -> None:
        try:
            from pxr import Gf, UsdGeom
        except Exception:
            return
        xformable = UsdGeom.Xformable(prim)
        translate_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == UsdGeom.XformOp.TypeTranslate]
        translate_op = translate_ops[0] if translate_ops else xformable.AddTranslateOp()
        translate_op.Set(Gf.Vec3d(*translation))

    def _ensure_rotate_op(self, prim: Any, axis: str, value_degrees: float) -> None:
        try:
            from pxr import UsdGeom
        except Exception:
            return
        self._set_rotate_op(UsdGeom.Xformable(prim), axis, value_degrees)

    def _set_rotate_op(self, xformable: Any, axis: str, value_degrees: float) -> None:
        try:
            from pxr import UsdGeom
        except Exception:
            return
        attr_name = f"xformOp:rotate{axis.upper()}"
        op_type = getattr(UsdGeom.XformOp, f"TypeRotate{axis.upper()}")
        rotate_ops = [op for op in xformable.GetOrderedXformOps() if op.GetOpType() == op_type]
        rotate_op = rotate_ops[0] if rotate_ops else getattr(xformable, f"AddRotate{axis.upper()}Op")()
        rotate_op.Set(float(value_degrees))

    def _joint_targets_to_positions(self, targets: JointTargets) -> list[float]:
        return [
            float(targets.fr_steer),
            float(targets.fr_wheel),
            float(targets.fl_steer),
            float(targets.fl_wheel),
            float(targets.rr_steer),
            float(targets.rr_wheel),
            float(targets.rl_steer),
            float(targets.rl_wheel),
        ]

    def _steering_angles_from_targets(self, targets: JointTargets) -> list[float]:
        return [float(targets.fr_steer), float(targets.fl_steer), float(targets.rr_steer), float(targets.rl_steer)]

    def _wheel_speeds_from_targets(self, targets: JointTargets) -> list[float]:
        return [float(targets.fr_wheel), float(targets.fl_wheel), float(targets.rr_wheel), float(targets.rl_wheel)]
