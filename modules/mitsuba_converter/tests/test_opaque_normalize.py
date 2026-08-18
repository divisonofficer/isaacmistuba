"""Unit tests for the opaque-PBR substitution resolver (Stage 1, pure data)."""
from __future__ import annotations

from mitsuba_converter.opaque_normalize import (
    build_substitutions, resolve_slot, _palette_pick, _factory_token,
)

RULES = {
    "version": "test",
    "near_delta_roughness_floor": 0.10,
    "near_white_luma_threshold": 0.85,
    "target_optical_classes": ["glass", "mirror"],
    "factory_rules": {
        "JarFactory": {"semantic": "opaque_container", "bsdf": "pplastic", "metallic": 0.0,
                       "roughness": 0.30, "base_color_policy": "palette", "palette": "plastic",
                       "reason": "jar"},
        "MirrorSmoothFactory": {"semantic": "x", "bsdf": "pplastic", "metallic": 0.0,
                                "roughness": 0.02, "base_color_policy": "constant",
                                "base_color": [0.1, 0.1, 0.1], "reason": "near-delta"},
    },
    "architectural_rules": {
        "window": {"semantic": "opaque_dark_panel", "bsdf": "pplastic", "metallic": 0.0,
                   "roughness": 0.30, "base_color_policy": "constant",
                   "base_color": [0.05, 0.05, 0.06], "reason": "window"},
    },
    "default_glass": {"semantic": "ceramic", "bsdf": "pplastic", "metallic": 0.0,
                      "roughness": 0.25, "base_color_policy": "palette", "palette": "ceramic",
                      "reason": "default"},
    "default_mirror": {"semantic": "brushed_metal_panel", "bsdf": "roughconductor",
                       "metallic": 1.0, "roughness": 0.20, "conductor": "aluminium",
                       "reason": "mirror"},
    "palettes": {"plastic": [[0.7, 0.2, 0.2], [0.2, 0.4, 0.7]], "ceramic": [[0.82, 0.80, 0.76]]},
}


def _unit(uid, factory, slots, pbr=None):
    return {"id": uid, "factory": factory, "material_slots": slots, "pbr": pbr or {}}


def test_non_target_slot_returns_none():
    unit = _unit("u", "JarFactory", [{"name": "m", "optical_class": "diffuse"}])
    assert resolve_slot(unit, unit["material_slots"][0], RULES) is None


def test_glass_maps_to_factory_pplastic():
    unit = _unit("JarFactory_1", "JarFactory", [{"name": "shader_glass.1", "optical_class": "glass"}])
    sub = resolve_slot(unit, unit["material_slots"][0], RULES)
    assert sub["canonical"]["bsdf"] == "pplastic"
    assert sub["canonical"]["semantic"] == "opaque_container"
    assert sub["canonical"]["metallic"] == 0.0
    assert sub["source"]["optical_class"] == "glass"
    assert sub["source"]["bsdf"] == "dielectric"


def test_mirror_maps_to_roughconductor():
    unit = _unit("m", "SomeFactory", [{"name": "shader_mirror.1", "optical_class": "mirror"}])
    sub = resolve_slot(unit, unit["material_slots"][0], RULES)
    assert sub["canonical"]["bsdf"] == "roughconductor"
    assert sub["canonical"]["metallic"] == 1.0
    assert sub["canonical"]["conductor"] == "aluminium"


def test_factory_rule_precedes_default():
    jar = _unit("JarFactory_1", "JarFactory", [{"name": "g", "optical_class": "glass"}])
    other = _unit("Vase_1", "UnknownFactory", [{"name": "g", "optical_class": "glass"}])
    assert resolve_slot(jar, jar["material_slots"][0], RULES)["canonical"]["semantic"] == "opaque_container"
    assert resolve_slot(other, other["material_slots"][0], RULES)["canonical"]["semantic"] == "ceramic"


def test_architectural_keyword_routes_window():
    win = _unit("WindowFactory_1", "WindowFactory", [{"name": "g", "optical_class": "glass"}])
    sub = resolve_slot(win, win["material_slots"][0], RULES)
    assert sub["canonical"]["semantic"] == "opaque_dark_panel"


def test_near_delta_roughness_floored():
    unit = _unit("MirrorSmoothFactory_1", "MirrorSmoothFactory",
                 [{"name": "g", "optical_class": "glass"}])
    sub = resolve_slot(unit, unit["material_slots"][0], RULES)
    assert sub["near_delta_floored"] is True
    assert sub["canonical"]["roughness"] == 0.10  # floored up from 0.02


def test_palette_pick_deterministic():
    a = _palette_pick(RULES["palettes"]["plastic"], "obj:mat")
    b = _palette_pick(RULES["palettes"]["plastic"], "obj:mat")
    assert a == b
    assert a in RULES["palettes"]["plastic"]


def test_factory_token_from_slashed_path():
    assert _factory_token({"factory": "meshes/JarFactory"}) == "JarFactory"
    assert _factory_token({"id": "CupFactory_123.spawn"}) == "CupFactory"


def test_build_substitutions_summary():
    manifest = {"scene_id": "s", "units": [
        _unit("JarFactory_1", "JarFactory", [
            {"name": "g", "optical_class": "glass"},
            {"name": "lid", "optical_class": "metal_aluminum"},  # not a target
        ]),
        _unit("WindowFactory_1", "WindowFactory", [{"name": "g", "optical_class": "glass"}]),
    ]}
    doc = build_substitutions(manifest, RULES)
    assert doc["substitution_count"] == 2  # metal slot excluded
    assert doc["by_semantic"]["opaque_container"] == 1
    assert doc["by_semantic"]["opaque_dark_panel"] == 1
