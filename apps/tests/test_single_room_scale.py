"""Single-room floor area is sampled, stays valid, and never shrinks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import floorplan_gen as F


def _area(plan):
    shape = list(plan["rooms"].values())[0]["shape"]
    n = [float(x) for x in shape[shape.index("(") + 1:shape.rindex(")")].split(",")]
    return (n[2] - n[0]) * (n[3] - n[1]), (n[2] - n[0]), (n[3] - n[1])


def test_area_varies_instead_of_taking_one_of_three_values():
    areas = {_area(F.build_single_room_plan(s, "office"))[0] for s in range(200)}
    assert len(areas) > 20, f"only {len(areas)} distinct areas; sampling is not happening"


def test_an_ordinary_room_stays_an_ordinary_room():
    # A single room is not an apartment. 136-175 m2 is right for a multi-room
    # flat and absurd for one office, and an earlier version of this sampler
    # scaled offices to 60 m2 because its multiplier did not know what it was
    # scaling.
    for rt in ("office", "meeting-room", "break-room", "living-room", "kitchen",
               "bedroom", "dining-room"):
        areas = [_area(F.build_single_room_plan(s, rt))[0] for s in range(150)]
        assert max(areas) <= F.SINGLE_ROOM_AREA_CAP_M2 + 2.0, f"{rt} reaches {max(areas):.1f} m2"
        assert min(areas) >= 9.0, f"{rt} drops to {min(areas):.1f} m2"


def test_a_small_room_is_not_inflated_into_a_hall():
    # A flat 30 m2 ceiling gave a 30 m2 bathroom and a 19 m2 closet; the ceiling
    # has to come from each type's own authored sizes.
    for rt, limit in (("bathroom", 20.0), ("closet", 16.0), ("restroom", 20.0), ("utility", 22.0)):
        worst = max(_area(F.build_single_room_plan(s, rt))[0] for s in range(150))
        assert worst <= limit, f"{rt} reaches {worst:.1f} m2, over {limit}"


def test_types_that_are_large_in_life_stay_large():
    for rt in ("warehouse", "open-office"):
        areas = [_area(F.build_single_room_plan(s, rt))[0] for s in range(120)]
        assert max(areas) > F.SINGLE_ROOM_AREA_CAP_M2 * 1.5, f"{rt} capped at {max(areas):.1f}"


def test_no_room_is_smaller_than_its_smallest_anchor():
    # A room below the authored floor is the case that could not be furnished:
    # asked for 40 objects, Infinigen placed 17 in 10.5 m2.
    for rt in ("office", "meeting-room", "break-room", "living-room", "kitchen"):
        floor = min(w * d for w, d in F.SINGLE_ROOM_PROFILES[rt]["sizes"])
        worst = min(_area(F.build_single_room_plan(s, rt))[0] for s in range(120))
        assert worst >= floor * 0.95, f"{rt}: {worst:.1f} < anchor floor {floor:.1f}"


def test_rooms_stay_room_shaped():
    for rt in ("office", "meeting-room", "warehouse"):
        for s in range(120):
            _, w, d = _area(F.build_single_room_plan(s, rt))
            assert 0.5 <= w / d <= 2.2, f"{rt} seed {s}: aspect {w/d:.2f}"
            assert min(w, d) >= F.MIN_DIM


def test_every_sampled_plan_still_validates():
    # build_single_room_plan raises on an invalid plan, so reaching the end is
    # the assertion: doors and windows must still fit the wall they sit on.
    for rt in F.SINGLE_ROOM_TYPES:
        for s in range(25):
            F.build_single_room_plan(s, rt)


def test_it_is_deterministic_for_a_seed():
    a = F.build_single_room_plan(4242, "office")
    b = F.build_single_room_plan(4242, "office")
    assert a == b
