from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infinigen_compat import (  # noqa: E402
    install_callable_floor_material_compat,
    install_concrete_wall_hint_compat,
    install_idempotent_collection_delete_compat,
)


def test_concrete_compat_discards_only_known_room_wall_hints() -> None:
    class ConcreteFixture:
        def generate(self):
            return "material"

        __call__ = generate

    install_concrete_wall_hint_compat(ConcreteFixture)
    concrete = ConcreteFixture()
    assert concrete(vertical=True, alternating=False, shape="square", is_ceramic=True) == "material"
    with pytest.raises(TypeError, match="unknown"):
        concrete(unknown=True)


def test_callable_floor_material_compat_repairs_only_known_ceramic_tile_module() -> None:
    class Tile:
        pass

    class TileModule:
        pass

    Ceramic = type("Ceramic", (), {"tile": TileModule, "Tile": Tile})

    class Assignments:
        utility_floor = [(object, 1.0), (TileModule, 2.0)]

    assert install_callable_floor_material_compat(Assignments, Ceramic) == 1
    assert Assignments.utility_floor == [(object, 1.0), (Tile, 2.0)]
    assert install_callable_floor_material_compat(Assignments, Ceramic) == 0


def test_collection_cleanup_deletes_objects_before_collection_and_skips_stale_handles() -> None:
    events: list[tuple] = []

    class ObjectFixture:
        def __init__(self, name: str): self.name = name

    class CollectionFixture:
        def __init__(self, name: str, objects: list[ObjectFixture]):
            self.name, self.objects = name, objects

    class Store(dict):
        def remove(self, value, **kwargs):
            events.append(("remove", type(value).__name__, value.name, kwargs))
            self.pop(value.name, None)

    valid, orphan, stale = ObjectFixture("valid"), ObjectFixture("orphan"), ObjectFixture("")
    collection = CollectionFixture("leaves", [valid, orphan, stale])
    objects, collections = Store({"valid": valid, "orphan": orphan}), Store({"leaves": collection})

    class BlenderUtilFixture:
        @staticmethod
        def delete(value):
            events.append(("delete", value.name))
            objects.pop(value.name, None)

        @staticmethod
        def delete_collection(_value): raise AssertionError("unpatched")

    class BpyFixture:
        class types:
            Collection = CollectionFixture
        class data:
            pass
        class context:
            class scene:
                objects = {"valid": valid}

    BpyFixture.data.objects = objects
    BpyFixture.data.collections = collections
    install_idempotent_collection_delete_compat(BlenderUtilFixture, BpyFixture)
    BlenderUtilFixture.delete_collection(collection)
    BlenderUtilFixture.delete_collection(collection)

    assert events == [
        ("delete", "valid"),
        ("remove", "ObjectFixture", "orphan", {"do_unlink": True}),
        ("remove", "CollectionFixture", "leaves", {}),
    ]
