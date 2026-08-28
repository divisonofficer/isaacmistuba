"""Editor-geometry fallbacks for OpticalNav scenes without a source USD.

The renderer's XML and the authoring map are sufficient to open an Infinigen
scene in the editor.  USD remains the preferred source when it exists, but it
must not be required for the editor to establish a useful world extent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


_DEFAULT_BOUNDS = {
    "min": [0.0, 0.0, 0.0],
    "max": [6.0, 0.1, 4.0],
    "size": [6.0, 0.1, 4.0],
    "center": [3.0, 0.05, 2.0],
}


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write a JSON sidecar without exposing a partially-written document."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _bounds_payload(minimum: list[float], maximum: list[float]) -> dict[str, list[float]]:
    low = [float(minimum[0]), float(minimum[1]), float(minimum[2])]
    high = [
        max(low[0] + 1e-4, float(maximum[0])),
        max(low[1] + 1e-4, float(maximum[1])),
        max(low[2] + 1e-4, float(maximum[2])),
    ]
    return {
        "min": low,
        "max": high,
        "size": [high[index] - low[index] for index in range(3)],
        "center": [(high[index] + low[index]) * 0.5 for index in range(3)],
    }


def _extend_box(
    low: list[float], high: list[float], center: Any, size: Any, base_height: Any = 0.0,
) -> bool:
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return False
    if not isinstance(size, (list, tuple)) or len(size) < 2:
        return False
    try:
        x = float(center[0])
        z = float(center[1])
        sx = max(0.01, float(size[0]))
        sy = max(0.01, float(size[1] if len(size) > 1 else 0.1))
        sz = max(0.01, float(size[2] if len(size) > 2 else size[1]))
        y = float(base_height or 0.0)
    except (TypeError, ValueError):
        return False
    low[0] = min(low[0], x - sx * 0.5)
    low[1] = min(low[1], y)
    low[2] = min(low[2], z - sz * 0.5)
    high[0] = max(high[0], x + sx * 0.5)
    high[1] = max(high[1], y + sy)
    high[2] = max(high[2], z + sz * 0.5)
    return True


def authoring_map_bounds(authoring_map: Mapping[str, Any] | None) -> dict[str, list[float]]:
    """Derive a stable world-XZ extent from normal authoring objects/regions."""
    if not isinstance(authoring_map, Mapping):
        return dict(_DEFAULT_BOUNDS)
    low = [float("inf"), float("inf"), float("inf")]
    high = [float("-inf"), float("-inf"), float("-inf")]
    found = False
    for item in list(authoring_map.get("objects") or []) + list(authoring_map.get("regions") or []):
        if not isinstance(item, Mapping):
            continue
        geometry = item.get("geometry") if isinstance(item.get("geometry"), Mapping) else {}
        bounds = geometry.get("bounds") if isinstance(geometry, Mapping) else None
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
            try:
                x0, z0, x1, z1 = [float(value) for value in bounds[:4]]
                low[0] = min(low[0], x0)
                low[1] = min(low[1], float(geometry.get("base_height_m") or 0.0))
                low[2] = min(low[2], z0)
                high[0] = max(high[0], x1)
                high[1] = max(high[1], float(geometry.get("base_height_m") or 0.0) + 0.1)
                high[2] = max(high[2], z1)
                found = True
                continue
            except (TypeError, ValueError):
                pass
        found = _extend_box(
            low,
            high,
            geometry.get("center") if isinstance(geometry, Mapping) else None,
            geometry.get("size_m") if isinstance(geometry, Mapping) else None,
            geometry.get("base_height_m") if isinstance(geometry, Mapping) else 0.0,
        ) or found
    if not found:
        return dict(_DEFAULT_BOUNDS)
    return _bounds_payload(low, high)


def build_non_usd_editor_geometry(
    scene_dir: str | Path,
    scene_id: str,
    *,
    usd_ref: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build the geometry-status payload for XML-native or map-only scenes.

    XML-native object meshes are drawn from ``xml_scene_index.json`` by the
    browser, so this payload deliberately has no proxy objects.  That prevents
    duplicate bounding boxes behind the actual mesh previews.
    """
    directory = Path(scene_dir)
    authoring_path = directory / "authoring_map.json"
    xml_index_path = directory / "xml_scene_index.json"
    authoring_map: Mapping[str, Any] | None = None
    if authoring_path.is_file():
        try:
            payload = json.loads(authoring_path.read_text(encoding="utf-8"))
            authoring_map = payload if isinstance(payload, Mapping) else None
        except (OSError, json.JSONDecodeError):
            authoring_map = None

    xml_native = False
    if xml_index_path.is_file():
        try:
            index = json.loads(xml_index_path.read_text(encoding="utf-8"))
            xml_native = isinstance(index, Mapping) and isinstance(index.get("shapes"), list)
        except (OSError, json.JSONDecodeError):
            xml_native = False

    if xml_native:
        source = "xml_native"
        simplification_mode = "xml_mesh_preview_v1"
    elif authoring_map is not None:
        source = "authoring_map"
        simplification_mode = "authoring_map_bounds_v1"
    else:
        return {
            "scene_id": scene_id,
            "status": "unavailable",
            "source": "fallback",
            "reason": reason or "No USD, XML scene index, or authoring map is available.",
            "usd_ref": usd_ref,
            "coordinate_system": "world_xz_authoring",
            "bounds": dict(_DEFAULT_BOUNDS),
            "objects": [],
            "floor_planes": [{"id": "floor_fallback", "bounds": dict(_DEFAULT_BOUNDS)}],
        }

    bounds = authoring_map_bounds(authoring_map)
    return {
        "scene_id": scene_id,
        "status": "ready",
        "source": source,
        "reason": reason,
        "usd_ref": None,
        "coordinate_system": "world_xz_authoring",
        "simplification_mode": simplification_mode,
        "bounds": bounds,
        "objects": [],
        "floor_planes": [
            {
                "id": "floor_authoring_bounds",
                "bounds": _bounds_payload(
                    [bounds["min"][0], 0.0, bounds["min"][2]],
                    [bounds["max"][0], 0.05, bounds["max"][2]],
                ),
            }
        ],
    }
