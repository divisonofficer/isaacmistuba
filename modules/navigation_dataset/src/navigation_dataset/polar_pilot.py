"""Deterministic selection and contracts for the RGB-Stokes active-polar pilot."""
from __future__ import annotations

import hashlib
import heapq
import json
import math
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence


POLAR_STOKES_RGB_V2 = "rgb_stokes_12"
POLAR_PILOT_VARIANTS = ("base", "perturbed", "perturbed_active_polar")


def score_preview(path: str | Path) -> float:
    """Return a deterministic low-resolution content score for an RGB preview.

    It intentionally prefers views with both luminance variation and edges,
    avoiding a heading that points at a blank wall.  The score is only used to
    choose one heading *after* spatial node sampling, never to select nodes.
    """
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        gray = np.asarray(image.convert("L").resize((96, 64)), dtype=np.float32) / 255.0
    contrast = float(gray.std())
    edge_x = float(np.abs(np.diff(gray, axis=1)).mean())
    edge_y = float(np.abs(np.diff(gray, axis=0)).mean())
    return contrast + edge_x + edge_y


def scores_from_base_previews(scene_dir: str | Path) -> dict[tuple[str, str], float]:
    """Score available base previews without traversing render-output roots.

    Supports both consolidated OpticalNav observations and the per-sensor
    layout used by current render versions.  A caller may provide external
    scores when previews have not yet been generated.
    """
    root = Path(scene_dir) / "observations"
    scores: dict[tuple[str, str], float] = {}
    if not root.is_dir():
        return scores
    for vp_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for heading_dir in sorted(path for path in vp_dir.iterdir() if path.is_dir()):
            candidates = [
                heading_dir / "rgb.png",
                heading_dir / "polar_rgb_preview.png",
                *sorted((heading_dir / "sensors").glob("*/rgb.png")),
                *sorted((heading_dir / "cameras").glob("*/rgb.png")),
            ]
            preview = next((path for path in candidates if path.is_file()), None)
            if preview is not None:
                scores[(vp_dir.name, heading_dir.name)] = score_preview(preview)
    return scores


def active_polar_assist_payload() -> dict[str, Any]:
    """Camera-local white area light used only by the third pilot condition."""
    return {
        "mode": "camera_aligned_rect",
        "distance_m": 0.12,
        "size_world": [2.2, 1.6],
        "spectrum_mode": "rgb_white",
        "polarized": True,
        "polarizer_angle_deg": 0.0,
        "extras": {"radiance": 18.0, "protocol": "rgb_stokes_12_active_polar_v1"},
    }


def _edges(graph: Mapping[str, Any]) -> dict[str, list[tuple[str, float]]]:
    positions = {str(node.get("node_id")): node.get("position") for node in graph.get("nodes", [])}
    result: dict[str, list[tuple[str, float]]] = {node_id: [] for node_id in positions}
    for edge in graph.get("edges", []):
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source not in positions or target not in positions:
            continue
        a, b = positions[source], positions[target]
        if not (isinstance(a, Sequence) and isinstance(b, Sequence) and len(a) >= 2 and len(b) >= 2):
            continue
        distance = math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))
        result[source].append((target, distance))
        result[target].append((source, distance))
    return result


