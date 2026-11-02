"""VLM review of one room's renders, following docs/review_feedback_rules.md (user 2026-10-19).

The model is never asked for a 1-10 score. Four stages, a blocker in an earlier stage stops the later ones:
  1 auto   scripts: brightness / clipping (LGT-EXP), albedo (GT-ALB), instance count drop (OBJ-CNT), near-camera depth (CAM-OCC)
  2 defects  per view yes/no checklist of the V codes, each "yes" carries a 3x3 grid cell + evidence; kept when >= 2 of N runs agree (votes)
  3 ref    reference spec card items answered match / differ / missing (needs --ref images + --spec card; --allow-ref-upload)
  4 ab     previous round, same view, both orders, 6 criteria better / same / worse + new issues (orders that disagree -> same)
Scores are derived from the defect list (9 - 2 per major - 0.5 per minor, floor 3); the output is the schema of the rules doc.

  python tools/infinigen/vlm_review.py --scene S9 --round r12 --room cafe --views out_dir_with_wide_pngs \
      [--prev prev_round_dir] [--gt gt_dir] [--depth depth_dir] [--counts cur.json --prev-counts prev.json] \
      [--spec spec.json --ref ref1.jpg --ref ref2.jpg --allow-ref-upload] [--votes 3] [--model claude-sonnet-5-5] [--dry-run] [--stage1-only] --out review.json
Privacy: only synthetic renders go to the API; reference photos only with --allow-ref-upload and only the people-free cleaned set.
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import io
import json
import os
import sys
from pathlib import Path

PROMPT_VERSION = "vlm-review-v2"      # v2 10-19: +CNT-04 FUN-01 MAT-01 GEO-01 LGT-02, per-defect cause, gt_stats (from the external 9-scene review the user pasted)
KEY_FILE = Path(os.environ.get("ROOM_PLANNER_KEY_FILE", str(Path.home() / ".config/robomituba/anthropic_key")))
CACHE = Path(os.environ.get("VLM_REVIEW_CACHE", "/jarvis/project/robomituba/out/vlm_review_cache"))
ITEMS = ["기능", "레이아웃", "업종", "완성도", "사용 흔적", "표면", "유사도"]
# code -> (description, severity, item index)  -- V codes only; A codes are computed below
V_CODES = {
    "ENV-01": ("outside the window there is a floor slab / cut-off ground / hard horizon edge, or background shows through a gap between window frame and wall, or the window shows nothing at all (blank gradient, shut blinds)", "major", 3),
    "LAY-01": ("a door or window is blocked by furniture, or a door that people must pass through is closed", "major", 1),
    "LAY-02": ("circulation or density is wrong: no walkable path, or empty floor, chairs facing away / unpaired, objects interpenetrating or floating", "major", 1),
    "CNT-01": ("an empty table: no chairs, or no food / tableware / drink on it", "major", 0),
    "CNT-02": ("goods, signs, ad boards, posters or mannequins repeat or lack variety", "major", 4),
    "CNT-03": ("small signs of use are missing (fridge notes, papers, bins, cleaning tools)", "minor", 4),
    "DOM-01": ("props, prints or screens belong to another kind of business", "major", 2),
    "AST-01": ("unrealistic plants, or boxy low-poly chairs", "major", 5),
    "AST-02": ("broken mesh / stair-step artefacts, or a texture wrapped over a whole box", "major", 3),
    "SRF-01": ("walls or ceiling are plain/boring, or their material differs from the reference", "major", 5),
    "SRF-02": ("surfaces too clean, or weathering so heavy it looks like stains / mould", "major", 4),
    "SRF-03": ("odd fonts, broken lettering, flat texture", "major", 5),
    "LGT-01": ("light fixtures sit flush on the ceiling and light does not spread", "minor", 3),
    "CNT-04": ("shelves, racks, display cases or counters meant to hold goods are mostly empty or have long gaps, visibly under ~70% full; the same product repeated in neat identical blocks is CNT-02, not this", "major", 4),
    "FUN-01": ("objects that define this kind of venue are missing: no cooler or checkout in a shop, no counter or espresso machine in a cafe, no desk or monitor in an office, no treatment chair in a clinic", "major", 2),
    "MAT-01": ("walls, furniture, plastic and fabric all share one flat matte look: no visible gloss, metal or glass contrast between material classes (plain matte white walls alone are NOT this)", "minor", 5),
    "GEO-01": ("furniture or fixtures look like bare CAD solids: razor-sharp edges, no bevel, very thin flat frames, no joints or seams", "minor", 3),
    "LGT-02": ("no contact shadow or depth where objects meet shelf boards, floor or walls, so objects look pasted on or floating", "minor", 3),
}
CAUSES = ["asset", "layout", "lighting", "render"]      # who fixes it: the object/material itself, where things are placed, the light rig, exposure/tone-mapping/texture filtering
A_SEV = {"LGT-EXP": ("blocker", 3), "GT-ALB": ("major", 5), "OBJ-CNT": ("blocker", 3), "CAM-OCC": ("blocker", 1)}
SEV_PENALTY = {"major": 2.0, "minor": 0.5}


# ---------------------------------------------------------------- images
def load_views(d: Path):
    """name -> path of the room's wide RGB views (png/jpg), sorted."""
    return {p.stem: p for p in sorted(d.iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg") and "_wide" in p.stem or (p.suffix.lower() in (".png", ".jpg") and p.stem.startswith("v"))}


def b64(path: Path, max_side=1568) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=92)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}


