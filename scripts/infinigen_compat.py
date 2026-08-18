"""Small, testable compatibility adapters for the deployed Infinigen tree."""

from __future__ import annotations

from typing import Any


CONCRETE_WALL_HINTS = frozenset({"vertical", "alternating", "shape", "is_ceramic"})


def install_concrete_wall_hint_compat(concrete_cls: type[Any]) -> None:
    """Allow non-semantic room-wall layout hints on legacy Concrete."""
    original = concrete_cls.generate

    def generate_compat(self: Any, *args: Any, **kwargs: Any) -> Any:
        unexpected = set(kwargs) - CONCRETE_WALL_HINTS
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise TypeError(f"Concrete.generate() got unexpected compatibility argument(s): {names}")
        return original(self, *args)

    concrete_cls.generate = generate_compat
    concrete_cls.__call__ = generate_compat


def install_idempotent_collection_delete_compat(blender_util: Any, bpy_module: Any) -> None:
    """Delete temporary asset collections before unlinking their objects.

    Infinigen 1.19.1 removes the collection datablock first and then tries to
    select its former objects. Blender 4.2 can already have unlinked those
    objects, leaving an invalid empty-name handle and aborting asset population.
    """
    if getattr(blender_util.delete_collection, "_robomituba_idempotent", False):
        return
    original_delete = blender_util.delete
    collection_type = bpy_module.types.Collection

    def delete_collection_compat(target: Any) -> None:
        name = str(getattr(target, "name", "") or "")
        if isinstance(target, collection_type):
            collection = bpy_module.data.collections.get(name) if name else None
            if collection is None:
                return
            # Snapshot while Blender still considers every object selectable.
            for obj in list(collection.objects):
                delete_collection_compat(obj)
            if name in bpy_module.data.collections:
                bpy_module.data.collections.remove(collection)
            return
        if not name or name not in bpy_module.data.objects:
            return
        if name in bpy_module.context.scene.objects:
            original_delete(target)
        else:
            bpy_module.data.objects.remove(target, do_unlink=True)

    delete_collection_compat._robomituba_idempotent = True
    blender_util.delete_collection = delete_collection_compat
