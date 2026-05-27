from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .authoring_map import (
    AuthoringGeometry,
    AuthoringMap,
    AuthoringMapIssue,
    AuthoringMapValidationError,
    AuthoringObject,
    AuthoringRegion,
    authoring_map_from_payload,
    authoring_map_to_payload,
    validate_authoring_map,
)
from .scene_annotations import (
    AnnotatedObject,
    GoalRegion,
    HazardRegion,
    Landmark,
    SceneAnnotation,
    TraversableRegion,
    validate_scene_annotation,
)


JsonDict = dict[str, Any]

TRANSPARENT_TYPES = {"glass_wall", "glass_door", "transparent_partition"}
REFLECTIVE_TYPES = {"mirror_wall"}
POINT_FOOTPRINT_RADIUS = {
    "chair": 0.25,
    "table": 0.4,
    "plant": 0.18,
    "shelf": 0.35,
    "landmark": 0.15,
}


@dataclass
class AuthoringCompileResult:
    annotation: SceneAnnotation
    summary: JsonDict
    sync: JsonDict


class AuthoringMapCompileError(ValueError):
    def __init__(self, issues: list[AuthoringMapIssue]):
        self.issues = issues
        message = "; ".join(f"{item.id or 'map'}:{item.field}: {item.reason}" for item in issues)
        super().__init__(message or "Authoring map cannot be compiled.")

    def to_payload(self) -> JsonDict:
        return {
            "ok": False,
            "stage": "compile_annotation",
            "status": "blocked",
            "message": "Authoring map cannot be compiled.",
            "errors": [item.to_payload() for item in self.issues],
        }


def _issue(issues: list[AuthoringMapIssue], item_id: str | None, field_name: str, reason: str, action: str | None = None) -> None:
    issues.append(AuthoringMapIssue(id=item_id, field=field_name, reason=reason, action=action))


def _pair(value: list[float] | None) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("expected [x, y]")
    return float(value[0]), float(value[1])


def _line_to_box(geometry: AuthoringGeometry) -> JsonDict:
    sx, sy = _pair(geometry.start)
    ex, ey = _pair(geometry.end)
    half = max(0.005, float(geometry.thickness_m or 0.08) / 2.0)
    return {
        "type": "box",
        "bounds": [
            min(sx, ex) - half,
            min(sy, ey) - half,
            max(sx, ex) + half,
            max(sy, ey) + half,
        ],
    }


def _rectangle_to_box(geometry: AuthoringGeometry) -> JsonDict:
    if not isinstance(geometry.bounds, list) or len(geometry.bounds) != 4:
        raise ValueError("rectangle requires bounds")
    min_x, min_y, max_x, max_y = [float(item) for item in geometry.bounds]
    return {"type": "box", "bounds": [min_x, min_y, max_x, max_y]}


def _point_to_circle(geometry: AuthoringGeometry, *, radius: float) -> JsonDict:
    cx, cy = _pair(geometry.center)
    return {"type": "circle", "center": [cx, cy], "radius": float(radius)}


def _geometry_to_annotation(geometry: AuthoringGeometry, *, point_radius: float = 0.2) -> JsonDict:
    if geometry.type == "line":
        return _line_to_box(geometry)
    if geometry.type == "rectangle":
        return _rectangle_to_box(geometry)
    if geometry.type == "point":
        return _point_to_circle(geometry, radius=point_radius)
    raise ValueError(f"Unsupported authoring geometry type: {geometry.type}")


def _geometry_center(geometry: AuthoringGeometry) -> list[float]:
    if geometry.type == "point":
        cx, cy = _pair(geometry.center)
        return [cx, cy, float(geometry.yaw_deg or 0.0)]
    if geometry.type == "line":
        sx, sy = _pair(geometry.start)
        ex, ey = _pair(geometry.end)
        return [(sx + ex) / 2.0, (sy + ey) / 2.0, 0.0]
    if geometry.type == "rectangle":
        box = _rectangle_to_box(geometry)
        min_x, min_y, max_x, max_y = [float(item) for item in box["bounds"]]
        return [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0, 0.0]
    raise ValueError(f"Unsupported authoring geometry type: {geometry.type}")