# ---------------------------------------------------------------- stage 1: scripts
def stage1(views, a):
    import numpy as np
    from PIL import Image
    out = []
    lo, hi, clip_max = a.l_range[0], a.l_range[1], a.clip_max
    for name, p in views.items():
        g = np.asarray(Image.open(p).convert("L"), dtype=np.float32)
        mean = float(g.mean()); clip = float(((g >= 250) | (g <= 2)).mean())
        if not lo <= mean <= hi or clip > clip_max:
            out.append({"code": "LGT-EXP", "view": name, "value": round(mean, 1), "clip": round(clip, 3), "target": f"mean {lo}-{hi}, clip <= {clip_max}", "pass": False})
        if a.gt:
            f = Path(a.gt) / f"{name}_albedo.png"
            if f.is_file():
                alb = np.asarray(Image.open(f).convert("RGB"), dtype=np.float32).max(axis=2) / 255.0
                alb = ((alb + 0.055) / 1.055) ** 2.4                    # the GT png is sRGB-encoded; the rule's 0.9 is linear albedo
                frac = float((alb > 0.9).mean())
                if frac > 0.30:
                    out.append({"code": "GT-ALB", "view": name, "value": round(frac, 3), "target": "<= 0.30 of pixels above 0.9", "pass": False})
        if a.depth:
            f = Path(a.depth) / f"{name}_depth.npy"
            if f.is_file():
                d = np.load(f); near = float((d < 0.5).mean())
                if near > 0.30:
                    out.append({"code": "CAM-OCC", "view": name, "value": round(near, 3), "target": "<= 0.30 of pixels within 0.5 m", "pass": False})
    if a.counts and a.prev_counts:
        cur, prev = json.load(open(a.counts)), json.load(open(a.prev_counts))
        for room, n in prev.items():
            m = cur.get(room, 0)
            if n and (n - m) / n >= 0.20:
                out.append({"code": "OBJ-CNT", "view": room, "value": m, "prev": n, "target": "drop < 20% vs previous round", "pass": False})
    return out


def gt_stats(views, a):
    """Per view: roughness spread, share of pixels near the median roughness, normal-map detail. Information only, never a defect: measured 10-19 over 37 scenes these did not
    separate rooms the human passed from ones it did not (rough std 0.14-0.30, normal detail 0.005-0.028), so no threshold is justified; they exist to compare two rounds of the same room."""
    import numpy as np
    from PIL import Image
    out = {}
    for name in views:
        f = Path(a.gt) / f"{name}_rough.png" if a.gt else None
        if not (f and f.is_file()):
            continue
        r = np.asarray(Image.open(f).convert("L"), dtype=np.float32) / 255
        st = {"rough_std": round(float(r.std()), 3), "rough_near_median": round(float((abs(r - np.median(r)) < 0.05).mean()), 2)}
        fn = Path(a.gt) / f"{name}_normal.png"
        if fn.is_file():
            g = np.asarray(Image.open(fn).convert("RGB"), dtype=np.float32).mean(axis=2) / 255
            st["normal_detail"] = round(float(np.abs(np.diff(g, axis=1)).mean() + np.abs(np.diff(g, axis=0)).mean()), 4)
        out[name] = st
    return out


# ---------------------------------------------------------------- API
_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY") or (KEY_FILE.read_text().strip() if KEY_FILE.is_file() else "")
        if not key:
            sys.exit(f"no API key: set ANTHROPIC_API_KEY or write {KEY_FILE} (chmod 600)")
        _client = anthropic.Anthropic(api_key=key, max_retries=4, default_headers={"Accept-Encoding": "gzip, deflate"})
    return _client


