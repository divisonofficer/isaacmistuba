"""Plan extra walking takes for an apartment whose walk is already rendered.

Runs inside bundled Blender (see apps/extend_apartment_hover.py, walk mode) on the scene's lit blend.
It uses the stock walk v2 planner (`_walking_multi_poses`) as a library, so every new take keeps the
corpus bands -- 0.2-0.6 m steps, 5-15 deg of turn per frame, 10-80 frames, the geometric preflight, the
lens/surface/glass/void gates and the dull-take gate -- and changes only WHERE the routes may go:

  * the scene's existing walk poses count as views already taken: a new pose that stands within 0.5 m AND
    faces within 30 deg of an old or earlier-new pose is dropped (the rule walk v2 applies between its own
    takes), and a route starts off ground the old takes walked when the room allows;
  * the draw uses its own seed, so it does not replay the routes of the first pass (seed 0);
  * a take must show at least half as many materials as the first pass's takes did on average (the stock floor
    is 4): without it the new takes fill the saturating corners and a 4-room flat came out at 9.9 materials a
    frame against the first pass's 13.4. The floor costs attempts, not frames.

The stock planner stops at its `takes` floor (the first pass asked for 8 and stopped after 7-14 attempts),
so the scene's real capacity was never reached. Here `min_frames` is the number of NEW frames wanted and the
attempt budget grows with it; a scene that saturates first (a 2-room flat flattens near +500) says so in the
summary.

The existing poses stay as a verbatim prefix and new takes continue the numbering (walk_008, ...), so frames
already rendered keep their names. Writes the extended pose_selection.json and a summary with the diversity
numbers that decide whether the extension may land: frames per room, cells covered, the heading histogram
and the view content (materials in view, glass, void), old against new.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import io
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan_hover_extension import _load_tool, _tool_defaults  # noqa: E402  (same renderer library, same defaults)


def _own_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", type=Path, required=True, help="the scene's current walk pose_selection.json")
    ap.add_argument("--out", type=Path, required=True, help="where the extended selection goes")
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--scene", required=True, help="scene id, only used to seed the draws")
    ap.add_argument("--new-frames", type=int, default=500, help="how many NEW walk frames to aim for")
    ap.add_argument("--attempts-per-take", type=int, default=30,
                    help="the stock planner's budget is ceil(new_frames / 10) * this; the first pass used 15 and never got near it")
    ap.add_argument("--max-seconds", type=float, default=1500.0)
    ap.add_argument("--min-take-frames", type=int, default=0, help="shortest take kept (user 2026-10-15: >= 20)")
    ap.add_argument("--content-floor", type=float, default=0.5,
                    help="a new take must average at least this share of the first pass's mean materials in view (0 = the stock floor of 4)")
    return ap.parse_args(argv)


def _u(*parts) -> float:
    digest = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)


def _yaw_hist(yaws, bins=12):
    counts = [0] * bins
    for y in yaws:
        counts[int(((y % 360.0) / 360.0) * bins) % bins] += 1
    return counts


def _entropy(counts):
    """Normalised Shannon entropy of a histogram: 1.0 is uniform, 0.0 is one bin."""
    total = sum(counts)
    if total <= 0 or len(counts) < 2:
        return 0.0
    return -sum((c / total) * math.log(c / total) for c in counts if c) / math.log(len(counts))


def _pct(values, q):
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(q * len(s)))], 3)


def _content(poses):
    mats = [p.get("walk_materials_in_view") for p in poses if p.get("walk_materials_in_view") is not None]
    return {"frames": len(poses),
            "materials_in_view_mean": round(statistics.mean(mats), 2) if mats else None,
            "glass_fraction_mean": round(statistics.mean(p.get("walk_glass_fraction_est", 0.0) for p in poses), 3) if poses else None,
            "void_fraction_mean": round(statistics.mean(p.get("walk_void_fraction_est", 0.0) for p in poses), 3) if poses else None,
            "step_m_p10_p50_p90": [_pct([p["walk_step_m"] for p in poses if p.get("walk_step_m")], q) for q in (0.1, 0.5, 0.9)],
            "abs_yaw_step_deg_p50_p90": [_pct([abs(p["walk_yaw_step_deg"]) for p in poses if p.get("walk_yaw_step_deg") is not None], q)
                                         for q in (0.5, 0.9)]}


def main() -> int:
    own = _own_args()
    started = time.time()
    tool = _load_tool()
    a = _tool_defaults(tool)
    import bpy  # type: ignore

    scene = bpy.context.scene
    walk = tool._walk
    payload = json.loads(own.selection.read_text(encoding="utf-8"))
    existing = payload["all"]
    old_views = [(p["position"][0], p["position"][1], p.get("walk_yaw_deg", p.get("walk_heading_deg", 0.0))) for p in existing]
    old_cells = {(round(x / walk.CELL_M), round(y / walk.CELL_M)) for x, y, _ in old_views}
    seed = int(_u(own.scene, "walk_ext_v1") * 2 ** 31) or 1

    state = {"attempts": 0}
    stock_overlapping, stock_route = walk.overlapping, walk.candidate_route

    def overlapping(poses, accepted, *args, **kw):
        return stock_overlapping(poses, list(accepted) + old_views, *args, **kw)

    def candidate_route(cells, clear, rng, **kw):
        state["attempts"] += 1
        if time.time() - started > own.max_seconds:
            return None                                       # out of time: the remaining attempts end at once
        kw["avoid"] = set(kw.get("avoid", ())) | old_cells    # start off ground the first pass walked
        return stock_route(cells, clear, rng, **kw)

    old_mats = [p["walk_materials_in_view"] for p in existing if p.get("walk_materials_in_view") is not None]
    stock_floor = tool.WALK_MIN_MATERIALS
    floor = max(stock_floor, round(own.content_floor * statistics.mean(old_mats))) if old_mats else stock_floor
    tool.WALK_MIN_MATERIALS = floor                           # the "dull take" gate reads this module constant at call time
    walk.overlapping, walk.candidate_route = overlapping, candidate_route
    stock_band = walk.TAKE_FRAMES_BAND
    stock_route_kw, stock_runs_def = dict(stock_route.__kwdefaults__ or {}), walk.runs.__defaults__   # the original, not the wrapper
    if own.min_take_frames:                                   # the take splitter drops pieces under the band's floor; the band is also
        band = (max(stock_band[0], own.min_take_frames), max(stock_band[1], own.min_take_frames))   # bound into two defaults
        walk.TAKE_FRAMES_BAND = band
        stock_route.__kwdefaults__ = {**stock_route_kw, "frames_band": band}
        walk.runs.__defaults__ = (band[0],)
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink):
            new_poses, _ = tool._walking_multi_poses(scene, hfov_deg=a.hfov_deg, takes=1, handheld_deg=a.hover_handheld_deg, seed=seed,
                                                     attempts_per_take=own.attempts_per_take, min_frames=own.new_frames)
    except RuntimeError as exc:                               # "found no take in N attempts": a full scene, not an error
        new_poses = []
        sink.write(json.dumps({"event": "walk_poses", "error": str(exc)[:300]}) + "\n")
    finally:
        walk.overlapping, walk.candidate_route = stock_overlapping, stock_route
        tool.WALK_MIN_MATERIALS = stock_floor
        walk.TAKE_FRAMES_BAND = stock_band
        stock_route.__kwdefaults__, walk.runs.__defaults__ = stock_route_kw, stock_runs_def
    if own.min_take_frames:                                   # whatever still came out short
        counts = collections.Counter(p["sequence_id"] for p in new_poses)
        new_poses = [p for p in new_poses if counts[p["sequence_id"]] >= own.min_take_frames]
    event = [json.loads(line) for line in sink.getvalue().splitlines() if '"event": "walk_poses"' in line]

    # Continue the numbering: the new planner starts again at walk_000.
    first = max((int(p["sequence_id"].split("_")[1]) for p in existing if str(p.get("sequence_id", "")).startswith("walk_")), default=-1) + 1
    order = list(dict.fromkeys(p["sequence_id"] for p in new_poses))
    rename = {sid: f"walk_{first + i:03d}" for i, sid in enumerate(order)}
    for p in new_poses:
        p["sequence_id"] = rename[p["sequence_id"]]
        p["walk_plan"] = "extension_v1"
    payload["all"] = existing + new_poses
    payload.setdefault("important", [])
    payload["pose_mode"] = "walking"
    own.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Diversity: where the new frames are, which way they face, what they look at -- old against new.
    rooms = [c for c in walk.components(tool._walkable_cells(scene)) if len(c) >= walk.MIN_COMPONENT_CELLS]

    def room_of(p):
        cell = (round(p["position"][0] / walk.CELL_M), round(p["position"][1] / walk.CELL_M))
        return next((i for i, r in enumerate(rooms) if cell in r), -1)

    def cells_of(poses):
        return {(round(p["position"][0] / walk.CELL_M), round(p["position"][1] / walk.CELL_M)) for p in poses}

    per_room = []
    for i, r in enumerate(rooms):
        o = [p for p in existing if room_of(p) == i]
        n = [p for p in new_poses if room_of(p) == i]
        per_room.append({"room": i, "cells": len(r), "old_frames": len(o), "new_frames": len(n),
                         "new_share": round(len(n) / max(1, len(new_poses)), 3),
                         "cells_visited_old": len(cells_of(o) & r), "cells_visited_after": len(cells_of(o + n) & r)})
    yaw = lambda ps: [p.get("walk_yaw_deg", p.get("walk_heading_deg", 0.0)) for p in ps]   # noqa: E731
    old_hist, new_hist = _yaw_hist(yaw(existing)), _yaw_hist(yaw(new_poses))
    flags = []
    if new_poses:
        if _entropy(new_hist) < 0.85:
            flags.append(f"new headings concentrated (entropy {_entropy(new_hist):.2f} < 0.85)")
        total_cells = sum(len(c) for c in rooms) or 1
        heavy = [r for r in per_room if len(rooms) >= 3 and r["new_share"] > 0.6 and r["new_share"] > r["cells"] / total_cells + 0.25]
        if heavy:
            flags.append(f"room {heavy[0]['room']} holds {heavy[0]['new_share']:.0%} of the new frames but {heavy[0]['cells'] / total_cells:.0%} of the floor")
        big = [r for r in per_room if r["cells"] >= 0.10 * sum(len(c) for c in rooms) and r["old_frames"] > 0 and r["new_frames"] == 0]
        if big:
            flags.append(f"rooms the first pass walked get no new frame: {[r['room'] for r in big]}")
        old_c, new_c = _content(existing), _content(new_poses)
        if old_c["materials_in_view_mean"] and new_c["materials_in_view_mean"] and new_c["materials_in_view_mean"] < 0.75 * old_c["materials_in_view_mean"]:
            flags.append(f"new views show fewer materials ({new_c['materials_in_view_mean']} vs {old_c['materials_in_view_mean']})")
    takes = collections.Counter(p["sequence_id"] for p in new_poses)
    summary = {
        "scene": own.scene, "had_poses": len(existing), "added_poses": len(new_poses), "total_poses": len(existing) + len(new_poses),
        "target_frames": len(existing) + own.new_frames, "added_takes": len(takes), "takes_by_visit": {"1": len(takes)},
        "families_before": None, "families_after": None, "content_floor_materials": floor,
        "frames_per_new_take": sorted(takes.values()), "seed": seed, "attempts": state["attempts"], "seconds": round(time.time() - started),
        "stock_event": event[-1] if event else None,
        "diversity": {"rooms": per_room, "yaw_hist_30deg": {"old": old_hist, "new": new_hist},
                      "yaw_entropy": {"old": round(_entropy(old_hist), 3), "new": round(_entropy(new_hist), 3),
                                      "all": round(_entropy([x + y for x, y in zip(old_hist, new_hist)]), 3)},
                      "content": {"old": _content(existing), "new": _content(new_poses)},
                      "cells_visited": {"old": len(cells_of(existing)), "after": len(cells_of(existing + new_poses)),
                                        "walkable": sum(len(r) for r in rooms)},
                      "flags": flags},
    }
    own.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("PLAN_DONE", json.dumps({k: summary[k] for k in ("had_poses", "added_poses", "added_takes", "attempts", "seconds")}), "flags:", flags)
    return 0


if __name__ == "__main__":
    sys.exit(main())
