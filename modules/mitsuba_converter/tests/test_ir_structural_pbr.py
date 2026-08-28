from __future__ import annotations

from mitsuba_converter.ir_structural_pbr import REGISTRY_SCHEMA, bindings_for_scene, build_manifest, structural_eligibility


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
        {"id": "wall", "blender_name": "room.wall", "kind": "structure", "semantic_type": "wall", "subtype": "wall", "collections": ["unique_assets:room_wall"], "material_slots": [{}, {}]},
        {"id": "cup", "blender_name": "cup", "kind": "furniture", "material_slots": [{}]},
    ]}
    first, excluded = bindings_for_scene(scene, _registry(), seed=7)
    assert [(x["unit_id"], x["slot_index"]) for x in first] == [("wall", 0), ("wall", 1)]
    assert first == bindings_for_scene(scene, _registry(), seed=7)[0]
    assert excluded[0]["reason"] == "not_exporter_structure"
    stage1 = tmp_path / "scene_manifest.json"; stage1.write_text("{}")
    result = build_manifest(stage1_manifest=scene, stage1_path=stage1, registry=_registry(),
        registry_path=tmp_path / "registry.json", child_scene_id="child", parent_scene_id="parent",
        parent_dataset_fingerprint="abc", material_variant_id="v1", material_seed=7)
    assert result["child_scene_id"] != result["parent_scene_id"]
    assert result["geometry_digest"] and result["digest"]
    assert result["selection"]["policy"] == "interior_structure_only_v2_role_curated"


def test_only_room_membership_interior_structure_is_eligible():
    interior = {"kind": "structure", "semantic_type": "wall", "subtype": "wall",
                "collections": ["unique_assets:room_wall"]}
    assert structural_eligibility(interior)["eligible"] is True
    for unit, reason in (
        ({**interior, "kind": "furniture"}, "not_exporter_structure"),
        ({**interior, "subtype": "exterior", "collections": ["unique_assets:room_exterior"]}, "excluded_structural_or_opening"),
        ({**interior, "subtype": "wall", "collections": ["unique_assets"]}, "missing_room_structural_membership"),
        ({**interior, "subtype": "window", "collections": ["unique_assets:room_window"]}, "excluded_structural_or_opening"),
    ):
        result = structural_eligibility(unit)
        assert result["eligible"] is False
        assert result["reason"] == reason


def test_explicit_roles_replace_keyword_inference_for_new_registry(tmp_path):
    registry = {
        "schema": REGISTRY_SCHEMA,
        "registry_version": "texturecan_structural_v1",
        "role_policy": "explicit_approved_roles_v1",
        "materials": [{
            "id": "texturecan_metal_001", "license": "CC0-1.0", "source_url": "https://example.invalid/metal",
            "maps": {"base_color": "a/base.jpg", "roughness": "a/rough.jpg", "normal_gl": "a/normal.png", "metallic": "a/metal.jpg"},
            "physical_size_m": {"width": 2.0, "height": 1.0}, "semantic_compatibility": ["panel"],
            "approved_roles": ["panel"], "normal_convention": "OpenGL",
            "metallic": {"mode": "texture", "map": "metallic"}, "projection": "object_meter_repeat_v3",
        }],
    }
    path = tmp_path / "registry.json"; path.write_text(__import__("json").dumps(registry))
    from mitsuba_converter.ir_structural_pbr import load_registry
    loaded = load_registry(path)
    scene = {"units": [
        {"id": "panel", "kind": "structure", "semantic_type": "panel", "subtype": "panel", "collections": ["room_panel"], "material_slots": [{}]},
    ]}
    bindings, _ = bindings_for_scene(scene, loaded, seed=2)
    assert [(row["unit_id"], row["metallic"]) for row in bindings] == [("panel", {"mode": "texture", "map": "metallic"})]
