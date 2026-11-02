"""Scene loop runner: one place to start a render round of any scene, with a lock per scene and a cap on concurrent rounds.

  scene_loop.py import [--ids data.json]        build configs/scene_loop_recipes.json from the newest launch line of every tag in the round scripts
  scene_loop.py status                          per scene: latest round, VLM major codes, running / complete
  scene_loop.py ps                              rounds running now (lock held)
  scene_loop.py run ID [--add K=V]... [--rm K]... [--full] [--queue] [--dry]
  scene_loop.py review ID [--round N] [--votes 2]   VLM review of a round on demand (runs of `run --no-review` skip the automatic review that gt_round.sh does)
  scene_loop.py suggest ID                      codes that appear in the last two rounds (persistent) -> flags not yet set (no launch)

A round = pipeline script -> (bg_render) -> gt_round.sh (GT + rvs_ snapshot + VLM review). Stages run as argv lists, never through sh -c, so
';' / quotes in env values survive. The runner never decides keep/revert and never promotes: scores and 'complete' stay with the user.
Recipes keep the full launch env of the newest round; --add/--rm change it and are stored on launch. GPUs stay what the recipe says (user rule: a run keeps its GPUs).
"""
import argparse, fcntl, glob, json, os, re, shlex, subprocess, sys, time
from pathlib import Path

REPO = Path("/jarvis/project/robomituba"); O = Path("/tmp/claude-0/objreal")
REG = REPO / "configs/scene_loop_recipes.json"; STATE = REPO / "out/scene_loop"; LOCKS = STATE / "locks"
MAX = int(os.environ.get("SCENE_LOOP_MAX", "4"))
SCRIPT = r"\./(venue_(?:pipeline_v\d+|floor_pipeline_v2|floor_kitonly)\.sh)"
FIX = {"SRF-02": {"ROOM_FLOOR_SCUFF": "1"}, "SRF-01": {"ROOM_BASEBOARD": "1"}, "ENV-01": {"ROOM_ENV_WINDOWS": "1", "ROOM_ENV_KIND": "street"},
       "LGT-01": {"ROOM_HUNG_LIGHTS": "1"}}      # defect code -> late flags that exist today; a table, extend it when a generator owner adds a knob


def parse_line(line):
    """One launch line of a round script -> (tag, round, recipe) or None. Handles `env K=V ... ./script args > venue_TAG_rN.out`, the `run OUT K=V ...` helper and bash -c "..." wrappers."""
    m = re.search(r"venue_(\w+?)(?:_r(\d+))?\.out", line)
    s = re.search(SCRIPT + r"\s+(.*?)\s*(?:>\s*venue_|&\s*$|$)", line)      # old `run OUT env ./script args &` lines have no redirect and no round number
    if not (m and s):
        return None
    tag, rnd = m.group(1), int(m.group(2) or 0)
    head = line[:s.start()].replace('\\"', '"')
    head = head.split(" env ")[-1] if " env " in head else re.sub(r"^.*?\brun\s+\S+\s+", "", head)
    head = re.sub(r"^\s*(\(|setsid nohup bash -c \"?|env )\s*", "", head)
    try:
        env = dict(t.split("=", 1) for t in shlex.split(head) if "=" in t and not t.startswith("-"))
        args = shlex.split(s.group(2).rstrip('"'))
    except ValueError:
        return None
    pipe = "venue_floor_kitonly.sh" if s.group(1) == "venue_floor_pipeline_v2.sh" else s.group(1)       # floors default to the cheap kit-only rerun, --full for a generator change
    rec = {"tag": tag, "pipeline": pipe, "args": args, "env": env}
    g = re.search(r"gt_round\.sh\s+\S+\s+r\d+\s+\S+\s+(\d)", line)
    rec["gpu"] = int(g.group(1)) if g else int(env.get("RENDER_GPU", 1))
    b = re.search(r"\./bg_render\.sh\s+(\S+)\s+(\S+)\s+\d\s+(\S+)", line)
    if b:
        rec["post"] = [["./bg_render.sh", b.group(1), b.group(2), "{gpu}", b.group(3)]]
    return tag, rnd, rec


