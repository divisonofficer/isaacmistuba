"""Ranger Mini RoboMitsuba sensor discovery and render helpers."""
from __future__ import annotations

import datetime as _dt
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROBOT_SENSOR_TYPES = {"rgb_camera", "nir_camera", "polar_camera", "lidar_3d"}
DEFAULT_SENSOR_MODALITIES = {
    "rgb_camera": ["rgb"],
    "nir_camera": ["nir_intensity"],
    "polar_camera": ["polar_rgb_preview", "s1_over_s0", "s2_over_s0", "dop", "aolp"],
    "lidar_3d": ["lidar_point_cloud"],
}


def _require_pxr():
    from pxr import Gf, Sdf, Usd, UsdGeom  # type: ignore

    return Gf, Sdf, Usd, UsdGeom


def _attr_value(prim: Any, name: str, default: Any = None) -> Any:
    attr = prim.GetAttribute(name)
    if not attr:
        return default
    value = attr.Get()
    return default if value is None else value


def _ensure_attr(prim: Any, name: str, value_type: Any, value: Any) -> None:
    attr = prim.GetAttribute(name)
    if not attr:
        attr = prim.CreateAttribute(name, value_type, custom=True)
    attr.Set(value)


def _matrix_to_list(matrix: Any) -> list[float]:
    candidate = np.asarray(matrix, dtype=np.float32)
    if candidate.shape == (16,):
        candidate = candidate.reshape(4, 4)
    if candidate.shape != (4, 4):
        raise ValueError(f"Expected 4x4 matrix, got {candidate.shape}")
    last_col = candidate[:3, 3]
    last_row = candidate[3, :3]
    if float(np.linalg.norm(last_row)) > max(1e-5, float(np.linalg.norm(last_col)) * 2.0):
        candidate = candidate.T
    return candidate.reshape(-1).astype(float).tolist()


def _fov_from_camera(camera: Any) -> float:
    import math

    focal_length = float(camera.GetFocalLengthAttr().Get() or 18.0)
    aperture = float(camera.GetHorizontalApertureAttr().Get() or 20.955)
    return float(2.0 * math.degrees(math.atan(aperture / max(2.0 * focal_length, 1e-6))))


