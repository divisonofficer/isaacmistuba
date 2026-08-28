from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "infinigen"))

from render_visibility_contract import hide_untracked_render_meshes, visible_untracked_mesh_names


class FakeObject:
    def __init__(self, name, *, object_type="MESH", hide_render=False):
        self.name = name
        self.type = object_type
        self.hide_render = hide_render


def test_untracked_visible_mesh_is_hidden_and_audited():
    tracked = FakeObject("tracked")
    untracked = FakeObject("book_stack")
    light = FakeObject("light", object_type="LIGHT")

    rows = hide_untracked_render_meshes([tracked, untracked, light], {"tracked"})

    assert not tracked.hide_render
    assert untracked.hide_render
    assert rows == [{
        "blender_object": "book_stack",
        "was_render_visible": True,
        "action": "hide_render",
        "reason": "not_in_stage1_manifest",
    }]
    assert visible_untracked_mesh_names([tracked, untracked, light], {"tracked"}) == []


def test_previously_hidden_untracked_mesh_remains_auditable():
    hidden = FakeObject("placeholder", hide_render=True)
    rows = hide_untracked_render_meshes([hidden], set())
    assert rows[0]["was_render_visible"] is False
    assert visible_untracked_mesh_names([hidden], set()) == []
