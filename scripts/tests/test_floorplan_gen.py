"""Pure-python invariant tests for floorplan_gen (no Blender/Infinigen/shapely).

Run with the default interpreter:  pytest scripts/tests/test_floorplan_gen.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

import floorplan_gen as fg  # noqa: E402

APARTMENT_SEEDS = range(20_010_000, 20_010_200)
OFFICE_SEEDS = range(20_510_000, 20_510_200)
SINGLE_ROOM_SEEDS = range(20_710_000, 20_710_020)


def _all(arch, seeds):
    return [fg.build_floor_plan(s, arch) for s in seeds]


def test_apartment_valid():
    for s in APARTMENT_SEEDS:
        plan = fg.build_floor_plan(s, "apartment")
        assert fg.validate_plan(plan) == [], f"seed={s}"


def test_office_valid():
    for s in OFFICE_SEEDS:
        plan = fg.build_floor_plan(s, "office")
        assert fg.validate_plan(plan) == [], f"seed={s}"


def test_determinism():
    for s in (20_010_042, 20_510_042):
        a = fg.build_floor_plan(s, "apartment" if s < 20_500_000 else "office")
        b = fg.build_floor_plan(s, "apartment" if s < 20_500_000 else "office")
        assert a == b


def test_room_counts():
    apt = [len(p["rooms"]) for p in _all("apartment", APARTMENT_SEEDS)]
    off = [len(p["rooms"]) for p in _all("office", OFFICE_SEEDS)]
    assert all(6 <= n <= 9 for n in apt), (min(apt), max(apt))
    assert min(off) >= 18, min(off)  # "dozens of rooms"


def _incident_rooms(line_pts, rects):
    """Rooms whose box edge the door/open line lies on (mirrors validate_plan)."""
    (ax, ay), (bx, by) = line_pts[0], line_pts[-1]
    vert = abs(ax - bx) < 1e-6
    const = ax if vert else ay
    lo, hi = (min(ay, by), max(ay, by)) if vert else (min(ax, bx), max(ax, bx))
    hit = []
    for n, r in rects.items():
        if vert and (abs(r[0] - const) < 1e-6 or abs(r[2] - const) < 1e-6):
            if min(r[3], hi) - max(r[1], lo) > 1e-6:
                hit.append(n)
        elif not vert and (abs(r[1] - const) < 1e-6 or abs(r[3] - const) < 1e-6):
            if min(r[2], hi) - max(r[0], lo) > 1e-6:
                hit.append(n)
    return hit


def test_no_thin_connecting_edges():
    """Every emitted door/open must sit on a SHARED EDGE strictly > Infinigen's
    1.4 m segment_margin (doors are placed only on edges >= 1.6)."""
    for arch, seeds in (("apartment", APARTMENT_SEEDS), ("office", OFFICE_SEEDS)):
        for s in seeds:
            plan = fg.build_floor_plan(s, arch)
            rects = {n: fg._parse_box(v["shape"]) for n, v in plan["rooms"].items()}
            for grp in ("doors", "opens"):
                for spec in plan[grp].values():
                    hit = _incident_rooms(fg._parse_line(spec["shape"]), rects)
                    # exterior entrance doors touch only one room; skip those
                    if len(hit) < 2:
                        continue
                    se = fg.shared_edge(rects[hit[0]], rects[hit[1]])
                    assert se and se[4] > fg.MARGIN, (arch, s, grp, se)


def test_naming_and_types():
    for arch, seeds in (("apartment", APARTMENT_SEEDS), ("office", OFFICE_SEEDS)):
        for s in seeds:
            for name in fg.build_floor_plan(s, arch)["rooms"]:
                assert fg._NAME_RE.match(name), name
                assert name.split("_")[0] in fg._VALID_TYPES, name


def test_archetype_signatures():
    apt = fg.build_floor_plan(20_010_001, "apartment")
    assert "living-room_0/0" in apt["rooms"]
    assert any(v.get("is_panoramic") for v in apt["windows"].values())  # 통창
    off = fg.build_floor_plan(20_510_001, "office")
    types = {n.split("_")[0] for n in off["rooms"]}
    assert "hallway" in types and "office" in types


def test_single_room_types_valid_and_windowed():
    for room_type in fg.SINGLE_ROOM_TYPES:
        for seed in SINGLE_ROOM_SEEDS:
            plan = fg.build_single_room_plan(seed, room_type)
            assert fg.validate_plan(plan) == [], (room_type, seed)
            assert len(plan["rooms"]) == 1
            assert f"{room_type}_0/0" in plan["rooms"]
            assert len(plan["doors"]) == 1
            assert len(plan["windows"]) == 1


def test_single_room_determinism_and_panoramic_living_room():
    for room_type in fg.SINGLE_ROOM_TYPES:
        assert fg.build_single_room_plan(20_710_042, room_type) == fg.build_single_room_plan(20_710_042, room_type)
    living = fg.build_single_room_plan(20_710_042, "living-room")
    assert next(iter(living["windows"].values()))["is_panoramic"] == 1
