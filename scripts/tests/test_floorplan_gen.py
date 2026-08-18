"""Pure-python invariant tests for floorplan_gen (no Blender/Infinigen/shapely).

Run with the default interpreter:  pytest scripts/tests/test_floorplan_gen.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

import floorplan_gen as fg  # noqa: E402

APARTMENT_SEEDS = range(20_010_000, 20_010_200)
OFFICE_SEEDS = range(20_510_000, 20_510_200)
MODERN_OFFICE_SEEDS = range(20_610_000, 20_610_200)
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


def test_modern_office_valid_and_bounded():
    for s in MODERN_OFFICE_SEEDS:
        plan = fg.build_floor_plan(s, fg.MODERN_OFFICE_ARCHETYPE)
        assert fg.validate_plan(plan) == [], f"seed={s}"
        rects = [fg._parse_box(spec["shape"]) for spec in plan["rooms"].values()]
        width = max(rect[2] for rect in rects) - min(rect[0] for rect in rects)
        height = max(rect[3] for rect in rects) - min(rect[1] for rect in rects)
        assert 180 <= width * height <= 300
        types = {name.split("_")[0] for name in plan["rooms"]}
        assert {"open-office", "meeting-room", "office", "break-room", "restroom", "warehouse", "hallway"} <= types


def test_determinism():
    for s in (20_010_042, 20_510_042):
        a = fg.build_floor_plan(s, "apartment" if s < 20_500_000 else "office")
        b = fg.build_floor_plan(s, "apartment" if s < 20_500_000 else "office")
        assert a == b
    for s in (20_610_042, 20_610_043):
        assert fg.build_floor_plan(s, fg.MODERN_OFFICE_ARCHETYPE) == fg.build_floor_plan(s, fg.MODERN_OFFICE_ARCHETYPE)


def test_room_counts():
    apt = [len(p["rooms"]) for p in _all("apartment", APARTMENT_SEEDS)]
    off = [len(p["rooms"]) for p in _all("office", OFFICE_SEEDS)]
    assert all(5 <= n <= 10 for n in apt), (min(apt), max(apt))
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
    for arch, seeds in (("apartment", APARTMENT_SEEDS), ("office", OFFICE_SEEDS),
                        (fg.MODERN_OFFICE_ARCHETYPE, MODERN_OFFICE_SEEDS)):
        for s in seeds:
            for name in fg.build_floor_plan(s, arch)["rooms"]:
                assert fg._NAME_RE.match(name), name
                assert name.split("_")[0] in fg._VALID_TYPES, name


def test_apartment_topology_diversity():
    """build_apartment now varies corridor axis and LDK/bedroom band side (see
    _mirror_y/_transpose_rect) instead of always the same layout; assert both
    corridor orientations actually occur across the seed range."""
    orientations = set()
    for s in APARTMENT_SEEDS:
        plan = fg.build_floor_plan(s, "apartment")
        hall_name = next(n for n in plan["rooms"] if n.startswith("hallway"))
        x0, y0, x1, y1 = fg._parse_box(plan["rooms"][hall_name]["shape"])
        orientations.add("horizontal" if (x1 - x0) > (y1 - y0) else "vertical")
        if orientations == {"horizontal", "vertical"}:
            break
    assert orientations == {"horizontal", "vertical"}, orientations


def test_archetype_signatures():
    apt = fg.build_floor_plan(20_010_001, "apartment")
    assert "living-room_0/0" in apt["rooms"]
    assert any(v.get("is_panoramic") for v in apt["windows"].values())  # 통창
    off = fg.build_floor_plan(20_510_001, "office")
    types = {n.split("_")[0] for n in off["rooms"]}
    assert "hallway" in types and "office" in types
    modern = fg.build_floor_plan(20_610_001, fg.MODERN_OFFICE_ARCHETYPE)
    modern_types = {name.split("_")[0] for name in modern["rooms"]}
    assert "open-office" in modern_types and "meeting-room" in modern_types


def test_modern_office_profile_metadata_has_all_topologies_and_glass_policy():
    seen = set()
    for seed in MODERN_OFFICE_SEEDS:
        metadata = fg.modern_office_metadata(seed)
        seen.add(metadata["topology"])
        assert metadata["profile"] == "modern_hybrid_v1"
        assert 180 <= metadata["footprint_area_m2"] <= 300
        assert metadata["requested_glass_partition_count"] == 3
    assert seen == set(fg.MODERN_OFFICE_TOPOLOGIES)


def test_modern_glass_spec_is_deterministic_and_has_structural_door_openings():
    for seed in (20_610_001, 20_610_042, 20_610_199):
        first = fg.modern_office_partition_spec(seed)
        assert first == fg.modern_office_partition_spec(seed)
        assert first["requested_partition_count"] == 3
        assert first["eligible_segment_count"] >= 3
        assert len(first["segments"]) == 3
        assert len(first["selected_segment_ids"]) == 3
        for segment in first["segments"]:
            assert segment["room"].split("_")[0] in {"meeting-room", "office", "break-room"}
            assert segment["corridor"].startswith("hallway_")
            assert len(segment["wall_endpoints_m"]) == len(segment["door_opening_m"]) == 2


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
