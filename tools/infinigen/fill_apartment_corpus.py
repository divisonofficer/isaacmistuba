#!/usr/bin/env python3
"""Keep Infinigen apartment generation going until N new scene.blend exist.

Stateless on purpose: it decides from the process table and the output folders,
never from its own memory, so it can be killed and restarted at any time and
picks up whatever is already running. An earlier driver held its attempts in
memory; killing it (to lift its timeout) orphaned four generators it then could
not count.

What the numbers behind the design are (apartment_natural_v1, normal_lived_in,
default room scale, measured 2026-10-01..03 on this 64-core host):
  * one finished scene took ~26.6 h of generator time at load ~100
    (solve_large 308 min, solve_medium 339, solve_small 605, populate 297);
  * four attempts under a 12 h timeout all died at exactly 720 min with no
    blend, while the one run without a timeout finished -- so NO wall-clock cap.
    A stuck process is caught by its log going quiet instead;
  * 1 of 5 attempts segfaulted at 53 min (rc 139), so a failed seed is replaced.

A generation slot is a live wizard. The wizard is started with --no-import and
the import is a separate, much lighter step run here:
  * the wizard's own import defaults to profile strict-pbr-v1, which bakes every
    unit (~2.2 h for 436 units) and then fails the whole import if one object's
    bake does not satisfy its gate. The IR pipeline never uses that profile: its
    controller imports with ir-bootstrap-v1 (no bake; ~1 s per unit), because the
    real GT bake is the later `geometry` stage and reads only the import's scene
    sidecars, not its baked textures.
  * a wizard that still runs the old strict import (started before this change)
    has that import killed and replaced by a bootstrap one.

Everything runs under nice 10: this host is shared and its other work has
deadlines.
"""
import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUTS = REPO / "data/infinigen_generated/outputs"
SCENES = REPO / "out/opticalnav/opticalnav-v0.2/scenes"
IMPORTS = REPO / "out/infinigen_imports"
SUFFIX = "_apartment_natural_v1_collision_aware_clutter_v1"
# Scenes of this campaign only; the nine already rendered date from September.
CAMPAIGN_START = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
IMPORT_PROFILE = "ir-bootstrap-v1"


def _argv(pid: str):
    try:
        return [a.decode("utf8", "replace")
                for a in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if a]
    except OSError:
        return []


def _seed_in(args: list[str]) -> str | None:
    for x in args:
        if f"/kr_" in x and SUFFIX in x:
            return x.split("/kr_", 1)[1].split("_", 1)[0]
    return None


def live_wizards() -> dict[str, int]:
    """seed -> pid of every running apartment wizard of this corpus.

    argv[0] must be the interpreter: a substring match over a re-joined command
    line also matches the shell and the tool doing the looking.
    """
    found = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        a = _argv(pid)
        if (a and os.path.basename(a[0]).startswith("python")
                and any(os.path.basename(x) == "infinigen_wizard.py" for x in a[1:3])
                and "--archetype" in a and a[a.index("--archetype") + 1] == "apartment"
                and "--seed" in a):
            found[a[a.index("--seed") + 1]] = int(pid)
    return found


def live_imports() -> dict[str, tuple[int, bool]]:
    """seed -> (pid, is_bootstrap) of every running import of this corpus."""
    found = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        a = _argv(pid)
        if not (a and os.path.basename(a[0]) == "bash"
                and any(os.path.basename(x) == "run_infinigen_import.sh" for x in a[1:3])):
            continue
        seed = _seed_in(a)
        if seed:
            boot = "--stage1-profile" in a and a[a.index("--stage1-profile") + 1] == IMPORT_PROFILE
            found[seed] = (int(pid), boot)
    return found


def has_blend(seed: str) -> bool:
    d = OUTPUTS / f"kr_{seed}{SUFFIX}" / "full"
    try:
        return ((d / "scene.blend").stat().st_size > 0
                and (d / "kr_preset.json").stat().st_mtime >= CAMPAIGN_START)
    except OSError:
        return False


