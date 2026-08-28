from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .viewpoint_graph import ViewpointGraph, write_viewpoint_graph


POLAR_SWEEP_MODALITIES = (
    "polar_rgb_preview",
    "s1_over_s0",
    "s2_over_s0",
    "dop",
    "aolp",
    "s1",
    "s2",
)


def _modality_suffix(modalities: list[str]) -> str:
    """Short stable suffix derived from the requested modalities.

    Lets the same viewpoint be re-submitted with a different modality set
    without colliding with an already-queued job_id (e.g. rgb then depth).
    """
    items = sorted({str(m) for m in modalities or []})
    if not items:
        return ""
    if len(items) == 1:
        return f"-{items[0]}"
    return "-" + hashlib.sha1(",".join(items).encode("utf-8")).hexdigest()[:8]


@dataclass
class SweepRenderRequest:
    node_id: str
    heading_id: str
    request: object
    sensor_ids: list[str] | None = None
    modalities_by_sensor: dict[str, list[str]] | None = None
    phase: str | None = None
    phase_index: int | None = None


@dataclass
class SweepRenderPhase:
    phase: str
    phase_index: int
    requests: list[SweepRenderRequest]


_SWEEP_EXECUTION_POLICIES = {"auto", "per_view", "modality_phases"}
_PHASE_ORDER = ("rgb", "polar", "lidar")


def _mat4_from_xy_yaw(x: float, y: float, yaw_rad: float, height_m: float = 1.0) -> list[float]:
    """Return the canonical Mitsuba camera pose in legacy flat storage.

    ``x, y`` are authoring-floor coordinates (Mitsuba X/Z), while ``height_m``
    is Mitsuba Y.  Keeping this adapter as the only sweep entry point prevents
    graph headings from drifting from Blender GT and kitchen probes.
    """
    from robomituba_bridge.camera_pose import matrix_to_legacy_flat, resolve_viewpoint_pose

    pose = resolve_viewpoint_pose(
        (float(x), float(y), 0.0),
        math.degrees(float(yaw_rad)),
        eye_height_m=float(height_m),
    )
    return matrix_to_legacy_flat(pose.camera_to_world_mitsuba)


def _sensor_pose_from_xy_yaw(
    x: float,
    y: float,
    yaw_rad: float,
    camera_template: object,
    *,
    fallback_height_m: float = 1.0,
) -> list[float]:
    extras = getattr(camera_template, "extras", {}) or {}
    mount = extras.get("robot_mount") if isinstance(extras, dict) else None
    if not isinstance(mount, dict):
        return _mat4_from_xy_yaw(x, y, yaw_rad, height_m=fallback_height_m)
    xyz = mount.get("xyz_m") or [0.0, fallback_height_m, 0.0]
    rpy = mount.get("rpy_deg") or [0.0, 0.0, 0.0]
    try:
        mx, my, mz = float(xyz[0]), float(xyz[1]), float(xyz[2])
    except Exception:
        mx, my, mz = 0.0, fallback_height_m, 0.0
    # Treat a fully-zero mount (the default value of a camera rig that the user
    # never customised) as "unset" so the UI's Camera height slider still works.
    if mx == 0.0 and my == 0.0 and mz == 0.0:
        my = fallback_height_m
    try:
        mount_yaw = math.radians(float(rpy[2]))
    except Exception:
        mount_yaw = 0.0
    c = math.cos(yaw_rad)
    s = math.sin(yaw_rad)
    world_x = float(x) + c * mx - s * mz
    world_y = my
    world_z = float(y) + s * mx + c * mz
    return _mat4_from_xy_yaw(world_x, world_z, yaw_rad + mount_yaw, height_m=world_y)


def _camera_templates_from_payloads(
    *,
    camera_spec_payload: dict | None,
    camera_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    sensor_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    allow_empty: bool = False,
    sensor_scope: str = "active",
    sensor_ids: Sequence[str] | None = None,
) -> list[object]:
    from robomituba_bridge import camera_spec_from_payload

    scope = str(sensor_scope or "active").strip().lower()
    selected_ids = {str(item) for item in (sensor_ids or []) if str(item)}
    raw_specs: list[Mapping[str, Any]]
    if scope in {"all_rig", "selected"} and camera_specs_payload:
        raw_specs = [dict(item) for item in camera_specs_payload if isinstance(item, Mapping)]
        if scope == "selected" and selected_ids:
            raw_specs = [item for item in raw_specs if str(item.get("camera_id") or "") in selected_ids]
    elif camera_spec_payload is not None:
        raw_specs = [dict(camera_spec_payload)]
    else:
        raw_specs = []
    if not raw_specs and allow_empty:
        return []
    if not raw_specs:
        raise ValueError("No camera_spec payload was provided for sweep rendering.")
    return [camera_spec_from_payload(dict(item)) for item in raw_specs]


