"""Object-centric 6-DoF camera placement for the IR dataset.

Replaces the navigation graph as the camera universe.  The graph gave floor
positions and, at each, the same 24-way yaw sweep at one near-horizontal pitch,
so frames faced whatever the heading happened to hit -- often a bare wall -- and
the distance to what was in view was uncontrolled.  Active NIR irradiance falls
as ``1/r^2``, so distance is not incidental: it decides whether the specular cue
the dataset exists to capture is present at all.

Poses here are placed around an object at a chosen distance and aimed at it, so
pitch follows from the geometry -- looking down at a plate on the floor and up at
a fixture near the ceiling both fall out of the same rule rather than needing a
special case.

Free space is checked without the graph.  Object footprints are extruded to
their real vertical span and tested at the camera's actual height, so a pose
above a table is admitted where a robot-height traversability grid would reject
it.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any, Mapping, Sequence

from .ir_object_anchors import is_structural

SCHEMA = "robomituba.ir_camera_6dof_poses.v1"
SAMPLER_VERSION = "object-orbit-6dof-v1"

#: Confirmed working distance: 1-2 m.
RADIUS_RANGE_M = (1.0, 2.0)
#: A small room physically cannot hold the preferred band -- the bathroom scene is
#: 2.75 x 2.38 m, so standing 1.5 m from a centred object puts the camera in the
#: wall.  Rather than losing those scenes the radius is fitted to the room, down
#: to this floor.  Below it the pose is rejected: 0.25 m was confirmed far too
#: close to be useful.
MIN_FITTED_RADIUS_M = 0.75
#: Where the camera sits relative to the anchor, in degrees.  Positive means
#: above it (so the view looks *down*), negative below (looking *up*).  This is
#: the parameter the dataset actually wants to control, so it is sampled
#: directly; deriving it from an absolute eye height instead made the reachable
#: angle depend on the anchor's height and left whole scenes one-sided.
CAMERA_ELEVATION_RANGE_DEG = (-30.0, 55.0)
#: Hard limits on where a camera may float, independent of the anchor.
EYE_HEIGHT_RANGE_M = (0.45, 1.90)
#: Only enough to keep the near plane off the wall -- there is no robot body
#: here, and a larger margin costs real standoff in a small room (a 0.30 m
#: margin left a 2.75 m bathroom with under 0.9 m to any wall, rejecting 74%
#: of the ring).  Blender's default clip start is 0.1 m.
MIN_WALL_MARGIN_M = 0.12
#: Keeps the camera off a degenerate straight-down view of the anchor.
MIN_GROUND_RADIUS_M = 0.25
ORBIT_ARC_SPAN_DEG = (70.0, 160.0)
ORBIT_STEPS = (6, 14)
#: Resolution of the per-anchor ring scan that finds which azimuths exist.
AZIMUTH_SCAN_STEPS = 72
#: Orbits per anchor.  Each commits to one radius and elevation, so a second
#: pass is how one anchor offers more than a single vantage -- and it is the
#: cheapest way to keep a scene's base-pose supply above the plan's floor.
ORBITS_PER_ANCHOR = 2
SPARSE_TUPLE_SIZE = (4, 8)
MIN_BASELINE_M = 0.5
MIN_AZIMUTH_SPAN_DEG = 90.0
#: Fraction of frame *area* the anchor's box may cover.  The old 0.70 ceiling
#: admitted poses where the object filled the shot and read as standing on
#: top of it.  At 2 m and a 50 deg FOV, 0.30 is about a 1.0 m wide object --
#: past that it is the standoff, not the framing, that would have to give.
FRAME_FILL_RANGE = (0.04, 0.30)
MAX_ANCHOR_OFFCENTER = 0.62
LOS_RAY_MIN_CLEAR = 3


def stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _rng(seed: int, *parts: Any) -> random.Random:
    """Digest-derived stream, so adding an anchor cannot perturb another's poses."""
    key = "|".join([SAMPLER_VERSION, *(str(p) for p in parts), str(int(seed))])
    return random.Random(int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16))