def scene_id(seed: str) -> str:
    return f"infinigen_apartment_natural_v1_{seed}"


def has_scene(seed: str) -> bool:
    """The import published its scene (Stage 2 wrote the authoring map)."""
    return (SCENES / scene_id(seed) / "authoring_map.json").is_file()


def scene_ready(seed: str) -> bool:
    """Everything the GT bake's front end reads from the scene is present.

    The import writes four of the five sidecars; material_canonical.json comes
    from the controller's separate material_extract + material_canonicalize
    stages (a second each, CPU only), without which source_scene_digest raises
    FileNotFoundError before any bake starts.
    """
    return has_scene(seed) and (SCENES / scene_id(seed) / "material_canonical.json").is_file()


def materials(seed: str, logs: Path) -> bool:
    """Run the two material stages for an imported scene; True when both pass."""
    scene = str(SCENES / scene_id(seed))
    with open(logs / f"{seed}.material.log", "a") as log:
        for step in ("extract", "canonicalize"):
            rc = subprocess.run(["nice", "-n", "10", sys.executable, "apps/material_pipeline.py", step,
                                 "--scene", scene], cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode
            if rc != 0:
                return False
    return True


def done_seeds() -> list[str]:
    return sorted(p.name[3:-len(SUFFIX)] for p in OUTPUTS.glob(f"kr_*{SUFFIX}")
                  if has_blend(p.name[3:-len(SUFFIX)]))


def kill_tree(pid: int) -> None:
    """SIGTERM then SIGKILL a process and everything under it.

    The import's bpy children inherit its lock file descriptor, so the lock is
    only released when the whole tree is gone.
    """
    kids: dict[int, list[int]] = {}
    for d in filter(str.isdigit, os.listdir("/proc")):
        try:
            ppid = int(Path(f"/proc/{d}/stat").read_text().rsplit(") ", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        kids.setdefault(ppid, []).append(int(d))
    tree, stack = [], [pid]
    while stack:
        p = stack.pop()
        tree.append(p)
        stack += kids.get(p, [])
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in reversed(tree):
            try:
                os.kill(p, sig)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(5)


def launch(seed: str, logs: Path) -> subprocess.Popen:
    cmd = ["nice", "-n", "10", sys.executable, "scripts/infinigen_wizard.py",
           "--archetype", "apartment", "--density", "normal_lived_in",
           "--placement-profile", "collision_aware_clutter_v1",
           "--room-scale", "default", "--stage", "full",
           "--seed", seed, "--no-import", "--yes"]
    log = open(logs / f"{seed}.log", "w")
    log.write("$ " + " ".join(cmd) + "\n")
    log.flush()
    # Its own session: the generator outlives this driver, and a stall kill can
    # take the whole group (the wizard spawns the generator, which spawns more).
    return subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)


def launch_import(seed: str, logs: Path) -> subprocess.Popen:
    full = OUTPUTS / f"kr_{seed}{SUFFIX}" / "full"
    # The IR controller's own import command (controller.py, stage "import").
    cmd = ["nice", "-n", "10", "bash", "apps/run_infinigen_import.sh", str(full),
           "--scene-id", scene_id(seed), "--stage1-profile", IMPORT_PROFILE,
           "--filter-small-high-poly", "--small-high-poly-max-extent-m", "0.5",
           "--small-high-poly-min-triangles", "100000"]
    log = open(logs / f"{seed}.import.log", "a")
    log.write("$ " + " ".join(cmd) + "\n")
    log.flush()
    return subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=50)
    ap.add_argument("--slots", type=int, default=4, help="concurrent generations")
    ap.add_argument("--import-slots", type=int, default=2, help="concurrent bootstrap imports")
    ap.add_argument("--import-attempts", type=int, default=2)
    ap.add_argument("--stall-s", type=int, default=3600,
                    help="kill a stream whose log has been silent this long")
    ap.add_argument("--max-attempts", type=int, default=200)
    ap.add_argument("--logs", type=Path, default=REPO / "out/ir_apartment_fill")
    ap.add_argument("--dry", action="store_true", help="report what it would do, launch nothing")
    args = ap.parse_args()
    args.logs.mkdir(parents=True, exist_ok=True)
    mine: dict[str, subprocess.Popen] = {}
    mine_imports: dict[str, subprocess.Popen] = {}
    import_tries: dict[str, int] = {}
    attempts = 0
    rng = random.SystemRandom()
    while True:
        wizards, done, imports = live_wizards(), done_seeds(), live_imports()
        generating = [s for s in wizards if not has_blend(s)]

        # A wizard started before the switch runs the strict (baking) import the
        # moment generation ends. Replace it: that import is ~2 h of baking the
        # pipeline never reads, and one unbakeable object fails all of it.
        for seed, (pid, boot) in imports.items():
            if not boot and has_blend(seed) and not has_scene(seed):
                print(json.dumps({"strict_import_replaced": seed}), flush=True)
                if not args.dry:
                    kill_tree(pid)
                    for stale in IMPORTS.glob(f"kr_{seed}*.strict-pbr-v1.staging.*"):
                        subprocess.run(["rm", "-rf", str(stale)], check=False)

        for seed, proc in list(mine.items()):          # reap, and record how each ended
            if proc.poll() is not None:
                (args.logs / f"{seed}.status.json").write_text(json.dumps(
                    {"seed": seed, "rc": proc.returncode, "blend": has_blend(seed)}) + "\n")
                del mine[seed]
        for seed, proc in list(mine_imports.items()):
            if proc.poll() is not None:
                (args.logs / f"{seed}.import.status.json").write_text(json.dumps(
                    {"seed": seed, "rc": proc.returncode, "scene": has_scene(seed), "ready": scene_ready(seed),
                     "tries": import_tries.get(seed, 0)}) + "\n")
                del mine_imports[seed]
        for seed, proc in mine.items():                # stall watchdog, not a wall clock
            log = args.logs / f"{seed}.log"
            if log.exists() and time.time() - log.stat().st_mtime > args.stall_s:
                print(json.dumps({"stalled_killed": seed}), flush=True)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        # Imports: a finished blend with no OpticalNav scene yet and no importer
        # running on it. A wizard still alive for the seed has not finished (it is
        # either generating or about to exit), so wait for it.
        pending = [s for s in done if not scene_ready(s)]
        started_imports = []
        for seed in pending:
            if has_scene(seed):
                # Imported already; only the material sidecar is missing.
                if seed not in imports and not args.dry:
                    print(json.dumps({"materials": seed, "ok": materials(seed, args.logs)}), flush=True)
                continue
            if (seed in imports or seed in wizards
                    or import_tries.get(seed, 0) >= args.import_attempts
                    or len(imports) + len(started_imports) >= args.import_slots):
                continue
            started_imports.append(seed)
            import_tries[seed] = import_tries.get(seed, 0) + 1
            if not args.dry:
                mine_imports[seed] = launch_import(seed, args.logs)

        launched = []
        while (len(wizards) + len(launched) < args.slots
               and len(done) + len(generating) + len(launched) < args.target
               and attempts < args.max_attempts):
            seed = str(rng.randrange(10_000_000, 99_999_999))
            if (OUTPUTS / f"kr_{seed}{SUFFIX}").exists():
                continue
            launched.append(seed)
            attempts += 1
            if not args.dry:
                mine[seed] = launch(seed, args.logs)
        print(json.dumps({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "done": len(done), "generating": len(generating),
                          "wizards": len(wizards), "launched": launched,
                          "imported": len(done) - len(pending), "importing": sorted(imports),
                          "import_started": started_imports,
                          "target": args.target, "attempts": attempts}), flush=True)
        unfinished_imports = [s for s in pending if has_scene(s) or import_tries.get(s, 0) < args.import_attempts]
        if args.dry or (len(done) >= args.target and not generating
                        and not imports and not unfinished_imports):
            return 0
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