def _goal_radius(geometry: AuthoringGeometry) -> float:
    if geometry.type == "rectangle":
        min_x, min_y, max_x, max_y = [float(item) for item in _rectangle_to_box(geometry)["bounds"]]
        return max(0.05, min(max_x - min_x, max_y - min_y) / 2.0)
    if geometry.type == "point":
        return 0.35
    if geometry.type == "line":
        sx, sy = _pair(geometry.start)
        ex, ey = _pair(geometry.end)
        return max(0.05, math.hypot(ex - sx, ey - sy) / 2.0)
    return 0.35


def _hazard_type_for_object(obj: AuthoringObject) -> str | None:
    if obj.navigation.hazard_type:
        return obj.navigation.hazard_type
    if obj.type == "glass_door":
        return "glass_door"
    if obj.type in TRANSPARENT_TYPES:
        return "transparent_obstacle"
    if obj.type in REFLECTIVE_TYPES:
        return "reflective_obstacle"
    return None


def _object_category(obj: AuthoringObject) -> str:
    if obj.type in TRANSPARENT_TYPES:
        return "transparent_surface"
    if obj.type in REFLECTIVE_TYPES:
        return "reflective_hazard"
    if obj.navigation.blocks_navigation and obj.type == "wall":
        return "obstacle"
    return obj.type


def _source_extras(item: AuthoringObject | AuthoringRegion) -> JsonDict:
    return {
        "authoring_id": item.id,
        "authoring_type": item.type,
        "source_geometry": item.geometry.__dict__,
        "navigation": item.navigation.__dict__,
        **dict(item.metadata or {}),
    }


