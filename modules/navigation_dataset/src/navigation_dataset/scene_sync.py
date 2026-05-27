from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .authoring_map import AuthoringMap, authoring_map_from_payload, authoring_map_to_payload
from .scene_annotations import SceneAnnotation, scene_annotation_to_payload


JsonDict = dict[str, Any]
SCENE_VARIANT_VERSION = "opticalnav-scene-variant-v0.2"


@dataclass
class RenderSceneSyncResult:
    scene_id: str
    scene_variant_ref: str
    overlay_ref: str
    scene_variant: JsonDict
    overlay: JsonDict
    sync: JsonDict


def _geometry_payload(value: Any) -> JsonDict:
    if hasattr(value, "__dict__"):
        return {key: item for key, item in value.__dict__.items() if item is not None and item != {}}
    return dict(value or {})


def _navigation_payload(value: Any) -> JsonDict:
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return dict(value or {})


def build_render_scene_sync_payload(
    authoring_map: AuthoringMap | JsonDict,
    annotation: SceneAnnotation,
    *,
    scene_variant_id: str | None = None,
) -> tuple[JsonDict, JsonDict, JsonDict]:
    model = authoring_map_from_payload(authoring_map) if isinstance(authoring_map, dict) else authoring_map
    variant_id = scene_variant_id or f"{annotation.scene_id}_variant_authoring_v0_2"
    annotation_payload = scene_annotation_to_payload(annotation)

    overlay_objects: list[JsonDict] = []
    material_bindings: list[JsonDict] = []
    for obj in model.objects:
        geometry = _geometry_payload(obj.geometry)
        navigation = _navigation_payload(obj.navigation)
        entry = {
            "id": obj.id,
            "type": obj.type,
            "label": obj.label,
            "placement": obj.placement,
            "geometry": geometry,
            "material": obj.material,
            "navigation": navigation,
            "source_ref": obj.source_ref,
            "metadata": dict(obj.metadata or {}),
        }
        overlay_objects.append(entry)
        if obj.material:
            material_bindings.append(
                {
                    "object_id": obj.id,
                    "material": obj.material,
                    "authoring_type": obj.type,
                    "geometry": geometry,
                }
            )

    overlay_regions = [
        {
            "id": region.id,
            "type": region.type,
            "label": region.label,
            "placement": region.placement,
            "geometry": _geometry_payload(region.geometry),
            "navigation": _navigation_payload(region.navigation),
            "metadata": dict(region.metadata or {}),
        }
        for region in model.regions
    ]

    mask_targets = [
        {
            "object_id": obj["object_id"],
            "category": obj["category"],
            "hazard_type": obj.get("hazard_type"),
            "geometry": obj.get("geometry", {}),
        }
        for obj in annotation_payload.get("objects", [])
        if obj.get("mask_export")
    ]
    hazard_regions = [
        {
            "region_id": item["region_id"],
            "hazard_type": item["hazard_type"],
            "geometry": item["geometry"],
            "object_refs": item.get("object_refs", []),
            "collision_risk": item.get("collision_risk", True),
        }
        for item in annotation_payload.get("hazard_regions", [])
    ]

    overlay = {
        "version": SCENE_VARIANT_VERSION,
        "scene_id": annotation.scene_id,
        "scene_variant_id": variant_id,
        "coordinate_system": annotation.coordinate_system,
        "objects": overlay_objects,
        "regions": overlay_regions,
        "hazard_mask_targets": mask_targets,
        "hazard_regions": hazard_regions,
        "material_bindings": material_bindings,
        "metadata": {
            "source": "authoring_map",
            "render_sync_mode": "overlay_manifest",
            "note": "This manifest materializes 2D editor overlays for render tooling. It is not an Isaac USD stage mutation.",
        },
    }
    scene_variant = {
        "version": SCENE_VARIANT_VERSION,
        "scene_id": annotation.scene_id,
        "scene_variant_id": variant_id,
        "base_usd_ref": annotation.usd_ref,
        "render_sync_mode": "overlay_manifest",
        "coordinate_system": annotation.coordinate_system,
        "authoring_map": authoring_map_to_payload(model),
        "scene_annotation": annotation_payload,
        "overlay_ref": "render_scene_overlays.json",
        "material_bindings": material_bindings,
        "hazard_mask_target_count": len(mask_targets),
        "metadata": {
            "source": "opticalnav_editor",
            "limitations": [
                "No live Isaac prims are created by this artifact.",
                "Renderers must explicitly consume render_scene_overlays.json to render edited geometry.",
            ],
        },
    }
    sync = {
        "dataset": "synced",
        "render_scene": "synced",
        "render_scene_mode": "overlay_manifest",
        "isaac_stage": "pending",
        "message": "Render-scene overlay manifest is synced. Isaac stage mutation is still pending.",
    }
    return scene_variant, overlay, sync


def write_render_scene_sync(
    scene_dir: str | Path,
    authoring_map: AuthoringMap | JsonDict,
    annotation: SceneAnnotation,
    *,
    project_dir: str | Path | None = None,
    scene_variant_id: str | None = None,
) -> RenderSceneSyncResult:
    scene_root = Path(scene_dir)
    scene_root.mkdir(parents=True, exist_ok=True)
    scene_variant, overlay, sync = build_render_scene_sync_payload(
        authoring_map,
        annotation,
        scene_variant_id=scene_variant_id,
    )
    variant_path = scene_root / "scene_variant.json"
    overlay_path = scene_root / "render_scene_overlays.json"
    variant_path.write_text(json.dumps(scene_variant, ensure_ascii=False, indent=2), encoding="utf-8")
    overlay_path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    root = Path(project_dir) if project_dir is not None else scene_root.parent.parent
    return RenderSceneSyncResult(
        scene_id=annotation.scene_id,
        scene_variant_ref=variant_path.relative_to(root).as_posix(),
        overlay_ref=overlay_path.relative_to(root).as_posix(),
        scene_variant=scene_variant,
        overlay=overlay,
        sync=sync,
    )