def ask(model, system, content, tool, tag, run, dry):
    """One tool-call answer, cached by (prompt version, model, tool, run index, content hash). tool_choice auto + one nudge (Sonnet 5.5 refuses a forced tool)."""
    h = hashlib.sha256(json.dumps([PROMPT_VERSION, model, tool["name"], run, system, [c if c["type"] == "text" else c["source"]["data"][:2000] + str(len(c["source"]["data"])) for c in content]]).encode()).hexdigest()[:24]
    path = CACHE / f"{h}.json"
    if path.is_file():
        return json.loads(path.read_text())
    if dry:
        return None
    msgs = [{"role": "user", "content": content}]
    r = client().messages.create(model=model, max_tokens=2000, system=system, tools=[tool], tool_choice={"type": "auto"}, messages=msgs)
    res = next((b.input for b in r.content if b.type == "tool_use" and b.name == tool["name"]), None)
    if res is None:
        r = client().messages.create(model=model, max_tokens=2000, system=system, tools=[tool], tool_choice={"type": "auto"},
                                     messages=msgs + [{"role": "assistant", "content": r.content}, {"role": "user", "content": f"Please answer by calling {tool['name']}."}])
        res = next(b.input for b in r.content if b.type == "tool_use" and b.name == tool["name"])
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res))
    return res


SYS = ("You inspect renders of a synthetic indoor scene for visible defects. Answer only about what is visible in the image. "
       "Never give a numeric quality score. A defect is 'yes' only if you can point to it: give the 3x3 grid cell "
       "(top-left, top-center, top-right, middle-left, center, middle-right, bottom-left, bottom-center, bottom-right) and one line of evidence naming the object. "
       "No evidence means no. Also give the most likely cause of each defect: 'asset' (the object or its material/texture), 'layout' (placement, density, missing objects), "
       "'lighting' (light rig, shadows) or 'render' (exposure, tone mapping, texture filtering, low resolution). If exposure or dim light could be hiding a defect, say so in the evidence. "
       "Plain matte white or grey surfaces are physically normal: report a surface only when it looks flat, repeated or unlike its material, not because it is matte.")
DEFECT_TOOL = {"name": "report_defects", "description": "Report the defects present in this view.",
               "input_schema": {"type": "object", "required": ["defects"], "properties": {"defects": {"type": "array", "items": {
                   "type": "object", "required": ["code", "where", "evidence"], "properties": {
                       "code": {"type": "string", "enum": list(V_CODES)}, "where": {"type": "string"}, "evidence": {"type": "string"},
                       "cause": {"type": "string", "enum": CAUSES}, "view": {"type": "string", "description": "only when several images are shown: the name of the view the defect is in"}}}}}}}
REF_TOOL = {"name": "report_ref", "description": "Compare the render with the reference spec card.",
            "input_schema": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
                "type": "object", "required": ["item", "match", "note"], "properties": {
                    "item": {"type": "string"}, "match": {"type": "string", "enum": ["match", "differ", "missing"]}, "note": {"type": "string"}}}}}}}
AB_TOOL = {"name": "report_ab", "description": "Compare image A and image B of the same view.",
           "input_schema": {"type": "object", "required": ["verdicts", "new_issues"], "properties": {
               "verdicts": {"type": "object", "properties": {k: {"type": "string", "enum": ["A better", "same", "B better"]} for k in ITEMS[:6]}},
               "new_issues": {"type": "array", "items": {"type": "string"}, "description": "problems present in B but not in A (or in A but not in B), say which image"}}}}


def stage2(views, a, ctx):
    checklist = "\n".join(f"- {c}: {d}" for c, (d, _, _) in V_CODES.items())
    found = collections.defaultdict(list)
    calls = 0
    if a.batch_views:                                  # one call per vote with every view: the checklist is paid once per vote, not once per view and vote
        content = [{"type": "text", "text": f"{ctx}\nThe {len(views)} images below are views of the same room, each preceded by its name. Check each item for each view and report only what is visibly true, naming the view in 'view':\n{checklist}"}]
        for name, p in views.items():
            content += [{"type": "text", "text": f"View '{name}':"}, b64(p)]
        for run in range(a.votes):
            res = ask(a.model_defects or a.model, SYS, content, DEFECT_TOOL, "defects_batch", run, a.dry_run); calls += 1
            if res is None:
                continue
            seen = set()
            for d in res.get("defects", []):
                name = d.get("view")
                if name in views and d["code"] in V_CODES and d.get("evidence", "").strip() and (name, d["code"]) not in seen:
                    seen.add((name, d["code"])); found[(name, d["code"])].append(d)
        views = {}                                     # nothing left for the per-view loop below
    for name, p in views.items():
        img = b64(p)
        for run in range(a.votes):
            txt = {"type": "text", "text": f"{ctx}\nView '{name}'. Check each item below; report only those that are visibly true:\n{checklist}"}
            res = ask(a.model_defects or a.model, SYS, [img, txt], DEFECT_TOOL, "defects", run, a.dry_run); calls += 1
            if res is None:
                continue
            seen = set()
            for d in res.get("defects", []):
                if d["code"] in V_CODES and d.get("evidence", "").strip() and (name, d["code"]) not in seen:
                    seen.add((name, d["code"])); found[(name, d["code"])].append(d)
    out = []
    for (name, code), ds in found.items():
        if len(ds) >= min(2, a.votes):
            cause = collections.Counter(d.get("cause") for d in ds if d.get("cause")).most_common(1)
            out.append({"code": code, "view": name, "where": ds[0]["where"], "evidence": ds[0]["evidence"], "severity": V_CODES[code][1], "votes": len(ds), "cause": cause[0][0] if cause else ""})
    return out, calls


