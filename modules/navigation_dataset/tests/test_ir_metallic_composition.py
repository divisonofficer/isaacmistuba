from __future__ import annotations

import numpy as np
import pytest

from navigation_dataset.ir_metallic_composition import (
    CONDUCTOR_FAMILIES,
    coat_field,
    composition_class,
    correlation_report,
    default_policy,
    hash_residual,
    luminance,
    material_seed,
    metallic_field,
    roughness_field,
    sample_coefficients,
    stable_digest,
)

POLICY = default_policy()
POLICY_DIGEST = stable_digest(POLICY)


def _slot(unit_id: str, material: str, *, slot: int = 0, family: str = "conductor"):
    composition = composition_class(
        unit={"id": unit_id, "kind": "asset"}, source_material=material, source_family=family,
    )
    seed = material_seed(policy_digest=POLICY_DIGEST, scene_id="scene",
                         unit_id=unit_id, slot=slot, source_material=material)
    return composition, seed, sample_coefficients(
        policy=POLICY, composition=composition["class"], seed=seed,
    )


def _corpus(count: int = 200, pixels: int = 4096, *, scene: str = "scene"):
    """A corpus shaped like the measured Infinigen metal population.

    Sampled from ``/bean/ir_dataset`` metal-bearing pixels: roughness is narrow
    *within* a material (std ~0.06) and varies mostly *between* materials
    (pooled mean 0.29).  A uniform-roughness corpus is far wider than reality
    and would tune the coupling against a distribution the renderer never
    produces -- that mistake is what the first cut of this model made.
    """
    rng = np.random.default_rng(11)
    materials = ("faucet", "pan_body", "fridge_shell", "chair_frame", "ornament", "knife")
    metallic, roughness = [], []
    for index in range(count):
        unit = f"u{index:04d}"
        material = materials[index % len(materials)]
        composition = composition_class(unit={"id": unit, "kind": "asset"},
                                        source_material=material, source_family="conductor")
        seed = material_seed(policy_digest=POLICY_DIGEST, scene_id=scene,
                             unit_id=unit, slot=0, source_material=material)
        coefficients = sample_coefficients(policy=POLICY, composition=composition["class"], seed=seed)
        material_roughness = float(np.clip(rng.normal(0.29, 0.13), 0.03, 0.85))
        rough = np.clip(rng.normal(material_roughness, 0.06, pixels), 0.0, 1.0).astype(np.float32)
        lum = np.clip(rng.normal(0.45, 0.22, pixels), 0.0, 1.0).astype(np.float32)
        residual = hash_residual((pixels,), seed=seed)
        metallic.append(metallic_field(
            source_metallic=np.ones(pixels, np.float32), roughness=rough, albedo_luminance=lum,
            residual=residual, coefficients=coefficients, source_family="conductor",
        ))
        roughness.append(rough)
    return np.concatenate(metallic), np.concatenate(roughness)


def test_composition_class_is_deterministic_and_records_evidence() -> None:
    for material, expected in (
        ("kitchen_knife_steel", "metal_tool"),
        ("frying_pan_base", "cookware"),
        ("sink_faucet_chrome", "metal_hardware"),
        ("fridge_shell_paint", "appliance_shell"),
        ("chair_frame_metal", "structural_metal"),
        ("brass_ornament", "decor_metal"),
        ("unlabelled_thing", "generic_metal"),
    ):
        first = composition_class(unit={"id": "u", "kind": "asset"},
                                  source_material=material, source_family="conductor")
        assert first["class"] == expected, material
        assert first == composition_class(unit={"id": "u", "kind": "asset"},
                                          source_material=material, source_family="conductor")
        if expected != "generic_metal":
            assert first["evidence"], material


def test_dielectric_is_never_promoted_into_metal() -> None:
    """A painted wall must not become metal, whatever its roughness or albedo."""
    composition = composition_class(unit={"id": "wall"}, source_material="plaster",
                                    source_family="dielectric")
    assert composition["class"] == "dielectric"
    assert "dielectric" not in CONDUCTOR_FAMILIES
    _, _, coefficients = _slot("wall", "plaster")
    result = metallic_field(
        source_metallic=np.ones(64, np.float32), roughness=np.linspace(0, 1, 64, dtype=np.float32),
        albedo_luminance=np.linspace(0, 1, 64, dtype=np.float32),
        residual=hash_residual((64,), seed=3), coefficients=coefficients,
        source_family="dielectric",
    )
    assert np.array_equal(result, np.zeros(64, np.float32))


def test_coefficients_are_reproducible_and_locally_seeded() -> None:
    _, seed_a, first = _slot("unit_a", "faucet")
    _, seed_a_again, again = _slot("unit_a", "faucet")
    assert seed_a == seed_a_again and first == again
    # A different slot of the same unit is an independent draw...
    _, seed_slot1, other_slot = _slot("unit_a", "faucet", slot=1)
    assert seed_slot1 != seed_a and other_slot != first
    # ...and an unrelated unit must not perturb this one.
    _slot("unit_b", "faucet")
    assert _slot("unit_a", "faucet")[2] == first


def test_conductor_prior_never_falls_below_its_floor() -> None:
    for material in ("knife", "pan", "faucet", "fridge_shell", "chair_frame", "ornament"):
        _, seed, coefficients = _slot("u", material)
        result = metallic_field(
            source_metallic=np.ones(512, np.float32),
            roughness=np.linspace(0.0, 1.0, 512, dtype=np.float32),
            albedo_luminance=np.zeros(512, np.float32),  # worst case for the albedo term
            residual=np.ones(512, np.float32),           # worst case for the residual term
            coefficients=coefficients, source_family="conductor",
        )
        assert float(result.min()) >= coefficients["metallic_floor"] - 1e-6, material
        assert float(result.max()) <= 1.0 + 1e-6


