from __future__ import annotations

import numpy as np

from navigation_dataset.ir_principled import (
    MATERIAL_CONTRACT_VERSION,
    apply_matched_luminance,
    ceiling_softbox_specs,
    diffuse_shading_from_component,
    formula_contract,
    matched_luminance_coefficients,
    material_normalization_record,
    pseudo_nir_albedo,
    unit_source_valid,
)


def _unit(**channels):
    defaults = {
        "base_color": {"source": "constant", "value": [[0.2, 0.3, 0.4]]},
        "roughness": {"source": "constant", "value": [0.4]},
        "metallic": {"source": "constant", "value": [0.0]},
        "normal": {"source": "not_applicable", "mode": "not_applicable"},
    }
    defaults.update(channels)
    return {
        "id": "object_1", "blender_name": "Object",
        "pbr": {"status": "ok", "channels": defaults},
    }


def test_pseudo_nir_uses_fixed_linear_max_complement_formula():
    rgb = np.asarray([[[0.0, 0.5, 1.0], [0.2, 0.3, 0.4]]], dtype=np.float32)
    actual = pseudo_nir_albedo(rgb)
    expected = np.maximum(rgb, 1.0 - rgb) @ np.asarray([0.229, 0.587, 0.114], np.float32)
    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-7)
    contract = formula_contract()
    assert contract["id"] == "pseudo_max_complement_bt601_v1"
    assert len(contract["implementation_digest"]) == 64


def test_absent_authored_normal_is_valid_but_missing_pbr_parameter_is_not():
    unit = _unit()
    assert unit_source_valid(unit)
    unit["pbr"]["channels"]["roughness"] = {"source": "not_applicable"}
    assert not unit_source_valid(unit)


def test_normal_texture_is_authored_source_even_when_legacy_source_is_not_applicable():
    unit = _unit(normal={
        "source": "not_applicable", "mode": "texture", "ref": "textures/normal.png",
    })
    assert unit_source_valid(unit)
    record = material_normalization_record(unit, "painted_metal", "none")
    assert record["source_valid"] is True
    assert record["fallback_channels"] == []


def test_semantic_surrogate_is_defined_replacement_not_primary_source_valid():
    record = material_normalization_record(_unit(), "window_glass", "window_glass")
    assert record["gt_defined"] is True
    assert record["source_valid"] is False
    assert record["replacement"] is True
    assert record["replacement_reasons"] == ["window_glass_to_opaque_principled"]


def test_fallback_channels_are_explicit_and_do_not_use_material_class_inference():
    unit = _unit(metallic={"source": "unresolved", "value": [0.0]})
    record = material_normalization_record(unit, "translucent_plate", "none")
    assert record["fallback_channels"] == ["metallic"]
    assert record["replacement_reasons"] == ["missing_metallic_fallback"]
    assert record["source_channels"]["metallic"]["source"] == "unresolved"
    assert record["applied_fallback_values"]["metallic"] == 0.0
    assert "physical_material" not in record
    assert MATERIAL_CONTRACT_VERSION == "blender42-principled-metallic-roughness-v3"


def test_luminance_ablation_matches_primary_mean_and_std_before_clipping():
    rng = np.random.default_rng(7)
    rgb = rng.uniform(0.2, 0.8, size=(128, 64, 3)).astype(np.float32)
    coeff = matched_luminance_coefficients(rgb)
    alternate = apply_matched_luminance(rgb, **coeff)
    primary = pseudo_nir_albedo(rgb)
    # This input range keeps the fitted affine result away from clipping.
    assert abs(float(alternate.mean()) - float(primary.mean())) < 1e-5
    assert abs(float(alternate.std()) - float(primary.std())) < 1e-5


def test_diffuse_shading_contract_reconstructs_component_and_masks_black_lobes():
    reflectance = np.asarray([[[0.5, 0.25, 0.1], [0.0, 0.0, 0.0]]], dtype=np.float32)
    expected_shading = np.asarray([[[2.0, 3.0, 4.0], [0.0, 0.0, 0.0]]], dtype=np.float32)
    component = reflectance * expected_shading
    shading, valid = diffuse_shading_from_component(component, reflectance)
    np.testing.assert_allclose(shading[0, 0], expected_shading[0, 0], atol=1e-6)
    np.testing.assert_allclose(shading * reflectance, component, atol=1e-6)
    assert valid.tolist() == [[True, False]]


def test_ceiling_softbox_policy_matches_kitchen_room_contract():
    specs = ceiling_softbox_specs([1.2841, 1.0281, 5.5061, 4.3891])
    assert len(specs) == 1
    np.testing.assert_allclose(specs[0]["center_xy"], [3.3951, 2.7086], atol=1e-6)
    np.testing.assert_allclose(specs[0]["size_m"], [1.3049203, 1.3049203], atol=1e-6)


def test_ceiling_softbox_policy_scales_to_four_panels_for_large_rooms():
    specs = ceiling_softbox_specs([0.0, 0.0, 12.0, 10.0])
    assert len(specs) == 4
    assert all(0.8 <= value <= 2.2 for spec in specs for value in spec["size_m"])
