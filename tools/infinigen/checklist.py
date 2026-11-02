"""Fixed reference checklists (user 2026-10-26: judge the same items every round, with two independent Codex reviewers, so the ratio is not noise).
  checklist.py build TAG PACK       freeze the items of PACK's refs_answer.json (matches + missing + different, per room) as checklists/TAG.json
  checklist.py task PACK            write PACK/checklist.json + PACK/CHECKLIST_TASK.md for the reviewers (needs checklists/TAG.json)
  checklist.py score PACK           ratio per reviewer file PACK/checklist_answer_*.json and the mean; prints per-room mean and the items the reviewers disagree on
Ratio = items judged 'match' / all items in the checklist (a missing answer counts as not matched)."""
import json, re, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]; Q = REPO / "out/vlm_queue"; CL = Path("/bean/ir_dataset_work/reviews/checklists")

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:24]

def build(tag, pack):
    d = json.load(open(Q / pack / "refs_answer.json")); items, seen = [], set()
    for room, v in d.items():
        if not isinstance(v, dict): continue
        for kind in ("matches", "missing", "different"):
            for t in v.get(kind, []) or []:
                if not isinstance(t, str) or (room, t) in seen: continue
                seen.add((room, t)); items.append({"id": f"{slug(room)}-{len(items):03d}", "room": room, "text": t, "baseline": kind})
    CL.mkdir(parents=True, exist_ok=True); json.dump({"tag": tag, "built_from": pack, "items": items}, open(CL / f"{tag}.json", "w"), ensure_ascii=False, indent=1)
    print(f"{tag}: {len(items)} items from {pack}")

TASK = """# Checklist review (same items every round; two reviewers work independently)
Open {pack}/checklist.json. Each item is a reference feature (or a known gap, worded as a difference). For EVERY item decide, using ALL views in views/ (including the hand-posed extra views) and the reference images in refs/:
- "match": the render reproduces that reference feature (visible in at least one view).
- "different": something of that kind is there but it does not look like the reference (shape, colour, finish, position, quantity).
- "missing": it is not visible in any view.
Write {pack}/checklist_answer_{who}.json exactly as {{"reviewer": "{who}", "answers": {{"<item id>": {{"verdict": "match|different|missing", "view": "<view name or empty>"}}, ...}}}} with an answer for every id. Do not read any other checklist_answer_*.json. Do not skip items.
"""

def task(pack):
    tag = pack.rsplit("_", 1)[0]; f = CL / f"{tag}.json"
    if not f.is_file(): return False
    (Q / pack / "checklist.json").write_text(f.read_text()); (Q / pack / "CHECKLIST_TASK.md").write_text(TASK.format(pack=f"out/vlm_queue/{pack}", who="A or B (your letter, given in the message)"))
    return True

def score(pack):
    tag = pack.rsplit("_", 1)[0]; items = json.load(open(CL / f"{tag}.json"))["items"]; ids = [i["id"] for i in items]
    ans = {}
    for f in sorted((Q / pack).glob("checklist_answer_*.json")):
        try: ans[f.stem[len("checklist_answer_"):]] = json.load(open(f))["answers"]
        except Exception: pass
    out = {"n": len(ids), "reviewers": {}}
    for w, a in ans.items():
        m = sum(1 for i in ids if (a.get(i) or {}).get("verdict") == "match"); out["reviewers"][w] = {"match": m, "answered": sum(1 for i in ids if i in a), "ratio": m / max(1, len(ids))}
    if out["reviewers"]: out["mean"] = sum(r["ratio"] for r in out["reviewers"].values()) / len(out["reviewers"])
    if len(ans) >= 2:
        w = sorted(ans)[:2]; out["disagree"] = [i for i in ids if (ans[w[0]].get(i) or {}).get("verdict") != (ans[w[1]].get(i) or {}).get("verdict")]
        out["by_room"] = {}
        for it in items:
            r = out["by_room"].setdefault(it["room"], [0, 0]); r[1] += 1; r[0] += sum(1 for x in w if (ans[x].get(it["id"]) or {}).get("verdict") == "match") / 2
    return out, items

if __name__ == "__main__":
    c = sys.argv[1]
    if c == "build": build(sys.argv[2], sys.argv[3])
    elif c == "task": print(task(sys.argv[2]))
    elif c == "score":
        o, _ = score(sys.argv[2]); print(json.dumps({k: v for k, v in o.items() if k != "disagree"}, indent=1)); print("disagree:", len(o.get("disagree", [])))
