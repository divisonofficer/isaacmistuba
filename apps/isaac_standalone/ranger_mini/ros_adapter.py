from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .constants import RangerMiniMotionMode
from .types import RangerMiniCommand, RangerMiniState


class RangerMiniRosAdapter:
    """Minimal ROS2-compatible adapter without depending on ROS Python packages."""

    def command_from_twist(self, twist: Any, *, current_mode: int = int(RangerMiniMotionMode.ACKERMANN)) -> RangerMiniCommand:
        linear = getattr(getattr(twist, "linear", twist), "x", 0.0)
        angular = getattr(getattr(twist, "angular", twist), "z", 0.0)
        if int(current_mode) == int(RangerMiniMotionMode.SPIN):
            return RangerMiniCommand(motion_mode=current_mode, spin_speed_radps=float(angular))
        return RangerMiniCommand(
            motion_mode=current_mode,
            linear_speed_mps=float(linear),
            steering_angle_rad=float(angular),
        )

    def state_messages(self, state: RangerMiniState, *, base_frame: str = "base_link", odom_frame: str = "odom") -> dict[str, dict[str, Any]]:
        ranger = {
            "motion_mode": int(state.motion_mode),
            "steering_angles": list(state.steering_angles),
            "wheel_speeds": list(state.wheel_speeds),
            "battery": {
                "voltage": float(state.battery_voltage),
                "soc": float(state.battery_soc),
            },
            "estop": bool(state.estop),
            "has_error": bool(state.has_error),
        }
        return {
            "/system_state": {
                "control_mode": 0,
                "motion_mode": int(state.motion_mode),
                "battery_voltage": float(state.battery_voltage),
                "error_code": 1 if state.has_error else 0,
                "vehicle_state": 1 if state.estop else 0,
            },
            "/motion_state": {
                "motion_mode": int(state.motion_mode),
                "linear_velocity": float(state.linear_speed_mps),
                "angular_velocity": float(state.spin_speed_radps),
                "steering_angle": float(state.steering_angle_rad),
            },
            "/actuator_state": {
                "joint_names": list(state.joint_names),
                "joint_positions": list(state.joint_positions),
                "steering_angles": list(state.steering_angles),
                "wheel_speeds": list(state.wheel_speeds),
            },
            "/battery_state": {
                "voltage": float(state.battery_voltage),
                "percentage": float(state.battery_soc),
                "power_supply_status": 1,
            },
            "/odom": {
                "header": {"frame_id": odom_frame},
                "child_frame_id": base_frame,
                "twist": {
                    "linear": {"x": float(state.linear_speed_mps), "y": 0.0, "z": 0.0},
                    "angular": {"x": 0.0, "y": 0.0, "z": float(state.spin_speed_radps)},
                },
                "pose_matrix": list(state.base_pose) if state.base_pose else None,
                "ranger_mini": ranger,
            },
            "/ranger/state": asdict(state),
        }