def do_import(a):
    best = {}
    for f in sorted(glob.glob(str(O / "round*.sh")) + glob.glob(str(O / "loop_*.sh"))):
        for line in open(f, errors="ignore"):
            p = parse_line(line)
            if p and (p[0] not in best or p[1] >= best[p[0]][0]):
                best[p[0]] = (p[1], p[2])
    reviewed = {re.sub(r"_r\d+$", "", Path(q).name) for q in glob.glob(str(REPO / "out/vlm_review/*_r*"))}
    best = {t: v for t, v in best.items() if t in reviewed}       # old probe tags with no VLM review are not scenes of the set
    ids = {}      # tag -> scene id: floors and the extra singles from build_data.py, the other singles from the review page data (desc starts with the tag)
    if a.ids:
        for f in json.load(open(a.ids)):
            if f["id"].startswith("S"):
                ids[f["desc"].split(" · ")[0]] = f["id"]
        for sid, tag in re.findall(r'\("(\w+)", "(\w+)", "r\d+"', (Path(a.ids).parent / "build_data.py").read_text()):
            ids[tag] = sid
    old = json.loads(REG.read_text()) if REG.exists() else {}
    out = {}
    for tag, (rnd, rec) in sorted(best.items()):
        rec["round"] = max([rnd] + [int(re.search(r"_r(\d+)$", q).group(1)) for q in glob.glob(str(REPO / f"out/vlm_review/{tag}_r*"))])      # rounds before numbering: the newest reviewed one
        sid = ids.get(tag) or next((k for k, v in old.items() if v["tag"] == tag), tag)
        out[sid] = old[sid] if sid in old and old[sid]["round"] >= rnd else rec
    REG.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{len(out)} recipes -> {REG}")


def reg():
    return json.loads(REG.read_text())