def _sensor_templates_from_payloads(sensor_specs_payload: Sequence[Mapping[str, Any]] | None) -> list[object]:
    from robomituba_bridge import isaac_sensor_spec_from_payload

    return [
        isaac_sensor_spec_from_payload(dict(item))
        for item in (sensor_specs_payload or [])
        if isinstance(item, Mapping)
    ]


def _sensor_render_modalities(sensor_template: object, fallback_modalities: Sequence[str]) -> list[str]:
    values = getattr(sensor_template, "modalities", None)
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and values:
        return [str(item) for item in values if str(item)]
    return [str(item) for item in fallback_modalities]


def _camera_render_modalities(camera_template: object, fallback_modalities: Sequence[str]) -> list[str]:
    extras = getattr(camera_template, "extras", {}) or {}
    sensor_modality = str(getattr(camera_template, "sensor_modality", "") or "").lower()
    canonical_values = extras.get("canonical_modalities") if isinstance(extras, Mapping) else None
    canonical_modalities: list[str] = []
    if isinstance(canonical_values, Sequence) and not isinstance(canonical_values, (str, bytes)):
        canonical_modalities = [str(item) for item in canonical_values if str(item)]
    values = extras.get("render_modalities") if isinstance(extras, Mapping) else None
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        modalities = [str(item) for item in values if str(item)]
        if modalities:
            if (
                sensor_modality == "polarization"
                or any(item in POLAR_SWEEP_MODALITIES for item in modalities)
                or any(item in POLAR_SWEEP_MODALITIES for item in canonical_modalities)
            ):
                return list(dict.fromkeys([*POLAR_SWEEP_MODALITIES, *canonical_modalities, *modalities]))
            return modalities
    value = extras.get("render_modality") if isinstance(extras, Mapping) else None
    if value:
        if sensor_modality == "polarization" or str(value) in POLAR_SWEEP_MODALITIES:
            return list(dict.fromkeys([*POLAR_SWEEP_MODALITIES, *canonical_modalities, str(value)]))
        return [str(value)]
    return [str(item) for item in fallback_modalities]


def _union_modalities(modalities_by_sensor: Mapping[str, Sequence[str]], fallback_modalities: Sequence[str]) -> list[str]:
    result: list[str] = []
    for modalities in modalities_by_sensor.values():
        for modality in modalities:
            item = str(modality)
            if item and item not in result:
                result.append(item)
    if result:
        return result
    return [str(item) for item in fallback_modalities]


def _needs_default_assist_light(modalities: Sequence[str]) -> bool:
    return any(str(item) in {"active_nir_intensity", "nir_intensity"} for item in modalities)


def _modality_phase(modalities: Sequence[str]) -> str:
    lidar_modalities = {"lidar_point_cloud", "lidar_range", "lidar_signal", "lidar_reflectivity", "lidar_near_ir", "lidar_valid", "lidar_xyz"}
    if any(str(item) in lidar_modalities for item in modalities):
        return "lidar"
    return "polar" if any(str(item) in POLAR_SWEEP_MODALITIES for item in modalities) else "rgb"


def _resolve_sweep_execution_policy(policy: str | None, sweep_requests: Sequence[SweepRenderRequest]) -> str:
    value = str(policy or "auto").strip().lower()
    if value not in _SWEEP_EXECUTION_POLICIES:
        value = "auto"
    if value != "auto":
        return value
    phases: set[str] = set()
    for sweep_request in sweep_requests:
        modalities_by_sensor = dict(sweep_request.modalities_by_sensor or {})
        for modalities in modalities_by_sensor.values():
            phases.add(_modality_phase(modalities))
    return "modality_phases" if len(phases) > 1 else "per_view"


