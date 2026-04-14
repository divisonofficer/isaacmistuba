from __future__ import annotations

from .types import MaterialRecord


def infer_material_kind(material: MaterialRecord) -> str:
    if material.kind and material.kind != "auto":
        return material.kind

    haystack = " ".join(
        part
        for part in [material.name, material.source_path, material.shader_model or ""]
        if part
    ).lower()

    if "glass" in haystack or "omni.glass" in haystack:
        return "glass"
    if "metal" in haystack or (material.metallic or 0.0) >= 0.5:
        return "metal"
    if "plastic" in haystack:
        return "plastic"
    if "floor" in haystack:
        return "floor"
    return "diffuse"


def texture_for_slot(material: MaterialRecord, *slots: str) -> str | None:
    for slot in slots:
        texture_path = material.textures.get(slot)
        if texture_path:
            return texture_path
    return None