def save(R, only=None):
    """Write the registry. With only=ID, re-read the file under a lock and replace just that recipe: two `run`s launched seconds
    apart each loaded the whole file and wrote their stale copy back, losing the other's round (10-22: I, N2, S29F)."""
    import fcntl
    with open(REG.with_suffix(".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if only is not None:
            cur = reg(); cur[only] = R[only]; R = cur
        tmp = REG.with_suffix(f".tmp{os.getpid()}"); tmp.write_text(json.dumps(R, indent=1, ensure_ascii=False)); os.replace(tmp, REG)


def holder(tag):
    """True if a round of this tag is running (its lock is held)."""
    LOCKS.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCKS / f"{tag}.lock", os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def legacy_busy(tag):
    """A round started outside the runner (old round scripts) holds no lock: its newest venue_*.out has no GT_DONE in the matching gt_run file yet and is under 3 h old."""
    outs = sorted(O.glob(f"venue_{tag}_r*.out"), key=lambda p: p.stat().st_mtime)
    if not outs:
        return False
    n = re.search(r"_r(\d+)\.out$", outs[-1].name).group(1); gt = O / f"gt_run_{tag}_r{n}.out"
    sf = STATE / f"{tag}_r{n}.json"
    if sf.is_file():                  # a runner round: busy only while its lock is held (stage "done" = ended, also failed; a killed round never writes "done")
        if not holder(tag):
            return False
        try:
            return json.loads(sf.read_text()).get("stage") != "done"
        except ValueError:            # the holder is rewriting its state file right now (S38 r21 crashed on this empty read, 10-25 16:12): treat as busy
            return True
    return time.time() - outs[-1].stat().st_mtime < 3 * 3600 and not (gt.exists() and "GT_DONE" in gt.read_text())


def running():
    held = {p.stem for p in LOCKS.glob("*.lock") if p.stem != "_slots" and holder(p.stem)}
    return sorted(held | {r["tag"] for r in reg().values() if legacy_busy(r["tag"])})


def codes(tag, rnd):
    by = {}
    for f in sorted((REPO / "out/vlm_review" / f"{tag}_r{rnd}").glob("*.json")):
        for x in json.loads(f.read_text()).get("defects", []):
            if x["severity"] == "major":
                by.setdefault(x["code"], []).append(f.stem)
    return by


def status(_):
    done = {}
    for p in glob.glob(str(Path("/tmp/claude-0/-jarvis-project-robomituba") / "*/scratchpad/review/completed.json")):
        done.update(json.load(open(p)))
    run = set(running())
    for sid, r in sorted(reg().items(), key=lambda kv: (kv[0][0], int(re.sub(r"\D", "", kv[0]) or 0))):
        by = codes(r["tag"], r["round"])
        sf = STATE / f"{r['tag']}_r{r['round']}.json"
        failed = sf.is_file() and json.loads(sf.read_text()).get("rc") not in (None, 0)
        flag = "RUN" if r["tag"] in run else ("FAIL" if failed else ("DONE" if sid in done else ""))
        print(f"{sid:5} {r['tag']:24} r{r['round']:<3} major={sum(map(len, by.values())):<3} {flag:4} " + " ".join(f"{c}x{len(v)}" for c, v in sorted(by.items(), key=lambda kv: -len(kv[1]))))


def ps(_):
    print("\n".join(running()) or "nothing running")


def suggest(a):
    r = reg()[a.id]; now, prev = codes(r["tag"], r["round"]), codes(r["tag"], r["round"] - 1)
    ver = lambda n: next(iter(sorted((REPO / "out/vlm_review" / f"{r['tag']}_r{n}").glob("*.json"))), None) and json.loads(next(iter(sorted((REPO / "out/vlm_review" / f"{r['tag']}_r{n}").glob("*.json")))).read_text()).get("prompt_version")
    if ver(r["round"]) != ver(r["round"] - 1):
        print(f"warning: r{r['round'] - 1} was reviewed with {ver(r['round'] - 1)}, r{r['round']} with {ver(r['round'])}; code sets are not comparable, re-review the old round first")
    for c in sorted(set(now) & set(prev)):
        todo = {k: v for k, v in FIX.get(c, {}).items() if r["env"].get(k) != v}
        print(f"{c}: in r{r['round'] - 1} and r{r['round']} ({len(now[c])} rooms) -> " + (" ".join(f"--add {k}={v}" for k, v in todo.items()) if todo else "flags already set or no late flag: ticket for the generator owner"))
    for c in sorted(set(now) - set(prev)):
        print(f"{c}: new in r{r['round']} only (one sighting, not acted on)")


def review(a):
    r = reg()[a.id]; rnd = a.round or r["round"]
    cmd = [sys.executable, str(REPO / "tools/infinigen/vlm_review_batch.py"), r["tag"], f"r{rnd}", "--votes", str(a.votes)]
    sys.exit(subprocess.run(cmd).returncode)


def stages(r, rnd, full):
    """argv lists of one round, in order. Floors rerun kit-only unless --full."""
    pipe = r["pipeline"]
    if full and pipe == "venue_floor_kitonly.sh":
        pipe = "venue_floor_pipeline_v2.sh"
    if r.get("rooms"):                                   # per-room regeneration: only these rooms are re-realized (venue_floor_rooms.sh, env ROOM_ONLY)
        pipe = "venue_floor_rooms.sh"
    gpu = str(r["gpu"]); seed = next(x for x in r["args"] if x.isdigit())
    out = [(["./" + pipe, *r["args"]], f"venue_{r['tag']}_r{rnd}.out")]
    for p in r.get("post", []):
        out.append(([x.replace("{gpu}", gpu) for x in p], f"bg_{r['tag']}_r{rnd}.out"))
    out.append((["bash", "gt_round.sh", r["tag"], f"r{rnd}", seed, gpu], f"gt_run_{r['tag']}_r{rnd}.out"))
    return out


def restore_pre_kit(r):
    """kit-only reruns start from the blend saved before the kit-lighting stage (scene_mat2_activity.blend1); atomic replace, never an in-place truncate."""
    seed, gen, tag = r["args"][:3]
    F = REPO / f"out/infinigen_v2/kr_{tag}_{seed}/full"; src, dst = F / "scene_mat2_activity.blend1", F / "scene_mat2_activity.blend"
    tmp = F / "scene_mat2_activity.blend.restore"
    subprocess.run(["cp", "-p", str(src), str(tmp)], check=True); os.replace(tmp, dst)


def snapshot_round(r, rnd, keep=4):
    """Keep each finished round's blend as full/rounds/r<N>.blend, a hard link: zero extra space until the next round's save
    (Blender writes a temp file and renames it over the original) replaces scene_mat2_activity.blend. The user promotes a
    round they looked at; O2 r15 was lost on 10-23 because r16/r17 overwrote it. Only the newest `keep` snapshots stay."""
    try:
        seed = next(x for x in r["args"] if x.isdigit())
        F = REPO / f"out/infinigen_v2/kr_{r['tag']}_{seed}/full"; src = F / "scene_mat2_activity.blend"
        if not src.is_file():
            return
        d = F / "rounds"; d.mkdir(exist_ok=True); dst = d / f"r{rnd}.blend"
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
        old = sorted(d.glob("r*.blend"), key=lambda p: int(p.stem[1:]))[:-keep]
        for p in old:
            p.unlink()
    except Exception as e:                              # a snapshot must never fail the round
        print("snapshot_round:", e, file=sys.stderr)


def execute(a):
    """Detached child: waits for a slot (--queue), holds the scene lock for the whole round, runs the stages, writes out/scene_loop/<tag>_rN.json."""
    r = json.loads(a.recipe); rnd = a.round; tag = r["tag"]; LOCKS.mkdir(parents=True, exist_ok=True)
    g = os.open(LOCKS / "_slots.lock", os.O_CREAT | os.O_RDWR); lk = None
    while lk is None:
        fcntl.flock(g, fcntl.LOCK_EX)
        cap = int((LOCKS / "_max").read_text()) if (LOCKS / "_max").exists() else MAX   # live cap: echo N > out/scene_loop/locks/_max (user 10-25 'slot expand')
        if len(running()) < cap:
            fd = os.open(LOCKS / f"{tag}.lock", os.O_CREAT | os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); lk = fd
            except BlockingIOError:
                sys.exit(f"{tag} already running")
        fcntl.flock(g, fcntl.LOCK_UN)
        if lk is None:
            time.sleep(30)
    st = STATE / f"{tag}_r{rnd}.json"; info = {"tag": tag, "round": rnd, "start": time.strftime("%FT%T"), "stage": "start", "rc": None}
    env = {**os.environ, **r["env"], "RENDER_GPU": str(r["gpu"])}
    if r.get("rooms"):
        env["ROOM_ONLY"] = r["rooms"]
    env.setdefault("ROOM_PLANNER_REVISE_MODEL", "claude-haiku-5-5")      # the planner's revision step: Haiku 5.5, not the 4.5 default in room_planner/client.py (user 2026-10-20)
    if a.no_review or a.peer_review:
        env["VLM_REVIEW"] = "0"                      # gt_round.sh: no automatic API review
    try:
        if r["pipeline"] == "venue_floor_kitonly.sh" and not a.full:
            restore_pre_kit(r)
        for argv, outname in stages(r, rnd, a.full):
            info["stage"] = " ".join(argv[:2]); st.write_text(json.dumps(info))
            with open(O / outname, "w") as fh:
                rc = subprocess.run(argv, cwd=O, env=env, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT).returncode
            if rc and argv[0].startswith("./venue_"):      # a failed pipeline has nothing to render; post/GT stages tolerate a nonzero like the old `;` chains
                info["rc"] = rc; break
        else:
            info["rc"] = 0
            snapshot_round(r, rnd)
            if a.peer_review:                        # queue the round for the peer reviewer (vlm_peer.py); ingest happens when its result files exist
                subprocess.run([sys.executable, str(REPO / "tools/infinigen/vlm_peer.py"), "pack", tag, f"r{rnd}"], stdout=open(STATE / f"{tag}_r{rnd}.log", "a"), stderr=subprocess.STDOUT)
    finally:
        info["stage"] = "done"; info["end"] = time.strftime("%FT%T"); st.write_text(json.dumps(info))


def run(a):
    R = reg(); r = R[a.id]; add = dict(kv.split("=", 1) for kv in a.add)
    env = {k: v for k, v in {**r["env"], **add}.items() if k not in a.rm}
    rnd = max([r["round"]] + [int(m.group(1)) for p in glob.glob(str(REPO / f"out/vlm_review/{r['tag']}_r*")) + glob.glob(str(STATE / f"{r['tag']}_r*.json"))
                              if (m := re.search(r"_r(\d+)(?:\.json)?$", p))]) + 1      # STATE records too: a recipe counter that went back (10-22: I, N2, S29F) must not reuse a round
    new = {**r, "env": env, "round": rnd, "added": add}
    if a.rooms:
        if not r["pipeline"].startswith("venue_floor_") or a.full:
            sys.exit(f"{a.id}: --rooms needs a multi-room floor recipe and no --full")
        new["rooms"] = a.rooms                           # only in this round's child recipe, never saved: a later full round must not inherit ROOM_ONLY
    if a.dry:
        for argv, outname in stages(new, rnd, a.full):
            print(shlex.join(argv), ">", outname)
        print("env diff:", {k: v for k, v in env.items() if r["env"].get(k) != v}, "removed:", a.rm)
        return
    if holder(r["tag"]) or (legacy_busy(r["tag"]) and not a.force):
        sys.exit(f"{a.id}: a round of {r['tag']} is already running (--force if the old one is dead)")
    if len(running()) >= MAX and not a.queue:
        sys.exit(f"{len(running())} rounds running (cap {MAX}); use --queue to wait for a slot")
    STATE.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, __file__, "_exec", json.dumps(new), str(rnd)] + (["--full"] if a.full else []) + (["--no-review"] if a.no_review else []) + (["--peer-review"] if a.peer_review else [])
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=open(STATE / f"{r['tag']}_r{rnd}.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
    R[a.id] = {k: v for k, v in new.items() if k != "rooms"}; save(R, only=a.id)
    print(f"{a.id}: r{rnd} started (GPU {r['gpu']}); log out/scene_loop/{r['tag']}_r{rnd}.log; added {add or '-'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("import"); p.add_argument("--ids"); p.set_defaults(f=do_import)
    sp.add_parser("status").set_defaults(f=status); sp.add_parser("ps").set_defaults(f=ps)
    p = sp.add_parser("review"); p.add_argument("id"); p.add_argument("--round", type=int); p.add_argument("--votes", type=int, default=3); p.set_defaults(f=review)
    p = sp.add_parser("suggest"); p.add_argument("id"); p.set_defaults(f=suggest)
    p = sp.add_parser("run"); p.add_argument("id"); p.add_argument("--add", action="append", default=[]); p.add_argument("--rm", action="append", default=[])
    p.add_argument("--full", action="store_true"); p.add_argument("--rooms", help="floors: re-realize only these room ids (comma list, as in plans.json); needs a previous full round"); p.add_argument("--queue", action="store_true"); p.add_argument("--dry", action="store_true"); p.add_argument("--force", action="store_true"); p.add_argument("--no-review", action="store_true"); p.add_argument("--peer-review", action="store_true", help="no API review; pack the round into out/vlm_queue for the peer reviewer"); p.set_defaults(f=run)
    p = sp.add_parser("_exec"); p.add_argument("recipe"); p.add_argument("round", type=int); p.add_argument("--full", action="store_true"); p.add_argument("--no-review", action="store_true"); p.add_argument("--peer-review", action="store_true"); p.set_defaults(f=execute)
    a = ap.parse_args(); a.f(a)