def _as_str_list(value: Any, default: Sequence[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except Exception:
        return list(default)


def _as_int_list(value: Any, default: Sequence[int]) -> list[int]:
    if value is None:
        return list(default)
    try:
        return [int(item) for item in value]
    except Exception:
        return list(default)


def _sensor_path(robot_prim_path: str, sensor_id: str) -> str:
    mapping = {
        "rgb_front": f"{robot_prim_path}/base_link/camera_front_link/rgb_camera",
        "nir_front": f"{robot_prim_path}/base_link/camera_front_link/nir_camera",
        "polar_front": f"{robot_prim_path}/base_link/camera_front_link/polar_camera",
        "lidar_top": f"{robot_prim_path}/base_link/lidar_link/lidar_3d",
    }
    return mapping.get(sensor_id, sensor_id if sensor_id.startswith("/") else f"{robot_prim_path}/{sensor_id}")


def _safe_prim_name(value: Any) -> str:
    raw = str(value or "").strip() or "sensor"
    chars = [ch if ch.isalnum() or ch == "_" else "_" for ch in raw]
    safe = "".join(chars).strip("_") or "sensor"
    if safe[0].isdigit():
        safe = f"sensor_{safe}"
    return safe


def _resolve_ranger_robot_prim_path(stage: Any, robot_prim_path: str) -> str:
    def is_ranger(prim: Any) -> bool:
        if not prim or not prim.IsValid():
            return False
        name = prim.GetName().lower()
        robot_name = str(_attr_value(prim, "robomituba:robotName", "") or "").lower()
        return robot_name == "ranger_mini_v3" or "rangermini" in name or "ranger_mini" in name

    candidate = stage.GetPrimAtPath(robot_prim_path)
    if is_ranger(candidate):
        return str(candidate.GetPath())
    if candidate and candidate.IsValid():
        try:
            from pxr import Usd  # type: ignore

            for prim in Usd.PrimRange(candidate):
                if is_ranger(prim):
                    return str(prim.GetPath())
        except Exception:
            pass
    try:
        for prim in stage.Traverse():
            if is_ranger(prim):
                return str(prim.GetPath())
    except Exception:
        pass
    raise RuntimeError(f"No RangerMini robot found under {robot_prim_path}.")


def _sequence_float(value: Any, default: Sequence[float], *, length: int) -> list[float]:
    try:
        result = [float(item) for item in value]
        if len(result) == length:
            return result
    except Exception:
        pass
    return [float(item) for item in default]


def _rig_sensor_to_attr_spec(sensor: Mapping[str, Any]) -> dict[str, Any]:
    sensor_type = str(sensor.get("sensor_type") or "rgb_camera")
    intrinsics = sensor.get("intrinsics") if isinstance(sensor.get("intrinsics"), Mapping) else {}
    render = sensor.get("render") if isinstance(sensor.get("render"), Mapping) else {}
    modalities = _as_str_list(sensor.get("modalities"), DEFAULT_SENSOR_MODALITIES.get(sensor_type, ["rgb"]))
    spec: dict[str, Any] = {
        "id": str(sensor.get("sensor_id") or "sensor"),
        "type": sensor_type,
        "modalities": modalities,
        "resolution": _as_int_list(intrinsics.get("resolution"), [1280, 720]),
        "path_spp": int(render.get("path_spp", 1 if sensor_type == "lidar_3d" else 4096)),
        "aov_spp": int(render.get("aov_spp", 1 if sensor_type == "lidar_3d" else 16)),
        "polar_spp": int(render.get("polar_spp", 1 if sensor_type == "lidar_3d" else 256)),
    }
    if render.get("samples_per_pass") not in (None, ""):
        spec["samples_per_pass"] = int(render.get("samples_per_pass"))
    if sensor_type == "nir_camera":
        nir = sensor.get("nir") if isinstance(sensor.get("nir"), Mapping) else {}
        spec["wavelength"] = (
            float(nir.get("wavelength_min_nm", 830.0)),
            float(nir.get("wavelength_max_nm", 870.0)),
        )
        spec["active_radiance"] = float(nir.get("active_emitter_radiance", 40.0))
    elif sensor_type == "polar_camera":
        pol = sensor.get("polarization") if isinstance(sensor.get("polarization"), Mapping) else {}
        spec["wavelength"] = (400.0, 700.0)
        spec["polarizer_angle"] = float(pol.get("polarizer_angle_deg", 0.0))
    elif sensor_type == "lidar_3d":
        lidar = sensor.get("lidar") if isinstance(sensor.get("lidar"), Mapping) else {}
        spec.update(
            {
                "horizontal_samples": int(lidar.get("horizontal_samples", 1024)),
                "vertical_channels": int(lidar.get("vertical_channels", 32)),
                "horizontal_fov_deg": float(lidar.get("horizontal_fov_deg", 360.0)),
                "vertical_fov_min_deg": float(lidar.get("vertical_fov_min_deg", -25.0)),
                "vertical_fov_max_deg": float(lidar.get("vertical_fov_max_deg", 15.0)),
                "min_range_m": float(lidar.get("min_range_m", 0.2)),
                "max_range_m": float(lidar.get("max_range_m", 80.0)),
                "wavelength_nm": float(lidar.get("wavelength_nm", 905.0)),
            }
        )
    else:
        spec["wavelength"] = (400.0, 700.0)
    return spec


def apply_camera_rig(stage: Any, robot_prim_path: str, rig: Mapping[str, Any], replace_existing: bool = True) -> dict[str, Any]:
    """Apply a canonical JSON camera rig preset to a Ranger Mini USD prim.

    The JSON preset remains canonical; this function authors the USD prims and
    RoboMitsuba attrs consumed by discovery/render helpers.
    """

    Gf, Sdf, _Usd, UsdGeom = _require_pxr()
    resolved_robot_path = _resolve_ranger_robot_prim_path(stage, robot_prim_path)
    rig_id = str(rig.get("rig_id") or "camera_rig")
    base_frame = _safe_prim_name(rig.get("base_frame") or "base_link")
    rig_root_path = f"{resolved_robot_path}/{base_frame}/camera_rig"
    if replace_existing and stage.GetPrimAtPath(rig_root_path):
        stage.RemovePrim(rig_root_path)

    rig_root = UsdGeom.Xform.Define(stage, rig_root_path).GetPrim()
    _ensure_attr(rig_root, "robomituba:cameraRigId", Sdf.ValueTypeNames.String, rig_id)
    _ensure_attr(rig_root, "robomituba:robotModel", Sdf.ValueTypeNames.String, str(rig.get("robot_model") or "ranger_mini_v3"))
    _ensure_attr(rig_root, "robomituba:baseFrame", Sdf.ValueTypeNames.String, base_frame)
    _ensure_attr(rig_root, "robomituba:updatedAt", Sdf.ValueTypeNames.String, _dt.datetime.now(_dt.timezone.utc).isoformat())

    authored: list[str] = []
    for raw_sensor in rig.get("sensors") or []:
        if not isinstance(raw_sensor, Mapping):
            continue
        sensor_type = str(raw_sensor.get("sensor_type") or "")
        if sensor_type not in ROBOT_SENSOR_TYPES:
            raise ValueError(f"Unsupported sensor_type: {sensor_type}")
        sensor_id = str(raw_sensor.get("sensor_id") or "").strip()
        if not sensor_id:
            raise ValueError("Camera rig sensor is missing sensor_id.")
        mount = raw_sensor.get("mount") if isinstance(raw_sensor.get("mount"), Mapping) else {}
        parent_frame = _safe_prim_name(mount.get("parent_frame") or base_frame)
        parent_path = f"{resolved_robot_path}/{parent_frame}/camera_rig"
        UsdGeom.Xform.Define(stage, parent_path)
        sensor_path = f"{parent_path}/{_safe_prim_name(sensor_id)}"
        if sensor_type == "lidar_3d":
            prim = UsdGeom.Xform.Define(stage, sensor_path).GetPrim()
        else:
            camera = UsdGeom.Camera.Define(stage, sensor_path)
            prim = camera.GetPrim()
            intrinsics = raw_sensor.get("intrinsics") if isinstance(raw_sensor.get("intrinsics"), Mapping) else {}
            focal_length_mm = 18.0
            fov_h = float(intrinsics.get("fov_h_deg", 75.0))
            aperture = 2.0 * focal_length_mm * math.tan(math.radians(max(fov_h, 1e-3)) * 0.5)
            camera.CreateFocalLengthAttr(float(focal_length_mm))
            camera.CreateHorizontalApertureAttr(float(aperture))
            camera.CreateClippingRangeAttr(
                Gf.Vec2f(
                    float(intrinsics.get("clip_near_m", 0.1)),
                    float(intrinsics.get("clip_far_m", 30.0)),
                )
            )
            _ensure_attr(prim, "robomituba:fovHDeg", Sdf.ValueTypeNames.Double, fov_h)
            _ensure_attr(prim, "robomituba:fovVDeg", Sdf.ValueTypeNames.Double, float(intrinsics.get("fov_v_deg", 60.0)))
            _ensure_attr(prim, "robomituba:focalLengthPx", Sdf.ValueTypeNames.Double, float(intrinsics.get("focal_length_px", 410.0)))

        xyz = _sequence_float(mount.get("xyz_m", [0.0, 0.0, 0.0]), [0.0, 0.0, 0.0], length=3)
        rpy = _sequence_float(mount.get("rpy_deg", [0.0, 0.0, 0.0]), [0.0, 0.0, 0.0], length=3)
        xformable = UsdGeom.Xformable(prim)
        xformable.ClearXformOpOrder()
        xformable.AddTranslateOp().Set(Gf.Vec3d(*xyz))
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(*rpy))

        spec = _rig_sensor_to_attr_spec(raw_sensor)
        _write_sensor_attrs(prim, Sdf, spec)
        _ensure_attr(prim, "robomituba:cameraRigId", Sdf.ValueTypeNames.String, rig_id)
        _ensure_attr(prim, "robomituba:parentFrame", Sdf.ValueTypeNames.String, parent_frame)
        _ensure_attr(prim, "robomituba:enabled", Sdf.ValueTypeNames.Bool, bool(raw_sensor.get("enabled", True)))
        authored.append(str(prim.GetPath()))

    return {
        "rig_id": rig_id,
        "robot_prim_path": resolved_robot_path,
        "rig_root_path": rig_root_path,
        "sensor_count": len(authored),
        "sensor_paths": authored,
        "replace_existing": bool(replace_existing),
    }


def attach_default_sensor_rig(stage: Any, robot_prim_path: str) -> list[str]:
    """Author default sensor prims onto an existing Ranger Mini robot."""

    Gf, Sdf, _Usd, UsdGeom = _require_pxr()
    specs = [
        {
            "path": f"{robot_prim_path}/base_link/camera_front_link/rgb_camera",
            "type": "rgb_camera",
            "id": "rgb_front",
            "modalities": ["rgb"],
            "resolution": [1280, 720],
            "translate": (0.035, -0.045, 0.015),
            "wavelength": (400.0, 700.0),
        },
        {
            "path": f"{robot_prim_path}/base_link/camera_front_link/nir_camera",
            "type": "nir_camera",
            "id": "nir_front",
            "modalities": ["nir_intensity"],
            "resolution": [1280, 720],
            "translate": (0.035, 0.0, 0.015),
            "wavelength": (830.0, 870.0),
            "active_radiance": 40.0,
        },
        {
            "path": f"{robot_prim_path}/base_link/camera_front_link/polar_camera",
            "type": "polar_camera",
            "id": "polar_front",
            "modalities": ["polar_rgb_preview", "dop", "aolp", "s1", "s2"],
            "resolution": [1280, 720],
            "translate": (0.035, 0.045, 0.015),
            "wavelength": (400.0, 700.0),
            "polarizer_angle": 0.0,
        },
    ]
    authored: list[str] = []
    for spec in specs:
        camera = UsdGeom.Camera.Define(stage, spec["path"])
        prim = camera.GetPrim()
        camera.CreateFocalLengthAttr(18.0)
        camera.CreateHorizontalApertureAttr(20.955)
        camera.CreateClippingRangeAttr(Gf.Vec2f(0.05, 80.0))
        xformable = UsdGeom.Xformable(prim)
        xformable.ClearXformOpOrder()
        xformable.AddTranslateOp().Set(Gf.Vec3d(*spec["translate"]))
        xformable.AddRotateXYZOp().Set(Gf.Vec3f(0.0, -90.0, 0.0))
        _write_sensor_attrs(prim, Sdf, spec)
        authored.append(str(prim.GetPath()))

    lidar_path = f"{robot_prim_path}/base_link/lidar_link/lidar_3d"
    lidar = stage.DefinePrim(lidar_path, "Xform")
    xformable = UsdGeom.Xformable(lidar)
    xformable.ClearXformOpOrder()
    xformable.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.025))
    xformable.AddRotateXYZOp().Set(Gf.Vec3f(0.0, -90.0, 0.0))
    _write_sensor_attrs(
        lidar,
        Sdf,
        {
            "type": "lidar_3d",
            "id": "lidar_top",
            "modalities": ["lidar_point_cloud"],
            "horizontal_samples": 1024,
            "vertical_channels": 32,
            "horizontal_fov_deg": 360.0,
            "vertical_fov_min_deg": -25.0,
            "vertical_fov_max_deg": 15.0,
            "min_range_m": 0.2,
            "max_range_m": 80.0,
            "wavelength_nm": 905.0,
        },
    )
    authored.append(str(lidar.GetPath()))
    return authored


