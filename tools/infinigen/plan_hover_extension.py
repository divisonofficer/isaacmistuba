"""Plan extra object_hover takes for an apartment whose hover is already rendered.

Runs inside bundled Blender (see apps/extend_apartment_hover.py) on the scene's lit blend.
It reuses the HSSD hover planner as a library -- every arc still passes the same hard
gates (clearance, visibility, room to climb), at the same 6 deg step -- and changes only
WHICH targets get a take, at what distance, and from which side:

  1. Diversity first. The planner walks its target pool in name order, so a 16-take
     scene is all Book*/Bottle*/Chair* (22 families over 15 scenes, every one of them
     A-D). Here candidates are taken round-robin over object families, fewest takes
     first, so new takes reach families the first 16 never did.
  2. Distance spread. Each take draws its own camera distance from the bounding
     surface (log-uniform, default 0.6-1.9 m) instead of a fixed 1.0 m.
  3. Re-entry. Only after every object that can be filmed once has been, an object is
     filmed again from a side >= 90 deg away from its earlier takes and at a distance
     >= 0.3 m different, up to --max-visits takes per object.

The existing poses are kept verbatim as a prefix, so frames already rendered keep their
names and indices; new takes are appended. Writes the extended pose_selection.json and a
plan summary.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "modules/hssd_blender_ir/tools/blender_render_hssd_ir_sample.py"


def _own_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", type=Path, required=True, help="the scene's current hover pose_selection.json")
    ap.add_argument("--out", type=Path, required=True, help="where the extended selection goes")
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--scene", required=True, help="scene id, only used to seed the draws")
    ap.add_argument("--target-frames", type=int, default=500, help="stop once the scene's hover has this many poses")
    ap.add_argument("--frame-budget", type=int, default=10,
                    help="frames a take may use. 10 is what the first 16 takes got (their realised step is ~7.3 deg); a bigger budget packs frames closer, which was asked not to happen")
    ap.add_argument("--radius-min", type=float, default=0.85,
                    help="below ~0.8 m a single material fills the frame (11%% of frames failed the still gate at 0.6-0.8)")
    ap.add_argument("--radius-max", type=float, default=1.9)
    ap.add_argument("--max-visits", type=int, default=3)
    ap.add_argument("--reentry-share", type=float, default=0.0,
                    help="share of the frames still to add spent on second and third takes of objects the scene already has "
                         "(0: every object's first take comes first and re-entry only fills what is left; 1: re-entry only)")
    ap.add_argument("--min-facing-sep-deg", type=float, default=90.0)
    ap.add_argument("--fallback-facing-sep-deg", type=float, default=60.0,
                    help="if the strict separation cannot reach the target (a cramped flat: 368 of 500 at 90 deg), "
                         "one more pass at this separation; 0 = never relax")
    ap.add_argument("--min-radius-sep-m", type=float, default=0.3)
    ap.add_argument("--max-target-objects", type=int, default=400)
    ap.add_argument("--radius-tries", type=int, default=3, help="distances tried on one object before it is given up")
    ap.add_argument("--max-still-fail-share", type=float, default=0.2,
                    help="a take whose frames fail the renderer's soft still gate (one material fills the frame, lens-against) more often than this is refused and another distance tried -- the planner only records that gate")
    ap.add_argument("--max-seconds", type=float, default=2400.0)
    ap.add_argument("--azimuth-span-deg", type=float, default=None,
                    help="sweep per take (renderer default 60 deg = ~10 frames at 6 deg); 2026-10-15 v2a: 130 for 20+ frame takes")
    ap.add_argument("--min-take-frames", type=int, default=0, help="refuse a take shorter than this (user 2026-10-15: >= 20)")
    return ap.parse_args(argv)


def _load_tool():
    spec = importlib.util.spec_from_file_location("hssd_render_tool", TOOL)
    tool = importlib.util.module_from_spec(spec)
    sys.modules["hssd_render_tool"] = tool
    spec.loader.exec_module(tool)
    return tool


def _tool_defaults(tool):
    """The renderer's own hover defaults, by running its parser with the flags the corpus uses."""
    saved = sys.argv
    sys.argv = ["blender", "--", "--out", "/tmp/_unused", "--width", "720", "--height", "540", "--spp", "192",
                "--max-bounces", "4", "--pose-mode", "object_hover", "--dataset"]
    try:
        return tool._args()
    finally:
        sys.argv = saved


def _u(*parts) -> float:
    """A deterministic number in [0, 1) from the parts."""
    digest = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)


def _family(source_id) -> str:
    return re.sub(r"Factory$", "", str(source_id or ""))


