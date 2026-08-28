from pathlib import Path
import json

from navigation_dataset.ir_prop_pbr import (
    MANIFEST_SCHEMA, PROVENANCE_CLASSES, build_manifest, load_registry, prop_eligibility,
)


def test_transmissive_and_structure_slots_are_not_curated():
    assert not prop_eligibility({"kind": "structure"}, "paint", "none")["eligible"]
    assert not prop_eligibility({"kind": "asset", "blender_name": "GlassCup"}, "glass", "none")["eligible"]
    assert PROVENANCE_CLASSES["curated_remediated"] == 3


def test_manifest_keeps_source_valid_distinct_from_curated(tmp_path: Path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"schema": "robomituba.ir_prop_pbr_registry.v2", "profiles": [
        {"id": "generic", "classes": ["generic_prop"], "values": {"base_color": [.2, .3, .4], "roughness": .5, "metallic": 0}},
    ]}))
    registry = load_registry(registry_path)
    manifest = {"units": [
        {"id": "good", "kind": "asset", "materials": ["P"]},
        {"id": "bad", "kind": "asset", "materials": ["Analytic"]},
        {"id": "glass", "kind": "asset", "blender_name": "GlassThing", "materials": ["Glass"]},
    ]}
    states = {
        "good": {"pbr_by_slot": {"0": {"status": "ok", "channels": {name: {"source": "texture"} for name in ("base_color", "roughness", "metallic", "normal")}}}},
        "bad": {"pbr_by_slot": {"0": {"status": "ok", "channels": {name: {"source": "unresolved"} for name in ("base_color", "roughness", "metallic", "normal")}}}},
        "glass": {"pbr_by_slot": {"0": {"status": "ok", "channels": {}}}},
    }
    result = build_manifest(stage1_manifest=manifest, unit_states=states, registry=registry, registry_path=registry_path,
                            child_scene_id="child", parent_scene_id="parent", parent_dataset_fingerprint=None, seed=7)
    assert result["schema"] == MANIFEST_SCHEMA
    assert result["counts"]["source_authored"] == 1
    assert result["counts"]["curated_remediated"] == 1
    assert result["bindings"][0]["unit_id"] == "bad"
    assert result["audit"][-1]["action"] == "excluded"


def test_uniform_fractional_metallic_is_curated_not_marked_source_authored(tmp_path: Path):
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({"schema": "robomituba.ir_prop_pbr_registry.v2", "profiles": [
        {"id": "generic", "classes": ["generic_prop"],
         "values": {"base_color": [.2, .3, .4], "roughness": .5, "metallic": 0}},
    ]}))
    registry = load_registry(registry_path)
    manifest = {"units": [{"id": "fractional", "kind": "asset", "materials": ["P"]}]}
    channels = {
        "base_color": {"source": "texture", "mode": "texture"},
        "roughness": {"source": "texture", "mode": "texture"},
        "metallic": {"source": "constant", "mode": "constant", "value": [.428296]},
        "normal": {"source": "not_applicable", "mode": "not_applicable"},
    }
    result = build_manifest(
        stage1_manifest=manifest,
        unit_states={"fractional": {"pbr_by_slot": {"0": {"status": "ok", "channels": channels}}}},
        registry=registry, registry_path=registry_path, child_scene_id="child", parent_scene_id="parent",
        parent_dataset_fingerprint=None, seed=7,
    )
    assert result["compiler_version"] == "prop-pbr-remediation-v2-metallic-family"
    assert result["counts"] == {"curated_remediated": 1, "source_authored": 0, "excluded": 0}
    assert result["bindings"][0]["remediation_reasons"] == ["uniform_fractional_metallic"]