def _write_sensor_attrs(prim: Any, Sdf: Any, spec: Mapping[str, Any]) -> None:
    _ensure_attr(prim, "robomituba:sensorId", Sdf.ValueTypeNames.String, str(spec["id"]))
    _ensure_attr(prim, "robomituba:sensorType", Sdf.ValueTypeNames.String, str(spec["type"]))
    _ensure_attr(prim, "robomituba:modalities", Sdf.ValueTypeNames.StringArray, list(spec["modalities"]))
    if "resolution" in spec:
        _ensure_attr(prim, "robomituba:resolution", Sdf.ValueTypeNames.IntArray, list(spec["resolution"]))
    if "wavelength" in spec:
        lo, hi = spec["wavelength"]
        _ensure_attr(prim, "robomituba:wavelengthMinNm", Sdf.ValueTypeNames.Double, float(lo))
        _ensure_attr(prim, "robomituba:wavelengthMaxNm", Sdf.ValueTypeNames.Double, float(hi))
    for key, attr_name in (
        ("active_radiance", "robomituba:activeEmitterRadiance"),
        ("polarizer_angle", "robomituba:polarizerAngleDeg"),
        ("path_spp", "robomituba:pathSpp"),
        ("aov_spp", "robomituba:aovSpp"),
        ("polar_spp", "robomituba:polarSpp"),
        ("samples_per_pass", "robomituba:samplesPerPass"),
        ("horizontal_samples", "robomituba:horizontalSamples"),
        ("vertical_channels", "robomituba:verticalChannels"),
        ("horizontal_fov_deg", "robomituba:horizontalFovDeg"),
        ("vertical_fov_min_deg", "robomituba:verticalFovMinDeg"),
        ("vertical_fov_max_deg", "robomituba:verticalFovMaxDeg"),
        ("min_range_m", "robomituba:minRangeM"),
        ("max_range_m", "robomituba:maxRangeM"),
        ("wavelength_nm", "robomituba:wavelengthNm"),
    ):
        if key in spec:
            value_type = Sdf.ValueTypeNames.Int if isinstance(spec[key], int) else Sdf.ValueTypeNames.Double
            _ensure_attr(prim, attr_name, value_type, spec[key])
    _ensure_attr(prim, "robomituba:enabled", Sdf.ValueTypeNames.Bool, True)
    _ensure_attr(prim, "robomituba:updatedAt", Sdf.ValueTypeNames.String, _dt.datetime.now(_dt.timezone.utc).isoformat())


