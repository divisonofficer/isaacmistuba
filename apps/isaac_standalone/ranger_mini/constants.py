from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class RangerMiniMotionMode(IntEnum):
    ACKERMANN = 0
    OBLIQUE = 1
    SPIN = 2
    PARKING = 3


JOINT_ORDER = [
    "fr_steer",
    "fr_wheel",
    "fl_steer",
    "fl_wheel",
    "rr_steer",
    "rr_wheel",
    "rl_steer",
    "rl_wheel",
]


@dataclass(frozen=True)
class RangerMiniParams:
    asset_repo_path: str = "assets/robots/ranger_mini_v3/ranger_mini_v3.usda"
    prim_path: str = "/World/RangerMini"
    chassis_length_m: float = 0.72
    chassis_width_m: float = 0.50
    chassis_height_m: float = 0.345
    wheelbase_m: float = 0.494
    track_width_m: float = 0.364
    ground_clearance_m: float = 0.105
    wheel_radius_m: float = 0.10
    wheel_width_m: float = 0.055
    total_mass_kg: float = 75.0
    base_mass_kg: float = 63.0
    steer_mass_kg: float = 2.0
    wheel_mass_kg: float = 1.0
    max_linear_speed_mps: float = 1.5
    max_manual_linear_speed_mps: float = 2.0
    max_ackermann_steer_rad: float = 0.6981
    max_oblique_steer_rad: float = 1.57
    max_spin_speed_radps: float = 3.259
    max_steer_joint_limit_rad: float = 1.57
    steering_drive_stiffness: float = 4000.0
    steering_drive_damping: float = 200.0
    steering_drive_max_force: float = 300.0
    wheel_drive_stiffness: float = 0.0
    wheel_drive_damping: float = 100.0
    wheel_drive_max_force: float = 200.0
