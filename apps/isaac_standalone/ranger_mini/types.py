from __future__ import annotations

from dataclasses import dataclass, field

from .constants import RangerMiniMotionMode


@dataclass
class RangerMiniCommand:
    motion_mode: int = int(RangerMiniMotionMode.ACKERMANN)
    linear_speed_mps: float = 0.0
    steering_angle_rad: float = 0.0
    spin_speed_radps: float = 0.0


@dataclass
class JointTargets:
    fr_steer: float
    fr_wheel: float
    fl_steer: float
    fl_wheel: float
    rr_steer: float
    rr_wheel: float
    rl_steer: float
    rl_wheel: float


@dataclass
class RangerMiniState:
    motion_mode: int = int(RangerMiniMotionMode.ACKERMANN)
    linear_speed_mps: float = 0.0
    steering_angle_rad: float = 0.0
    spin_speed_radps: float = 0.0
    joint_names: list[str] = field(default_factory=list)
    joint_positions: list[float] = field(default_factory=list)
    steering_angles: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    wheel_speeds: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    battery_voltage: float = 48.0
    battery_soc: float = 1.0
    estop: bool = False
    has_error: bool = False
    base_pose: list[float] | None = None