def discover_robot_sensors(stage: Any, robot_prim_path: str) -> list[dict[str, Any]]:
    _Gf, _Sdf, Usd, UsdGeom = _require_pxr()
    root = stage.GetPrimAtPath(robot_prim_path)
    if not root or not root.IsValid():
        raise RuntimeError(f"Robot prim not found: {robot_prim_path}")

    xform_cache = UsdGeom.XformCache()
    sensors: list[dict[str, Any]] = []
    for prim in Usd.PrimRange(root):
        sensor_type = str(_attr_value(prim, "robomituba:sensorType", "") or "")
        if sensor_type not in ROBOT_SENSOR_TYPES:
            continue
        sensor_id = str(_attr_value(prim, "robomituba:sensorId", prim.GetName()) or prim.GetName())
        modalities = _as_str_list(_attr_value(prim, "robomituba:modalities"), DEFAULT_SENSOR_MODALITIES[sensor_type])
        transform = _matrix_to_list(xform_cache.GetLocalToWorldTransform(prim))
        sensors.append(
            {
                "sensor_id": sensor_id,
                "name": prim.GetName(),
                "prim_path": str(prim.GetPath()),
                "sensor_type": sensor_type,
                "modalities": modalities,
                "camera_to_world": transform,
                "resolution": _as_int_list(_attr_value(prim, "robomituba:resolution"), [1280, 720]),
                "enabled": bool(_attr_value(prim, "robomituba:enabled", True)),
            }
        )
    sensors.sort(key=lambda item: item["sensor_id"])
    return sensors