def _distances(source: str, adjacency: Mapping[str, Sequence[tuple[str, float]]]) -> dict[str, float]:
    result = {source: 0.0}
    queue: list[tuple[float, str]] = [(0.0, source)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != result.get(node):
            continue
        for target, weight in adjacency.get(node, []):
            candidate = cost + weight
            if candidate < result.get(target, float("inf")):
                result[target] = candidate
                heapq.heappush(queue, (candidate, target))
    return result


def select_spatially_diverse_nodes(graph: Mapping[str, Any], *, count: int = 10, seed: int = 20260811) -> list[str]:
    """Farthest-point sample graph nodes, deterministically across components."""
    node_ids = sorted(str(node.get("node_id")) for node in graph.get("nodes", []) if node.get("node_id"))
    if count < 1 or not node_ids:
        return []
    adjacency = _edges(graph)
    first = node_ids[int(hashlib.sha256(str(seed).encode()).hexdigest(), 16) % len(node_ids)]
    selected = [first]
    distance_maps = {first: _distances(first, adjacency)}
    while len(selected) < min(count, len(node_ids)):
        def score(node_id: str) -> tuple[float, str]:
            if node_id in selected:
                return (-1.0, node_id)
            nearest = min(mapping.get(node_id, float("inf")) for mapping in distance_maps.values())
            # Disconnected components are deliberately selected before a second
            # nearby node; use a stable finite sentinel for sorting.
            return (1e12 if math.isinf(nearest) else nearest, node_id)
        candidate = max(node_ids, key=score)
        selected.append(candidate)
        distance_maps[candidate] = _distances(candidate, adjacency)
    return selected


def select_pilot_views(
    graph: Mapping[str, Any], *, count: int = 10, seed: int = 20260811,
    heading_scores: Mapping[tuple[str, str], float] | None = None,
) -> list[dict[str, Any]]:
    """Choose one best-scored heading for each spatially diverse graph node."""
    nodes = {str(node.get("node_id")): node for node in graph.get("nodes", [])}
    result = []
    for node_id in select_spatially_diverse_nodes(graph, count=count, seed=seed):
        headings = sorted(nodes[node_id].get("headings") or [], key=lambda item: str(item.get("heading_id")))
        if not headings:
            continue
        chosen = max(headings, key=lambda item: (float((heading_scores or {}).get((node_id, str(item.get("heading_id"))), 0.0)), str(item.get("heading_id"))))
        result.append({
            "node_id": node_id,
            "heading_id": str(chosen.get("heading_id")),
            "yaw_deg": float(chosen.get("yaw_deg", 0.0)),
            "content_score": float((heading_scores or {}).get((node_id, str(chosen.get("heading_id"))), 0.0)),
        })
    return result


def build_pilot_contract(*, scene_id: str, graph_revision: str | None, views: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Serializable, immutable 30-capture pilot contract."""
    return {
        "schema": "opticalnav.polar_stokes_rgb_pilot.v1",
        "scene_id": scene_id,
        "graph_revision": graph_revision,
        "polar_color_mode": POLAR_STOKES_RGB_V2,
        "stokes_channel_order": ["S0_RGB", "S1_RGB", "S2_RGB", "S3_RGB"],
        "stokes_basis": "camera_image_x_y",
        "variants": list(POLAR_PILOT_VARIANTS),
        "active_polar_assist_light": active_polar_assist_payload(),
        "views": [dict(view) for view in views],
        "expected_capture_count": len(views) * len(POLAR_PILOT_VARIANTS),
    }


def _overlay_digest(render_request: Any) -> str:
    """Stable provenance for the shared perturbed overlay in a pilot triad."""
    existing = dict(render_request.extras or {}).get("overlay_digest")
    if isinstance(existing, str) and existing:
        return existing
    override = render_request.scene_override
    payload = asdict(override) if is_dataclass(override) else (override or {})
    scene_ref = str(getattr(render_request.scene_state, "mitsuba_scene_ref", ""))
    encoded = json.dumps({"scene_ref": scene_ref, "scene_override": payload}, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def with_polar_pilot_variant(render_request: Any, variant: str) -> Any:
    """Return one collision-free passive/active-polar request for a pilot view."""
    if variant not in POLAR_PILOT_VARIANTS:
        raise ValueError(f"unsupported polar pilot variant: {variant}")
    from robomituba_bridge import AssistLightSpec

    token = "perturbed-active-polar" if variant == "perturbed_active_polar" else variant
    job_id = f"{render_request.job_id}-{token}-polar"
    scene_state = replace(render_request.scene_state, job_id=job_id)
    settings = {**dict(render_request.render_settings or {}), "polar_color_mode": POLAR_STOKES_RGB_V2}
    extras = {
        **dict(render_request.extras or {}),
        "observation_variant": variant,
        "polar_active": variant == "perturbed_active_polar",
        "polar_pilot": True,
        # `perturbed` and `perturbed_active_polar` deliberately receive the
        # same digest; acceptance tooling can reject a mismatched overlay.
        "overlay_digest": _overlay_digest(render_request),
    }
    assist = AssistLightSpec(**active_polar_assist_payload()) if variant == "perturbed_active_polar" else None
    return replace(
        render_request,
        request_id=f"{render_request.request_id}-{token}-polar",
        job_id=job_id,
        scene_state=scene_state,
        render_settings=settings,
        assist_light=assist,
        # The pilot must not inherit a scene's preconfigured polar flash.
        active_lights=[],
        extras=extras,
    )
