"""VLM review done by a peer agent (a Codex session) instead of the Anthropic API: zero Sonnet tokens.

  vlm_peer.py pack TAG ROUND            write out/vlm_queue/TAG_ROUND/ : TASK.md (protocol + checklist), manifest.json, views/ (links to the renders)
  vlm_peer.py ingest TAG ROUND [--dest DIR]   read out/vlm_queue/TAG_ROUND/results/<room>[.pN].json -> out/vlm_review/TAG_ROUND/<room>.json (same schema as vlm_review.py)
  vlm_peer.py todo                      rounds packed but not ingested, rounds with results waiting

The reviewer is a defect finder only (docs/review_feedback_rules.md): no 1-10 scores, every defect has a view, a 3x3 cell, one line of evidence naming the object and a cause.
Stage 1 (exposure, GT albedo, roughness stats) is computed here from the files, not by the reviewer. A room with several pass files keeps a defect seen in >= 2 passes.
Only synthetic renders are in the queue. Reference photos with people never are.
"""
import re
import argparse, collections, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vlm_review as vr

REPO = Path("/jarvis/project/robomituba"); O = Path("/tmp/claude-0/objreal")
Q = REPO / "out/vlm_queue"; R = REPO / "out/vlm_review"
CELLS = "top-left, top-center, top-right, middle-left, center, middle-right, bottom-left, bottom-center, bottom-right"


def rooms_of(snap):
    out = collections.OrderedDict()
    for p in sorted(snap.glob("*_wide*.png")):
        out.setdefault(p.stem.rsplit("_wide", 1)[0], []).append(p)
    return out


def task_md(tag, rnd, rooms):
    codes = "\n".join(f"- {c} ({sev}): {d}" for c, (d, sev, _) in vr.V_CODES.items())
    return f"""# VLM review task: {tag} {rnd}

You are the VLM reviewer. Rules (user's document docs/review_feedback_rules.md): you find visible defects, you do NOT give a 1-10 score, and you never judge "is it good".
A defect counts only if you can point at it. The human score stays the only bar.

## What to do
For every room in manifest.json, look at each of its views (views/<name>.png, a synthetic render) and report the defects from the checklist below that are visibly true.
A door leaf swung open stands perpendicular beside or inside its frame and shows as a flat panel at the side of the doorway (often tan or the door colour): that is an OPEN door, not a closed one. Report LAY-01 for a door only if the doorway itself is blocked (a leaf filling the opening, furniture in front).
Plain matte white or grey surfaces are physically normal: report a surface only if it looks flat, repeated or unlike its material. If dim light or exposure could hide a defect, say so in the evidence.
Do two independent passes per room (separate files, look at the views again each time, do not copy the first answer): results/<room>.p1.json and results/<room>.p2.json.

## Result file (one per room and pass)
{{"room": "<room>", "pass": 1, "defects": [{{"code": "SRF-02", "view": "<view name from the manifest>", "where": "<one of: {CELLS}>", "evidence": "<one line naming the object>", "cause": "asset|layout|lighting|render"}}]}}
`defects` may be empty. No evidence, no defect. Do not invent codes. `cause`: asset = the object or its material, layout = placement / density / missing objects, lighting = light rig or shadows,
render = exposure, tone mapping, texture filtering, resolution.

## Checklist
{codes}

## Do not
- upload these images anywhere; send nothing to a network service
- change any file outside out/vlm_queue/{tag}_{rnd}/results/
- compare with other scenes or give any score

A view named <room>_wideTop is an orthographic top-down of the room with the ceiling cut away: use it for layout (where the furniture stands), not for surfaces.
If REFS_TASK.md exists in this folder, do that reference comparison too (refs_answer.json). When there is a <room>_wideTop view and a refs/plan image (or a refs/*topdown* image: an exact top-down of the reference room in the same frame, entrance wall at the bottom; compare the two top views object by object), also add to that room's entry
"layout": ["<one short phrase per object or group that sits in a clearly different place, or is missing / extra, compared with the plan, e.g. 'bar counter on the left wall, plan has it on the back wall'>"]. When all rooms have both passes (and the refs answer, if asked), create results/DONE and tell the requester. Rooms: {", ".join(rooms)}.
"""


def pack(a):
    snap = O / f"rvs_{a.tag}_{a.round}"
    if not snap.is_dir():
        sys.exit(f"no snapshot {snap}")
    d = Q / f"{a.tag}_{a.round}"; (d / "views").mkdir(parents=True, exist_ok=True); (d / "results").mkdir(exist_ok=True)
    rooms = rooms_of(snap)
    for r_ in rooms:                                             # the orthographic layout view (PROBE_TOPDOWN) always rides along, past the cap
        top = [p for p in rooms[r_] if p.stem.endswith("_wideTop")]
        rest = [p for p in rooms[r_] if p not in top]
        std = [p for p in rest if re.search(r"_wide[0-4]$", p.stem)]       # corner wides ride under the cap; hand-posed extras (wide5+, wideX1, *_wide_door ...) always ride along
        extra = [p for p in rest if p not in std]
        rooms[r_] = std[: a.max_views] + extra + top
    for views in rooms.values():
        for p in views:
            link = d / "views" / p.name
            if not link.exists():
                link.symlink_to(p)
    man = {"tag": a.tag, "round": a.round, "created": time.strftime("%FT%T"), "rooms": {r: [p.stem for p in v] for r, v in rooms.items()}}
    (d / "manifest.json").write_text(json.dumps(man, indent=1))
    (d / "TASK.md").write_text(task_md(a.tag, a.round, list(rooms)))
    refs_task(d, a.tag, rooms)
    print(f"{d}: {len(rooms)} rooms, {sum(len(v) for v in man['rooms'].values())} views")


