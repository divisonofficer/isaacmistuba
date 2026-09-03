"""What the structural finish budget has to guarantee."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from mitsuba_converter.ir_structural_finish import (
    DEFAULT_SMOOTH_RATE,
    POLICY_SCHEMA,
    choose_for_role,
    finish_report,
    load_policy,
    shell_smooth_fraction,
    smooth_rate_for,
)

REPO = Path(__file__).resolve().parents[3]

#: Fraction of each material's roughness map that can hold a highlight.  The
#: real registry splits like this too: a few mostly-smooth, most with none.
SMOOTH_INDEX = {"polish_a": 0.82, "polish_b": 0.61, "satin": 0.34,
                "matte_a": 0.00, "matte_b": 0.00, "matte_c": 0.01}
SMOOTH_IDS = {"polish_a", "polish_b", "satin"}


def _choices(names=None):
    return [{"id": n} for n in (names or SMOOTH_INDEX)]


def test_shipped_policy_loads_and_covers_every_structural_role() -> None:
    policy = load_policy(REPO / "configs" / "ir_materials" / "structural_finish_v1.json")
    assert policy["schema"] == POLICY_SCHEMA
    assert set(policy["smooth_rate"]) == set(DEFAULT_SMOOTH_RATE)


def test_a_ceiling_never_draws_a_smooth_material() -> None:
    """Flat is what a ceiling is, and its rate says so."""
    policy = load_policy(None)
    assert smooth_rate_for(policy, "ceiling") == 0.0
    rng = random.Random(0)
    picked = {choose_for_role(_choices(), "ceiling", rng,
                              policy=policy, roughness=SMOOTH_INDEX)["id"]
              for _ in range(120)}
    assert not (picked & SMOOTH_IDS)


def test_a_floor_draws_smooth_far_more_often_than_a_wall() -> None:
    policy = load_policy(None)
    def rate(role):
        rng = random.Random(7)
        hits = sum(choose_for_role(_choices(), role, rng, policy=policy,
                                   roughness=SMOOTH_INDEX)["id"] in SMOOTH_IDS
                   for _ in range(600))
        return hits / 600
    floor, wall = rate("floor"), rate("wall")
    assert floor > wall
    assert floor == pytest.approx(smooth_rate_for(policy, "floor"), abs=0.08)
    assert wall == pytest.approx(smooth_rate_for(policy, "wall"), abs=0.08)


def test_an_empty_pool_falls_through_rather_than_failing() -> None:
    """A finish preference must never be why a scene cannot be rendered."""
    policy = load_policy(None)
    only_smooth = {"polish_a": 0.82}
    record = choose_for_role(_choices(only_smooth), "ceiling", random.Random(1),
                             policy=policy, roughness=only_smooth)
    assert record["id"] == "polish_a"


def test_a_role_with_no_rate_keeps_the_uniform_draw() -> None:
    """An unlisted role must behave exactly as it did before the policy."""
    policy = load_policy(None)
    assert smooth_rate_for(policy, "soffit") is None
    rng_a, rng_b = random.Random(3), random.Random(3)
    chosen = choose_for_role(_choices(), "soffit", rng_a,
                             policy=policy, roughness=SMOOTH_INDEX)
    plain = _choices()[rng_b.randrange(len(_choices()))]
    assert chosen["id"] == plain["id"]


def test_material_with_no_measurement_counts_as_matte() -> None:
    """An unreadable map must not be treated as a highlight source."""
    policy = load_policy(None)
    picked = {choose_for_role(_choices(["unmeasured", "polish_a"]), "floor", random.Random(4),
                              policy=policy, roughness={"polish_a": 0.82})["id"]
              for _ in range(80)}
    assert picked <= {"unmeasured", "polish_a"}
    assert shell_smooth_fraction([{"material_id": "unmeasured"}], {}) is None


def test_shell_fraction_estimates_the_rendered_measurement() -> None:
    bindings = [{"material_id": n, "role": "wall"} for n in ("polish_a", "matte_a")]
    assert shell_smooth_fraction(bindings, SMOOTH_INDEX) == pytest.approx(0.41)


def test_report_flags_a_shell_that_collapsed_to_one_extreme() -> None:
    """The corpus failure this policy exists to prevent, in both directions."""
    policy = load_policy(None)
    def report(name, n=6):
        return finish_report([{"material_id": name, "role": "wall"} for _ in range(n)],
                             SMOOTH_INDEX, policy)
    assert report("matte_a")["within_target"] is False
    assert report("polish_a")["within_target"] is False
    mixed = [{"material_id": n, "role": "wall"} for n in ("polish_b", "matte_a", "matte_b", "matte_c")]
    assert finish_report(mixed, SMOOTH_INDEX, policy)["within_target"] is True


def test_report_is_deterministic_for_the_same_policy() -> None:
    policy = load_policy(None)
    bindings = [{"material_id": n, "role": "floor"} for n in SMOOTH_INDEX]
    first = finish_report(bindings, SMOOTH_INDEX, policy)
    assert first == finish_report(bindings, SMOOTH_INDEX, policy)


def test_policy_rejects_a_rate_that_is_not_a_probability(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": POLICY_SCHEMA, "smooth_rate": {"floor": 1.4}}))
    with pytest.raises(ValueError, match="probability"):
        load_policy(bad)


def test_a_wall_does_not_get_a_coarse_wood_texture() -> None:
    """The defect a render A/B exposed: smooth bought at the cost of sense.

    Wood is the coarsest family the registry stocks, and a 2 m repeat on a wall
    reads as planks running the length of the room.
    """
    from mitsuba_converter.ir_structural_finish import suitable
    policy = load_policy(REPO / "configs" / "ir_materials" / "structural_finish_v1.json")
    wood = {"id": "wood", "surface_family": "wood",
            "physical_size_m": {"width": 2.0, "height": 2.0}}
    tile = {"id": "tile", "surface_family": "tile",
            "physical_size_m": {"width": 1.2, "height": 1.2}}
    assert suitable(wood, "floor", policy) is True
    assert suitable(wood, "wall", policy) is False
    assert suitable(tile, "wall", policy) is True


def test_a_repeat_too_coarse_for_the_role_is_rejected() -> None:
    from mitsuba_converter.ir_structural_finish import suitable
    policy = load_policy(REPO / "configs" / "ir_materials" / "structural_finish_v1.json")
    coarse = {"id": "c", "surface_family": "tile",
              "physical_size_m": {"width": 2.0, "height": 2.0}}
    fine = {"id": "f", "surface_family": "tile",
            "physical_size_m": {"width": 1.2, "height": 1.2}}
    assert suitable(coarse, "wall", policy) is False   # over the 1.5 m wall limit
    assert suitable(coarse, "floor", policy) is True   # a floor takes it
    assert suitable(fine, "wall", policy) is True


def test_suitability_outranks_the_smooth_budget() -> None:
    """A smooth but unsuitable material must not win the draw."""
    policy = load_policy(REPO / "configs" / "ir_materials" / "structural_finish_v1.json")
    choices = [{"id": "smooth_wood", "surface_family": "wood",
                "physical_size_m": {"width": 2.4, "height": 2.4}},
               {"id": "matte_tile", "surface_family": "tile",
                "physical_size_m": {"width": 1.2, "height": 1.2}}]
    rough = {"smooth_wood": 0.90, "matte_tile": 0.0}
    picked = {choose_for_role(choices, "wall", random.Random(n),
                              policy=policy, roughness=rough)["id"] for n in range(40)}
    assert picked == {"matte_tile"}


def test_repeat_ceiling_holds_without_any_policy() -> None:
    """The stretched wall is a defect, so it is checked whatever the finish is."""
    from mitsuba_converter.ir_structural_finish import repeat_fits
    coarse = {"id": "c", "surface_family": "wood",
              "physical_size_m": {"width": 2.4, "height": 2.4}}
    fine = {"id": "f", "surface_family": "wood",
            "physical_size_m": {"width": 1.2, "height": 1.2}}
    assert repeat_fits(coarse, "wall") is False
    assert repeat_fits(coarse, "floor") is True    # seen obliquely, it reads fine
    assert repeat_fits(fine, "wall") is True
    # A role the ceiling does not name is left alone.
    assert repeat_fits(coarse, "soffit") is True