def test_coverage_mixed_preserves_authored_zero_coverage() -> None:
    """Authored coverage geometry stays the authority on *where* metal is."""
    _, seed, coefficients = _slot("panel", "steel_panel", family="coverage_mixed")
    coverage = np.concatenate([np.zeros(128, np.float32), np.ones(128, np.float32)])
    result = metallic_field(
        source_metallic=coverage, roughness=np.full(256, 0.4, np.float32),
        albedo_luminance=np.full(256, 0.5, np.float32), residual=hash_residual((256,), seed=seed),
        coefficients=coefficients, source_family="coverage_mixed",
    )
    assert np.array_equal(result[:128], np.zeros(128, np.float32))
    assert float(result[128:].min()) > 0.0


def test_augmented_metallic_is_not_determined_by_roughness() -> None:
    """The guard for the research claim.

    A deterministic ``M = f(R)`` would let a network read metalness straight off
    the roughness channel, making any "active NIR improved metallic estimation"
    measurement meaningless.  The guarantee is therefore stated as *absence of
    recoverability* -- low ``R^2`` and a conditional spread that stays clearly
    above zero in every roughness bin -- plus the physical sign.

    The correlation *magnitude* is deliberately not pinned: it depends on how
    much composition-class diversity a scene has.  Measured on
    ``/bean/ir_dataset`` the audit sees no semantics at all, collapses every
    slot to ``generic_metal`` and reads ``-0.52``; with class diversity present
    it falls to about ``-0.06``.  Both are acceptable, an ``R^2`` near 1 is not.
    """
    metallic, roughness = _corpus()
    report = correlation_report(metallic, roughness)
    assert report["pearson"] is not None
    assert report["pearson"] < 0.0, "a heavier coat must mean rougher and less metallic"
    assert report["r_squared"] < 0.40, report["r_squared"]
    assert report["min_conditional_std"] >= 0.04, report["conditional_std"]


def test_no_leak_even_when_every_slot_shares_one_composition_class() -> None:
    """The worst case for leakage, and the one real datasets actually hit.

    When no semantic evidence is available every slot classifies as
    ``generic_metal``, so class variance vanishes and roughness becomes the
    dominant between-material signal.  The residual must still carry enough
    independent variance that metalness is not recoverable.
    """
    rng = np.random.default_rng(5)
    metallic, roughness = [], []
    for index in range(200):
        unit = f"g{index:04d}"
        seed = material_seed(policy_digest=POLICY_DIGEST, scene_id="degenerate",
                             unit_id=unit, slot=0, source_material=unit)
        coefficients = sample_coefficients(policy=POLICY, composition="generic_metal", seed=seed)
        material_roughness = float(np.clip(rng.normal(0.29, 0.13), 0.03, 0.85))
        rough = np.clip(rng.normal(material_roughness, 0.06, 4096), 0.0, 1.0).astype(np.float32)
        metallic.append(metallic_field(
            source_metallic=np.ones(4096, np.float32), roughness=rough,
            albedo_luminance=np.clip(rng.normal(0.45, 0.22, 4096), 0, 1).astype(np.float32),
            residual=hash_residual((4096,), seed=seed), coefficients=coefficients,
            source_family="conductor",
        ))
        roughness.append(rough)
    report = correlation_report(np.concatenate(metallic), np.concatenate(roughness))
    assert report["r_squared"] < 0.40, report["r_squared"]
    assert report["min_conditional_std"] >= 0.04, report["conditional_std"]


def test_augmentation_matches_the_measured_reference_distribution() -> None:
    """Break the binary distribution, but keep the pure-metal tail that is real.

    96.4 % of Infinigen metallic GT pixels sit at 0 or 1, which is the problem.
    Coating *everything* over-corrects it though: measured over 34.7 M
    InteriorVerse pixels, genuine PBR interiors keep 1.6 % of metal-bearing
    pixels at metalness >= 0.98, rising to 18.8 % among strongly metallic ones.
    Polished cutlery and chrome really are bare. So the target is a broad
    intermediate mass *with* a surviving tail, not a tail of zero.
    """
    metallic, _ = _corpus()
    intermediate = float(((metallic > 0.02) & (metallic < 0.98)).mean())
    bare = float((metallic >= 0.98).mean())
    assert intermediate > 0.60, intermediate
    assert 0.01 <= bare <= 0.35, bare


def test_roughness_rises_monotonically_with_coat() -> None:
    _, seed, coefficients = _slot("u", "fridge_shell")
    rough = np.full(64, 0.30, np.float32)
    light = coat_field(roughness=rough, albedo_luminance=np.full(64, 0.9, np.float32),
                       residual=np.zeros(64, np.float32), coefficients=coefficients)
    heavy = coat_field(roughness=rough, albedo_luminance=np.zeros(64, np.float32),
                       residual=np.ones(64, np.float32), coefficients=coefficients)
    assert float(heavy.mean()) > float(light.mean())
    assert float(roughness_field(roughness=rough, coat=heavy, coefficients=coefficients).mean()) > \
           float(roughness_field(roughness=rough, coat=light, coefficients=coefficients).mean())


def test_luminance_rejects_non_rgb() -> None:
    assert luminance(np.ones((4, 4, 3), np.float32)).shape == (4, 4)
    with pytest.raises(ValueError):
        luminance(np.ones((4, 4), np.float32))


def test_correlation_report_is_degenerate_safe() -> None:
    flat = correlation_report(np.zeros(64, np.float32), np.zeros(64, np.float32))
    assert flat["pearson"] is None and flat["min_conditional_std"] is None