def compile_authoring_map(authoring_map: AuthoringMap | JsonDict, *, usd_ref: str | None = None) -> AuthoringCompileResult:
    try:
        model = authoring_map_from_payload(authoring_map) if isinstance(authoring_map, dict) else authoring_map
        validate_authoring_map(model, require_compile_ready=True)
    except AuthoringMapValidationError as exc:
        raise AuthoringMapCompileError(exc.issues) from exc
    except Exception as exc:
        raise AuthoringMapCompileError([AuthoringMapIssue(None, "authoring_map", str(exc), "fix_authoring_map")]) from exc

    issues: list[AuthoringMapIssue] = []
    objects: list[AnnotatedObject] = []
    transparent_surfaces: list[str] = []
    reflective_hazards: list[str] = []
    hazard_regions: list[HazardRegion] = []
    goal_regions: list[GoalRegion] = []
    landmarks: list[Landmark] = []
    traversable_regions: list[TraversableRegion] = []
    metadata_regions: list[JsonDict] = []

    for obj in model.objects:
        try:
            point_radius = POINT_FOOTPRINT_RADIUS.get(obj.type, 0.2)
            geometry = _geometry_to_annotation(obj.geometry, point_radius=point_radius)
            hazard_type = _hazard_type_for_object(obj)
            mask_export = bool(obj.navigation.include_in_hazard_mask or hazard_type)
            annotated = AnnotatedObject(
                object_id=obj.id,
                category=_object_category(obj),
                source_ref=obj.source_ref,
                hazard_type=hazard_type,
                geometry=geometry,
                mask_export=mask_export,
                extras={
                    **_source_extras(obj),
                    "material": obj.material,
                    "height_m": obj.geometry.height_m,
                    "thickness_m": obj.geometry.thickness_m,
                },
            )
            objects.append(annotated)
            if obj.type in TRANSPARENT_TYPES:
                transparent_surfaces.append(obj.id)
            if obj.type in REFLECTIVE_TYPES:
                reflective_hazards.append(obj.id)
            if hazard_type:
                hazard_regions.append(
                    HazardRegion(
                        region_id=f"hazard_{obj.id}",
                        hazard_type=hazard_type,
                        geometry=geometry,
                        object_refs=[obj.id],
                        collision_risk=True,
                        extras=_source_extras(obj),
                    )
                )
            if obj.navigation.blocks_navigation:
                traversable_regions.append(
                    TraversableRegion(
                        region_id=f"obstacle_{obj.id}",
                        geometry=geometry,
                        traversable=False,
                        extras=_source_extras(obj),
                    )
                )
            if obj.navigation.instruction_candidate or obj.navigation.goal_candidate or obj.type in {"chair", "table", "plant", "landmark"}:
                landmarks.append(
                    Landmark(
                        landmark_id=obj.id,
                        label=obj.label or obj.id,
                        center=_geometry_center(obj.geometry),
                        object_ref=obj.id,
                        goal_candidate=bool(obj.navigation.goal_candidate),
                        extras=_source_extras(obj),
                    )
                )
        except Exception as exc:
            _issue(issues, obj.id, "geometry", str(exc), "fix_object_geometry")

    for region in model.regions:
        try:
            geometry = _geometry_to_annotation(region.geometry, point_radius=0.35)
            if region.type == "goal":
                goal_regions.append(
                    GoalRegion(
                        region_id=region.id,
                        center=_geometry_center(region.geometry),
                        radius=_goal_radius(region.geometry),
                        label=region.label or region.id,
                        landmark_refs=[],
                        extras=_source_extras(region),
                    )
                )
            elif region.type == "traversable":
                traversable_regions.append(
                    TraversableRegion(region_id=region.id, geometry=geometry, traversable=True, extras=_source_extras(region))
                )
            elif region.type in {"forbidden", "obstacle"}:
                traversable_regions.append(
                    TraversableRegion(region_id=region.id, geometry=geometry, traversable=False, extras=_source_extras(region))
                )
            elif region.type == "hazard":
                hazard_regions.append(
                    HazardRegion(
                        region_id=region.id,
                        hazard_type=region.navigation.hazard_type or "hazard",
                        geometry=geometry,
                        object_refs=[],
                        collision_risk=bool(region.navigation.blocks_navigation),
                        extras=_source_extras(region),
                    )
                )
                if region.navigation.blocks_navigation:
                    traversable_regions.append(
                        TraversableRegion(region_id=f"obstacle_{region.id}", geometry=geometry, traversable=False, extras=_source_extras(region))
                    )
            elif region.type in {"start", "stop_before"}:
                metadata_regions.append({"id": region.id, "type": region.type, "label": region.label, "geometry": geometry, "extras": _source_extras(region)})
            else:
                _issue(issues, region.id, "type", f"Unsupported region type for compile: {region.type}", "choose_supported_region_type")
        except Exception as exc:
            _issue(issues, region.id, "geometry", str(exc), "fix_region_geometry")

    if issues:
        raise AuthoringMapCompileError(issues)

    annotation = SceneAnnotation(
        scene_id=model.scene_id,
        usd_ref=usd_ref,
        coordinate_system="xy_yaw",
        objects=objects,
        transparent_surfaces=transparent_surfaces,
        reflective_hazards=reflective_hazards,
        hazard_regions=hazard_regions,
        goal_regions=goal_regions,
        landmarks=landmarks,
        traversable_regions=traversable_regions,
        metadata={
            "source": "authoring_map",
            "authoring_map_version": model.version,
            "authoring_map": authoring_map_to_payload(model),
            "authoring_regions": metadata_regions,
            "sync": {
                "dataset": "synced",
                "render_scene": "pending",
                "isaac_stage": "pending",
                "message": "Annotation is updated, but render scene and Isaac stage are not synced yet.",
            },
        },
        schema_version="0.2",
    )
    try:
        validate_scene_annotation(annotation)
    except Exception as exc:
        raise AuthoringMapCompileError([AuthoringMapIssue(None, "scene_annotation", str(exc), "fix_authoring_map")]) from exc

    sync = dict(annotation.metadata["sync"])
    summary = {
        "scene_id": annotation.scene_id,
        "object_count": len(annotation.objects),
        "transparent_surface_count": len(annotation.transparent_surfaces),
        "reflective_hazard_count": len(annotation.reflective_hazards),
        "hazard_region_count": len(annotation.hazard_regions),
        "goal_region_count": len(annotation.goal_regions),
        "traversable_region_count": len(annotation.traversable_regions),
        "landmark_count": len(annotation.landmarks),
    }
    return AuthoringCompileResult(annotation=annotation, summary=summary, sync=sync)