def refs_task(d, tag, rooms):
    """Reference similarity is part of every review of a scene that has references (configs/floor_refs.json, user 2026-10-20): copy them to refs/ and ask for refs_answer.json."""
    fr = json.loads((REPO / "configs/floor_refs.json").read_text()).get(tag) if (REPO / "configs/floor_refs.json").exists() else None
    if not fr:
        return
    (d / "refs").mkdir(exist_ok=True); lines = []
    for src in ([fr["plan"]] if fr.get("plan") else []):
        name = "plan" + Path(src).suffix; os.system(f"cp -p '{src}' '{d / 'refs' / name}'"); lines.append(f"- refs/{name}: floor plan of the whole floor")
    for room, xs in fr["rooms"].items():
        for i, (src, cap) in enumerate(xs):
            name = f"{room}__{i}{Path(src).suffix}"; os.system(f"cp -p '{src}' '{d / 'refs' / name}'"); lines.append(f"- refs/{name}: {room} ({cap})")
    (d / "REFS_TASK.md").write_text(f"""# Reference similarity: {tag} (do it after the two defect passes)
For every room with reference images below, compare its views/ with them; also compare the whole floor with the plan. Write refs_answer.json in this folder:
{{"<room>": {{"matches": [..], "missing": [..], "different": [..]}}, "_floor": {{...}}}} - one short phrase per item naming the object / finish / layout. No scores. Local files only.
Rooms without references: skip. Then create results/DONE as usual (DONE means both jobs are done).

""" + "\n".join(lines) + "\n" + inventory_check(d, fr, rooms) + layout_check(fr, rooms))


def inventory_check(d, fr, rooms):
    """Missing-object check (user 2026-10-22): per room with reference images, count every reference object and the same object in the render, so a
    shortfall becomes an addition to the next plan (refs_missing.py). Categories: refs/catalog.txt (the placer's own names)."""
    import importlib
    sys.path.insert(0, str(Path(__file__).parent))
    cat = importlib.import_module("room_planner.catalog")
    lines = ["# furniture (category: rooms it is allowed in)"] + [f"{k}: {','.join(v.get('rooms', [])[:6])}" for k, v in sorted(cat.FURNITURE.items())]
    lines += ["", "# small items placed ON furniture (lived_in)"] + sorted(cat.LIVED_IN)
    (d / "refs" / "catalog.txt").write_text("\n".join(lines) + "\n")
    rr = [r for r in fr.get("rooms", {}) if r in rooms]
    if not rr:
        return ""
    return f"""
## Inventory check (every room with reference images: {", ".join(rr)})
For each such room, list EVERY object you can see in its reference images (furniture, shelving, wall art, plants, lamps, rugs, curtains, tabletop
items that matter, and architecture: windows, doors, built-ins) and count it in the reference and in our render views. Add to refs_answer.json["<room>"]:
"inventory": [{{"object": "<plain noun>", "category": "<the closest name from refs/catalog.txt, or null>", "kind": "furniture" | "decor" | "architecture",
               "ref_count": 2, "render_count": 1, "where": "<where it stands in the reference: wall / zone / next to what>"}}, ...]
Count what is visible; if a reference shows only part of the room, count only that part and say "partial" in where. One entry per object type.
"""


def layout_check(fr, rooms):
    """Explicit layout check (user 2026-10-22): when the scene has a reference layout.json (configs/floor_refs.json "layout": {room: path}),
    list its objects and ask for each one whether the render's top view (<room>_wideTop) has it in the same place."""
    out = []
    for room, path in (fr.get("layout") or {}).items():
        if room not in rooms or not os.path.exists(path):
            continue
        items = json.load(open(path)).get("items", [])
        rows = [f"- L{i + 1:02d} {it['category']} ({it.get('note', '')}) at u {it['u']:.2f} v {it['v']:.2f}, facing {it.get('facing')}, against {it.get('against')}"
                for i, it in enumerate(items)]
        out.append(f"""
## Layout check: {room}
Frame (same as refs/*topdown* and the render {room}_wideTop): entrance wall at the BOTTOM; u 0 = left .. 1 = right, v 0 = entrance .. 1 = back wall.
For EVERY reference object below, look at {room}_wideTop (and the other views to identify objects) and add to refs_answer.json["{room}"]:
"layout_check": [{{"id": "L01", "status": "ok" | "moved" | "missing", "where": "<only for moved: where it is instead, e.g. 'against the left wall, v~0.3'>"}}, ...]  (one entry per id, all ids)
"layout_extra": ["<large object in the render that has no counterpart in the list, with its rough u,v>", ...]
ok = same object type within about 0.15 of its u,v and the same orientation; moved = present but elsewhere or turned; missing = not in the render.
Chairs/stools count individually. If the WHOLE room is a left-right mirror of the reference, say so once in "layout_extra" and judge positions after mirroring.
""" + "\n".join(rows))
    return "\n".join(out) + ("\n" if out else "")


