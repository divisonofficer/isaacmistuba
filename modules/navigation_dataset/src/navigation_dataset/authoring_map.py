from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Literal


JsonDict = dict[str, Any]
PlacementType = Literal["point", "line", "rectangle"]
GeometryType = Literal["point", "line", "rectangle"]

AUTHORING_MAP_VERSION = "opticalnav-authoring-map-v0.2"
OBJECT_TYPES = {
    "wall",
    "glass_wall",
    "glass_door",
    "mirror_wall",
    "transparent_partition",
    "chair",
    "table",
    "plant",
    "shelf",
    "landmark",
}
REGION_TYPES = {
    "traversable",
    "obstacle",
    "hazard",
    "goal",
    "start",
    "forbidden",
    "stop_before",
}
PLACEMENT_TYPES = {"point", "line", "rectangle"}
GEOMETRY_TYPES = {"point", "line", "rectangle"}
MATERIAL_PRESETS = {
    "painted_wall",
    "clear_glass",
    "frosted_glass",
    "mirror",
    "wood",
    "fabric",
    "tile",
}


@dataclass
class AuthoringMapIssue:
    id: str | None
    field: str
    reason: str
    action: str | None = None

    def to_payload(self) -> JsonDict:
        payload: JsonDict = {"field": self.field, "reason": self.reason}
        if self.id is not None:
            payload["id"] = self.id
        if self.action:
            payload["action"] = self.action
        return payload


class AuthoringMapValidationError(ValueError):
    def __init__(self, issues: list[AuthoringMapIssue]):
        self.issues = issues
        message = "; ".join(f"{item.id or 'map'}:{item.field}: {item.reason}" for item in issues)
        super().__init__(message or "Invalid authoring map.")

    def to_payload(self) -> JsonDict:
        return {
            "ok": False,
            "stage": "validate_authoring_map",
            "status": "blocked",
            "message": "Authoring map is invalid.",
            "errors": [item.to_payload() for item in self.issues],
        }


@dataclass
class AuthoringGeometry:
    type: str
    center: list[float] | None = None
    yaw_deg: float = 0.0
    start: list[float] | None = None
    end: list[float] | None = None
    bounds: list[float] | None = None
    height_m: float | None = None
    thickness_m: float | None = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class AuthoringNavigationFlags:
    blocks_navigation: bool = False
    hazard_type: str | None = None
    include_in_hazard_mask: bool = False
    instruction_candidate: bool = False
    goal_candidate: bool = False


@dataclass
class AuthoringMaterial:
    material_id: str
    category: str | None = None
    params: JsonDict = field(default_factory=dict)


@dataclass
class AuthoringObject:
    id: str
    type: str
    label: str
    placement: str
    geometry: AuthoringGeometry
    material: str | None = None
    navigation: AuthoringNavigationFlags = field(default_factory=AuthoringNavigationFlags)
    source_ref: str | None = None
    metadata: JsonDict = field(default_factory=dict)


@dataclass
class AuthoringRegion:
    id: str
    type: str
    label: str
    placement: str
    geometry: AuthoringGeometry
    navigation: AuthoringNavigationFlags = field(default_factory=AuthoringNavigationFlags)
    metadata: JsonDict = field(default_factory=dict)


@dataclass
class AuthoringMap:
    scene_id: str
    version: str = AUTHORING_MAP_VERSION
    unit: str = "meter"
    floorplan_ref: str | None = None
    objects: list[AuthoringObject] = field(default_factory=list)
    regions: list[AuthoringRegion] = field(default_factory=list)
    materials: list[AuthoringMaterial] = field(default_factory=list)
    settings: JsonDict = field(default_factory=lambda: {
        "grid_size_m": 0.25,
        "default_wall_height_m": 2.4,
        "default_wall_thickness_m": 0.08,
    })
    metadata: JsonDict = field(default_factory=dict)


def _issue(issues: list[AuthoringMapIssue], item_id: str | None, field_name: str, reason: str, action: str | None = None) -> None:
    issues.append(AuthoringMapIssue(id=item_id, field=field_name, reason=reason, action=action))