def split_sweep_requests_by_modality_phase(
    sweep_requests: Sequence[SweepRenderRequest],
    *,
    sweep_execution_policy: str | None = "auto",
) -> list[SweepRenderPhase]:
    """Split mixed RGB/polar rig requests into stable modality phases.

    RGB/NIR-style sensors can share the resident base scene. Plain ambient
    polarization also uses a shared Stokes base scene, but it needs a different
    Mitsuba variant/cache family from RGB. The split keeps the final observation
    frame id unchanged while giving each phase its own job id and recycle point.
    """
    policy = _resolve_sweep_execution_policy(sweep_execution_policy, sweep_requests)
    if policy == "per_view":
        return [SweepRenderPhase(phase="per_view", phase_index=0, requests=list(sweep_requests))]

    phases: list[SweepRenderPhase] = []
    for phase_index, phase_name in enumerate(_PHASE_ORDER):
        phase_requests: list[SweepRenderRequest] = []
        for sweep_request in sweep_requests:
            request = sweep_request.request
            camera_specs = list(getattr(request, "camera_specs", []) or [])
            sensor_specs = list(getattr(request, "sensor_specs", []) or [])
            modalities_by_sensor = dict(sweep_request.modalities_by_sensor or getattr(request, "extras", {}).get("modalities_by_sensor") or {})
            phase_camera_specs = []
            phase_sensor_specs = []
            phase_modalities_by_sensor: dict[str, list[str]] = {}
            for camera_spec in camera_specs:
                camera_id = str(getattr(camera_spec, "camera_id", "") or "")
                camera_modalities = [str(item) for item in modalities_by_sensor.get(camera_id, []) if str(item)]
                if not camera_modalities:
                    continue
                if _modality_phase(camera_modalities) != phase_name:
                    continue
                phase_camera_specs.append(camera_spec)
                phase_modalities_by_sensor[camera_id] = camera_modalities
            for sensor_spec in sensor_specs:
                sensor_id = str(getattr(sensor_spec, "sensor_id", "") or "")
                sensor_modalities = [str(item) for item in modalities_by_sensor.get(sensor_id, _sensor_render_modalities(sensor_spec, [])) if str(item)]
                if not sensor_modalities or _modality_phase(sensor_modalities) != phase_name:
                    continue
                phase_sensor_specs.append(sensor_spec)
                phase_modalities_by_sensor[sensor_id] = sensor_modalities
            if not phase_camera_specs and not phase_sensor_specs:
                continue

            phase_modalities = _union_modalities(phase_modalities_by_sensor, [])
            phase_sensor_ids = [str(getattr(item, "camera_id", "") or "") for item in phase_camera_specs] + [str(getattr(item, "sensor_id", "") or "") for item in phase_sensor_specs]
            phase_job_id = f"{request.job_id}-{phase_name}"
            phase_scene_state = replace(request.scene_state, job_id=phase_job_id)
            phase_extras = {
                **dict(getattr(request, "extras", {}) or {}),
                "sweep_execution_policy": policy,
                "phase": phase_name,
                "phase_index": phase_index,
                "phase_sensor_ids": phase_sensor_ids,
                "sensor_ids": phase_sensor_ids,
                "sensor_count": len(phase_sensor_ids),
                "modalities_by_sensor": phase_modalities_by_sensor,
            }
            phase_request = replace(
                request,
                request_id=f"{request.request_id}-{phase_name}",
                job_id=phase_job_id,
                scene_state=phase_scene_state,
                camera_specs=phase_camera_specs,
                sensor_specs=phase_sensor_specs,
                modalities=phase_modalities,
                assist_light=request.assist_light if _needs_default_assist_light(phase_modalities) else None,
                extras=phase_extras,
            )
            phase_requests.append(
                SweepRenderRequest(
                    node_id=sweep_request.node_id,
                    heading_id=sweep_request.heading_id,
                    request=phase_request,
                    sensor_ids=phase_sensor_ids,
                    modalities_by_sensor=phase_modalities_by_sensor,
                    phase=phase_name,
                    phase_index=phase_index,
                )
            )
        if phase_requests:
            phases.append(SweepRenderPhase(phase=phase_name, phase_index=phase_index, requests=phase_requests))
    if not phases:
        return [SweepRenderPhase(phase="per_view", phase_index=0, requests=list(sweep_requests))]
    return phases