def capture_robot_sensor_spec(stage: Any, robot_prim_path: str, sensor_id: str):
    from robomituba_bridge import IsaacSensorSpec

    _Gf, _Sdf, _Usd, UsdGeom = _require_pxr()
    path = _sensor_path(robot_prim_path, sensor_id)
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        candidates = {item["sensor_id"]: item["prim_path"] for item in discover_robot_sensors(stage, robot_prim_path)}
        if sensor_id in candidates:
            prim = stage.GetPrimAtPath(candidates[sensor_id])
        if not prim or not prim.IsValid():
            raise RuntimeError(f"Robot sensor not found: {sensor_id} on {robot_prim_path}")

    sensor_type = str(_attr_value(prim, "robomituba:sensorType", "rgb_camera") or "rgb_camera")
    resolved_sensor_id = str(_attr_value(prim, "robomituba:sensorId", sensor_id) or sensor_id)
    modalities = _as_str_list(_attr_value(prim, "robomituba:modalities"), DEFAULT_SENSOR_MODALITIES.get(sensor_type, ["rgb"]))
    xform_cache = UsdGeom.XformCache()
    camera_to_world = _matrix_to_list(xform_cache.GetLocalToWorldTransform(prim))
    is_camera = prim.IsA(UsdGeom.Camera)
    fov_deg = _fov_from_camera(UsdGeom.Camera(prim)) if is_camera else float(_attr_value(prim, "robomituba:horizontalFovDeg", 360.0))
    resolution = _as_int_list(
        _attr_value(prim, "robomituba:resolution"),
        [
            int(_attr_value(prim, "robomituba:horizontalSamples", 1024)),
            int(_attr_value(prim, "robomituba:verticalChannels", 32)),
        ] if sensor_type == "lidar_3d" else [1280, 720],
    )
    extras = {
        "robot_prim_path": robot_prim_path,
        "sensor_prim_path": str(prim.GetPath()),
        "sensor_type": sensor_type,
        "wavelength_min_nm": _attr_value(prim, "robomituba:wavelengthMinNm"),
        "wavelength_max_nm": _attr_value(prim, "robomituba:wavelengthMaxNm"),
        "wavelength_nm": _attr_value(prim, "robomituba:wavelengthNm"),
        "active_emitter_radiance": _attr_value(prim, "robomituba:activeEmitterRadiance"),
        "polarizer_angle_deg": _attr_value(prim, "robomituba:polarizerAngleDeg"),
        "horizontal_samples": _attr_value(prim, "robomituba:horizontalSamples"),
        "vertical_channels": _attr_value(prim, "robomituba:verticalChannels"),
        "horizontal_fov_deg": _attr_value(prim, "robomituba:horizontalFovDeg"),
        "vertical_fov_min_deg": _attr_value(prim, "robomituba:verticalFovMinDeg"),
        "vertical_fov_max_deg": _attr_value(prim, "robomituba:verticalFovMaxDeg"),
        "min_range_m": _attr_value(prim, "robomituba:minRangeM"),
        "max_range_m": _attr_value(prim, "robomituba:maxRangeM"),
        "path_spp": _attr_value(prim, "robomituba:pathSpp"),
        "aov_spp": _attr_value(prim, "robomituba:aovSpp"),
        "polar_spp": _attr_value(prim, "robomituba:polarSpp"),
        "samples_per_pass": _attr_value(prim, "robomituba:samplesPerPass"),
    }
    return IsaacSensorSpec(
        sensor_id=resolved_sensor_id,
        name=prim.GetName(),
        modalities=modalities,
        calibration_ref=str(_attr_value(prim, "robomituba:calibrationRef", f"{robot_prim_path}/{resolved_sensor_id}")),
        camera_to_world=camera_to_world,
        fov_deg=float(fov_deg),
        resolution=resolution,
        sensor_sync_group=f"{robot_prim_path}:sensors",
        pose_source=str(prim.GetPath()),
        extras={key: value for key, value in extras.items() if value is not None},
    )


