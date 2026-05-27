from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal


JsonDict = dict[str, Any]
RegionKind = Literal["box", "circle", "polygon"]


@dataclass
class AnnotatedObject:
    object_id: str
    category: str
    source_ref: str | None = None
    hazard_type: str | None = None
    geometry: JsonDict = field(default_factory=dict)
    mask_export: bool = False
    extras: JsonDict = field(default_factory=dict)


@dataclass
class GoalRegion:
    region_id: str
    center: list[float]
    radius: float = 0.4
    label: str | None = None
    landmark_refs: list[str] = field(default_factory=list)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class HazardRegion:
    region_id: str
    hazard_type: str
    geometry: JsonDict
    object_refs: list[str] = field(default_factory=list)
    collision_risk: bool = True
    extras: JsonDict = field(default_factory=dict)


@dataclass
class TraversableRegion:
    region_id: str
    geometry: JsonDict
    traversable: bool = True
    extras: JsonDict = field(default_factory=dict)


@dataclass
class Landmark:
    landmark_id: str
    label: str
    center: list[float]
    object_ref: str | None = None
    goal_candidate: bool = False
    extras: JsonDict = field(default_factory=dict)


@dataclass
class SceneAnnotation:
    scene_id: str
    usd_ref: str | None = None
    coordinate_system: str = "xy_yaw"
    objects: list[AnnotatedObject] = field(default_factory=list)
    transparent_surfaces: list[str] = field(default_factory=list)
    reflective_hazards: list[str] = field(default_factory=list)
    hazard_regions: list[HazardRegion] = field(default_factory=list)
    goal_regions: list[GoalRegion] = field(default_factory=list)
    landmarks: list[Landmark] = field(default_factory=list)
    traversable_regions: list[TraversableRegion] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)
    schema_version: str = "0.1"


def _validate_relative_ref(value: str | None, *, field_name: str) -> None:
    if not value:
        return
    path = PurePosixPath(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{field_name} must be package-relative: {value}")


def _validate_xy(value: list[float], *, field_name: str) -> None:
    if len(value) < 2:
        raise ValueError(f"{field_name} must contain at least x and y.")
    float(value[0])
    float(value[1])


def _validate_geometry(geometry: JsonDict, *, field_name: str) -> None:
    kind = geometry.get("type", "box")
    if kind == "box":
        bounds = geometry.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError(f"{field_name}.bounds must be [min_x, min_y, max_x, max_y].")
        min_x, min_y, max_x, max_y = [float(item) for item in bounds]
        if max_x <= min_x or max_y <= min_y:
            raise ValueError(f"{field_name}.bounds must have positive extent.")
    elif kind == "circle":
        center = geometry.get("center")
        radius = float(geometry.get("radius", 0.0))
        if not isinstance(center, list):
            raise ValueError(f"{field_name}.center must be [x, y].")
        _validate_xy(center, field_name=f"{field_name}.center")
        if radius <= 0:
            raise ValueError(f"{field_name}.radius must be positive.")
    elif kind == "polygon":
        points = geometry.get("points")
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError(f"{field_name}.points must contain at least 3 points.")
        for point in points:
            _validate_xy(point, field_name=f"{field_name}.points[]")
    else:
        raise ValueError(f"Unsupported {field_name}.type: {kind}")


def validate_scene_annotation(annotation: SceneAnnotation) -> None:
    if not annotation.scene_id:
        raise ValueError("scene_id must not be empty.")
    _validate_relative_ref(annotation.usd_ref, field_name="usd_ref")
    object_ids = {item.object_id for item in annotation.objects}
    if len(object_ids) != len(annotation.objects):
        raise ValueError("objects must have unique object_id values.")
    for obj in annotation.objects:
        if not obj.object_id:
            raise ValueError("object_id must not be empty.")
        if not obj.category:
            raise ValueError(f"object {obj.object_id} category must not be empty.")
        _validate_relative_ref(obj.source_ref, field_name=f"objects.{obj.object_id}.source_ref")
        if obj.geometry:
            _validate_geometry(obj.geometry, field_name=f"objects.{obj.object_id}.geometry")
    for object_id in annotation.transparent_surfaces + annotation.reflective_hazards:
        if object_id not in object_ids:
            raise ValueError(f"Unknown object reference: {object_id}")
    goal_ids = set()
    for goal in annotation.goal_regions:
        if not goal.region_id:
            raise ValueError("goal region_id must not be empty.")
        if goal.region_id in goal_ids:
            raise ValueError(f"Duplicate goal region_id: {goal.region_id}")
        goal_ids.add(goal.region_id)
        _validate_xy(goal.center, field_name=f"goal_regions.{goal.region_id}.center")
        if float(goal.radius) <= 0:
            raise ValueError(f"goal_regions.{goal.region_id}.radius must be positive.")
    if not annotation.goal_regions:
        raise ValueError("At least one goal region is required.")
    for hazard in annotation.hazard_regions:
        if not hazard.region_id:
            raise ValueError("hazard region_id must not be empty.")
        if not hazard.hazard_type:
            raise ValueError(f"hazard_regions.{hazard.region_id}.hazard_type must not be empty.")
        _validate_geometry(hazard.geometry, field_name=f"hazard_regions.{hazard.region_id}.geometry")
        for object_id in hazard.object_refs:
            if object_id not in object_ids:
                raise ValueError(f"Unknown hazard object reference: {object_id}")
    for region in annotation.traversable_regions:
        if not region.region_id:
            raise ValueError("traversable region_id must not be empty.")
        _validate_geometry(region.geometry, field_name=f"traversable_regions.{region.region_id}.geometry")
    if not annotation.traversable_regions:
        raise ValueError("At least one traversable region is required.")


def scene_annotation_to_payload(annotation: SceneAnnotation) -> JsonDict:
    return asdict(annotation)


def scene_annotation_from_payload(payload: JsonDict) -> SceneAnnotation:
    annotation = SceneAnnotation(
        scene_id=str(payload["scene_id"]),
        usd_ref=payload.get("usd_ref"),
        coordinate_system=str(payload.get("coordinate_system", "xy_yaw")),
        objects=[AnnotatedObject(**item) for item in payload.get("objects", [])],
        transparent_surfaces=[str(item) for item in payload.get("transparent_surfaces", [])],
        reflective_hazards=[str(item) for item in payload.get("reflective_hazards", [])],
        hazard_regions=[HazardRegion(**item) for item in payload.get("hazard_regions", [])],
        goal_regions=[GoalRegion(**item) for item in payload.get("goal_regions", [])],
        landmarks=[Landmark(**item) for item in payload.get("landmarks", [])],
        traversable_regions=[TraversableRegion(**item) for item in payload.get("traversable_regions", [])],
        metadata=dict(payload.get("metadata", {})),
        schema_version=str(payload.get("schema_version", "0.1")),
    )
    validate_scene_annotation(annotation)
    return annotation


def read_scene_annotation(path: str | Path) -> SceneAnnotation:
    return scene_annotation_from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def write_scene_annotation(path: str | Path, annotation: SceneAnnotation) -> Path:
    validate_scene_annotation(annotation)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scene_annotation_to_payload(annotation), ensure_ascii=False, indent=2), encoding="utf-8")
    return output