def build_sweep_render_requests(
    graph: ViewpointGraph,
    *,
    scene_state_payload: dict,
    camera_spec_payload: dict | None,
    modalities: list[str],
    job_id_mode: str = "per_heading",
    node_ids: list[str] | None = None,
    heading_ids_by_node: Mapping[str, Sequence[str]] | None = None,
    camera_height_m: float = 1.0,
    render_settings: dict | None = None,
    node_heights: dict | None = None,
    camera_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    sensor_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    sensor_scope: str = "active",
    sensor_ids: Sequence[str] | None = None,
    active_lights: Sequence[Mapping[str, Any]] | None = None,
) -> list[SweepRenderRequest]:
    from robomituba_bridge import ActiveLightSpec, AssistLightSpec, RenderRequest, RobotState
    from robomituba_bridge import active_light_spec_from_payload, scene_state_from_payload

    scene_state = scene_state_from_payload(scene_state_payload)
    # Rig-mounted active lights (RGB/NIR flash + polarizer). Positioned at
    # base_pose @ mount by the renderer; passed on every request (the renderer
    # filters each light by its `modalities` per render pass).
    rig_active_lights = [
        active_light_spec_from_payload(dict(item))
        for item in (active_lights or [])
        if isinstance(item, Mapping) and item.get("enabled", True)
    ]
    sensor_templates = _sensor_templates_from_payloads(sensor_specs_payload)
    camera_templates = _camera_templates_from_payloads(
        camera_spec_payload=camera_spec_payload,
        camera_specs_payload=camera_specs_payload,
        allow_empty=bool(sensor_templates),
        sensor_scope=sensor_scope,
        sensor_ids=sensor_ids,
    )
    node_id_set = set(node_ids) if node_ids else None
    heading_id_sets = {
        str(node_id): {str(heading_id) for heading_id in heading_ids}
        for node_id, heading_ids in (heading_ids_by_node or {}).items()
    }
    requests: list[SweepRenderRequest] = []
    for node in graph.nodes:
        if node_id_set is not None and node.node_id not in node_id_set:
            continue
        for heading in node.headings:
            allowed_headings = heading_id_sets.get(node.node_id)
            if allowed_headings is not None and heading.heading_id not in allowed_headings:
                continue
            frame_id = f"{graph.scene_id}_{node.node_id}_{heading.heading_id}"
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            yaw_rad = math.radians(float(heading.yaw_deg))
            # Per-viewpoint height override (UI's "Camera height" slider against a selected viewpoint).
            node_height = camera_height_m
            if node_heights and node.node_id in node_heights:
                try:
                    node_height = float(node_heights[node.node_id])
                except (TypeError, ValueError):
                    pass
            base_pose = _mat4_from_xy_yaw(float(node.position[0]), float(node.position[1]), yaw_rad, height_m=node_height)
            camera_specs = []
            sensor_specs = []
            modalities_by_sensor: dict[str, list[str]] = {}
            for camera_template in camera_templates:
                pose = _sensor_pose_from_xy_yaw(float(node.position[0]), float(node.position[1]), yaw_rad, camera_template, fallback_height_m=node_height)
                camera_id = str(getattr(camera_template, "camera_id", "") or f"camera_{len(camera_specs) + 1}")
                camera_modalities = _camera_render_modalities(camera_template, modalities)
                modalities_by_sensor[camera_id] = camera_modalities
                camera_specs.append(replace(camera_template, camera_to_world=pose))
            for sensor_template in sensor_templates:
                pose = _sensor_pose_from_xy_yaw(float(node.position[0]), float(node.position[1]), yaw_rad, sensor_template, fallback_height_m=node_height)
                sensor_id = str(getattr(sensor_template, "sensor_id", "") or f"sensor_{len(sensor_specs) + 1}")
                sensor_modalities = _sensor_render_modalities(sensor_template, modalities)
                modalities_by_sensor[sensor_id] = sensor_modalities
                sensor_specs.append(replace(sensor_template, camera_to_world=pose))
            request_modalities = _union_modalities(modalities_by_sensor, modalities)
            sensor_ids_list = [str(getattr(item, "camera_id", "") or "") for item in camera_specs] + [str(getattr(item, "sensor_id", "") or "") for item in sensor_specs]
            mod_suffix = _modality_suffix(list(request_modalities))
            job_id = scene_state.job_id
            if job_id_mode == "per_heading":
                job_id = f"{scene_state.job_id}-{node.node_id}-{heading.heading_id}{mod_suffix}"
            elif job_id_mode != "shared":
                raise ValueError("job_id_mode must be 'shared' or 'per_heading'.")
            timestep_scene_state = replace(scene_state, job_id=job_id, frame_id=frame_id, timestamp=timestamp)
            request = RenderRequest(
                request_id=f"{graph.graph_id}-{node.node_id}-{heading.heading_id}",
                job_id=timestep_scene_state.job_id,
                frame_id=frame_id,
                timestamp=timestamp,
                scene_state=timestep_scene_state,
                camera_specs=camera_specs,
                sensor_specs=sensor_specs,
                modalities=request_modalities,
                robot_state=RobotState(base_pose=base_pose),
                render_settings=dict(render_settings or {}),
                assist_light=AssistLightSpec() if (_needs_default_assist_light(request_modalities) and not rig_active_lights) else None,
                active_lights=list(rig_active_lights),
                extras={
                    "graph_id": graph.graph_id,
                    "scene_id": graph.scene_id,
                    "node_id": node.node_id,
                    "heading_id": heading.heading_id,
                    "yaw_deg": float(heading.yaw_deg),
                    "render_mode": "viewpoint_sweep",
                    "sensor_scope": str(sensor_scope or "active"),
                    "sensor_ids": sensor_ids_list,
                    "sensor_count": len(sensor_ids_list),
                    "modalities_by_sensor": modalities_by_sensor,
                },
            )
            requests.append(
                SweepRenderRequest(
                    node_id=node.node_id,
                    heading_id=heading.heading_id,
                    request=request,
                    sensor_ids=sensor_ids_list,
                    modalities_by_sensor=modalities_by_sensor,
                )
            )
    return requests


