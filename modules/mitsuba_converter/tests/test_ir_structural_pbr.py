from __future__ import annotations

from mitsuba_converter.ir_structural_pbr import REGISTRY_SCHEMA, bindings_for_scene, build_manifest


def _registry():
    return {"schema": REGISTRY_SCHEMA, "materials": [
        {"id": "plaster_a", "license": "CC0-1.0", "source_url": "https://example.invalid/a",
         "maps": {"base_color": "a/base.png", "roughness": "a/rough.png", "normal_gl": "a/norm.png"},
         "physical_size_m": {"width": 1.0, "height": 1.0}, "semantic_compatibility": ["wall"]},
        {"id": "tile_b", "license": "CC0-1.0", "source_url": "https://example.invalid/b",
         "maps": {"base_color": "b/base.png", "roughness": "b/rough.png", "normal_gl": "b/norm.png"},
         "physical_size_m": {"width": 0.5, "height": 0.5}, "semantic_compatibility": ["floor"]},
    ]}


def test_structural_slots_get_deterministic_independent_bindings(tmp_path):
    scene = {"units": [
        {"id": "wall", "blender_name": "room.wall", "material_slots": [{}, {}]},
        {"id": "cup", "blender_name": "cup", "material_slots": [{}]},
    ]}
    first = bindings_for_scene(scene, _registry(), seed=7)
    assert [(x["unit_id"], x["slot_index"]) for x in first] == [("wall", 0), ("wall", 1)]
    assert first == bindings_for_scene(scene, _registry(), seed=7)
    stage1 = tmp_path / "scene_manifest.json"; stage1.write_text("{}")
    result = build_manifest(stage1_manifest=scene, stage1_path=stage1, registry=_registry(),
        registry_path=tmp_path / "registry.json", child_scene_id="child", parent_scene_id="parent",
        parent_dataset_fingerprint="abc", material_variant_id="v1", material_seed=7)
    assert result["child_scene_id"] != result["parent_scene_id"]
    assert result["geometry_digest"] and result["digest"]
