"""Camera paths that hover around one ABO object, for video inverse rendering.

The Cornell-box placement is this file's; the angle arithmetic is not. That
lives in hssd_blender_ir.hover_path, written for the HSSD hover mode, and is
imported rather than reimplemented -- the two corpora disagree about what a
room is, and agree exactly about what a sphere is.

What this does NOT share with the HSSD mode is target selection. That one
picks interior assets out of a furnished room and runs an interior preflight;
here a single ABO product sits in a five-metre box, and the questions are
different ones: which object is not buried inside another, and where can the
camera stand without a table between it and the object.

Aim point: the object's measured bounding-box centre, never its origin. ABO
GLB origins sit on the object's base, which is the host table's surface -- a
camera aimed there frames the tabletop and clips the object's head off. At
1 m radius the frame is 0.83 x 0.62 m, so an origin 0.23 m below the centre
is 37% of the frame height of error, which is what it looked like.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "hssd_blender_ir" / "src"))
from hssd_blender_ir import hover_path  # noqa: E402

SCHEMA = "abo_hover_trajectory/3"

RADIUS_M = 1.0
AZIMUTH_SPAN_DEG = 60.0     # the total sweep, -30..+30, as the HSSD mode names it
ELEVATION_DEG = 55.0
# pace() takes an amount, not an angle; this is the factor the HSSD mode uses to
# turn one handheld knob into both the aim wander and the uneven pacing.
PACING_PER_DEG = 0.045
WALL_CLEARANCE_M = 0.25
FLOOR_CLEARANCE_M = 0.30
CEILING_CLEARANCE_M = 0.30
# Above this, two props are sharing a position rather than merely touching,
# and neither is a sensible thing to point a camera at and call identifiable.
BURIAL_FRACTION = 0.50
# With one target the camera sits on a sphere around it and cannot reach
# anything else. Chaining moves the centre it orbits, so the camera now
# translates through the room and can end up inside a lamp -- a line-of-sight
# test never sees that, because the ray it casts starts there.
CAMERA_CLEARANCE_M = 0.12


def _aabb_overlap_fraction(a: dict, b: dict) -> float:
    """Intersection volume over the smaller box. A screen, not a proof: a
    concave host (a table) has a bounding box full of the air its props sit in,
    so a prop on a table scores high against it without touching it. Only
    applied between props of comparable size, where that excuse does not hold.
    """
    inter = 1.0
    for axis in range(3):
        span = min(a["hi"][axis], b["hi"][axis]) - max(a["lo"][axis], b["lo"][axis])
        if span <= 0.0:
            return 0.0
        inter *= span
    volumes = [max(1e-9, box["size"][0] * box["size"][1] * box["size"][2]) for box in (a, b)]
    return inter / min(volumes)


def _contains(point, box) -> bool:
    return all(box["lo"][axis] <= point[axis] <= box["hi"][axis] for axis in range(3))


def _segment_hits_box(origin, end, box) -> bool:
    """Slab test: does the camera-to-object segment pass through this box.

    A box that CONTAINS the segment's end is never an occluder of it: the ray
    stops inside, so nothing in that box stands between the camera and the
    target. Without this the test rejects on the target's own host. ABO props
    sit embedded in their table's bounding box -- measured on abo_cornell_0900,
    a table whose box tops out at 0.865 m holding props centred at 0.80 -- so
    the aim point is inside the table's box and every ray to it "hits" the
    table. That read as total occlusion from all 36 facings on three of five
    chains, which is a check reporting a scene is unshootable because of the
    furniture the subject is standing on.
    """
    if _contains(end, box):
        return False
    near, far = 0.0, 1.0
    for axis in range(3):
        direction = end[axis] - origin[axis]
        lo, hi = box["lo"][axis], box["hi"][axis]
        if abs(direction) < 1e-9:
            if origin[axis] < lo or origin[axis] > hi:
                return False
            continue
        t0 = (lo - origin[axis]) / direction
        t1 = (hi - origin[axis]) / direction
        if t0 > t1:
            t0, t1 = t1, t0
        near, far = max(near, t0), min(far, t1)
        if near > far:
            return False
    return True


def _box_clearance(position, box) -> float:
    """Distance from a point to a box; 0 when the point is inside it."""
    return math.sqrt(sum(max(box["lo"][axis] - position[axis], 0.0,
                             position[axis] - box["hi"][axis]) ** 2
                         for axis in range(3)))


def _inside_room(position, room) -> bool:
    half_width = room["width_m"] / 2.0 - WALL_CLEARANCE_M
    half_depth = room["depth_m"] / 2.0 - WALL_CLEARANCE_M
    return (abs(position[0]) <= half_width and abs(position[1]) <= half_depth
            and FLOOR_CLEARANCE_M <= position[2] <= room["height_m"] - CEILING_CLEARANCE_M)


def _smoothstep(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def centroid_at(targets: list[dict], t: float, window: float) -> tuple[list[float], int]:
    """Where the camera is looking at fraction `t` of the take, and whose it is.

    With one target this is that target, forever. With several the aim slides
    from one to the next over a window in the middle of each leg, so the take
    is a camera walking from object to object rather than a cut between two
    orbits. The camera keeps its radius from THIS point, not from the object it
    started on, which is what makes the move read as carrying the framing
    across rather than drifting away from one thing and back onto another.

    Returns the interpolated centre and the index of whichever target the aim
    is closer to, which is the one the occlusion gate and the record use.
    """
    if len(targets) == 1:
        return list(targets[0]["centre"]), 0
    legs = len(targets) - 1
    scaled = min(0.999999, max(0.0, t)) * legs
    leg = int(scaled)
    local = scaled - leg
    start, end = targets[leg]["centre"], targets[leg + 1]["centre"]
    # Dwell, hand over, dwell. `window` is the fraction of a leg spent moving.
    edge = (1.0 - window) / 2.0
    blend = _smoothstep((local - edge) / window) if window > 0 else (0.0 if local < 0.5 else 1.0)
    centre = [a + (b - a) * blend for a, b in zip(start, end)]
    return centre, (leg if blend < 0.5 else leg + 1)


def candidate_chains(picks: list[dict], count: int, tries: int = 4):
    """Chains to try, nearest neighbour first, in the order worth attempting.

    Nearest is the right first guess and a poor only guess. The nearest object
    to a good subject is often a small one wedged among clutter, and a chain is
    rejected if ANY frame of it is blocked -- so pairing greedily by distance
    throws away takes that a slightly farther partner would have allowed. On
    abo_cornell_0900, nearest-only shot 1 take of 5; the four it lost were all
    small partners (0.18-0.26 m) surrounded on the table, rejected at 27-31 of
    36 facings while a 0.49 m partner cleared 28.
    """
    if not picks:
        return
    if count <= 1:
        for start in picks:
            yield [start]
        return
    for start in picks:
        # Distance alone pairs a 0.56 m subject with the 0.18 m thing nearest
        # it, and at a fixed 1 m the second object then fills 21% of frame
        # width against the first's 68%. The radius is the user's spec and not
        # the place to absorb that, so the size ratio is paid for here: a
        # partner twice the distance away is worth it if it frames comparably.
        def pairing_cost(other):
            ratio = max(max(start["size"]), max(other["size"])) / \
                    max(1e-6, min(max(start["size"]), max(other["size"])))
            return math.dist(start["centre"], other["centre"]) * (1.0 + 0.6 * (ratio - 1.0))
        rest = sorted((b for b in picks if b is not start), key=pairing_cost)
        for partner in rest[:tries]:
            chain = [start, partner]
            while len(chain) < count:
                used = {id(c) for c in chain}
                more = [b for b in picks if id(b) not in used]
                if not more:
                    break
                chain.append(min(more, key=lambda b: math.dist(chain[-1]["centre"], b["centre"])))
            if len(chain) == count:
                yield chain


def plan_arc(targets: list[dict], blockers: list[dict], room: dict, *, frames: int,
             radius: float, azimuth_span_deg: float, elevation_deg: float,
             facing_candidates: int, handheld_deg: float, shape: str,
             seed: int, handoff_window: float) -> dict[str, Any] | None:
    """One unobstructed take across `targets`, or None if no facing gives one.

    All or nothing, deliberately. A blocked sample dropped from the middle of a
    take leaves a video with a hole in it, which is worse than a scene that
    reports it could not be shot. With several targets that gate gets harder,
    because every sample has to clear against whichever object it is on.
    """
    lowest = highest = None
    for target in targets:
        low, high = hover_path.elevation_band_deg(
            target["centre"][2], radius,
            band=(FLOOR_CLEARANCE_M, room["height_m"] - CEILING_CLEARANCE_M),
            requested=elevation_deg)
        # The take is one move, so it has to fit inside what EVERY object it
        # visits allows. Taking the first object's band would put the camera
        # through the floor over a lower one later in the same shot.
        lowest = low if lowest is None else max(lowest, low)
        highest = high if highest is None else min(highest, high)
    highest = max(lowest, highest)

    samples = hover_path.arc(frames, azimuth_span_deg, lowest, highest,
                             pacing=handheld_deg * PACING_PER_DEG, seed=seed, shape=shape)
    hands = [hover_path.handheld(index, frames, handheld_deg, seed)
             for index in range(frames)]
    span = [centroid_at(targets, index / max(1, frames - 1), handoff_window)
            for index in range(frames)]

    rejected = 0
    for index in range(facing_candidates):
        facing = 2.0 * math.pi * index / facing_candidates
        positions = [hover_path.camera_position(centre, radius * hand["radius_scale"],
                                                facing, s["azimuth_deg"], s["elevation_deg"])
                     for s, hand, (centre, _) in zip(samples, hands, span)]
        if not all(_inside_room(p, room) for p in positions):
            rejected += 1
            continue
        if any(_box_clearance(p, box) < CAMERA_CLEARANCE_M
               for p in positions for box in blockers):
            rejected += 1
            continue
        # Cast at the object, never along the wandered aim. Testing where the
        # camera happens to be pointing lets the hand walk the ray off the
        # target and report an occlusion that is really just a hand.
        if any(_segment_hits_box(p, centre, box)
               for p, (centre, owner) in zip(positions, span)
               for box in blockers if box is not targets[owner]):
            rejected += 1
            continue
        aims = [hover_path.aim_point(p, centre, hand["yaw_deg"], hand["pitch_deg"])
                for p, hand, (centre, _) in zip(positions, hands, span)]
        # The gate is pass/fail per sample and cannot see a trend: a take that
        # walks steadily into a corner passes every frame and still ends with a
        # wall filling part of it. Recorded per take so the worst frame is
        # visible without re-deriving it -- a peer's user found exactly that on
        # HSSD by reading the table, where clearance fell 1.34 m to 0.334 m
        # across one shot with every sample clearing.
        half = (room["width_m"] / 2.0, room["depth_m"] / 2.0)
        wall = [min(half[0] - abs(p[0]), half[1] - abs(p[1]),
                    p[2], room["height_m"] - p[2]) for p in positions]
        near = [min(_box_clearance(p, box) for box in blockers) for p in positions]
        return {"facing_rad": facing, "samples": samples, "positions": positions,
                "aims": aims, "hands": hands, "span": span,
                "wall_clearance_m": [round(min(wall), 3), round(max(wall), 3)],
                "object_clearance_m": [round(min(near), 3), round(max(near), 3)],
                "wall_clearance_trend": round(
                    (sum(wall[len(wall)//2:]) / max(1, len(wall) - len(wall)//2))
                    / max(1e-6, sum(wall[:len(wall)//2]) / max(1, len(wall)//2)), 3),
                "elevation_from_deg": lowest, "elevation_to_deg": highest,
                "facings_rejected": rejected,
                "angular_steps_deg": hover_path.angular_steps_deg(samples),
                "turn_angles_deg": hover_path.turn_angles_deg(samples)}
    return None


def choose_targets(boxes: list[dict], instances: list[dict], count: int) -> list[dict]:
    """Props that are neither hosts, luminaires, nor buried in another prop."""
    for box, instance in zip(boxes, instances):
        box["source_id"] = instance.get("source_id")
        box["instance_id"] = instance.get("instance_id")
        box["role"] = instance.get("abo_role")
    props = [b for b in boxes if b.get("role") == "prop"]
    out = []
    for box in sorted(props, key=lambda b: -max(b["size"])):
        buried = max((_aabb_overlap_fraction(box, other) for other in props
                      if other is not box
                      and 0.5 <= max(other["size"]) / max(box["size"]) <= 2.0),
                     default=0.0)
        box["burial_fraction"] = buried
        if buried <= BURIAL_FRACTION:
            out.append(box)
        if len(out) >= count:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", type=Path, required=True,
                        help="composed scene directory holding scene_manifest.json")
    parser.add_argument("--bboxes", type=Path, required=True,
                        help="measured world bounding boxes (apps/dump_abo_scene_bboxes.py)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=20, help="frames per trajectory")
    parser.add_argument("--radius", type=float, default=RADIUS_M)
    parser.add_argument("--azimuth-span-deg", type=float, default=AZIMUTH_SPAN_DEG,
                        help="the TOTAL sweep, as the HSSD hover mode names it")
    parser.add_argument("--elevation-deg", type=float, default=ELEVATION_DEG)
    parser.add_argument("--targets", type=int, default=1,
                        help="how many separate takes to write")
    parser.add_argument("--chain", type=int, default=1,
                        help="objects visited within ONE take; the aim hands over from each "
                             "to its nearest unused neighbour without cutting")
    parser.add_argument("--handoff-window", type=float, default=0.40,
                        help="fraction of each leg spent moving the aim; the rest dwells")
    parser.add_argument("--facing-candidates", type=int, default=36)
    parser.add_argument("--hover-handheld-deg", type=float, default=hover_path.HANDHELD_DEG,
                        help="how far the aim may wander, in degrees, plus the roll and "
                             "uneven pacing that come with it; 0 gives a rigid orbit")
    parser.add_argument("--hover-shape", choices=["quartic", "corner"], default="quartic",
                        help="quartic bends the path; corner is the original two-segment L, "
                             "kept reachable for frames already rendered against it")
    parser.add_argument("--seed", type=int, default=0,
                        help="picks the hand; the same seed always gives the same camera")
    args = parser.parse_args()

    manifest = json.loads((args.scene / "scene_manifest.json").read_text(encoding="utf-8"))
    room = manifest["room"]
    instances = manifest["instances"]
    measured = json.loads(args.bboxes.read_text(encoding="utf-8"))
    boxes = [b for b in measured if b["name"].startswith("RootNode")]
    if len(boxes) != len(instances):
        parser.error(f"{len(boxes)} measured boxes vs {len(instances)} instances: "
                     "the dump is from a different scene")

    targets = choose_targets(boxes, instances, max(1, args.targets) * max(1, args.chain))
    if not targets:
        parser.error("every prop in this scene is buried inside another one")

    poses, summaries = [], []
    used: set[int] = set()
    for _ in range(max(1, args.targets)):
        available = [t for t in targets if id(t) not in used]
        chain = plan = None
        for candidate in candidate_chains(available, args.chain):
            # The chain's own members are not occluders of each other. One
            # does stand in front of the other -- on the first chain here the
            # starting object was in front of the finishing one for frames
            # 26-30 -- and that is footage, not a defect: the subject is still
            # in frame, nothing is buried in the camera, and a take that walks
            # between two objects on one table is going to see both. Rejecting
            # on it took the facings rejected from 0-20 up to 25-29 and would
            # have thrown away takes to enforce a rule nobody wanted.
            attempt = plan_arc(candidate, [b for b in boxes if b not in candidate], room,
                               frames=args.frames, radius=args.radius,
                               azimuth_span_deg=args.azimuth_span_deg,
                               elevation_deg=args.elevation_deg,
                               facing_candidates=args.facing_candidates,
                               handheld_deg=args.hover_handheld_deg,
                               shape=args.hover_shape, seed=args.seed + len(summaries),
                               handoff_window=args.handoff_window)
            if attempt is not None:
                chain, plan = candidate, attempt
                break
        if plan is None:
            # Nothing left that can be shot, rather than one pairing that could
            # not be. Objects are consumed on success only: a chain rejected for
            # occlusion must not take its members out of the pool, or one bad
            # partner costs a good subject its take.
            break
        used.update(id(t) for t in chain)
        for order, (sample, position, aim, hand, (centre, owner)) in enumerate(
                zip(plan["samples"], plan["positions"], plan["aims"],
                    plan["hands"], plan["span"])):
            target = chain[owner]
            poses.append({
                "position": list(position),
                # `target` is where the camera looks, which the hand has moved
                # off the object; `object_centroid` is what it is looking at,
                # and with a chain that point MOVES -- it slides from one
                # object to the next rather than cutting. `object_source_id`
                # says whose it is closest to at this frame.
                "target": list(aim),
                "object_centroid": [round(v, 6) for v in centre],
                "pose_mode": "hover_trajectory",
                "trajectory_order": order,
                "trajectory_segment": sample["segment"],
                "sequence_index": order, "sequence_length": args.frames,
                "take_index": len(summaries),
                "hover_segment": sample["segment"],
                "hover_shape": args.hover_shape,
                "hover_azimuth_deg": round(sample["azimuth_deg"], 4),
                "hover_elevation_deg": round(sample["elevation_deg"], 4),
                "hover_radius_m": round(args.radius * hand["radius_scale"], 4),
                "handheld_roll_deg": round(hand["roll_deg"], 4),
                "handheld_deg": args.hover_handheld_deg,
                "chain_index": owner, "chain_length": len(chain),
                "target_distance_m": args.radius,
                "target_source_id": target["source_id"],
                "target_instance_id": target["instance_id"],
                "specular_score": 0.0, "base_score": 0.0,
                "coverage": {}, "pose_qc": {}, "specular": {},
            })
        steps = plan["angular_steps_deg"]
        moves = [math.dist(plan["positions"][i], plan["positions"][i + 1])
                 for i in range(len(plan["positions"]) - 1)]
        summaries.append({
            "source_id": " -> ".join(t["source_id"] for t in chain),
            "chain": [t["source_id"] for t in chain],
            "instance_id": chain[0]["instance_id"],
            "target": chain[0]["centre"], "size_m": chain[0]["size"],
            "burial_fraction": round(chain[0]["burial_fraction"], 4),
            "radius_m": args.radius, "facing_rad": plan["facing_rad"],
            "facings_rejected": plan["facings_rejected"],
            "elevation_requested_deg": args.elevation_deg,
            "elevation_from_deg": plan["elevation_from_deg"],
            "elevation_to_deg": plan["elevation_to_deg"],
            "frames": args.frames,
            "handoff_window": args.handoff_window,
            "angular_step_deg": [round(min(steps), 3), round(max(steps), 3)],
            "move_cm": [round(100 * min(moves), 2), round(100 * max(moves), 2)],
            "max_turn_deg": round(max(plan["turn_angles_deg"]), 3) if plan["turn_angles_deg"] else 0.0,
            "shape": args.hover_shape, "handheld_deg": args.hover_handheld_deg,
            "seed": args.seed + len(summaries),
            "roll_deg": [round(min(h["roll_deg"] for h in plan["hands"]), 3),
                         round(max(h["roll_deg"] for h in plan["hands"]), 3)],
            "wall_clearance_m": plan["wall_clearance_m"],
            "object_clearance_m": plan["object_clearance_m"],
            # Second half's mean clearance over the first half's. Below about
            # 0.7 the take is walking into something over its length, which no
            # per-sample gate reports.
            "wall_clearance_trend": plan["wall_clearance_trend"],
        })

    if not poses:
        print("[hover] nothing shootable in this scene")
        return 1

    # An empty `important` list renders the baseline lighting only: a video
    # wants one lighting condition from its first frame to its last.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"all": poses, "important": [],
                                    "hover": {"schema": SCHEMA, "trajectories": summaries}},
                                   indent=2), encoding="utf-8")
    print(f"[hover] {len(summaries)} trajectories, {len(poses)} poses -> {args.out}")
    for s in summaries:
        print(f"    {s['source_id']}   move {s['move_cm'][0]}-{s['move_cm'][1]}cm/frame")
        print(f"      elevation {s['elevation_from_deg']:.1f}..{s['elevation_to_deg']:.1f}deg"
              f" (asked {s['elevation_requested_deg']:.0f})   {s['shape']}"
              f"   step {s['angular_step_deg'][0]}-{s['angular_step_deg'][1]}deg"
              f"   max turn {s['max_turn_deg']}deg")
        print(f"      hand {s['handheld_deg']:.1f}deg seed {s['seed']}"
              f"   roll {s['roll_deg'][0]}..{s['roll_deg'][1]}deg")
        print(f"      facings rejected before one cleared: {s['facings_rejected']}"
              f"   burial {s['burial_fraction']*100:.0f}%")
        print(f"      clearance wall {s['wall_clearance_m'][0]}-{s['wall_clearance_m'][1]}m"
              f" (trend {s['wall_clearance_trend']})"
              f"   object {s['object_clearance_m'][0]}-{s['object_clearance_m'][1]}m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