def room_bounds(authoring_map: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    """Extent of the room the camera may occupy.

    The floor slab, not the navigation regions.  A region's bounds are the
    *traversable* area -- inset from the walls by the robot radius -- and on the
    bathroom scene that inset box excludes four of six anchors outright, since
    objects sit against the walls that navigation keeps clear of.  A camera has
    no robot body, so the floor is the honest limit.
    """
    floor = []
    for record in authoring_map.get("objects") or []:
        name = str(record.get("id") or "").lower()
        kind = str(record.get("type") or record.get("kind") or "").lower()
        if not (name.endswith(".floor") or "floor" in kind):
            continue
        geometry = record.get("geometry") or {}
        centre, size = geometry.get("center"), geometry.get("size_m") or []
        if not isinstance(centre, (list, tuple)) or len(centre) < 2 or len(size) < 3:
            continue
        try:
            hx, hy = float(size[0]) / 2.0, float(size[2]) / 2.0
            cx, cy = float(centre[0]), float(centre[1])
        except (TypeError, ValueError):
            continue
        floor.append((cx - hx, cy - hy, cx + hx, cy + hy))
    if floor:
        return (min(b[0] for b in floor), min(b[1] for b in floor),
                max(b[2] for b in floor), max(b[3] for b in floor))

    boxes = []
    for region in authoring_map.get("regions") or []:
        bounds = (region.get("geometry") or {}).get("bounds") or region.get("bounds")
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
            boxes.append(tuple(float(v) for v in bounds[:4]))
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _occluders(authoring_map: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Solid props only.

    The room shell must not appear here.  ``bathroom_0_0.wall`` is a single
    object whose axis-aligned box spans the entire room, so treating it as an
    occluder puts every possible camera "inside an object" and blocks every
    line of sight.  Walls are enforced through :func:`room_bounds` instead.
    """
    out = []
    for record in authoring_map.get("objects") or []:
        if is_structural(record):
            continue
        geometry = record.get("geometry") or {}
        centre, size = geometry.get("center"), geometry.get("size_m") or []
        if not isinstance(centre, (list, tuple)) or len(centre) < 2 or len(size) < 3:
            continue
        try:
            base = float(geometry.get("base_height_m") or 0.0)
            out.append({"id": str(record.get("id") or ""),
                        "cx": float(centre[0]), "cy": float(centre[1]),
                        "hx": float(size[0]) / 2.0, "hy": float(size[2]) / 2.0,
                        "z0": base, "z1": base + float(size[1])})
        except (TypeError, ValueError):
            continue
    return out


def _inside(box: Mapping[str, Any], x: float, y: float, z: float) -> bool:
    return (abs(x - box["cx"]) <= box["hx"] and abs(y - box["cy"]) <= box["hy"]
            and box["z0"] <= z <= box["z1"])


def _segment_blocked(box: Mapping[str, Any], a: Sequence[float], b: Sequence[float]) -> bool:
    lo = (box["cx"] - box["hx"], box["cy"] - box["hy"], box["z0"])
    hi = (box["cx"] + box["hx"], box["cy"] + box["hy"], box["z1"])
    t0, t1 = 0.0, 1.0
    for axis in range(3):
        direction = b[axis] - a[axis]
        if abs(direction) < 1e-9:
            if a[axis] < lo[axis] or a[axis] > hi[axis]:
                return False
            continue
        near = (lo[axis] - a[axis]) / direction
        far = (hi[axis] - a[axis]) / direction
        if near > far:
            near, far = far, near
        t0, t1 = max(t0, near), min(t1, far)
        if t0 > t1:
            return False
    return True


def _framing(eye, target, anchor, *, fov_deg, width, height):
    forward = [target[i] - eye[i] for i in range(3)]
    length = math.dist(eye, target)
    if length < 1e-6:
        return None
    forward = [v / length for v in forward]
    up = (0.0, 1.0, 0.0)
    if abs(forward[1]) > 1.0 - 1e-6:
        up = (0.0, 0.0, 1.0)
    right = [forward[1] * up[2] - forward[2] * up[1],
             forward[2] * up[0] - forward[0] * up[2],
             forward[0] * up[1] - forward[1] * up[0]]
    norm = math.sqrt(sum(v * v for v in right)) or 1.0
    right = [v / norm for v in right]
    true_up = [right[1] * forward[2] - right[2] * forward[1],
               right[2] * forward[0] - right[0] * forward[2],
               right[0] * forward[1] - right[1] * forward[0]]
    tan_x = math.tan(math.radians(fov_deg) / 2.0)
    tan_y = tan_x * float(height) / float(width)
    hx, hy = anchor["half_extent_xy"]
    # The anchor's own vertical extent.  Falling back to the planar extent, as
    # this once did, scored a flat prop at several times its real frame area
    # and let visibly-too-close poses through the fill gate.
    hz = float(anchor.get("vertical_extent_m") or max(hx, hy) * 2.0) / 2.0
    xs, ys = [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                corner = [anchor["center_mitsuba"][0] + sx * hx,
                          anchor["center_mitsuba"][1] + sz * hz,
                          anchor["center_mitsuba"][2] + sy * hy]
                rel = [corner[i] - eye[i] for i in range(3)]
                depth = sum(rel[i] * forward[i] for i in range(3))
                if depth <= 1e-4:
                    return None
                xs.append(sum(rel[i] * right[i] for i in range(3)) / (depth * tan_x))
                ys.append(sum(rel[i] * true_up[i] for i in range(3)) / (depth * tan_y))
    fill = (min(max(max(xs) - min(xs), 0.0), 2.0) / 2.0) * (min(max(max(ys) - min(ys), 0.0), 2.0) / 2.0)
    offcenter = max(abs((max(xs) + min(xs)) / 2.0), abs((max(ys) + min(ys)) / 2.0))
    return fill, offcenter


def _azimuth_span(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    ordered = sorted(v % 360.0 for v in values)
    gaps = [(ordered[i + 1] - ordered[i]) for i in range(len(ordered) - 1)]
    gaps.append(360.0 - ordered[-1] + ordered[0])
    return 360.0 - max(gaps)


def _longest_arc(ring: Sequence[tuple[float, dict[str, Any]]],
                 rng: random.Random) -> list[dict[str, Any]]:
    """Pick a short contiguous arc out of the viable azimuths, or nothing.

    An orbit with a hole in it is not a small-baseline sequence, so a run that
    cannot be filled contiguously is discarded rather than stitched.
    """
    if not ring:
        return []
    step_deg = 360.0 / AZIMUTH_SCAN_STEPS
    indices = [round(a / step_deg) for a, _ in ring]
    best: list[int] = []
    current = [0]
    for k in range(1, len(indices)):
        if indices[k] == indices[k - 1] + 1:
            current.append(k)
        else:
            best = max(best, current, key=len)
            current = [k]
    best = max(best, current, key=len)
    # The ring wraps, so a run ending at 355 deg continues at 0 deg.
    if len(indices) > 1 and indices[0] == 0 and indices[-1] == AZIMUTH_SCAN_STEPS - 1:
        head = [k for k in range(len(indices)) if indices[k] == k]
        tail: list[int] = []
        for k in range(len(indices) - 1, 0, -1):
            if indices[k] != indices[k - 1] + 1:
                break
            tail.insert(0, k)
        if len(tail) + len(head) > len(best):
            best = tail + head
    if len(best) < ORBIT_STEPS[0] or (len(best) - 1) * step_deg < ORBIT_ARC_SPAN_DEG[0]:
        return []
    # An orbit is a short arc, not a lap: spreading members over a whole viable
    # ring would put ~1.7 m between adjacent frames.
    want_span = rng.uniform(*ORBIT_ARC_SPAN_DEG)
    arc_width = max(ORBIT_STEPS[0], min(len(best), int(want_span / step_deg) + 1))
    offset = rng.randint(0, len(best) - arc_width)
    window = best[offset:offset + arc_width]
    keep = min(len(window), ORBIT_STEPS[1])
    picked = [window[round(i * (len(window) - 1) / (keep - 1))] for i in range(keep)]
    return [ring[k][1] for k in dict.fromkeys(picked)]


def build_free_camera_poses(anchors, authoring_map, *, scene_id, seed, pose_budget=120,
                            fov_deg=60.0, width=684, height=512):
    bounds = room_bounds(authoring_map)
    occluders = _occluders(authoring_map)
    orbits, tuples, poses = [], [], []
    rejected: dict[str, int] = {}

    def note(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    def fitted_ground(anchor, theta):
        """Largest ground radius along this azimuth that stays inside the room."""
        limit = float("inf")
        if bounds is not None:
            cx, _, cz = anchor["center_mitsuba"]
            for origin, direction, lo_b, hi_b in (
                (cx, math.cos(theta), bounds[0] + MIN_WALL_MARGIN_M, bounds[2] - MIN_WALL_MARGIN_M),
                (cz, math.sin(theta), bounds[1] + MIN_WALL_MARGIN_M, bounds[3] - MIN_WALL_MARGIN_M),
            ):
                if abs(direction) < 1e-9:
                    continue
                limit = min(limit, ((hi_b if direction > 0 else lo_b) - origin) / direction)
        return limit

    def elevation_window(anchor, distance):
        """Feasible camera elevations at this distance, given the height limits."""
        anchor_y = anchor["center_mitsuba"][1]
        lo = math.degrees(math.asin(max(-1.0, min(1.0, (EYE_HEIGHT_RANGE_M[0] - anchor_y) / distance))))
        hi = math.degrees(math.asin(max(-1.0, min(1.0, (EYE_HEIGHT_RANGE_M[1] - anchor_y) / distance))))
        lo = max(lo, CAMERA_ELEVATION_RANGE_DEG[0])
        hi = min(hi, CAMERA_ELEVATION_RANGE_DEG[1])
        return (lo, hi) if hi > lo else None

    def framing_distance(anchor, rng):
        """Standoff that frames this anchor, clamped to the working band.

        Drawing the distance blind and letting the fill gate judge it after the
        fact threw away whole orbits: an orbit commits to one distance, so a
        single too-close draw killed every member.  Solving for it instead means
        a large object is met from the far end of the band and a small one from
        the near end, which is what "1-2 m" was always meant to express.

        The result is then nudged to a distance that actually admits an
        elevation: something mounted well above eye level can only be looked up
        at from far enough back, and framing alone does not know that.
        """
        tan_x = math.tan(math.radians(fov_deg) / 2.0)
        tan_y = tan_x * float(height) / float(width)
        hx, hy = anchor["half_extent_xy"]
        hz = float(anchor.get("vertical_extent_m") or max(hx, hy) * 2.0) / 2.0
        # Solve against the bounding sphere, not the axis-aligned span.  The box
        # is generally seen cornerwise, and its near face is closer than its
        # centre, so a span-based estimate under-predicted the projected area by
        # two to three times and put the camera far too close.  A sphere over-
        # estimates slightly, which errs toward standing back.
        radius = math.sqrt(hx * hx + hy * hy + hz * hz)
        target = rng.uniform(0.08, 0.22)
        ideal = radius + radius / math.sqrt(max(target * tan_x * tan_y, 1e-9))
        ideal = max(RADIUS_RANGE_M[0], min(RADIUS_RANGE_M[1], ideal))
        if elevation_window(anchor, ideal) is not None:
            return ideal
        steps = 12
        for step in range(steps + 1):
            probe = RADIUS_RANGE_M[0] + (RADIUS_RANGE_M[1] - RADIUS_RANGE_M[0]) * step / steps
            if elevation_window(anchor, probe) is not None:
                return probe
        return ideal

    def candidate(anchor, azimuth_deg, rng, *, fixed_elevation=None, fixed_distance=None):
        theta = math.radians(azimuth_deg)
        distance = (framing_distance(anchor, rng) if fixed_distance is None else fixed_distance)
        window = elevation_window(anchor, distance)
        if window is None:
            note("no_elevation"); return None
        if fixed_elevation is None:
            elevation = rng.uniform(*window)
        elif not window[0] <= fixed_elevation <= window[1]:
            note("no_elevation"); return None
        else:
            elevation = fixed_elevation

        phi = math.radians(elevation)
        ground = distance * math.cos(phi)
        if ground < MIN_GROUND_RADIUS_M:
            note("too_steep"); return None
        if ground > fitted_ground(anchor, theta) + 1e-9:
            note("room_too_small"); return None

        cx, ay, cz = anchor["center_mitsuba"]
        eye_height = ay + distance * math.sin(phi)
        eye = (cx + ground * math.cos(theta), eye_height, cz + ground * math.sin(theta))
        jitter = [(rng.random() - 0.5) * 0.6 * anchor["half_extent_xy"][0],
                  (rng.random() - 0.5) * 0.4 * max(anchor["half_extent_xy"]),
                  (rng.random() - 0.5) * 0.6 * anchor["half_extent_xy"][1]]
        target = tuple(anchor["center_mitsuba"][i] + jitter[i] for i in range(3))
        if bounds is not None and not (
            bounds[0] + MIN_WALL_MARGIN_M <= eye[0] <= bounds[2] - MIN_WALL_MARGIN_M
            and bounds[1] + MIN_WALL_MARGIN_M <= eye[2] <= bounds[3] - MIN_WALL_MARGIN_M
        ):
            note("outside_room"); return None
        if any(_inside(box, eye[0], eye[2], eye[1]) for box in occluders):
            note("inside_object"); return None
        clear = 0
        for sx, sy in ((0, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            probe = (anchor["center_mitsuba"][0] + sx * anchor["half_extent_xy"][0] * 0.8,
                     anchor["center_mitsuba"][1],
                     anchor["center_mitsuba"][2] + sy * anchor["half_extent_xy"][1] * 0.8)
            blocked = any(box["id"] != anchor.get("object_id")
                          and _segment_blocked(box, (eye[0], eye[2], eye[1]),
                                               (probe[0], probe[2], probe[1]))
                          for box in occluders)
            clear += 0 if blocked else 1
        if clear < LOS_RAY_MIN_CLEAR:
            note("occluded"); return None
        framed = _framing(eye, target, anchor, fov_deg=fov_deg, width=width, height=height)
        if framed is None:
            note("behind_camera"); return None
        fill, offcenter = framed
        if not FRAME_FILL_RANGE[0] <= fill <= FRAME_FILL_RANGE[1]:
            note("frame_fill"); return None
        if offcenter > MAX_ANCHOR_OFFCENTER:
            note("offcenter"); return None
        forward_y = (target[1] - eye[1]) / max(math.dist(eye, target), 1e-6)
        return {"eye_mitsuba": [round(v, 6) for v in eye],
                "target_mitsuba": [round(v, 6) for v in target],
                "up_mitsuba": [0.0, 1.0, 0.0], "roll_deg": 0.0,
                "anchor_id": anchor["anchor_id"],
                "anchor_distance_m": round(math.dist(eye, target), 6),
                "azimuth_deg": round(azimuth_deg % 360.0, 6),
                "elevation_deg": round(math.degrees(math.asin(max(-1.0, min(1.0, forward_y)))), 6),
                "eye_height_m": round(eye[1], 6),
                "frame_fill_fraction": round(fill, 6),
                "anchor_offcenter": round(offcenter, 6),
                "heading_deg": round(math.degrees(math.atan2(
                    target[0] - eye[0], target[2] - eye[2])) % 360.0, 6),
                "position_xy": [round(eye[0], 6), round(eye[2], 6)]}

    for anchor in anchors:
        aid = anchor["anchor_id"]
        # Sweep the full ring first instead of guessing.  Near a wall most
        # azimuths have no room for a 1-2 m standoff at all, so a blind arc
        # walk kept breaking its own run and yielded no orbits; scanning tells
        # us which azimuths exist before we try to string any together.
        scan_rng = _rng(seed, scene_id, aid, "scan")
        viable: list[tuple[float, dict[str, Any]]] = []
        for step in range(AZIMUTH_SCAN_STEPS):
            pose = candidate(anchor, 360.0 * step / AZIMUTH_SCAN_STEPS, scan_rng)
            if pose is not None:
                viable.append((360.0 * step / AZIMUTH_SCAN_STEPS, pose))

        # An orbit holds its radius and elevation and varies only azimuth --
        # that is what keeps adjacent frames a small baseline apart.  Letting
        # every member redraw them produced a 1.6 m jump between neighbours.
        # Each orbit therefore contributes exactly one vantage, so an anchor
        # needs more than one of them to carry its share of the pose budget.
        for orbit_index in range(ORBITS_PER_ANCHOR):
            orbit_rng = _rng(seed, scene_id, aid, f"orbit{orbit_index}")
            orbit_distance = framing_distance(anchor, orbit_rng)
            orbit_window = elevation_window(anchor, orbit_distance)
            if orbit_window is None:
                note("orbit_no_elevation")
                continue
            # Split the feasible elevation band between orbits so the second is
            # a different vantage rather than a near-duplicate of the first.
            low, high = orbit_window
            slot = (high - low) / ORBITS_PER_ANCHOR
            orbit_elevation = orbit_rng.uniform(low + slot * orbit_index,
                                                low + slot * (orbit_index + 1))
            ring: list[tuple[float, dict[str, Any]]] = []
            for step in range(AZIMUTH_SCAN_STEPS):
                azimuth = 360.0 * step / AZIMUTH_SCAN_STEPS
                pose = candidate(anchor, azimuth, orbit_rng,
                                 fixed_elevation=orbit_elevation, fixed_distance=orbit_distance)
                if pose is not None:
                    ring.append((azimuth, pose))

            run = _longest_arc(ring, orbit_rng)
            if not run:
                note("orbit_too_short")
                continue
            orbit_id = f"orbit:{aid}:{orbit_index:02d}"
            for ordinal, pose in enumerate(run):
                poses.append({**pose, "capture_kind": "orbit", "orbit_id": orbit_id,
                              "sequence_index": ordinal, "viewpoint_id": orbit_id,
                              "pose_id": f"{aid}|orbit|{orbit_index:02d}|{ordinal:03d}"})
            orbits.append({"orbit_id": orbit_id, "anchor_id": aid, "member_count": len(run),
                           "arc_span_deg": round(
                               _azimuth_span([p["azimuth_deg"] for p in run]), 3)})

        # Sparse tuples draw from the same scan, greedily spread for baseline.
        trng = _rng(seed, scene_id, aid, "tuple")
        pool = [pose for _, pose in viable]
        trng.shuffle(pool)
        wanted = trng.randint(*SPARSE_TUPLE_SIZE)
        picked_poses: list[dict[str, Any]] = []
        for pose in sorted(pool, key=lambda q: -q["frame_fill_fraction"]):
            if len(picked_poses) >= wanted:
                break
            if any(math.dist(pose["position_xy"], other["position_xy"]) < MIN_BASELINE_M
                   for other in picked_poses):
                continue
            picked_poses.append(pose)
        tuple_span = _azimuth_span([p["azimuth_deg"] for p in picked_poses])
        if len(picked_poses) >= SPARSE_TUPLE_SIZE[0] and tuple_span >= MIN_AZIMUTH_SPAN_DEG:
            tuple_id = f"tuple:{aid}:00"
            for ordinal, pose in enumerate(picked_poses):
                poses.append({**pose, "capture_kind": "sparse_tuple", "tuple_id": tuple_id,
                              "camera_set_ids": [tuple_id], "tuple_member_index": ordinal,
                              "viewpoint_id": tuple_id,
                              "pose_id": f"{aid}|tuple|00|{ordinal:03d}"})
            tuples.append({"tuple_id": tuple_id, "anchor_id": aid,
                           "member_count": len(picked_poses),
                           "azimuth_span_deg": round(tuple_span, 3)})
        else:
            note("tuple_rejected")

    poses.sort(key=lambda row: row["pose_id"])
    if len(poses) > pose_budget:
        poses = poses[:pose_budget]
    core = {"schema": SCHEMA, "sampler_version": SAMPLER_VERSION, "scene_id": str(scene_id),
            "source_authoring_map_digest": stable_digest(authoring_map),
            "sampling_seed": int(seed), "requested_pose_count": int(pose_budget),
            "actual_pose_count": len(poses), "anchor_count": len(anchors),
            "orbit_count": len(orbits), "tuple_count": len(tuples),
            "radius_range_m": list(RADIUS_RANGE_M),
            "min_fitted_radius_m": MIN_FITTED_RADIUS_M,
            "eye_height_range_m": list(EYE_HEIGHT_RANGE_M),
            "camera_elevation_range_deg": list(CAMERA_ELEVATION_RANGE_DEG),
            "rejected": dict(sorted(rejected.items())),
            "orbits": orbits, "tuples": tuples, "poses": poses}
    return {**core, "free_pose_digest": stable_digest(core)}


__all__ = ["SAMPLER_VERSION", "SCHEMA", "build_free_camera_poses", "room_bounds", "stable_digest"]
