"""Codex-only review loop, v2 (user 2026-10-26: no Claude tokens for review; same checklist judged by TWO independent Codex reviewers per round, ratio from a frozen checklist).
New packs (created after the first start) go to a primary reviewer A (full protocol: TASK.md/REFS_TASK.md + the checklist) and a second reviewer B (checklist only). When A's results/DONE and B's
checklist_answer_B.json exist (B waited at most 45 min) it runs `vlm_peer.py ingest`, refs_ratio and checklist score and writes /bean/ir_dataset_work/reviews/<pack>.md + one INBOX.txt line.
Scenes without a frozen checklist (tools/infinigen/checklist.py build TAG PACK) get the v1 behaviour. State lives in /bean/ir_dataset_work/codex_review/daemon_state.json, so restarts are safe.
  python3 codex_review_daemon.py                         run forever (setsid nohup)
  baseline: append pack names to /bean/ir_dataset_work/codex_review/baseline_requests.txt"""
import json, subprocess, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]; Q = REPO / "out/vlm_queue"; RV = Path("/bean/ir_dataset_work/reviews"); ST = Path("/bean/ir_dataset_work/codex_review/daemon_state.json")
sys.path.insert(0, str(REPO / "tools/infinigen")); import refs_ratio as rr, checklist as ck
REV = {"R1": "term_fb75d86c-89c9-4879-b777-ad69d738514f", "R2": "term_3db279f6-1a51-43e5-a478-b9f9e124b118", "R3": "term_3af1e1b4-878a-4063-be56-3b95c9c90f1e"}
FULL = ("New review batch, same protocol (TASK.md then REFS_TASK.md in the folder; two passes per room; results/<room>.p1|p2.json, refs_answer.json, then results/DONE). Full realism + reference-similarity review. "
        "views/ holds every hand-posed extra view (wide5+, wideX*, *_wide_*): judge those too. ")
CHK = "Checklist review: read CHECKLIST_TASK.md in the folder, then write checklist_answer_{w}.json (your letter is {w}); work independently, do not read the other checklist_answer file. "
PROP = """# Proposals review (concrete fixes tied to the scene's Blender file)
For the {n} open items with the largest effect on the reference match (missing / different in refs_answer.json or the frozen checklist, biggest rooms first), open the scene file READ-ONLY (CPU: CUDA_VISIBLE_DEVICES= /root/miniconda3/envs/infinigen/bin/python with bpy; never save; the file is the pack's source: {blend}) and write {pack}/proposals.json = a list of objects:
{{"item": "<item text or id>", "room": "...", "evidence": {{"objects": ["<Blender object names involved or 'absent'>"], "bbox_m": [[x0,y0,z0],[x1,y1,z1]] or null, "material": "<name and key values>" or null, "view": "<view that shows it>"}}, "cause": "<which shell part / flag / generator produces the current state, e.g. hotel5_shell part X, apt_shell part Y, kit_lighting, layout item Z>", "fix": {{"action": "add|replace|move|resize|recolor|remove", "asset": "<library pool / HSSD or ABO id / procedural builder>", "size_m": [w,d,h], "position_plan_m": [x,y,z] (plan frame = Blender x, -y, z; on a wall use the real inner face from wall_face.py), "material": "<values>"}}, "flips": ["<checklist item ids this should turn into match>"], "effort": "kit|full|layout", "risk": "<what could break>"}}
Keep each proposal executable by someone who has not seen the images: exact names, metres, plan coordinates. Do not edit any file. Put layout-level items (effort=layout) in the list too, marked.
"""
def log(s): print(time.strftime("%FT%T"), s, flush=True)
def sh(*a): return subprocess.run(a, capture_output=True, text=True)
def load():
    try: return json.loads(ST.read_text())
    except Exception: return {"t0": time.time(), "packs": {}}
def save(s): ST.write_text(json.dumps(s, indent=1))
def send(term, text): r = sh("orca", "terminal", "send", "--terminal", term, "--text", text, "--enter", "--wait-submit", "20"); log(f"sent -> {term[:13]} {r.stdout.strip()[-50:]}")
def load_of(s):
    n = {k: 0 for k in REV}
    for p in s["packs"].values():
        if not p.get("reported"):
            for w in ("A", "B"):
                if p.get(w): n[p[w]] += 1
    return n
def assign(s, pack, mode):
    tag = pack.rsplit("_", 1)[0]; has = ck.task(pack); n = load_of(s)
    found = sorted((REPO / "out/infinigen_v2").glob(f"kr_{tag}_*/full/scene_mat2_activity.blend"))
    blend = str(found[0]) if found else "(its out/infinigen_v2/kr_<tag>_<seed>/full/scene_mat2_activity.blend)"
    if mode == "full": (Q / pack / "PROPOSALS_TASK.md").write_text(PROP.format(n=15, blend=blend, pack=f"out/vlm_queue/{pack}"))
    a = min(n, key=n.get) if mode == "full" else None
    if mode == "checklist": order = sorted(n, key=n.get); a, b = order[0], order[1]
    else: b = min((k for k in n if k != a), key=n.get) if has else None
    s["packs"][pack] = {"mode": mode, "A": a, "B": b, "t": time.time(), "has": has}
    path = f"Pack: out/vlm_queue/{pack}."
    send(REV[a], (FULL + (CHK.format(w="A") if has else "") + "Then PROPOSALS_TASK.md (concrete fixes tied to the blend; write proposals.json). " if mode == "full" else CHK.format(w="A")) + path)
    if b: send(REV[b], CHK.format(w="B") + path)
    save(s)