def _key(pose) -> tuple:
    return (pose.get("target_source_id"), pose.get("target_instance_id"))


def main() -> int:
    own = _own_args()
    started = time.time()
    tool = _load_tool()
    a = _tool_defaults(tool)
    import bpy  # type: ignore

    scene = bpy.context.scene
    payload = json.loads(own.selection.read_text(encoding="utf-8"))
    existing = payload["all"]
    have_takes = len({p["sequence_id"] for p in existing})

    pool = tool._closeup_target_objects(scene, own.max_target_objects)
    pool_by_key = {(t["source_id"], t["instance_id"]): t for t in pool}
    tool._closeup_target_objects = lambda _scene, _limit: pool          # the pool is fixed for this plan
    all_keys = set(pool_by_key)

    # What each object has had so far: facings and distances of earlier takes.
    visits = collections.defaultdict(list)
    for p in existing:
        if p.get("sequence_index") is not None and p["sequence_id"] not in {v["seq"] for v in visits[_key(p)]}:
            visits[_key(p)].append({"seq": p["sequence_id"], "facing": math.radians(p.get("hover_facing_deg", 0.0)),
                                    "radius": p.get("hover_radius_nominal_m", a.hover_radius_m)})
    family_takes = collections.Counter(_family(k[0]) for k, v in visits.items() for _ in v)

    sep_now = [own.min_facing_sep_deg]
    original_sweep = tool._hover_sweep

    def sweep(scn, chain, facing, **kw):
        key = (chain[0]["source_id"], chain[0]["instance_id"])
        for earlier in visits.get(key, ()):
            gap = abs((facing - earlier["facing"] + math.pi) % (2 * math.pi) - math.pi)
            if gap < math.radians(sep_now[0]) - 1e-6:
                return None, f"re-entry facing {math.degrees(facing):.0f} deg is {math.degrees(gap):.0f} deg from an earlier take"
        # The renderer seeds each take by its position in ONE call; one candidate per call would give every
        # take seed 0 and the same hand wander. Seed by object and visit instead.
        kw["seed"] = int(_u(own.scene, "seed", key, len(visits.get(key, ()))) * 2 ** 31)
        return original_sweep(scn, chain, facing, **kw)

    tool._hover_sweep = sweep

    def draw_radius(key, visit_no, attempt) -> float:
        taken = [v["radius"] for v in visits.get(key, ())]
        for extra in range(24):                          # resample until it clears the earlier distances
            u = _u(own.scene, "radius", key, visit_no, attempt, extra)
            radius = own.radius_min * (own.radius_max / own.radius_min) ** u
            if all(abs(radius - r) >= own.min_radius_sep_m for r in taken):
                return round(radius, 3)
        return round(own.radius_min * (own.radius_max / own.radius_min) ** u, 3)

    new_poses, takes, rejected = [], [], collections.Counter()
    gave_up: set = set()
    attempts = 0
    log = []

    def total_frames() -> int:
        return len(existing) + len(new_poses)

    # First takes stop at this many frames; the rest of the target is left to re-entry (rounds 2 and 3).
    first_take_cap = len(existing) + (own.target_frames - len(existing)) * (1.0 - min(max(own.reentry_share, 0.0), 1.0))

    def order(visit_no: int):
        """Candidates for visit number `visit_no` (1 = first take of an object), least-covered families first."""
        out = []
        for key in all_keys:
            if key in gave_up or len(visits.get(key, ())) != visit_no - 1:
                continue
            out.append((family_takes[_family(key[0])], _u(own.scene, "order", key, visit_no), key))
        out.sort()
        return [k for _, _, k in out]

    # Tier 0 keeps the strict facing separation. If a cramped flat cannot reach the target that way, one more
    # pass relaxes it (default 60 deg): still a different side of the object, just not a quarter turn away.
    tiers = [own.min_facing_sep_deg]
    if 0 < own.fallback_facing_sep_deg < own.min_facing_sep_deg:
        tiers.append(own.fallback_facing_sep_deg)
    for tier_no, tier_sep in enumerate(tiers):
        if tier_no and total_frames() >= own.target_frames:
            break
        sep_now[0] = tier_sep
        if tier_no:
            log.append({"relaxed_facing_separation_deg": tier_sep, "frames_before": total_frames()})
        stalled = False
        for visit_no in range(2 if tier_no else 1, own.max_visits + 1):
            gave_up.clear()
            while total_frames() < own.target_frames and not stalled and (visit_no > 1 or total_frames() < first_take_cap - 1e-9):
                if time.time() - started > own.max_seconds:
                    log.append({"stopped": "time", "visit": visit_no})
                    stalled = True
                    break
                candidates = order(visit_no)
                if not candidates:
                    break
                picked = False
                for key in candidates[:12]:             # re-sorted after every success; a failure moves on to the next
                    for attempt in range(own.radius_tries):
                        attempts += 1
                        radius = draw_radius(key, visit_no, attempt)
                        exclude = {k for k in all_keys if k != key}
                        sink = io.StringIO()
                        try:
                            with contextlib.redirect_stdout(sink):
                                poses, _ = tool._object_hover_poses(
                                    scene, own.frame_budget, 0, max_target_objects=own.max_target_objects,
                                    hfov_deg=a.hfov_deg, radius_m=radius,
                                    azimuth_span_deg=own.azimuth_span_deg or a.hover_azimuth_deg,
                                    elevation_deg=a.hover_elevation_deg, sequences=1, handheld_deg=a.hover_handheld_deg,
                                    shape=a.hover_shape, cross_track_deg=a.hover_cross_track_deg,
                                    chain_length=a.hover_chain, step_deg=a.hover_step_deg, exclude=exclude,
                                    sequence_offset=have_takes + len(takes))
                        except RuntimeError as exc:
                            poses = []
                            reasons = str(exc).split("last reasons: ", 1)[-1].split("; ")
                            for reason, n in tool._reason_counts(reasons).items():
                                rejected[reason] += n
                        for line in sink.getvalue().splitlines():
                            if '"event": "hover_poses"' in line:
                                try:
                                    for reason, n in json.loads(line)["rejected_by"].items():
                                        rejected[reason] += n
                                except (ValueError, KeyError):
                                    pass
                        if poses and len(poses) < own.min_take_frames:
                            rejected[f"take under {own.min_take_frames} frames, refused"] += 1
                            poses = []
                        if poses and sum(1 for p in poses if not p.get("still_gate_pass", True)) / len(poses) > own.max_still_fail_share:
                            rejected["still gate (soft), take refused"] += 1
                            poses = []
                        if poses:
                            facing = math.radians(poses[0].get("hover_facing_deg", 0.0))
                            for p in poses:
                                p["hover_visit_index"] = visit_no
                                p["hover_radius_requested_m"] = radius
                                p["hover_plan"] = "extension_v1"
                            visits[key].append({"seq": poses[0]["sequence_id"], "facing": facing, "radius": radius})
                            family_takes[_family(key[0])] += 1
                            new_poses.extend(poses)
                            takes.append({"sequence_id": poses[0]["sequence_id"], "visit": visit_no, "family": _family(key[0]),
                                          "radius_m": radius, "facing_deg": poses[0].get("hover_facing_deg"),
                                          "frames": len(poses), "facing_separation_deg": sep_now[0]})
                            picked = True
                            break
                    if picked:
                        break
                    gave_up.add(key)
                if not picked and not order(visit_no):
                    break
                if not picked and len(gave_up) >= len(all_keys):
                    break
            if total_frames() >= own.target_frames or stalled:
                break
        if stalled:
            break

    # Keep the plan from overshooting by a whole take: drop trailing takes once the target is met without them.
    while takes and total_frames() - takes[-1]["frames"] >= own.target_frames:
        last = takes.pop()
        new_poses = [p for p in new_poses if p["sequence_id"] != last["sequence_id"]]

    payload["all"] = existing + new_poses
    payload.setdefault("important", [])
    payload["pose_mode"] = "object_hover"
    own.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    by_visit = collections.Counter(t["visit"] for t in takes)
    radii = sorted(t["radius_m"] for t in takes)
    keys_after = {_key(p) for p in payload["all"]}
    fam_after = collections.Counter(_family(k[0]) for k in keys_after)
    summary = {
        "scene": own.scene, "had_takes": have_takes, "had_poses": len(existing), "added_takes": len(takes),
        "added_poses": len(new_poses), "total_poses": len(payload["all"]), "target_frames": own.target_frames,
        "takes_by_visit": dict(sorted(by_visit.items())), "frames_per_take_new": sorted(collections.Counter(t["frames"] for t in takes).items()),
        "radius_m": {"min": radii[0] if radii else None, "median": radii[len(radii) // 2] if radii else None,
                     "max": radii[-1] if radii else None},
        "families_before": len({_family(k[0]) for k in {_key(p) for p in existing}}), "families_after": len(fam_after),
        "objects_filmed_before": len({_key(p) for p in existing}), "objects_filmed_after": len(keys_after),
        "pool": len(pool), "attempts": attempts, "rejected_arcs_by": dict(rejected.most_common()),
        "seconds": round(time.time() - started), "log": log, "takes": takes,
    }
    own.summary.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("takes", "log")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