def _as_float_pair(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        return [float(value[0]), float(value[1])]
    except Exception:
        return None


def _normalize_geometry(payload: Any) -> AuthoringGeometry:
    if isinstance(payload, AuthoringGeometry):
        return payload
    data = dict(payload or {})
    extras = dict(data.get("extras", {}))
    return AuthoringGeometry(
        type=str(data.get("type") or ""),
        center=[float(item) for item in data["center"]] if isinstance(data.get("center"), list) else None,
        yaw_deg=float(data.get("yaw_deg", 0.0)),
        start=[float(item) for item in data["start"]] if isinstance(data.get("start"), list) else None,
        end=[float(item) for item in data["end"]] if isinstance(data.get("end"), list) else None,
        bounds=[float(item) for item in data["bounds"]] if isinstance(data.get("bounds"), list) else None,
        height_m=float(data["height_m"]) if data.get("height_m") is not None else None,
        thickness_m=float(data["thickness_m"]) if data.get("thickness_m") is not None else None,
        extras=extras,
    )


def _normalize_navigation(payload: Any) -> AuthoringNavigationFlags:
    if isinstance(payload, AuthoringNavigationFlags):
        return payload
    data = dict(payload or {})
    return AuthoringNavigationFlags(
        blocks_navigation=bool(data.get("blocks_navigation", False)),
        hazard_type=str(data["hazard_type"]) if data.get("hazard_type") else None,
        include_in_hazard_mask=bool(data.get("include_in_hazard_mask", False)),
        instruction_candidate=bool(data.get("instruction_candidate", False)),
        goal_candidate=bool(data.get("goal_candidate", False)),
    )


def _normalize_material(payload: Any) -> AuthoringMaterial:
    if isinstance(payload, AuthoringMaterial):
        return payload
    if isinstance(payload, str):
        return AuthoringMaterial(material_id=payload)
    data = dict(payload or {})
    return AuthoringMaterial(
        material_id=str(data.get("material_id") or data.get("id") or ""),
        category=str(data["category"]) if data.get("category") else None,
        params=dict(data.get("params", {})),
    )


def _normalize_object(payload: Any) -> AuthoringObject:
    if isinstance(payload, AuthoringObject):
        return payload
    data = dict(payload or {})
    object_type = str(data.get("type") or "")
    return AuthoringObject(
        id=str(data.get("id") or ""),
        type=object_type,
        label=str(data.get("label") or object_type or data.get("id") or ""),
        placement=str(data.get("placement") or ""),
        geometry=_normalize_geometry(data.get("geometry")),
        material=str(data["material"]) if data.get("material") else None,
        navigation=_normalize_navigation(data.get("navigation")),
        source_ref=str(data["source_ref"]) if data.get("source_ref") else None,
        metadata=dict(data.get("metadata", {})),
    )


def _normalize_region(payload: Any) -> AuthoringRegion:
    if isinstance(payload, AuthoringRegion):
        return payload
    data = dict(payload or {})
    region_type = str(data.get("type") or "")
    return AuthoringRegion(
        id=str(data.get("id") or ""),
        type=region_type,
        label=str(data.get("label") or region_type or data.get("id") or ""),
        placement=str(data.get("placement") or ""),
        geometry=_normalize_geometry(data.get("geometry")),
        navigation=_normalize_navigation(data.get("navigation")),
        metadata=dict(data.get("metadata", {})),
    )


def authoring_map_from_payload(payload: JsonDict | AuthoringMap) -> AuthoringMap:
    if isinstance(payload, AuthoringMap):
        return payload
    data = dict(payload or {})
    return AuthoringMap(
        scene_id=str(data.get("scene_id") or ""),
        version=str(data.get("version") or AUTHORING_MAP_VERSION),
        unit=str(data.get("unit") or "meter"),
        floorplan_ref=str(data["floorplan_ref"]) if data.get("floorplan_ref") else None,
        objects=[_normalize_object(item) for item in data.get("objects", [])],
        regions=[_normalize_region(item) for item in data.get("regions", [])],
        materials=[_normalize_material(item) for item in data.get("materials", [])],
        settings=dict(data.get("settings", {})) or {
            "grid_size_m": 0.25,
            "default_wall_height_m": 2.4,
            "default_wall_thickness_m": 0.08,
        },
        metadata=dict(data.get("metadata", {})),
    )


def authoring_map_to_payload(authoring_map: AuthoringMap | JsonDict) -> JsonDict:
    model = authoring_map_from_payload(authoring_map) if isinstance(authoring_map, dict) else authoring_map
    return asdict(model)


def _validate_geometry(item_id: str, placement: str, geometry: AuthoringGeometry, issues: list[AuthoringMapIssue]) -> None:
    if geometry.type not in GEOMETRY_TYPES:
        _issue(issues, item_id, "geometry.type", f"Unsupported geometry type: {geometry.type!r}.", "choose_supported_geometry")
        return
    if placement and placement != geometry.type:
        _issue(issues, item_id, "placement", f"Placement {placement!r} must match geometry type {geometry.type!r}.", "match_placement_to_geometry")

    if geometry.type == "point":
        if _as_float_pair(geometry.center) is None:
            _issue(issues, item_id, "geometry.center", "Point geometry requires center [x, y].", "set_center")
    elif geometry.type == "line":
        start = _as_float_pair(geometry.start)
        end = _as_float_pair(geometry.end)
        if start is None:
            _issue(issues, item_id, "geometry.start", "Line geometry requires start [x, y].", "set_line_start")
        if end is None:
            _issue(issues, item_id, "geometry.end", "Line geometry requires end [x, y].", "set_line_end")
        if start is not None and end is not None and math.hypot(end[0] - start[0], end[1] - start[1]) <= 1e-6:
            _issue(issues, item_id, "geometry.end", "Line geometry must have positive length.", "move_line_endpoint")
    elif geometry.type == "rectangle":
        bounds = geometry.bounds
        if not isinstance(bounds, list) or len(bounds) != 4:
            _issue(issues, item_id, "geometry.bounds", "Rectangle geometry requires bounds [min_x, min_y, max_x, max_y].", "set_bounds")
            return
        min_x, min_y, max_x, max_y = [float(item) for item in bounds]
        if max_x <= min_x or max_y <= min_y:
            _issue(issues, item_id, "geometry.bounds", "Rectangle geometry must have positive area.", "resize_region")


def validate_authoring_map(authoring_map: AuthoringMap | JsonDict, *, require_compile_ready: bool = False) -> None:
    model = authoring_map_from_payload(authoring_map) if isinstance(authoring_map, dict) else authoring_map
    issues: list[AuthoringMapIssue] = []
    if not model.scene_id:
        _issue(issues, None, "scene_id", "scene_id must not be empty.", "set_scene_id")
    if model.unit != "meter":
        _issue(issues, None, "unit", "Only unit='meter' is supported in v0.2.", "set_unit_meter")

    object_ids: set[str] = set()
    for obj in model.objects:
        if not obj.id:
            _issue(issues, None, "objects[].id", "Object id must not be empty.", "set_object_id")
        elif obj.id in object_ids:
            _issue(issues, obj.id, "id", "Object ids must be unique.", "rename_object")
        object_ids.add(obj.id)
        if obj.type not in OBJECT_TYPES:
            _issue(issues, obj.id or None, "type", f"Unsupported object type: {obj.type!r}.", "choose_supported_object_type")
        if obj.placement not in PLACEMENT_TYPES:
            _issue(issues, obj.id or None, "placement", f"Unsupported placement: {obj.placement!r}.", "choose_supported_placement")
        if obj.material and obj.material not in MATERIAL_PRESETS and obj.material not in {item.material_id for item in model.materials}:
            _issue(issues, obj.id or None, "material", f"Unknown material preset: {obj.material!r}.", "choose_supported_material")
        _validate_geometry(obj.id, obj.placement, obj.geometry, issues)

    region_ids: set[str] = set()
    for region in model.regions:
        if not region.id:
            _issue(issues, None, "regions[].id", "Region id must not be empty.", "set_region_id")
        elif region.id in region_ids:
            _issue(issues, region.id, "id", "Region ids must be unique.", "rename_region")
        region_ids.add(region.id)
        if region.type not in REGION_TYPES:
            _issue(issues, region.id or None, "type", f"Unsupported region type: {region.type!r}.", "choose_supported_region_type")
        if region.placement not in PLACEMENT_TYPES:
            _issue(issues, region.id or None, "placement", f"Unsupported placement: {region.placement!r}.", "choose_supported_placement")
        _validate_geometry(region.id, region.placement, region.geometry, issues)

    material_ids: set[str] = set()
    for material in model.materials:
        if not material.material_id:
            _issue(issues, None, "materials[].material_id", "Material id must not be empty.", "set_material_id")
        elif material.material_id in material_ids:
            _issue(issues, material.material_id, "material_id", "Material ids must be unique.", "rename_material")
        material_ids.add(material.material_id)

    if require_compile_ready:
        if not any(region.type == "traversable" for region in model.regions):
            _issue(issues, None, "regions", "At least one traversable region is required before compile.", "draw_traversable_region")
        if not any(region.type == "goal" for region in model.regions):
            _issue(issues, None, "regions", "At least one goal region is required before compile.", "draw_goal_region")

    if issues:
        raise AuthoringMapValidationError(issues)


def starter_authoring_map(scene_id: str, floorplan_ref: str | None = None) -> AuthoringMap:
    return AuthoringMap(
        scene_id=scene_id,
        floorplan_ref=floorplan_ref,
        metadata={"starter": True},
    )


def load_authoring_map(path: str | Path) -> AuthoringMap:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    model = authoring_map_from_payload(payload)
    validate_authoring_map(model)
    return model


def save_authoring_map(path: str | Path, authoring_map: AuthoringMap | JsonDict) -> Path:
    model = authoring_map_from_payload(authoring_map) if isinstance(authoring_map, dict) else authoring_map
    validate_authoring_map(model)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(authoring_map_to_payload(model), ensure_ascii=False, indent=2), encoding="utf-8")
    return output

