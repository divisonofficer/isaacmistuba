"""Single-room floor area is sampled, stays valid, and never shrinks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import floorplan_gen as F


def _area(plan):
    shape = list(plan["rooms"].values())[0]["shape"]
    n = [float(x) for x in shape[shape.index("(") + 1:shape.rindex(")")].split(",")]
    return (n[2] - n[0]) * (n[3] - n[1]), (n[2] - n[0]), (n[3] - n[1])


def test_area_varies_far_more_than_the_three_authored_anchors():
    areas = {_area(F.build_single_room_plan(s, "office"))[0] for s in range(200)}
    assert len(areas) > 20, f"only {len(areas)} distinct areas; sampling is not happening"
    anchors = [w * d for w, d in F.SINGLE_ROOM_PROFILES["office"]["sizes"]]
    assert max(areas) > max(anchors) * 2.5


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
