"""One step of the VLM review -> fix -> re-render loop (rules: docs/review_feedback_rules.md, loop: docs/review_fix_loop.md).

  review_loop.py status                       latest round, VLM major findings per code, last verdict, per scene
  review_loop.py next SCENE --add K=V --add K=V     re-render the floor kit-only with extra late flags (one round, flags logged); gt_round.sh then reviews it (VLM + A/B)
  review_loop.py judge SCENE                  compare the newest round with the previous one; keep the added flags or revert them
Only late (kit_lighting) flags are tried here; defects that need new props/code stay tickets for the generator owner. The human score stays the only bar:
the loop never closes a ticket, it only decides keep / revert of the flags it added and writes out/review_loop/log.jsonl.
"""
import argparse, json, subprocess, sys, time, shlex
from pathlib import Path

REPO = Path("/jarvis/project/robomituba"); O = Path("/tmp/claude-0/objreal"); REG = REPO / "configs/scene_recipes.json"; LOG = REPO / "out/review_loop/log.jsonl"
TARGET = {"ROOM_ENV_WINDOWS": "ENV-01", "ROOM_HUNG_LIGHTS": "LGT-01", "ROOM_FLAT_ONLY": "SRF-02"}      # flag -> the defect code it is meant to clear
PARENT = {"ROOM_ENV_KIND": "ROOM_ENV_WINDOWS", "ROOM_ENV_SEED": "ROOM_ENV_WINDOWS", "ROOM_HUNG_STYLE": "ROOM_HUNG_LIGHTS", "ROOM_HUNG_ROOMS": "ROOM_HUNG_LIGHTS",
          "ROOM_HUNG_PITCH": "ROOM_HUNG_LIGHTS", "ROOM_HUNG_W": "ROOM_HUNG_LIGHTS"}   # parameters follow their flag; they have no code of their own
NOISE = 3        # VLM major counts move by a few between two renders of the same scene; a fix is judged on its own code, the total may rise by this much


def reg():
    return json.loads(REG.read_text())


def codes(tag, rnd):
    """{code: rooms with it} for a reviewed round, plus the total of major findings."""
    d = REPO / "out/vlm_review" / f"{tag}_r{rnd}"; by = {}; maj = 0
    for f in sorted(d.glob("*.json")):
        j = json.loads(f.read_text())
        for x in j.get("defects", []):
            by.setdefault(x["code"], []).append(f.stem); maj += x["severity"] == "major"
    return by, maj


def log(**kw):
    LOG.parent.mkdir(parents=True, exist_ok=True); kw["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(LOG, "a") as f:
        f.write(json.dumps(kw, ensure_ascii=False) + "\n")


def status(_):
    for s, r in reg().items():
        if s.startswith("_"):
            continue
        by, maj = codes(r["tag"], r["round"])
        print(f"{s} {r['tag']} r{r['round']}: major={maj} " + " ".join(f"{c}x{len(v)}" for c, v in sorted(by.items(), key=lambda kv: -len(kv[1]))))


def nxt(a):
    R = reg(); r = R[a.scene]; add = dict(kv.split("=", 1) for kv in a.add)
    new = r["round"] + 1; env = {**r["env"], **add}
    F = REPO / f"out/infinigen_v2/kr_{r['tag']}_{r['seed']}/full"
    script = O / f"loop_{r['tag']}_r{new}.sh"
    envs = " ".join(f"{k}={shlex.quote(v)}" for k, v in {**env, "RENDER_GPU": str(r["gpu"]), "ROOM_ENV_KIND": env.get("ROOM_ENV_KIND", "street")}.items())
    script.write_text(f"""#!/bin/bash
cd {O}
cp -p {F}/scene_mat2_activity.blend1 {F}/scene_mat2_activity.blend
env {envs} ./venue_floor_kitonly.sh {r['seed']} {r['gen']} {r['tag']} > venue_{r['tag']}_r{new}.out 2>&1 && bash gt_round.sh {r['tag']} r{new} {r['seed']} {r['gpu']} venue_{r['tag']}_r{new}.out > gt_run_{r['tag']}_r{new}.out 2>&1
""")
    subprocess.Popen(["setsid", "-f", "nohup", "bash", str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    R[a.scene] = {**r, "round": new, "env": env, "prev_env": r["env"], "added": add}
    REG.write_text(json.dumps(R, indent=1, ensure_ascii=False))
    log(scene=a.scene, action="next", round=new, parent=r["round"], added=add)
    print(f"{a.scene}: launched r{new} with {add}")


def judge(a):
    R = reg(); r = R[a.scene]; new, old = r["round"], r["round"] - 1
    add = r.get("added") or {}
    b1, m1 = codes(r["tag"], new); b0, m0 = codes(r["tag"], old)
    if not b1 and not list((REPO / "out/vlm_review" / f"{r['tag']}_r{new}").glob("*.json")):
        sys.exit(f"r{new} has no review yet")
    verdict = {}
    for k in add:
        if k in PARENT:
            continue
        c = TARGET.get(k)
        before, after = len(b0.get(c, [])), len(b1.get(c, []))
        verdict[k] = {"code": c, "before": before, "after": after, "keep": (m1 <= m0 + NOISE) if not c else bool(after <= before and m1 <= m0 + NOISE)}      # a flag with no target code (floor wear, door colours) is kept unless the total majors jump
    revert = [k for k, v in verdict.items() if not v["keep"]] 
    revert += [k for k in add if PARENT.get(k) in revert]
    if revert:
        for k in revert:
            r["env"].pop(k, None)
        REG.write_text(json.dumps(R, indent=1, ensure_ascii=False))
    log(scene=a.scene, action="judge", round=new, vs=old, major=[m0, m1], verdict=verdict, reverted=revert)
    print(json.dumps({"major": [m0, m1], "verdict": verdict, "reverted": revert}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status").set_defaults(f=status)
    p = sp.add_parser("next"); p.add_argument("scene"); p.add_argument("--add", action="append", default=[], help="K=V, repeatable (values may contain commas)"); p.set_defaults(f=nxt)
    p = sp.add_parser("judge"); p.add_argument("scene"); p.set_defaults(f=judge)
    a = ap.parse_args(); a.f(a)