def capture_robot_sensor_specs(stage: Any, robot_prim_path: str, sensors: Sequence[str] | None = None) -> list[Any]:
    discovered = discover_robot_sensors(stage, robot_prim_path)
    if sensors is None:
        sensor_ids = [item["sensor_id"] for item in discovered if item.get("enabled", True)]
    else:
        sensor_ids = [str(sensor) for sensor in sensors]
    return [capture_robot_sensor_spec(stage, robot_prim_path, sensor_id) for sensor_id in sensor_ids]


def register_robot_sensors(
    stage: Any,
    robot_prim_path: str,
    *,
    sensors: Sequence[str] | None = None,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    try:
        from .daemon_client import register_isaac_sensors
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        try:
            from isaac_extension.daemon_client import register_isaac_sensors
        except ImportError:
            from daemon_client import register_isaac_sensors

    specs = capture_robot_sensor_specs(stage, robot_prim_path, sensors=sensors)
    return register_isaac_sensors(specs, daemon_url=daemon_url, timeout_s=timeout_s)


def render_robot_sensor(
    scene_id: str,
    robot_prim_path: str,
    sensor_id: str,
    *,
    stage: Any | None = None,
    daemon_url: str | None = None,
    submit_mode: str = "blocking",
    modalities: Sequence[str] | None = None,
    render_settings: Mapping[str, Any] | None = None,
    timeout_s: float = 1800.0,
    variant: str | None = None,
    sync_policy: str = "auto",
    force_resync: bool = False,
) -> dict[str, Any]:
    try:
        from .daemon_client import render_sensor_from_daemon
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        try:
            from isaac_extension.daemon_client import render_sensor_from_daemon
        except ImportError:
            from daemon_client import render_sensor_from_daemon

    if stage is None:
        import omni.usd  # type: ignore

        stage = omni.usd.get_context().get_stage()
    spec = capture_robot_sensor_spec(stage, robot_prim_path, sensor_id)
    register_robot_sensors(stage, robot_prim_path, sensors=[spec.sensor_id], daemon_url=daemon_url, timeout_s=min(timeout_s, 30.0))
    requested_modalities = list(modalities) if modalities is not None else list(spec.modalities)
    merged_render_settings = dict(render_settings or {})
    if spec.extras.get("sensor_type") == "lidar_3d":
        for extra_key, setting_key in (
            ("horizontal_fov_deg", "lidar_horizontal_fov_deg"),
            ("vertical_fov_min_deg", "lidar_vertical_fov_min_deg"),
            ("vertical_fov_max_deg", "lidar_vertical_fov_max_deg"),
            ("min_range_m", "lidar_min_range_m"),
            ("max_range_m", "lidar_max_range_m"),
            ("wavelength_nm", "lidar_wavelength_nm"),
        ):
            if spec.extras.get(extra_key) is not None:
                merged_render_settings.setdefault(setting_key, spec.extras[extra_key])
    if "nir_intensity" in requested_modalities:
        if spec.extras.get("wavelength_min_nm") is not None:
            merged_render_settings.setdefault("nir_wavelength_min_nm", spec.extras["wavelength_min_nm"])
        if spec.extras.get("wavelength_max_nm") is not None:
            merged_render_settings.setdefault("nir_wavelength_max_nm", spec.extras["wavelength_max_nm"])
        if spec.extras.get("active_emitter_radiance") is not None:
            merged_render_settings.setdefault("nir_active_emitter_radiance", spec.extras["active_emitter_radiance"])
    for extra_key in ("path_spp", "aov_spp", "polar_spp", "samples_per_pass"):
        if spec.extras.get(extra_key) is not None:
            merged_render_settings.setdefault(extra_key, spec.extras[extra_key])
    result = render_sensor_from_daemon(
        scene_id,
        spec.sensor_id,
        stage=stage,
        daemon_url=daemon_url,
        submit_mode=submit_mode,
        modalities=requested_modalities,
        render_settings=merged_render_settings,
        timeout_s=timeout_s,
        variant=variant,
        sync_policy=sync_policy,
        force_resync=force_resync,
    )
    _write_latest_result_to_sensor_prim(stage, spec.pose_source or "", result)
    return result


def render_robot_sensor_suite(
    scene_id: str,
    robot_prim_path: str,
    *,
    stage: Any | None = None,
    sensors: Sequence[str] | None = None,
    daemon_url: str | None = None,
    submit_mode: str = "blocking",
    render_settings: Mapping[str, Any] | None = None,
    timeout_s: float = 1800.0,
    variant: str | None = None,
    sync_policy: str = "auto",
    force_resync: bool = False,
) -> dict[str, Any]:
    if stage is None:
        import omni.usd  # type: ignore

        stage = omni.usd.get_context().get_stage()
    specs = capture_robot_sensor_specs(stage, robot_prim_path, sensors=sensors)
    register_robot_sensors(stage, robot_prim_path, sensors=[spec.sensor_id for spec in specs], daemon_url=daemon_url, timeout_s=min(timeout_s, 30.0))
    results: dict[str, Any] = {}
    for spec in specs:
        results[spec.sensor_id] = render_robot_sensor(
            scene_id,
            robot_prim_path,
            spec.sensor_id,
            stage=stage,
            daemon_url=daemon_url,
            submit_mode=submit_mode,
            modalities=spec.modalities,
            render_settings=render_settings,
            timeout_s=timeout_s,
            variant=variant,
            sync_policy=sync_policy,
            force_resync=force_resync,
        )
    return {"scene_id": scene_id, "robot_prim_path": robot_prim_path, "results": results}


def _write_latest_result_to_sensor_prim(stage: Any, prim_path: str, result: Mapping[str, Any]) -> None:
    if not prim_path:
        return
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return
    _Gf, Sdf, _Usd, _UsdGeom = _require_pxr()
    _ensure_attr(prim, "robomituba:lastJobId", Sdf.ValueTypeNames.String, str(result.get("job_id") or ""))
    _ensure_attr(prim, "robomituba:lastFrameId", Sdf.ValueTypeNames.String, str(result.get("frame_id") or ""))
    _ensure_attr(prim, "robomituba:lastManifestPath", Sdf.ValueTypeNames.String, str(result.get("manifest_path") or ""))
    artifacts = result.get("artifacts") if isinstance(result, Mapping) else None
    _ensure_attr(
        prim,
        "robomituba:lastArtifactsJson",
        Sdf.ValueTypeNames.String,
        json.dumps(artifacts if isinstance(artifacts, Mapping) else {}, ensure_ascii=False, sort_keys=True),
    )
    _ensure_attr(prim, "robomituba:lastRenderedAt", Sdf.ValueTypeNames.String, _dt.datetime.now(_dt.timezone.utc).isoformat())
