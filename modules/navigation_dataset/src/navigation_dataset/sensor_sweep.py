from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Callable

from .viewpoint_graph import ViewpointGraph, write_viewpoint_graph


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


def _mat4_from_xy_yaw(x: float, y: float, yaw_rad: float, height_m: float = 1.0) -> list[float]:
    c = math.cos(yaw_rad)
    s = math.sin(yaw_rad)
    return [
        c, 0.0, -s, 0.0,
        0.0, 1.0, 0.0, 0.0,
        s, 0.0, c, 0.0,
        float(x), float(height_m), float(y), 1.0,
    ]


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


def build_sweep_render_requests(
    graph: ViewpointGraph,
    *,
    scene_state_payload: dict,
    camera_spec_payload: dict,
    modalities: list[str],
    job_id_mode: str = "per_heading",
    node_ids: list[str] | None = None,
    camera_height_m: float = 1.0,
    render_settings: dict | None = None,
    node_heights: dict | None = None,
) -> list[SweepRenderRequest]:
    from robomituba_bridge import RenderRequest, RobotState
    from robomituba_bridge import camera_spec_from_payload, scene_state_from_payload

    scene_state = scene_state_from_payload(scene_state_payload)
    camera_template = camera_spec_from_payload(camera_spec_payload)
    node_id_set = set(node_ids) if node_ids else None
    requests: list[SweepRenderRequest] = []
    for node in graph.nodes:
        if node_id_set is not None and node.node_id not in node_id_set:
            continue
        for heading in node.headings:
            frame_id = f"{graph.scene_id}_{node.node_id}_{heading.heading_id}"
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            mod_suffix = _modality_suffix(list(modalities))
            job_id = scene_state.job_id
            if job_id_mode == "per_heading":
                job_id = f"{scene_state.job_id}-{node.node_id}-{heading.heading_id}{mod_suffix}"
            elif job_id_mode != "shared":
                raise ValueError("job_id_mode must be 'shared' or 'per_heading'.")
            yaw_rad = math.radians(float(heading.yaw_deg))
            # Per-viewpoint height override (UI's "Camera height" slider against a selected viewpoint).
            node_height = camera_height_m
            if node_heights and node.node_id in node_heights:
                try:
                    node_height = float(node_heights[node.node_id])
                except (TypeError, ValueError):
                    pass
            pose = _sensor_pose_from_xy_yaw(float(node.position[0]), float(node.position[1]), yaw_rad, camera_template, fallback_height_m=node_height)
            timestep_scene_state = replace(scene_state, job_id=job_id, frame_id=frame_id, timestamp=timestamp)
            camera_spec = replace(camera_template, camera_to_world=pose, sensor_modality="multimodal")
            request = RenderRequest(
                request_id=f"{graph.graph_id}-{node.node_id}-{heading.heading_id}",
                job_id=timestep_scene_state.job_id,
                frame_id=frame_id,
                timestamp=timestamp,
                scene_state=timestep_scene_state,
                camera_specs=[camera_spec],
                modalities=list(modalities),
                robot_state=RobotState(base_pose=pose),
                render_settings=dict(render_settings or {}),
                extras={
                    "graph_id": graph.graph_id,
                    "scene_id": graph.scene_id,
                    "node_id": node.node_id,
                    "heading_id": heading.heading_id,
                    "yaw_deg": float(heading.yaw_deg),
                    "render_mode": "viewpoint_sweep",
                },
            )
            requests.append(SweepRenderRequest(node_id=node.node_id, heading_id=heading.heading_id, request=request))
    return requests


def build_custom_position_render_requests(
    custom_positions: list[dict],
    *,
    scene_state_payload: dict,
    camera_spec_payload: dict,
    modalities: list[str],
    scene_id: str,
    camera_height_m: float = 1.0,
    render_settings: dict | None = None,
) -> list[SweepRenderRequest]:
    """Build render requests for arbitrary (x, y, yaw_deg) positions not in the graph."""
    from robomituba_bridge import RenderRequest, RobotState
    from robomituba_bridge import camera_spec_from_payload, scene_state_from_payload

    scene_state = scene_state_from_payload(scene_state_payload)
    camera_template = camera_spec_from_payload(camera_spec_payload)
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
        pose = _sensor_pose_from_xy_yaw(x, y, yaw_rad, camera_template, fallback_height_m=per_pos_height)
        frame_id = f"{scene_id}_{node_id}_{heading_id}"
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        job_id = f"{scene_state.job_id}-{node_id}-{heading_id}{_modality_suffix(list(modalities))}"
        timestep_scene_state = replace(scene_state, job_id=job_id, frame_id=frame_id, timestamp=timestamp)
        camera_spec = replace(camera_template, camera_to_world=pose, sensor_modality="multimodal")
        request = RenderRequest(
            request_id=str(pos.get("request_id") or f"custom-{node_id}-{heading_id}"),
            job_id=job_id,
            frame_id=frame_id,
            timestamp=timestamp,
            scene_state=timestep_scene_state,
            camera_specs=[camera_spec],
            modalities=list(modalities),
            robot_state=RobotState(base_pose=pose),
            render_settings=dict(render_settings or {}),
            extras={
                "scene_id": scene_id,
                "node_id": node_id,
                "heading_id": heading_id,
                "yaw_deg": yaw_deg,
                "render_mode": str(pos.get("render_mode") or "custom_position"),
            },
        )
        if pos.get("preview_id") is not None:
            request.extras["preview_id"] = str(pos["preview_id"])
        requests.append(SweepRenderRequest(node_id=node_id, heading_id=heading_id, request=request))
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
    camera_spec_payload: dict,
    modalities: list[str],
    render_fn: Callable | None = None,
    variant: str = "auto",
) -> ViewpointGraph:
    if render_fn is None:
        from mitsuba_converter import render_timestep_bundle_split_lighting

        render_fn = render_timestep_bundle_split_lighting
    root = Path(dataset_root).resolve()
    sweep_requests = build_sweep_render_requests(
        graph,
        scene_state_payload=scene_state_payload,
        camera_spec_payload=camera_spec_payload,
        modalities=modalities,
        job_id_mode="per_heading",
    )
    for sweep_request in sweep_requests:
        bundle = render_fn(sweep_request.request, repo_root=root, variant=variant)
        manifest_ref = bundle.bundle_root.rstrip("/") + "/manifest.json"
        _set_heading_observation(graph, sweep_request.node_id, sweep_request.heading_id, modalities, manifest_ref)
    write_viewpoint_graph(graph_path, graph)
    return graph