def stage3(views, a, ctx):
    if not (a.spec and a.ref):
        return [], 0
    if not a.allow_ref_upload:
        sys.exit("--ref images are uploaded to the API: pass --allow-ref-upload only for the people-free cleaned reference set")
    card = json.load(open(a.spec))
    refs = [b64(Path(r)) for r in a.ref]
    pick = list(views.values())[: a.ref_views]
    txt = {"type": "text", "text": "Reference photos first, then the renders. For each spec card item answer match / differ / missing for the RENDERS versus the reference.\n" + json.dumps(card, ensure_ascii=False)}
    res = ask(a.model, SYS, refs + [b64(p) for p in pick] + [txt], REF_TOOL, "ref", 0, a.dry_run)
    return (res or {}).get("items", []), 1


def stage4(views, a):
    if not a.prev:
        return None, 0
    prev = load_views(Path(a.prev)); score = collections.defaultdict(lambda: collections.Counter()); issues = []; calls = 0
    for name, p in views.items():
        if name not in prev:
            continue
        new, old = b64(p), b64(prev[name])
        for order in (0, 1):                                    # swap sides so a position bias cancels
            A, B = (old, new) if order == 0 else (new, old)
            txt = {"type": "text", "text": f"Image A then image B: the same view in two render rounds. For each criterion say which is better. Criteria: {', '.join(ITEMS[:6])}."}
            res = ask(a.model, SYS, [A, B, txt], AB_TOOL, "ab", order, a.dry_run); calls += 1
            if res is None:
                continue
            for k, v in res.get("verdicts", {}).items():
                better_new = (v == "B better") if order == 0 else (v == "A better")
                worse_new = (v == "A better") if order == 0 else (v == "B better")
                score[k]["better" if better_new else "worse" if worse_new else "same"] += 1
            issues += res.get("new_issues", [])
    if not score:
        return None, calls
    n_views = sum(1 for n in views if n in prev)
    better = [k for k, c in score.items() if c["better"] >= n_views + 1]        # both orders agree on most views
    worse = [k for k, c in score.items() if c["worse"] >= n_views + 1]
    return {"vs": Path(a.prev).name, "better": better, "worse": worse, "new_issues": issues[:8]}, calls


# ---------------------------------------------------------------- aggregate + derive + gate
def aggregate(defects):
    """One finding per code for the room (the same defect seen in several views is one finding listing its views); strongest votes first."""
    by = collections.OrderedDict()
    for d in sorted(defects, key=lambda x: -x.get("votes", 1)):
        g = by.setdefault(d["code"], {"code": d["code"], "views": [], "where": d.get("where", ""), "evidence": d.get("evidence", ""),
                                      "severity": d["severity"], "votes": d.get("votes", 1), "cause": d.get("cause", "")})
        for v in d.get("views") or [d["view"]]:
            if v not in g["views"]:
                g["views"].append(v)
    out = list(by.values())
    for g in out:
        g["views"].sort(); g["view"] = g["views"][0]; g["n_views"] = len(g["views"])
    return out


def reaggregate_file(path):
    """Re-run aggregation and the derived scores on a saved review (no API)."""
    d = json.load(open(path))
    d["defects"] = aggregate(d.get("defects", []))
    d["derived"] = derive(d.get("auto", []), d["defects"], d.get("ref") or [])
    json.dump(d, open(path, "w"), ensure_ascii=False, indent=1)
    return d


