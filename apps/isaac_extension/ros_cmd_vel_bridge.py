"""Optional ROS2 cmd_vel bridge for Ranger Mini PhysX wheel drives."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass
class CmdVel:
    linear_x: float = 0.0
    angular_z: float = 0.0


class RangerMiniCmdVelBridge:
    def __init__(self, stage: Any, robot_prim_path: str, *, topic: str = "/cmd_vel", node_name: str = "robomituba_ranger_cmd_vel") -> None:
        self.stage = stage
        self.robot_prim_path = robot_prim_path
        self.topic = topic
        self.node_name = node_name
        self._lock = Lock()
        self._last_cmd = CmdVel()
        self._rclpy: Any = None
        self._node: Any = None
        self._subscription: Any = None
        self._update_subscription: Any = None
        self._physics_subscription: Any = None
        self._articulation_handle: Any = None
        self.last_error: str | None = None

    def start(self) -> dict[str, Any]:
        try:
            import rclpy  # type: ignore
            from geometry_msgs.msg import Twist  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "ROS2 Python packages are unavailable inside this Isaac process. "
                "Enable Isaac ROS2 bridge/rclpy, or call drive_ranger_mini_cmd_vel() manually."
            ) from exc

        try:
            import omni.kit.app  # type: ignore
            import omni.physx  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"Isaac update/physics stream is unavailable: {exc}") from exc

        if not rclpy.ok():
            rclpy.init(args=None)
        self._rclpy = rclpy
        self._node = rclpy.create_node(self.node_name)
        self._subscription = self._node.create_subscription(Twist, self.topic, self._on_twist, 10)
        stream = omni.kit.app.get_app().get_update_event_stream()
        self._update_subscription = stream.create_subscription_to_pop(self._on_update, name="robomituba_ranger_cmd_vel")
        self._physics_subscription = omni.physx.get_physx_interface().subscribe_physics_step_events(self._on_physics_step)
        return {
            "robot_prim_path": self.robot_prim_path,
            "topic": self.topic,
            "node_name": self.node_name,
            "drive_loop": "physics_step",
            "last_error": self.last_error,
        }

    def stop(self) -> None:
        self._update_subscription = None
        self._physics_subscription = None
        self._articulation_handle = None
        if self._node is not None and self._subscription is not None:
            try:
                self._node.destroy_subscription(self._subscription)
            except Exception:
                pass
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
        self._subscription = None
        self._node = None

    def _on_twist(self, msg: Any) -> None:
        with self._lock:
            self._last_cmd = CmdVel(
                linear_x=float(getattr(getattr(msg, "linear", msg), "x", 0.0)),
                angular_z=float(getattr(getattr(msg, "angular", msg), "z", 0.0)),
            )

    def _on_update(self, _event: Any) -> None:
        if self._rclpy is None or self._node is None:
            return
        self._rclpy.spin_once(self._node, timeout_sec=0.0)

    def _on_physics_step(self, _step_size: float) -> None:
        if self._rclpy is None or self._node is None:
            return
        with self._lock:
            cmd = CmdVel(self._last_cmd.linear_x, self._last_cmd.angular_z)
        try:
            try:
                from isaac_extension.ranger_mini_stage import bind_ranger_mini_articulation, drive_ranger_mini_cmd_vel
            except ImportError:  # pragma: no cover - Isaac runtime fallback
                from ranger_mini_stage import bind_ranger_mini_articulation, drive_ranger_mini_cmd_vel

            if self._articulation_handle is None:
                self._articulation_handle = bind_ranger_mini_articulation(self.stage, self.robot_prim_path)
            drive_ranger_mini_cmd_vel(
                self.stage,
                self.robot_prim_path,
                linear_x=cmd.linear_x,
                angular_z=cmd.angular_z,
                articulation_handle=self._articulation_handle,
            )
            self.last_error = None
        except Exception as exc:
            self._articulation_handle = None
            self.last_error = str(exc)
            line = f"[RangerMiniCmdVelBridge] physics-step drive error: {exc}"
            try:
                import carb  # type: ignore

                carb.log_error(line)
            except Exception:
                pass
            print(line)


_ACTIVE_BRIDGE: RangerMiniCmdVelBridge | None = None


def start_cmd_vel_bridge(stage: Any, robot_prim_path: str, *, topic: str = "/cmd_vel") -> dict[str, Any]:
    global _ACTIVE_BRIDGE
    if _ACTIVE_BRIDGE is not None:
        _ACTIVE_BRIDGE.stop()
    _ACTIVE_BRIDGE = RangerMiniCmdVelBridge(stage, robot_prim_path, topic=topic)
    return _ACTIVE_BRIDGE.start()


def stop_cmd_vel_bridge() -> None:
    global _ACTIVE_BRIDGE
    if _ACTIVE_BRIDGE is not None:
        _ACTIVE_BRIDGE.stop()
        _ACTIVE_BRIDGE = None