def build_custom_position_render_requests(
    custom_positions: list[dict],
    *,
    scene_state_payload: dict,
    camera_spec_payload: dict | None,
    modalities: list[str],
    scene_id: str,
    camera_height_m: float = 1.0,
    render_settings: dict | None = None,
    camera_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    sensor_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    sensor_scope: str = "active",
    sensor_ids: Sequence[str] | None = None,
    active_lights: Sequence[Mapping[str, Any]] | None = None,
) -> list[SweepRenderRequest]:
    """Build render requests for arbitrary (x, y, yaw_deg) positions not in the graph."""
    from robomituba_bridge import AssistLightSpec, RenderRequest, RobotState
    from robomituba_bridge import active_light_spec_from_payload, scene_state_from_payload

    scene_state = scene_state_from_payload(scene_state_payload)
    rig_active_lights = [
        active_light_spec_from_payload(dict(item))
        for item in (active_lights or [])
        if isinstance(item, Mapping) and item.get("enabled", True)
    ]
    sensor_templates = _sensor_templates_from_payloads(sensor_specs_payload)
    camera_templates = _camera_templates_from_payloads(
        camera_spec_payload=camera_spec_payload,
        camera_specs_payload=camera_specs_payload,
        allow_empty=bool(sensor_templates),
        sensor_scope=sensor_scope,
        sensor_ids=sensor_ids,
    )
    requests: list[SweepRenderRequest] = []
    for idx, pos in enumerate(custom_positions):
        node_id = str(pos.get("node_id") or f"custom_{idx}")
        heading_id = str(pos.get("heading_id") or "h0")
        x = float(pos.get("x", 0))
        y = float(pos.get("y", 0))
        yaw_deg = float(pos.get("yaw_deg", 0))
        yaw_rad = math.radians(yaw_deg)
        per_pos_height = camera_height_m
        if pos.get("height_m") is not None:
            try:
                per_pos_height = float(pos["height_m"])
            except (TypeError, ValueError):
                pass
        base_pose = _mat4_from_xy_yaw(x, y, yaw_rad, height_m=per_pos_height)
        camera_specs = []
        sensor_specs = []
        modalities_by_sensor: dict[str, list[str]] = {}
        for camera_template in camera_templates:
            pose = _sensor_pose_from_xy_yaw(x, y, yaw_rad, camera_template, fallback_height_m=per_pos_height)
            camera_id = str(getattr(camera_template, "camera_id", "") or f"camera_{len(camera_specs) + 1}")
            camera_modalities = _camera_render_modalities(camera_template, modalities)
            modalities_by_sensor[camera_id] = camera_modalities
            camera_specs.append(replace(camera_template, camera_to_world=pose))
        for sensor_template in sensor_templates:
            pose = _sensor_pose_from_xy_yaw(x, y, yaw_rad, sensor_template, fallback_height_m=per_pos_height)
            sensor_id = str(getattr(sensor_template, "sensor_id", "") or f"sensor_{len(sensor_specs) + 1}")
            sensor_modalities = _sensor_render_modalities(sensor_template, modalities)
            modalities_by_sensor[sensor_id] = sensor_modalities
            sensor_specs.append(replace(sensor_template, camera_to_world=pose))
        request_modalities = _union_modalities(modalities_by_sensor, modalities)
        sensor_ids_list = [str(getattr(item, "camera_id", "") or "") for item in camera_specs] + [str(getattr(item, "sensor_id", "") or "") for item in sensor_specs]
        frame_id = f"{scene_id}_{node_id}_{heading_id}"
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        job_id = f"{scene_state.job_id}-{node_id}-{heading_id}{_modality_suffix(list(request_modalities))}"
        timestep_scene_state = replace(scene_state, job_id=job_id, frame_id=frame_id, timestamp=timestamp)
        request = RenderRequest(
            request_id=str(pos.get("request_id") or f"custom-{node_id}-{heading_id}"),
            job_id=job_id,
            frame_id=frame_id,
            timestamp=timestamp,
            scene_state=timestep_scene_state,
            camera_specs=camera_specs,
            sensor_specs=sensor_specs,
            modalities=request_modalities,
            robot_state=RobotState(base_pose=base_pose),
            render_settings=dict(render_settings or {}),
            assist_light=AssistLightSpec() if (_needs_default_assist_light(request_modalities) and not rig_active_lights) else None,
            active_lights=list(rig_active_lights),
            extras={
                "scene_id": scene_id,
                "node_id": node_id,
                "heading_id": heading_id,
                "yaw_deg": yaw_deg,
                "render_mode": str(pos.get("render_mode") or "custom_position"),
                "sensor_scope": str(sensor_scope or "active"),
                "sensor_ids": sensor_ids_list,
                "sensor_count": len(sensor_ids_list),
                "modalities_by_sensor": modalities_by_sensor,
            },
        )
        if pos.get("preview_id") is not None:
            request.extras["preview_id"] = str(pos["preview_id"])
        requests.append(
            SweepRenderRequest(
                node_id=node_id,
                heading_id=heading_id,
                request=request,
                sensor_ids=sensor_ids_list,
                modalities_by_sensor=modalities_by_sensor,
            )
        )
    return requests


