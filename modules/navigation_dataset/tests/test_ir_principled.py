from __future__ import annotations

import numpy as np

from navigation_dataset.ir_principled import (
    MATERIAL_CONTRACT_VERSION,
    METALLIC_CONTRACT_SCHEMA,
    apply_matched_luminance,
    ceiling_softbox_specs,
    diffuse_shading_from_component,
    diffuse_component_from_transport,
    formula_contract,
    matched_luminance_coefficients,
    material_normalization_record,
    normalize_legacy_metallic_scalar,
    pseudo_nir_albedo,
    unit_source_valid,
    validate_metallic_contract,
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


def test_pseudo_nir_is_a_monotone_scale_matched_lift():
    rgb = np.asarray([[[0.0, 0.5, 1.0], [0.2, 0.3, 0.4]]], dtype=np.float32)
    luma = rgb @ np.asarray([0.299, 0.587, 0.114], np.float32)
    expected = np.clip((luma / 0.5) ** 0.75 * 0.5, 0.0, 1.0)
    np.testing.assert_allclose(pseudo_nir_albedo(rgb), expected, rtol=0.0, atol=1e-6)
    contract = formula_contract()
    assert contract["id"] == "pseudo_monotone_gamma_bt601_v2"
    assert contract["monotone"] is True
    assert len(contract["implementation_digest"]) == 64


def test_pseudo_nir_never_ranks_a_dark_surface_above_a_light_one():
    """The v1 defect: max(c, 1-c) is V-shaped, so black outshone mid-grey.

    A non-monotone albedo has no inverse, which is fatal for a network meant to
    recover material from the NIR band.
    """
    ramp = np.linspace(0.0, 1.0, 128, dtype=np.float32).reshape(-1, 1).repeat(3, 1)
    values = pseudo_nir_albedo(ramp)
    assert np.all(np.diff(values) >= -1e-7)
    assert values[0] < values[len(values) // 2] < values[-1]


def test_pseudo_nir_holds_the_reference_albedo_fixed():
    """Scale matching: the lift changes contrast, not the overall level.

    An unanchored lift is what put NIR albedo at 1.6-3.0x the visible and left
    the active flash term with nothing to stand out against.
    """
    mid = np.full((1, 1, 3), 0.5, dtype=np.float32)
    np.testing.assert_allclose(pseudo_nir_albedo(mid), 0.5, atol=1e-6)
    dark = pseudo_nir_albedo(np.full((1, 1, 3), 0.1, dtype=np.float32))
    assert 0.1 < float(dark) < 0.5      # lifted, but still below the reference


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
    assert MATERIAL_CONTRACT_VERSION == "blender42-principled-metallic-roughness-v4"


def test_metallic_contract_v2_requires_physical_family_and_non_color_encoding():
    contract = {
        "schema": METALLIC_CONTRACT_SCHEMA, "family": "coverage_mixed",
        "representation": "spatial_texture", "encoding": "linear_scalar",
        "color_space": "non_color", "source": "generated",
        "approximation": "principled_coverage", "generator_id": "worn_metal_coverage_v1", "seed": 7,
    }
    assert validate_metallic_contract(contract) == (True, [])
    invalid = {**contract, "color_space": "sRGB"}
    valid, failures = validate_metallic_contract(invalid)
    assert not valid and "metallic_not_non_color" in failures


def test_legacy_fractional_metallic_is_snapped_and_marked_as_changed():
    dielectric = normalize_legacy_metallic_scalar(0.428296)
    conductor = normalize_legacy_metallic_scalar(0.72)
    assert dielectric["effective_value"] == 0.0
    assert dielectric["reason"] == "legacy_uniform_fractional_to_dielectric"
    assert conductor["effective_value"] == 1.0
    assert conductor["reason"] == "legacy_uniform_fractional_to_conductor"
    assert dielectric["changed"] is True and conductor["changed"] is True


def test_legacy_binary_metallic_is_not_remediated():
    assert normalize_legacy_metallic_scalar(0.0)["changed"] is False
    assert normalize_legacy_metallic_scalar(1.0)["changed"] is False


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


def test_v3_diffuse_transport_contract_multiplies_without_reflectance_division():
    transport = np.asarray([[[2.0, 3.0, 4.0], [9.0, 9.0, 9.0]]], dtype=np.float32)
    reflectance = np.asarray([[[0.5, 0.25, 0.1], [0.0, 0.0, 0.0]]], dtype=np.float32)
    component, valid = diffuse_component_from_transport(transport, reflectance)
    np.testing.assert_allclose(component, transport * reflectance, atol=1e-6)
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


def _v2_contract(family: str = "conductor", **extra):
    return {
        "schema": "robomituba.metallic_contract.v2",
        "family": family,
        "representation": "spatial_texture" if family == "coverage_mixed" else "scalar",
        "encoding": "linear_scalar",
        "color_space": "non_color",
        "source": "original",
        "approximation": "principled_coverage" if family == "coverage_mixed" else "none",
        "generator_id": "legacy_pure_conductor_v1",
        "seed": 0,
        "legacy_inferred": False,
        **extra,
    }


def _augmentation(**extra):
    return {
        "policy_id": "metallic_composition_v1",
        "policy_digest": "d" * 64,
        "node_graph_version": "metallic_aug_nodes_v1",
        "seed": 7,
        "material_seed": 1234567,
        "source_family": "conductor",
        "source_representation": "scalar",
        "semantic_class": "none",
        "composition_class": "metal_hardware",
        "composition_evidence": ["faucet"],
        "source_material": "sink_faucet_chrome",
        "parameters": {"coat_centre": 0.15, "exposed_threshold": 0.7},
        **extra,
    }


def test_v2_metallic_contract_still_validates_and_v3_is_refused_by_default() -> None:
    """Three production call sites validate published contracts with no kwargs.

    Defaulting ``allow_v3`` on would silently widen the acceptance surface of
    every existing dataset, so the default must keep refusing v3.
    """
    from navigation_dataset.ir_principled import validate_metallic_contract as validate

    assert validate(_v2_contract()) == (True, [])
    assert validate(_v2_contract("coverage_mixed")) == (True, [])
    assert validate(_v2_contract("dielectric", approximation="none")) == (True, [])

    v3 = {"schema": "robomituba.metallic_contract.v3"}
    assert validate(v3) == (False, ["invalid_schema"])
    # v2 payloads are unaffected by the opt-in flag.
    assert validate(_v2_contract(), allow_v3=True) == (True, [])


def test_v3_continuous_contract_requires_full_augmentation_provenance() -> None:
    from navigation_dataset.ir_principled import (
        validate_metallic_contract as validate, wrap_continuous_metallic_contract,
    )

    contract = wrap_continuous_metallic_contract(_v2_contract(), _augmentation())
    assert validate(contract, allow_v3=True) == (True, [])

    for key in ("policy_id", "material_seed", "source_family", "parameters", "composition_class"):
        broken = wrap_continuous_metallic_contract(
            _v2_contract(), {k: v for k, v in _augmentation().items() if k != key},
        )
        valid, failures = validate(broken, allow_v3=True)
        assert not valid and f"missing_augmentation_{key}" in failures, key

    missing_source = dict(contract)
    missing_source.pop("source_contract")
    valid, failures = validate(missing_source, allow_v3=True)
    assert not valid and "missing_source_contract" in failures


def test_wrapping_retains_the_v2_payload_verbatim() -> None:
    """The binary label must stay recoverable for a label-level ablation.

    Generated conductors (``rich_metal``) carry extra keys the wrapper never
    knows about; keeping the whole v2 dict rather than rebuilding it preserves
    them, and preserves the authored contract a rebuild would have to guess.
    """
    from navigation_dataset.ir_principled import wrap_continuous_metallic_contract

    authored = _v2_contract(profile="brushed", parameter_digest="a" * 64)
    contract = wrap_continuous_metallic_contract(authored, _augmentation())
    assert contract["source_contract"] == authored
    assert contract["source_contract"]["profile"] == "brushed"
    assert contract["source_contract"]["parameter_digest"] == "a" * 64
    assert contract["generator_id"] == "metallic_composition_v1::legacy_pure_conductor_v1"
    assert contract["seed"] == 1234567


def test_a_dielectric_is_never_promoted_by_the_wrapper() -> None:
    from navigation_dataset.ir_principled import wrap_continuous_metallic_contract

    dielectric = _v2_contract("dielectric")
    assert wrap_continuous_metallic_contract(dielectric, _augmentation()) == dielectric


def test_metallic_family_ids_are_append_only() -> None:
    """0/1/2 are baked into a published categorical uint8 AOV."""
    from navigation_dataset.ir_principled import METALLIC_FAMILY_IDS

    assert METALLIC_FAMILY_IDS["dielectric"] == 0
    assert METALLIC_FAMILY_IDS["conductor"] == 1
    assert METALLIC_FAMILY_IDS["coverage_mixed"] == 2
    assert METALLIC_FAMILY_IDS["continuous_composite"] == 3
