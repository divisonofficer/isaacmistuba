"""Render-visibility helpers shared by Blender IR preparation and tests."""

from __future__ import annotations

from typing import Any, Iterable


def hide_untracked_render_meshes(objects: Iterable[Any], tracked_names: set[str]) -> list[dict[str, Any]]:
    """Hide every mesh that has no Stage-1 unit binding.

    An object excluded from Stage 1 has no prepared Principled material, object
    ID, or GT AOV outputs.  Allowing it to remain visible would make RGB contain
    pixels whose PBR supervision is all zero.  Return an audit row for every
    untracked mesh, including meshes that were already hidden upstream.
    """
    rows: list[dict[str, Any]] = []
    for obj in objects:
        if str(getattr(obj, "type", "")) != "MESH":
            continue
        name = str(getattr(obj, "name", ""))
        if name in tracked_names:
            continue
        was_hidden = bool(getattr(obj, "hide_render", False))
        obj.hide_render = True
        rows.append({
            "blender_object": name,
            "was_render_visible": not was_hidden,
            "action": "hide_render",
            "reason": "not_in_stage1_manifest",
        })
    return rows


def visible_untracked_mesh_names(objects: Iterable[Any], tracked_names: set[str]) -> list[str]:
    """Return visible mesh names that violate the RGB/GT authority contract."""
    return sorted(
        str(getattr(obj, "name", ""))
        for obj in objects
        if str(getattr(obj, "type", "")) == "MESH"
        and str(getattr(obj, "name", "")) not in tracked_names
        and not bool(getattr(obj, "hide_render", False))
    )
