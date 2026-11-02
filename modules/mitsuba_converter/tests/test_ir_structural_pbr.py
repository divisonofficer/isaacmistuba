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


def test_loadbearing_structures_skip_assets_with_metallic_texture():
    registry = {
        "schema": REGISTRY_SCHEMA,
        "role_policy": "explicit_approved_roles_v1",
        "materials": [
            {
                "id": "bad_floor", "license": "CC0-1.0", "maps": {"base_color": "a", "roughness": "b", "normal_gl": "c", "metallic": "d"},
                "physical_size_m": {"width": 1.0, "height": 1.0}, "approved_roles": ["floor"],
                "metallic": {"mode": "texture", "map": "metallic"},
            },
            {
                "id": "good_floor", "license": "CC0-1.0", "maps": {"base_color": "e", "roughness": "f", "normal_gl": "g"},
                "physical_size_m": {"width": 1.0, "height": 1.0}, "approved_roles": ["floor"],
                "metallic": {"mode": "constant", "value": 0.0},
            },
        ],
    }
    scene = {"units": [{"id": "floor", "kind": "structure", "semantic_type": "floor", "subtype": "floor",
                         "collections": ["room_floor"], "material_slots": [{}]}]}
    bindings, _ = bindings_for_scene(scene, registry, seed=2)
    assert bindings[0]["material_id"] == "good_floor"


def _tiny_scene():
    return {"units": [{"id": "u", "blender_name": "room.wall", "subtype": "wall",
                       "material_slots": [None]}]}


def test_a_coarse_texture_never_lands_on_a_wall() -> None:
    """8.8% of wall slots drew a 2.0-2.4 m texture before this held."""
    from mitsuba_converter.ir_structural_finish import repeat_fits
    from mitsuba_converter.ir_structural_pbr import bindings_for_scene
    from pathlib import Path
    import json
    registry_path = Path("/bean/ir_pbr_assets/texturecan_structural_extended_v1/registry.lock.json")
    if not registry_path.is_file():
        import pytest
        pytest.skip("structural registry is not available on this host")
    registry = json.loads(registry_path.read_text())
    by_id = {m["id"]: m for m in registry["materials"]}
    stage1 = json.loads((Path("/bean/ir_dataset_work/.pipeline")
                         / "infinigen_bedroom_20260810_v2" / "ir_geometry" / "stage1"
                         / "scene_manifest.json").read_text())
    for seed in range(25):
        bindings, _ = bindings_for_scene(stage1, registry, seed=seed)
        for b in bindings:
            assert repeat_fits(by_id[b["material_id"]], b["role"]), (seed, b["role"], b["material_id"])
