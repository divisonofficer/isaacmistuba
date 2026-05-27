from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Callable

from .viewpoint_graph import ViewpointGraph, write_viewpoint_graph


@dataclass
class SweepRenderRequest:
    node_id: str
    heading_id: str
    request: object


def _mat4_from_xy_yaw(x: float, y: float, yaw_rad: float) -> list[float]:
    c = math.cos(yaw_rad)
    s = math.sin(yaw_rad)
    return [
        c, 0.0, -s, 0.0,
        0.0, 1.0, 0.0, 0.0,
        s, 0.0, c, 0.0,
        float(x), 0.0, float(y), 1.0,
    ]


def build_sweep_render_requests(
    graph: ViewpointGraph,
    *,
    scene_state_payload: dict,
    camera_spec_payload: dict,
    modalities: list[str],
    job_id_mode: str = "per_heading",
) -> list[SweepRenderRequest]:
    from robomituba_bridge import RenderRequest, RobotState
    from robomituba_bridge import camera_spec_from_payload, scene_state_from_payload

    scene_state = scene_state_from_payload(scene_state_payload)
    camera_template = camera_spec_from_payload(camera_spec_payload)
    requests: list[SweepRenderRequest] = []
    for node in graph.nodes:
        for heading in node.headings:
            frame_id = f"{graph.scene_id}_{node.node_id}_{heading.heading_id}"
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            job_id = scene_state.job_id
            if job_id_mode == "per_heading":
                job_id = f"{scene_state.job_id}-{node.node_id}-{heading.heading_id}"
            elif job_id_mode != "shared":
                raise ValueError("job_id_mode must be 'shared' or 'per_heading'.")
            yaw_rad = math.radians(float(heading.yaw_deg))
            pose = _mat4_from_xy_yaw(float(node.position[0]), float(node.position[1]), yaw_rad)
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
