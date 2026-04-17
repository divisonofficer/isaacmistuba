from __future__ import annotations

from math import atan2, pi, sqrt, tan

from .constants import RangerMiniMotionMode, RangerMiniParams
from .types import JointTargets, RangerMiniCommand


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def saturate_command(command: RangerMiniCommand, params: RangerMiniParams) -> RangerMiniCommand:
    mode = int(command.motion_mode)
    linear_speed = float(command.linear_speed_mps)
    steering_angle = float(command.steering_angle_rad)
    spin_speed = float(command.spin_speed_radps)

    if mode == int(RangerMiniMotionMode.ACKERMANN):
        steering_angle = _clip(steering_angle, -params.max_ackermann_steer_rad, params.max_ackermann_steer_rad)
        speed_limit = 1.0 if abs(steering_angle) > 0.349 else params.max_linear_speed_mps
        linear_speed = _clip(linear_speed, -speed_limit, speed_limit)
        spin_speed = 0.0
    elif mode == int(RangerMiniMotionMode.OBLIQUE):
        steering_angle = _clip(steering_angle, -params.max_oblique_steer_rad, params.max_oblique_steer_rad)
        linear_speed = _clip(linear_speed, -params.max_linear_speed_mps, params.max_linear_speed_mps)
        spin_speed = 0.0
    elif mode == int(RangerMiniMotionMode.SPIN):
        linear_speed = 0.0
        steering_angle = 0.0
        spin_speed = _clip(spin_speed, -params.max_spin_speed_radps, params.max_spin_speed_radps)
    else:
        mode = int(RangerMiniMotionMode.PARKING)
        linear_speed = 0.0
        steering_angle = 0.0
        spin_speed = 0.0

    return RangerMiniCommand(
        motion_mode=mode,
        linear_speed_mps=linear_speed,
        steering_angle_rad=steering_angle,
        spin_speed_radps=spin_speed,
    )


def compute_joint_targets(command: RangerMiniCommand, params: RangerMiniParams) -> JointTargets:
    command = saturate_command(command, params)
    wheel_radius = params.wheel_radius_m
    wheelbase = params.wheelbase_m
    track = params.track_width_m

    if command.motion_mode == int(RangerMiniMotionMode.ACKERMANN):
        delta = command.steering_angle_rad
        if abs(delta) < 1e-6:
            v_left = command.linear_speed_mps
            v_right = command.linear_speed_mps
        else:
            radius = wheelbase / (2.0 * tan(abs(delta)))
            inner = command.linear_speed_mps * (radius - track / 2.0) / radius
            outer = command.linear_speed_mps * (radius + track / 2.0) / radius
            if delta > 0.0:
                v_left, v_right = inner, outer
            else:
                v_left, v_right = outer, inner
        return JointTargets(
            fr_steer=delta,
            fr_wheel=v_right / wheel_radius,
            fl_steer=delta,
            fl_wheel=v_left / wheel_radius,
            rr_steer=-delta,
            rr_wheel=v_right / wheel_radius,
            rl_steer=-delta,
            rl_wheel=v_left / wheel_radius,
        )

    if command.motion_mode == int(RangerMiniMotionMode.OBLIQUE):
        wheel_speed = command.linear_speed_mps / wheel_radius
        return JointTargets(
            fr_steer=command.steering_angle_rad,
            fr_wheel=wheel_speed,
            fl_steer=command.steering_angle_rad,
            fl_wheel=wheel_speed,
            rr_steer=command.steering_angle_rad,
            rr_wheel=wheel_speed,
            rl_steer=command.steering_angle_rad,
            rl_wheel=wheel_speed,
        )

    if command.motion_mode == int(RangerMiniMotionMode.SPIN):
        spin_angle = atan2(wheelbase, track)
        tangent_radius = sqrt((wheelbase / 2.0) ** 2 + (track / 2.0) ** 2)
        wheel_speed = (command.spin_speed_radps * tangent_radius) / wheel_radius
        return JointTargets(
            fr_steer=-spin_angle,
            fr_wheel=-wheel_speed,
            fl_steer=spin_angle,
            fl_wheel=wheel_speed,
            rr_steer=spin_angle,
            rr_wheel=wheel_speed,
            rl_steer=-spin_angle,
            rl_wheel=-wheel_speed,
        )

    park_angle = pi / 4.0
    return JointTargets(
        fr_steer=-park_angle,
        fr_wheel=0.0,
        fl_steer=park_angle,
        fl_wheel=0.0,
        rr_steer=park_angle,
        rr_wheel=0.0,
        rl_steer=-park_angle,
        rl_wheel=0.0,
    )