def ingest(a):
    d = Q / f"{a.tag}_{a.round}"; man = json.loads((d / "manifest.json").read_text())
    gt = O / f"gt_{a.tag}_{a.round}"; out = Path(a.dest or R) / f"{a.tag}_{a.round}"; out.mkdir(parents=True, exist_ok=True)
    ns = argparse.Namespace(l_range=[25.0, 215.0], clip_max=0.15, gt=str(gt) if gt.is_dir() else None, depth=None, counts=None, prev_counts=None)
    bad = []
    for room, names in man["rooms"].items():
        files = sorted((d / "results").glob(f"{room}.p*.json"))
        if not files:
            bad.append(f"{room}: no result file"); continue
        passes = [json.loads(f.read_text()) for f in files]
        views = {n: d / "views" / f"{n}.png" for n in names}
        found = collections.defaultdict(list)
        for pj in passes:
            seen = set()
            for x in pj.get("defects", []):
                c, v = x.get("code"), x.get("view")
                if c not in vr.V_CODES or v not in views or not str(x.get("evidence", "")).strip():
                    bad.append(f"{room} p{pj.get('pass')}: dropped {c}/{v} (unknown code or view, or no evidence)"); continue
                if (v, c) not in seen:
                    seen.add((v, c)); found[(v, c)].append(x)
        need = min(2, len(passes))                                   # a code counts when >= 2 passes report it (any view: two passes often pick different views of the same defect); its views are the union
        per_pass = collections.Counter(c for pj in passes for c in {x.get("code") for x in pj.get("defects", [])})
        defects = [{"code": c, "view": v, "where": ds[0].get("where", ""), "evidence": ds[0]["evidence"], "severity": vr.V_CODES[c][1], "votes": per_pass[c], "cause": ds[0].get("cause", "")}
                   for (v, c), ds in found.items() if per_pass[c] >= need]
        res = {"scene": a.tag, "round": a.round, "room": room, "model": "codex-peer", "prompt_version": "codex-review-v1", "passes": len(passes)}
        res["auto"] = vr.stage1(views, ns); res["gt_stats"] = vr.gt_stats(views, ns)
        res.update(ref=[], ab=None, defects=vr.aggregate(defects))
        res["derived"] = vr.derive(res["auto"], res["defects"], [])
        blockers = [x for x in res["auto"] if vr.A_SEV[x["code"]][0] == "blocker"]
        res["gate"] = "blocked" if blockers else "to_human"; res["api_calls"] = 0
        ra = d / "refs_answer.json"
        if ra.exists():
            lc = (json.loads(ra.read_text()).get(room.replace("/", "-")) or json.loads(ra.read_text()).get(room) or {})
            inv = [x for x in (lc.get("inventory") or []) if isinstance(x, dict)]
            if inv:
                res["missing_objects"] = [{**x, "missing": max(0, int(x.get("ref_count") or 0) - int(x.get("render_count") or 0))}
                                          for x in inv if int(x.get("ref_count") or 0) > int(x.get("render_count") or 0)]
            chk = lc.get("layout_check") or []
            if chk:
                st = collections.Counter(x.get("status") for x in chk)
                res["layout"] = {"ok": st.get("ok", 0), "moved": st.get("moved", 0), "missing": st.get("missing", 0), "extra": len(lc.get("layout_extra") or []), "n": len(chk)}
        (out / f"{room}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"{room}: passes={len(passes)} defects={len(res['defects'])} derived={res['derived']}")
    (d / "ingested").write_text(time.strftime("%FT%T"))
    print("\n".join(bad) or "ok")


def todo(_):
    for d in sorted(Q.glob("*_r*")):
        res = len(list((d / "results").glob("*.json"))) if (d / "results").is_dir() else 0
        state = "ingested" if (d / "ingested").exists() else "skipped (superseded)" if (d / "SKIP").exists() else ("results waiting" if res else "waiting for the reviewer")
        print(f"{d.name}: {state} ({res} result files)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    for n, f in (("pack", pack), ("ingest", ingest)):
        p = sp.add_parser(n); p.add_argument("tag"); p.add_argument("round"); p.add_argument("--max-views", type=int, default=5); p.set_defaults(f=f)
        if n == "ingest":
            p.add_argument("--dest", help="write the review JSON here instead of out/vlm_review (calibration rounds that already have an API review)")
    sp.add_parser("todo").set_defaults(f=todo)
    a = ap.parse_args(); a.f(a)