# ---------------------------------------------------------------- derive + gate
def derive(auto, defects, ref):
    pen = [0.0] * 7
    for d in defects:
        pen[V_CODES[d["code"]][2]] += SEV_PENALTY[d["severity"]] if d["code"] in V_CODES else 0
    for code in {d["code"] for d in auto}:                                                     # a code counts once per room, however many views show it
        sev, i = A_SEV[code]
        if sev == "major":
            pen[i] += 2.0
    derived = [max(3.0, 9.0 - p) for p in pen[:6]]
    if ref:
        ok = sum(1 for r in ref if r["match"] == "match") / len(ref)
        derived.append(round(max(3.0, 3.0 + 6.0 * ok), 1))                                  # match share, re-fit against the human scores each round
    return [round(x, 1) for x in derived]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reaggregate", nargs="+", help="re-aggregate saved review JSON files and exit (no API)")
    ap.add_argument("--scene"); ap.add_argument("--round"); ap.add_argument("--room")
    ap.add_argument("--views"); ap.add_argument("--prev"); ap.add_argument("--gt"); ap.add_argument("--depth")
    ap.add_argument("--counts"); ap.add_argument("--prev-counts", dest="prev_counts")
    ap.add_argument("--spec"); ap.add_argument("--ref", action="append"); ap.add_argument("--allow-ref-upload", action="store_true")
    ap.add_argument("--ref-views", type=int, default=3)
    ap.add_argument("--l-range", type=float, nargs=2, default=[25.0, 215.0], help="mean luma range; calibrated 10-19: human-passed rooms 36-212 (dark pub 37-67, white corridor), S23 r6 pub with the new ceiling ~30 is intended, the C r16 dark bug is 11-17")
    ap.add_argument("--clip-max", type=float, default=0.15, help="share of crushed (<=2) or blown (>=250) pixels; the human-passed dark pub has 0.09-0.13, the C r16 bug 0.08-0.23 (caught by the mean)")
    ap.add_argument("--votes", type=int, default=3); ap.add_argument("--model", default=os.environ.get("VLM_REVIEW_MODEL", "claude-sonnet-5-5"))
    ap.add_argument("--model-defects", dest="model_defects", default=os.environ.get("VLM_REVIEW_MODEL_DEFECTS"), help="model for the stage-2 defect checklist (the bulk of the calls); stages 3-4 keep --model")
    ap.add_argument("--batch-views", dest="batch_views", action="store_true", default=os.environ.get("VLM_REVIEW_BATCH") == "1", help="stage 2 in one call per vote with all views (about 5x fewer calls)")
    ap.add_argument("--max-views", type=int, default=8)
    ap.add_argument("--stage1-only", action="store_true"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--out")
    a = ap.parse_args()
    if a.reaggregate:
        for f in a.reaggregate:
            d = reaggregate_file(f); print(f"{Path(f).parent.name}/{Path(f).stem}: defects={len(d['defects'])} derived={d['derived']}")
        return
    if not (a.scene and a.round and a.room and a.views):
        ap.error("--scene --round --room --views are required")
    allv = load_views(Path(a.views))
    views = dict(list({n: p for n, p in allv.items() if n.startswith(a.room)}.items() or allv.items())[: a.max_views])   # a floor dir holds every room: keep this room's views
    if not views:
        sys.exit(f"no wide views in {a.views}")
    res = {"scene": a.scene, "round": a.round, "room": a.room, "model": a.model, "prompt_version": PROMPT_VERSION}
    res["auto"] = stage1(views, a)
    res["gt_stats"] = gt_stats(views, a)
    blockers = [x for x in res["auto"] if A_SEV[x["code"]][0] == "blocker"]
    res.update(defects=[], ref=[], ab=None)
    calls = 0
    if not blockers and not a.stage1_only:
        ctx = f"Scene {a.scene}, room '{a.room}', round {a.round}."
        res["defects"], c2 = stage2(views, a, ctx)
        res["defects"] = aggregate(res["defects"])
        res["ref"], c3 = stage3(views, a, ctx)
        res["ab"], c4 = stage4(views, a)
        calls = c2 + c3 + c4
    res["derived"] = derive(res["auto"], res["defects"], res["ref"])
    res["gate"] = "blocked" if blockers else "stage1_only" if a.stage1_only else "dry_run" if a.dry_run else (
        "to_human")                                                                         # majors lower the derived item, only blockers keep a scene from the human
    res["api_calls"] = calls
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    print(txt if not a.out else f"{a.scene} {a.round} {a.room}: gate={res['gate']} auto={len(res['auto'])} defects={len(res['defects'])} derived={res['derived']} calls={calls} -> {a.out}")


if __name__ == "__main__":
    main()