def done(p, rec):
    d = Q / p
    a_ok = (d / "results/DONE").exists() if rec["mode"] == "full" else (d / "checklist_answer_A.json").exists()
    b_ok = (not rec.get("B")) or (d / "checklist_answer_B.json").exists()
    p_ok = (not (d / "PROPOSALS_TASK.md").exists()) or (d / "proposals.json").exists() or time.time() - rec.get("a_done", time.time()) > 2400
    return a_ok and p_ok and (b_ok or time.time() - rec.get("a_done", time.time()) > 2700) if a_ok else False
def report(p, rec):
    tag, rnd = p.rsplit("_", 1); L = []; head = ""
    chk = None
    if rec.get("has"):
        try: chk, items = ck.score(p)
        except Exception as e: log(f"{p}: checklist score failed {e}")
    if rec["mode"] == "full":
        ing = sh("python3", str(REPO / "tools/infinigen/vlm_peer.py"), "ingest", tag, rnd).stdout
        try: m, x, y, r = rr.ratio(p)
        except Exception: m = x = y = 0; r = -1.0
        head = f"free-form match {m}/{m+x+y} = {r:.2f}"
    if chk and chk.get("mean") is not None:
        rv = ", ".join(f"{w} {v['ratio']:.2f}" for w, v in chk["reviewers"].items()); head = f"CHECKLIST mean {chk['mean']:.2f} ({rv}; {chk['n']} fixed items)" + ((" · " + head) if head else "")
    L = [f"# {p}: Codex review (automatic) — {head} (target >= 0.50)\n"]
    if chk and chk.get("by_room"):
        L.append("## Checklist per room (mean of two reviewers: matched / items)"); L += [f"- {k}: {v[0]:.1f}/{v[1]}" for k, v in sorted(chk["by_room"].items())]
        L.append(f"- reviewers disagree on {len(chk.get('disagree', []))} of {chk['n']} items")
    if rec["mode"] == "full":
        L.append("\n## Fix list: every missing/different item by room (free-form, Codex wording)")
        try:
            for room, v in rr.load(p).items():
                if v.get("missing") or v.get("different"): L.append(f"\n### {room}"); L += [f"- MISSING: {i}" for i in v.get("missing", [])] + [f"- DIFFERENT: {i}" for i in v.get("different", [])]
        except Exception: pass
        L += ["\n## Defect scores per room (derived, 9 = clean)", "```", ing.strip(), "```"]
    pj = Q / p / "proposals.json"
    if pj.is_file():
        try:
            L.append("\n## Concrete proposals tied to the Blender file (Codex)")
            for i, x in enumerate(json.load(open(pj)), 1):
                fx = x.get("fix", {}); ev = x.get("evidence", {})
                L.append(f"{i}. [{x.get('effort','?')}] {x.get('room','')}: {x.get('item','')}\n   - evidence: {ev.get('objects')} bbox {ev.get('bbox_m')} material {ev.get('material')} (view {ev.get('view')})\n   - cause: {x.get('cause')}\n   - fix: {fx.get('action')} {fx.get('asset')} size {fx.get('size_m')} at {fx.get('position_plan_m')} material {fx.get('material')}\n   - flips: {x.get('flips')}; risk: {x.get('risk')}")
        except Exception as e: L.append(f"(proposals.json unreadable: {e})")
    (RV / (f"{p}.md" if rec["mode"] == "full" else f"{p}.checklist.md")).write_text("\n".join(L) + "\n")
    with open(RV / "INBOX.txt", "a") as f: f.write(f"{time.strftime('%FT%TZ', time.gmtime())} CODEX: wrote {p}{'' if rec['mode']=='full' else '.checklist'}.md ({head})\n")
    log(f"{p}: report written, {head}")
def main():
    s = load(); save(s); base = sys.argv[1:2] == ["--baseline"]
    if base:
        for p in sys.argv[2:]:
            if p not in s["packs"]: assign(s, p, "checklist")
    while True:
        if not base:
            for d in sorted(Q.glob("*_r*")):
                if d.name in s["packs"] or (d / "SKIP").exists() or not (d / "manifest.json").exists() or d.stat().st_mtime < s["t0"] or (d / "results/DONE").exists(): continue
                assign(s, d.name, "full")
        rq = Path("/bean/ir_dataset_work/codex_review/baseline_requests.txt")      # one pack per line: a checklist-only baseline round (two reviewers) for a pack that already has a full review
        if rq.is_file():
            for ln in rq.read_text().split():
                if ln not in s["packs"] and (Q / ln / "manifest.json").exists() and ck.task(ln): assign(s, ln, "checklist")
        for p, rec in list(s["packs"].items()):
            if rec.get("reported"): continue
            d = Q / p
            a_ok = (d / "results/DONE").exists() if rec["mode"] == "full" else (d / "checklist_answer_A.json").exists()
            if a_ok and "a_done" not in rec: rec["a_done"] = time.time(); save(s)
            if done(p, rec):
                time.sleep(20)
                try: report(p, rec); rec["reported"] = True; save(s)
                except Exception as e: log(f"{p}: report failed {e}")
        if base and all(r.get("reported") for r in s["packs"].values()): return
        time.sleep(60)
main()
