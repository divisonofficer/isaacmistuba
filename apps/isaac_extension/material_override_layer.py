"""USD override-layer helpers for RoboMitsuba material assignments."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable


MATERIAL_ATTR_PREFIX = "robomituba:material:"
ATTR_ENABLED = f"{MATERIAL_ATTR_PREFIX}enabled"
ATTR_KIND = f"{MATERIAL_ATTR_PREFIX}kind"
ATTR_PRESET = f"{MATERIAL_ATTR_PREFIX}preset"
ATTR_BSDF = f"{MATERIAL_ATTR_PREFIX}bsdf"
ATTR_DATASET_ID = f"{MATERIAL_ATTR_PREFIX}datasetId"
ATTR_MATERIAL_ID = f"{MATERIAL_ATTR_PREFIX}materialId"
ATTR_MEASURED_FILE_PATH = f"{MATERIAL_ATTR_PREFIX}measuredFilePath"
ATTR_PARAMS_JSON = f"{MATERIAL_ATTR_PREFIX}paramsJson"
MATERIAL_ATTR_NAMES = (
    ATTR_ENABLED,
    ATTR_KIND,
    ATTR_PRESET,
    ATTR_BSDF,
    ATTR_DATASET_ID,
    ATTR_MATERIAL_ID,
    ATTR_MEASURED_FILE_PATH,
    ATTR_PARAMS_JSON,
)


@dataclass
class ResolvedMaterialOverride:
    prim_path: str
    source: str
    source_path: str | None
    label: str
    override: Any | None = None
    visual_material_path: str | None = None
    layer_path: str | None = None


def default_override_layer_path(stage: Any, *, scene_id: str = "live") -> Path:
    root_layer = stage.GetRootLayer()
    raw_path = str(getattr(root_layer, "realPath", "") or getattr(root_layer, "identifier", "") or "")
    if raw_path and not raw_path.startswith("anon:"):
        path = Path(PureWindowsPath(raw_path)) if "\\" in raw_path or (len(raw_path) > 1 and raw_path[1] == ":") else Path(raw_path)
        return path.with_name(f"{path.stem}_robomitsuba_overrides.usda")
    repo_root = (
        os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
        or os.environ.get("ROBOMITUBA_ROOT")
        or os.environ.get("ROBOMITUBA_LOCAL_REPO_ROOT")
        or os.getcwd()
    )
    safe_scene_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(scene_id or "live"))
    return Path(PureWindowsPath(repo_root)) / "out" / "isaac_overrides" / f"{safe_scene_id}_robomitsuba_overrides.usda"


def ensure_override_layer(stage: Any, *, scene_id: str = "live") -> Any:
    from pxr import Sdf

    path = default_override_layer_path(stage, scene_id=scene_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    identifier = str(path)
    layer = Sdf.Layer.FindOrOpen(identifier)
    if layer is None:
        layer = Sdf.Layer.CreateNew(identifier)
    session_layer = stage.GetSessionLayer()
    if identifier not in list(session_layer.subLayerPaths):
        session_layer.subLayerPaths.append(identifier)
    return layer


def attach_existing_override_layer(stage: Any, *, scene_id: str = "live") -> Any | None:
    from pxr import Sdf

    path = default_override_layer_path(stage, scene_id=scene_id)
    if not path.exists():
        return None
    layer = Sdf.Layer.FindOrOpen(str(path))
    if layer is None:
        return None
    session_layer = stage.GetSessionLayer()
    if str(path) not in list(session_layer.subLayerPaths):
        session_layer.subLayerPaths.append(str(path))
    return layer


def material_record_to_override(record: dict[str, Any]) -> Any:
    from robomituba_bridge import BsdfOverride

    kind = str(record.get("kind") or "")
    if kind == "curated":
        return BsdfOverride(
            bsdf_type="curated",
            material_id=str(record.get("material_id") or "") or None,
            extras={
                "curated_display_name": str(record.get("display_name") or record.get("material_id") or ""),
                "curated_category": str(record.get("category") or ""),
            },
        )
    return BsdfOverride(
        bsdf_type=str(record.get("bsdf_type") or "measured_polarized"),
        measured_file_path=str(record.get("native_file") or "") or None,
        dataset_id=str(record.get("dataset_id") or "") or None,
        material_id=str(record.get("material_id") or "") or None,
    )


def write_material_override(
    stage: Any,
    prim_paths: Iterable[str],
    override: Any,
    *,
    scene_id: str = "live",
    kind: str = "bsdf",
    preset: str = "",
    params: dict[str, Any] | None = None,
) -> int:
    from pxr import Sdf, Usd

    layer = ensure_override_layer(stage, scene_id=scene_id)
    count = 0
    with Usd.EditContext(stage, layer):
        for prim_path in prim_paths:
            path = str(prim_path or "")
            if not path:
                continue
            prim = stage.OverridePrim(path)
            prim.CreateAttribute(ATTR_ENABLED, Sdf.ValueTypeNames.Bool, custom=True).Set(True)
            prim.CreateAttribute(ATTR_KIND, Sdf.ValueTypeNames.Token, custom=True).Set(str(kind or "bsdf"))
            prim.CreateAttribute(ATTR_PRESET, Sdf.ValueTypeNames.String, custom=True).Set(str(preset or ""))
            prim.CreateAttribute(ATTR_BSDF, Sdf.ValueTypeNames.Token, custom=True).Set(str(getattr(override, "bsdf_type", "") or ""))
            prim.CreateAttribute(ATTR_DATASET_ID, Sdf.ValueTypeNames.String, custom=True).Set(str(getattr(override, "dataset_id", "") or ""))
            prim.CreateAttribute(ATTR_MATERIAL_ID, Sdf.ValueTypeNames.String, custom=True).Set(str(getattr(override, "material_id", "") or ""))
            prim.CreateAttribute(ATTR_MEASURED_FILE_PATH, Sdf.ValueTypeNames.Asset, custom=True).Set(
                Sdf.AssetPath(str(getattr(override, "measured_file_path", "") or ""))
            )
            payload = dict(params or {})
            extras = getattr(override, "extras", None)
            if isinstance(extras, dict) and extras:
                payload.setdefault("extras", extras)
            prim.CreateAttribute(ATTR_PARAMS_JSON, Sdf.ValueTypeNames.String, custom=True).Set(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            count += 1
    try:
        layer.Save()
    except Exception:
        pass
    return count


def clear_material_override(stage: Any, prim_paths: Iterable[str], *, scene_id: str = "live") -> int:
    from pxr import Usd

    layer = ensure_override_layer(stage, scene_id=scene_id)
    count = 0
    with Usd.EditContext(stage, layer):
        for prim_path in prim_paths:
            prim = stage.GetPrimAtPath(str(prim_path))
            if not prim or not prim.IsValid():
                prim = stage.OverridePrim(str(prim_path))
            for attr_name in MATERIAL_ATTR_NAMES:
                try:
                    prim.RemoveProperty(attr_name)
                except Exception:
                    pass
            count += 1
    try:
        layer.Save()
    except Exception:
        pass
    return count


def _attr_value(prim: Any, name: str, default: Any = None) -> Any:
    attr = prim.GetAttribute(name)
    if not attr:
        return default
    value = attr.Get()
    return default if value is None else value


def _asset_path_string(value: Any) -> str:
    path = getattr(value, "path", None)
    if path is not None:
        return str(path)
    return str(value or "")


def _bsdf_from_prim_attrs(prim: Any) -> Any | None:
    from robomituba_bridge import BsdfOverride

    enabled = bool(_attr_value(prim, ATTR_ENABLED, False))
    if not enabled:
        return None
    bsdf_type = str(_attr_value(prim, ATTR_BSDF, "") or "")
    kind = str(_attr_value(prim, ATTR_KIND, "") or "")
    if not bsdf_type and kind == "curated":
        bsdf_type = "curated"
    if not bsdf_type:
        return None
    extras: dict[str, Any] = {}
    raw_params = str(_attr_value(prim, ATTR_PARAMS_JSON, "") or "")
    if raw_params:
        try:
            decoded = json.loads(raw_params)
            if isinstance(decoded, dict):
                extras = dict(decoded.get("extras") or {})
        except Exception:
            extras = {}
    return BsdfOverride(
        bsdf_type=bsdf_type,
        dataset_id=str(_attr_value(prim, ATTR_DATASET_ID, "") or "") or None,
        material_id=str(_attr_value(prim, ATTR_MATERIAL_ID, "") or "") or None,
        measured_file_path=_asset_path_string(_attr_value(prim, ATTR_MEASURED_FILE_PATH, "")) or None,
        extras=extras,
    )


def resolve_material_override(stage: Any, prim_path: str, *, scene_id: str = "live") -> ResolvedMaterialOverride:
    layer_path = str(default_override_layer_path(stage, scene_id=scene_id))
    prim = stage.GetPrimAtPath(str(prim_path))
    if not prim or not prim.IsValid():
        return ResolvedMaterialOverride(str(prim_path), "none", None, "No valid prim", layer_path=layer_path)

    current = prim
    while current and current.IsValid():
        override = _bsdf_from_prim_attrs(current)
        if override is not None:
            source_path = str(current.GetPath())
            material_id = getattr(override, "material_id", None)
            bsdf_type = getattr(override, "bsdf_type", "")
            label = f"{bsdf_type}: {material_id}" if material_id else str(bsdf_type)
            source = "explicit" if source_path == str(prim_path) else "parent"
            return ResolvedMaterialOverride(str(prim_path), source, source_path, label, override=override, layer_path=layer_path)
        current = current.GetParent()

    visual_material = bound_visual_material_path(prim)
    if visual_material:
        return ResolvedMaterialOverride(str(prim_path), "visual_material", visual_material, f"Visual material: {visual_material}", visual_material_path=visual_material, layer_path=layer_path)
    return ResolvedMaterialOverride(str(prim_path), "none", None, "No RoboMitsuba override", layer_path=layer_path)


def bound_visual_material_path(prim: Any) -> str | None:
    try:
        from pxr import UsdShade

        material, _rel = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if material:
            return str(material.GetPath())
    except Exception:
        return None
    return None


def read_stage_material_overrides(stage: Any, prim_paths: Iterable[str], *, scene_id: str = "live") -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for prim_path in prim_paths:
        resolved = resolve_material_override(stage, str(prim_path), scene_id=scene_id)
        if resolved.override is not None:
            overrides[str(prim_path)] = resolved.override
    return overrides


def expand_material_scope(stage: Any, prim_paths: Iterable[str], *, scope: str) -> list[str]:
    from pxr import Usd, UsdGeom

    selected = [str(path) for path in prim_paths if str(path)]
    if scope == "selected":
        return selected
    if scope == "children":
        out: list[str] = []
        for path in selected:
            prim = stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            for child in Usd.PrimRange(prim):
                if child.IsA(UsdGeom.Mesh) or str(child.GetPath()) == path:
                    out.append(str(child.GetPath()))
        return sorted(set(out))
    if scope == "same_visual":
        targets = {bound_visual_material_path(stage.GetPrimAtPath(path)) for path in selected}
        targets.discard(None)
        if not targets:
            return selected
        out = []
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Mesh) and bound_visual_material_path(prim) in targets:
                out.append(str(prim.GetPath()))
        return sorted(set(out))
    return selected