def _set_heading_observation(graph: ViewpointGraph, node_id: str, heading_id: str, modalities: list[str], manifest_ref: str) -> None:
    for node in graph.nodes:
        if node.node_id != node_id:
            continue
        for heading in node.headings:
            if heading.heading_id != heading_id:
                continue
            heading.sensor_observations["bundle"] = manifest_ref
            for modality in modalities:
                heading.sensor_observations[modality] = manifest_ref
            return
    raise KeyError(f"Unknown node/heading: {node_id}/{heading_id}")


def render_viewpoint_sweep_direct(
    graph: ViewpointGraph,
    *,
    dataset_root: str | Path,
    graph_path: str | Path,
    scene_state_payload: dict,
    camera_spec_payload: dict | None,
    modalities: list[str],
    render_fn: Callable | None = None,
    variant: str = "auto",
    camera_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    sensor_specs_payload: Sequence[Mapping[str, Any]] | None = None,
    sensor_scope: str = "active",
    sensor_ids: Sequence[str] | None = None,
    active_lights: Sequence[Mapping[str, Any]] | None = None,
) -> ViewpointGraph:
    if render_fn is None:
        from mitsuba_converter import render_timestep_bundle_split_lighting

        render_fn = render_timestep_bundle_split_lighting
    root = Path(dataset_root).resolve()
    sweep_requests = build_sweep_render_requests(
        graph,
        scene_state_payload=scene_state_payload,
        camera_spec_payload=camera_spec_payload,
        camera_specs_payload=camera_specs_payload,
        sensor_specs_payload=sensor_specs_payload,
        sensor_scope=sensor_scope,
        sensor_ids=sensor_ids,
        active_lights=active_lights,
        modalities=modalities,
        job_id_mode="per_heading",
    )
    for sweep_request in sweep_requests:
        bundle = render_fn(sweep_request.request, repo_root=root, variant=variant)
        manifest_ref = bundle.bundle_root.rstrip("/") + "/manifest.json"
        _set_heading_observation(graph, sweep_request.node_id, sweep_request.heading_id, list(sweep_request.request.modalities), manifest_ref)
    write_viewpoint_graph(graph_path, graph)
    return graph
