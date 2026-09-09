#!/usr/bin/env python3
"""Generate and render a batch of ABO Cornell-box scenes, one scene per GPU.

Each seed is an independent four-stage chain, and every stage is skipped when
its output already exists, so an interrupted run continues rather than
restarts:

    build_abo_cornell_scene.py   -> scene_manifest.json + stage/cornell_box.glb
    blender_build_scene.py       -> source.blend
    blender_prepare_hssd_ir.py   -> ir_scene.blend
    blender_render_hssd_ir_sample.py --dataset -> render/

Claiming follows `tools/run_tod_render_queue.sh`: a worker owns one GPU and one
scene start to finish, and claims are atomic directory creations so two workers
cannot take the same seed.  Stale claims -- a scene whose worker died -- are
released at startup, which is safe because nothing is rendering yet then.

Camera and quality match the v2 dataset, so an ABO frame differs from an HSSD
v2 frame by scene content alone: 720x540 at hFOV 44.98 deg (JAI FS-1600 behind
a 6 mm lens), 512 spp RGB and 1536 NIR.

Pose count does not match v2, and cannot.  A Cornell box holds around nine
objects where an HSSD scene holds hundreds, and `_object_closeup_poses` samples
a bounded ring per object, so asking for v2's 50 raises rather than returning
what it found.  The request is therefore trimmed per scene to what that box can
supply, and the frame count follows from it: the baseline lighting variant for
every pose, plus the other five for the important ones.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "hssd_blender_ir" / "src"))

from hssd_blender_ir.box_lighting import PROFILE as BOX_LIGHTING_PROFILE  # noqa: E402

#: Kept in step with `build_abo_cornell_scene.COMPOSER_VERSION`; a scene whose
#: manifest declares a different one was built by different code.
COMPOSER_VERSION = "abo-cornell-v3"
COMPOSER = REPO_ROOT / "apps" / "build_abo_cornell_scene.py"
BLENDER_LAUNCHER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
#: Blender exits 0 even when the script it was handed raises, so a crashed
#: stage looks exactly like a finished one -- four scenes "succeeded" in five
#: seconds here with no frames on disk before this was added. The flag must
#: come BEFORE --python; after it, Blender still exits 0.
BLENDER_PREAMBLE = ["--background", "--python-exit-code", "1"]
HSSD_TOOLS = REPO_ROOT / "modules" / "hssd_blender_ir" / "tools"
BUILD_SCENE = HSSD_TOOLS / "blender_build_scene.py"
PREPARE = HSSD_TOOLS / "blender_prepare_hssd_ir.py"
RENDER = HSSD_TOOLS / "blender_render_hssd_ir_sample.py"

#: Matches `run_v2_render_queue.sh` / `run_tod_dataset_queue.sh`, so a frame
#: from this dataset differs from an HSSD v2 frame by scene content alone.
DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_HFOV = 720, 540, 44.98
DEFAULT_SPP, DEFAULT_NIR_SPP, DEFAULT_BOUNCES = 512, 1536, 8
#: box_lighting supplies six variants; only the baseline is rendered for every
#: pose, the rest for the important ones.
VARIANT_COUNT = 6
DEFAULT_POSE_COUNT, DEFAULT_IMPORTANT_COUNT = 36, 8
#: `_object_closeup_poses` samples a ring per interior asset and caps it at
#: `_CLOSEUP_MAX_POSES_PER_TARGET`, then *raises* rather than returning fewer.
#: So a scene cannot supply more than this many poses per object it holds, and
#: asking for the HSSD queue's 50 in a nine-object box fails the whole render
#: with "could only select 21/50". Mirrored here so the request is trimmed to
#: what the composed scene can actually give.
MAX_POSES_PER_TARGET = 3
#: The pose gates reject part of every ring (an occluder against the lens, one
#: material filling the frame), and the rejected share is scene-dependent: one
#: box lost 25%, the next 48%. Rather than tune a constant that is wrong for
#: half the catalogue, this is only the opening bid -- `_ACHIEVABLE` reads the
#: count the sampler actually reached out of its own error and retries there.
POSE_GATE_YIELD = 0.6
#: "could only select 14/20 object_closeup poses"
_ACHIEVABLE = re.compile(r"could only select (\d+)/(\d+) object_closeup poses")

_print_lock = threading.Lock()
#: Live child process groups, so an interrupted queue does not leave Blender
#: rendering unattended. Observed the hard way: killing the launcher left an
#: orphaned Blender holding a GPU and writing frames nobody was tracking, which
#: on a contended box is somebody else's slowdown with no visible owner.
_children: set[int] = set()
_children_lock = threading.Lock()


def _reap(signum=None, frame=None) -> None:
    """Stop every child process group we started, then exit.

    A cancel that signals only the top of the tree leaves the real work
    running -- the queue looks stopped while a Blender per GPU carries on.
    """
    with _children_lock:
        pids = sorted(_children)
    for pid in pids:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    if signum is not None:
        log(f"received signal {signum}; terminated {len(pids)} render process group(s)")
        raise SystemExit(128 + int(signum))


def log(message: str) -> None:
    with _print_lock:
        print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def _run(command: list[str], *, log_path: Path, env: dict[str, str] | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n$ {' '.join(command)}\n")
        handle.flush()
        # Own process group: Blender ignores a plain terminate often enough
        # that signalling the group is the only reliable way to stop it.
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                   env={**os.environ, **(env or {})}, cwd=str(REPO_ROOT),
                                   start_new_session=True)
        with _children_lock:
            _children.add(process.pid)
        try:
            return process.wait()
        finally:
            with _children_lock:
                _children.discard(process.pid)


def _rendered_frames(scene_dir: Path) -> int:
    return len([d for d in (scene_dir / "render").glob("shard_*/*") if d.is_dir()])


def scene_intact(scene_dir: Path) -> tuple[bool, str]:
    """Do this scene's manifest paths still resolve?

    Frame count answers "did the render finish". It does not answer "is the
    scene still buildable", and since the bundles moved into a shared
    `_asset_cache` those are different questions with the same evidence: delete
    the cache and every rendered frame is still on disk, so every scene reads
    complete, and a rerun of this queue would find nothing to do and exit 0
    while the whole corpus had stopped resolving.

    That is the shape a peer hit from the other side -- a work list scoped from
    an artefact another process later deleted, which did not fail but silently
    emptied, because doing nothing and succeeding look identical from outside.
    Worth stating plainly about the cache: its name promises it is disposable
    and it is not. It is regenerable, but only by recomposing every scene that
    points into it.
    """
    manifest = scene_dir / "scene_manifest.json"
    if not manifest.is_file():
        return False, "no scene_manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError as error:
        return False, f"unparseable manifest ({error})"
    stage = (payload.get("stage") or {}).get("bundle")
    if not stage or not Path(stage).is_file():
        return False, "stage bundle missing"
    missing = [i["source_id"] for i in payload.get("instances") or []
               if not Path(i.get("bundle", "")).is_file()]
    if missing:
        return False, f"{len(missing)} instance bundles missing (e.g. {missing[:3]})"
    return True, ""


def scene_done(scene_dir: Path, expected_frames: int | None = None) -> bool:
    """A scene counts as finished only once its own planned frame count is met.

    The render manifest alone is not enough: it is rewritten after every shard,
    so it exists long before the scene is complete. The plan is per-scene --
    pose count is capped by how many objects that box holds -- so the target is
    read back from the manifest the renderer wrote rather than assumed.
    """
    manifest = scene_dir / "render" / "manifest.json"
    if not manifest.is_file():
        return False
    if expected_frames is None:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            expected_frames = (int(payload["pose_count"])
                               + int(payload["important_count"]) * (VARIANT_COUNT - 1))
        except (ValueError, KeyError):
            return False
    return _rendered_frames(scene_dir) >= expected_frames


#: The cross-session allocation every job on this box writes to. This work
#: root's own lock narrows further within it; this one says which devices are
#: this session's to use at all.
MACHINE_POOL_LOCK = Path("/bean/ir_dataset_work/gpu_pool.lock.json")


def machine_pool(path: Path, holder: str) -> set[int] | None:
    """GPUs the machine-wide lock assigns to `holder`, or None if it cannot say.

    There were three files named gpu_pool.lock.json on this box with different
    schemas -- one per work root plus this one -- and no job read any but its
    own. Every "I have updated the lock" was true and invisible to everybody
    else, so the actual coordination was carried by the conversation between
    sessions while each of us believed a file was doing it. It never caused a
    collision, which is the part that should worry anyone: an unread file and a
    working protocol are indistinguishable right up until the conversation stops.

    Returns None rather than an empty set when the file is missing, unreadable
    or has no row for `holder`. Narrowing to nothing on a schema this code does
    not recognise would let another job's format change silently halt this one,
    which is a worse failure than the overlap it would prevent -- the lock is
    advisory and a human is always in the loop. It logs loudly instead.
    """
    if not path.is_file():
        log(f"machine pool lock {path} absent; not narrowing")
        return None
    try:
        holders = json.loads(path.read_text(encoding="utf-8"))["all_holders"]
        return {int(value) for value in holders[holder]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        log(f"machine pool lock {path} unusable for holder {holder!r} ({error}); not narrowing")
        return None


def eligible_gpus(requested: list[int], lock_path: Path) -> list[int]:
    """Narrow a GPU request to the pool this work root is allowed to use.

    `--gpus` is an argument, so the split between the jobs sharing this machine
    is held by whoever types the relaunch correctly -- and a relaunch that
    forgets it silently reverts to the default and leases into someone else's
    devices. This makes the pool a property of the work root instead.

    It can only ever narrow. An explicit request for fewer devices still wins,
    and the file cannot be used to claim more than was asked for, so a stale
    lock file cannot widen anyone's footprint.
    """
    if not lock_path.is_file():
        return requested
    try:
        allowed = {int(v) for v in json.loads(lock_path.read_text(encoding="utf-8"))["gpu_indices"]}
    except (ValueError, KeyError, TypeError):
        log(f"{lock_path} is unreadable; using --gpus as given")
        return requested
    narrowed = [g for g in requested if g in allowed]
    if narrowed != requested:
        log(f"gpu pool lock narrows {requested} to {narrowed} ({lock_path})")
    return narrowed


def gpu_claimants(gpu: int, *, exclude: set[int] | None = None) -> list[tuple[int, str]]:
    """Every live process bound to this GPU, whoever started it.

    Not `nvidia-smi --query-compute-apps`. That lists processes holding a CUDA
    *context*, which is a narrower thing than holding the device: a Blender bake
    binds its GPU for the whole run but only creates a context once it reaches
    the Cycles step, so during its CPU phases it is absent from that query while
    still fully intending to come back. Reading the count as "one app, so it is
    mine" put a render onto a device another job was mid-way through using --
    the query was accurate and the inference from it was wrong.

    It is also robust to the pid-namespace split: nvidia-smi reports host pids
    that match nothing in `ps` here, so a pid-to-owner comparison finds no owner
    for any process and reads exactly like an idle device. `environ` is on this
    side of that boundary.
    """
    exclude = exclude or set()
    needle = f"CUDA_VISIBLE_DEVICES={gpu}"
    found: list[tuple[int, str]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in exclude:
            continue
        try:
            # A process can exit between the listdir and either read; both files
            # vanish together, so one guard covers the race.
            if needle not in (entry / "environ").read_bytes().decode(
                    "utf-8", "replace").split("\0"):
                continue
            command = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
        except (OSError, ValueError):
            continue
        found.append((pid, command.replace("\0", " ").strip()[:100]))
    return sorted(found)


def _render_running_for(scene_dir: Path) -> bool:
    """Is a Blender still rendering this scene, whatever owns it?

    The claim records the *queue's* pid, which is not the same question. Kill a
    queue hard and its Blender survives in its own session -- observed here --
    so a restarted queue sees a dead owner, releases the claim and starts a
    second render writing the same frames as the first. The pid on the claim
    cannot see that; the render's own command line can.
    """
    try:
        listing = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True,
                                 timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False  # cannot tell; fall back to the pid check alone
    needle = str(scene_dir.resolve())
    return any(needle in line and "blender" in line.lower() for line in listing.splitlines())


def _claim_owner_alive(claim: Path) -> bool:
    """Is the process that took this claim still running?

    An unstamped claim predates this check and is treated as dead, which is the
    old behaviour and safe for a genuine restart.
    """
    try:
        pid = int((claim / "owner").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError) as error:
        return isinstance(error, PermissionError)  # exists but not ours to signal
    return True


def policy_of(args: argparse.Namespace) -> dict[str, str]:
    """What a scene composed under the current settings should declare."""
    return {"composer_version": COMPOSER_VERSION,
            "nir_model": "class_band_prior_v1" if args.nir_class_prior else "derived_pseudo_nir",
            "lighting_profile": BOX_LIGHTING_PROFILE}


def stale_reason(scene_dir: Path, args: argparse.Namespace) -> str | None:
    """Why an existing scene no longer matches the settings asked for.

    Every stage here resumes on the *existence* of its output, which answers
    "has this been built" and not "was it built the way I am asking for now".
    A composer change or a flip of --nir-class-prior would otherwise be
    invisible: the scene is present, so it is skipped, and the batch quietly
    mixes two policies. The manifest states what it was built under, so that
    is what gets compared.
    """
    manifest = scene_dir / "scene_manifest.json"
    if not manifest.is_file():
        return None
    try:
        declared = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return "scene_manifest.json is unreadable"
    for key, want in policy_of(args).items():
        got = declared.get(key)
        if got != want:
            return f"{key}={got!r} but this run wants {want!r}"
    return None


def build_one(seed: int, gpu: int, args: argparse.Namespace, expected_frames: int) -> bool:
    scene_id = f"{args.prefix}_{seed:04d}"
    scene_dir = args.out_root / scene_id
    logs = scene_dir / "queue.log"

    stale = stale_reason(scene_dir, args)
    if stale:
        if not args.rebuild_stale:
            # Rebuilding means discarding a source blend, a prepared blend and
            # any rendered frames, so it is opt-in rather than a side effect of
            # noticing.
            log(f"[gpu {gpu}] {scene_id} SKIPPED: {stale} (pass --rebuild-stale to redo it)")
            return False
        log(f"[gpu {gpu}] {scene_id} rebuilding: {stale}")
        for path in ("scene_manifest.json", "source.blend", "ir_scene.blend",
                     "object_selection.json", "abo_semantics.csv"):
            (scene_dir / path).unlink(missing_ok=True)
        shutil.rmtree(scene_dir / "render", ignore_errors=True)
        shutil.rmtree(scene_dir / "assets", ignore_errors=True)

    if not (scene_dir / "scene_manifest.json").is_file():
        log(f"[gpu {gpu}] {scene_id} compose")
        command = [sys.executable, str(COMPOSER), "--index", str(args.index),
                   "--out", str(scene_dir), "--scene-id", scene_id, "--seed", str(seed),
                   "--hosts", str(args.hosts), "--props", str(args.props),
                   "--luminaires", str(args.luminaires),
                   "--hfov-deg", str(args.hfov_deg), "--frame-width-px", str(args.width),
                   "--asset-cache", str(args.asset_cache or (args.out_root / "_asset_cache"))]
        if args.accent_walls:
            command.append("--accent-walls")
        if args.nir_class_prior:
            command.append("--nir-class-prior")
        if _run(command, log_path=logs) != 0:
            log(f"[gpu {gpu}] {scene_id} FAILED at compose")
            return False

    if not (scene_dir / "source.blend").is_file():
        log(f"[gpu {gpu}] {scene_id} build-blend")
        if _run([sys.executable, str(BLENDER_LAUNCHER), *BLENDER_PREAMBLE,
                 "--python", str(BUILD_SCENE), "--",
                 "--manifest", str(scene_dir / "scene_manifest.json"),
                 "--out-blend", str(scene_dir / "source.blend")], log_path=logs) != 0:
            log(f"[gpu {gpu}] {scene_id} FAILED at build-blend")
            return False

    if not (scene_dir / "ir_scene.blend").is_file():
        log(f"[gpu {gpu}] {scene_id} prepare")
        if _run([sys.executable, str(BLENDER_LAUNCHER), *BLENDER_PREAMBLE,
                 str(scene_dir / "source.blend"), "--python", str(PREPARE), "--",
                 "--source-blend", str(scene_dir / "source.blend"),
                 "--out-blend", str(scene_dir / "ir_scene.blend"),
                 "--manifest", str(scene_dir / "scene_manifest.json"),
                 "--hssd-semantics", str(scene_dir / "abo_semantics.csv")], log_path=logs) != 0:
            log(f"[gpu {gpu}] {scene_id} FAILED at prepare")
            return False

    # What this particular scene can supply, rather than what was asked for.
    targets = len(json.loads((scene_dir / "object_selection.json")
                             .read_text(encoding="utf-8"))["objects"])
    ceiling = int(targets * MAX_POSES_PER_TARGET * POSE_GATE_YIELD)
    pose_count = min(args.pose_count, max(1, ceiling))
    important = min(args.important_count, pose_count)
    if pose_count < args.pose_count:
        log(f"[gpu {gpu}] {scene_id} {targets} targets caps poses at {pose_count} "
            f"(asked {args.pose_count})")
    frames = pose_count + important * (VARIANT_COUNT - 1)
    log(f"[gpu {gpu}] {scene_id} render ({frames} frames, {pose_count} poses)")
    status = _render(scene_dir, gpu, args, pose_count, important, logs)
    if status != 0:
        log(f"[gpu {gpu}] {scene_id} FAILED at render (status {status}, see {logs})")
        return False
    return True


def _render(scene_dir: Path, gpu: int, args: argparse.Namespace,
            pose_count: int, important: int, logs: Path) -> int:
    """Render, retrying once at whatever pose count the sampler could reach.

    `_object_closeup_poses` raises rather than returning fewer poses than asked
    for, and the reachable number depends on how the gates fall in that
    particular box. The error names the count it got to, and pose selection is
    deterministic, so retrying at exactly that number succeeds.
    """
    for attempt in range(2):
        status = _render_once(scene_dir, gpu, args, pose_count, important, logs)
        if status == 0:
            return 0
        match = _ACHIEVABLE.search(logs.read_text(encoding="utf-8", errors="replace")[-4000:])
        if attempt or not match:
            return status
        reached = int(match.group(1))
        if reached < 1:
            return status
        pose_count = reached
        important = min(important, reached)
        log(f"[gpu {gpu}] {scene_dir.name} sampler reached {reached} poses; retrying there")
    return status


def _render_once(scene_dir: Path, gpu: int, args: argparse.Namespace,
                 pose_count: int, important: int, logs: Path) -> int:
    return _run([sys.executable, str(BLENDER_LAUNCHER), *BLENDER_PREAMBLE,
                   str(scene_dir / "ir_scene.blend"), "--python", str(RENDER), "--",
                   "--out", str(scene_dir / "render"),
                   "--width", str(args.width), "--height", str(args.height),
                   "--hfov-deg", str(args.hfov_deg),
                   "--spp", str(args.spp), "--nir-spp", str(args.nir_spp),
                   "--max-bounces", str(args.max_bounces), "--dataset",
                   "--pose-mode", "object_closeup",
                   "--pose-count", str(pose_count),
                   "--important-count", str(important),
                   "--channel-format", args.channel_format,
                   "--include-active", "--resume"],
                  log_path=logs, env={"CUDA_VISIBLE_DEVICES": str(gpu)})


def worker(gpu: int, seeds: list[int], claims: Path, args: argparse.Namespace,
           expected_frames: int, results: dict[int, bool]) -> None:
    for seed in seeds:
        scene_dir = args.out_root / f"{args.prefix}_{seed:04d}"
        # Completeness is checked *after* policy, not before. A finished scene
        # built under an older composer is not done, it is stale -- and asking
        # "is it complete" first short-circuits the question that decides
        # whether it should exist at all.
        if stale_reason(scene_dir, args) is None and scene_done(scene_dir):
            continue
        claim = claims / f"{seed:04d}"
        try:
            claim.mkdir()  # atomic: only one worker wins
        except FileExistsError:
            continue
        # Stamp the owner so a later instance can tell "in progress elsewhere"
        # from "abandoned", instead of assuming nothing is running.
        (claim / "owner").write_text(f"{os.getpid()}\n", encoding="utf-8")
        results[seed] = build_one(seed, gpu, args, expected_frames)
        if not results[seed]:
            # Release so a later pass retries; --resume keeps what was rendered.
            shutil.rmtree(claim, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=Path, default=Path("/bean/ir_dataset/abo_v1/abo_object_index.json"))
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--prefix", default="abo_cornell")
    parser.add_argument("--seeds", default="0-7", help="inclusive range, e.g. 0-49, or a comma list")
    parser.add_argument("--gpus", default="0,1,2,3",
                        help="comma-separated CUDA device indices; one scene at a time each")
    parser.add_argument("--hosts", type=int, default=1)
    parser.add_argument("--props", type=int, default=6)
    parser.add_argument("--luminaires", type=int, default=1)
    parser.add_argument("--accent-walls", action="store_true", default=True)
    parser.add_argument("--nir-class-prior", action="store_true", default=False)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--hfov-deg", type=float, default=DEFAULT_HFOV)
    parser.add_argument("--spp", type=int, default=DEFAULT_SPP)
    parser.add_argument("--nir-spp", type=int, default=DEFAULT_NIR_SPP)
    parser.add_argument("--max-bounces", type=int, default=DEFAULT_BOUNCES)
    parser.add_argument("--pose-count", type=int, default=DEFAULT_POSE_COUNT)
    parser.add_argument("--important-count", type=int, default=DEFAULT_IMPORTANT_COUNT)
    parser.add_argument("--channel-format", choices=["legacy", "compact"], default="compact",
                        help="compact stores each channel in the smallest form its content "
                             "allows, measured 2.3-3x smaller than the 32-bit EXR the renderer "
                             "wrote before it existed. legacy reproduces that older layout")
    parser.add_argument("--gpu-pool-lock", type=Path,
                        help="JSON with gpu_indices this work root may use; defaults to "
                             "<out-root>/gpu_pool.lock.json. It can only narrow --gpus, so a "
                             "relaunch that forgets the flag cannot stray onto another job's "
                             "devices, and a stale file cannot widen anyone's footprint")
    parser.add_argument("--rebuild-stale", action="store_true",
                        help="recompose and re-render scenes whose manifest declares a different "
                             "composer version, NIR model or lighting profile than this run asks "
                             "for; without it such scenes are reported and skipped")
    parser.add_argument("--dry-run", action="store_true", help="list the plan and exit")
    parser.add_argument("--asset-cache", type=Path, default=None,
                        help="shared bundle cache for the composer, keyed by source content. "
                             "Defaults to `_asset_cache` under --out-root, which is what makes an "
                             "asset used by ten scenes get converted and stored once rather than "
                             "ten times.")
    parser.add_argument("--holder", default=None,
                        help="this session's row in the machine-wide pool lock's `all_holders`; "
                             "without it that lock is not consulted")
    parser.add_argument("--machine-pool-lock", type=Path, default=MACHINE_POOL_LOCK)
    args = parser.parse_args()

    if "-" in args.seeds and "," not in args.seeds:
        low, high = (int(v) for v in args.seeds.split("-", 1))
        seeds = list(range(low, high + 1))
    else:
        seeds = [int(v) for v in args.seeds.split(",") if v.strip()]
    gpus = eligible_gpus([int(v) for v in args.gpus.split(",") if v.strip()],
                         args.gpu_pool_lock or (args.out_root / "gpu_pool.lock.json"))
    if args.holder:
        machine = machine_pool(args.machine_pool_lock, args.holder)
        if machine is not None:
            kept = [g for g in gpus if g in machine]
            if kept != gpus:
                log(f"machine pool lock narrows {gpus} to {kept} "
                    f"(holder {args.holder} in {args.machine_pool_lock})")
            gpus = kept
    if not seeds or not gpus:
        parser.error("need at least one seed, and at least one GPU the pool lock allows")

    # Report, do not refuse: the pool lock is what grants a device, and sharing
    # one is sometimes deliberate. What is never wanted is discovering it later
    # as an unexplained slowdown.
    for gpu in gpus:
        for pid, command in gpu_claimants(gpu, exclude={os.getpid()}):
            log(f"gpu {gpu} already claimed by pid {pid}: {command}")

    # The renderer walks every variant per pose but only writes the non-baseline
    # ones for important poses, so the frame count is not poses x variants. This
    # is the ceiling; a sparse box renders fewer and records that in its own
    # render manifest, which `scene_done` reads back.
    expected_frames = args.pose_count + args.important_count * (VARIANT_COUNT - 1)

    args.out_root.mkdir(parents=True, exist_ok=True)
    claims = args.out_root / ".claims"
    claims.mkdir(exist_ok=True)
    # Releasing claims assumes nothing is rendering, which holds for a restart
    # but not for a second instance started alongside a first -- and not for a
    # --dry-run, which must not touch shared state at all.
    released = 0
    if args.dry_run:
        log(f"seeds={len(seeds)} gpus={gpus} frames/scene<={args.pose_count + args.important_count * (VARIANT_COUNT - 1)}")
        for seed in seeds:
            scene_dir = args.out_root / f"{args.prefix}_{seed:04d}"
            stale = stale_reason(scene_dir, args)
            state = (stale if stale
                     else "done" if scene_done(scene_dir)
                     else "pending")
            log(f"  seed {seed:04d}: {state}")
        return 0
    for claim in claims.iterdir():
        if not claim.is_dir():
            continue
        scene_dir = args.out_root / f"{args.prefix}_{claim.name}"
        # Policy before completeness, for the third time in this file. A claim
        # on a finished-but-stale scene would otherwise be held forever: the
        # release loop calls it done, so the claim stays, and the worker then
        # cannot take the seed to rebuild it. The scene becomes permanently
        # unbuildable and nothing says so.
        if stale_reason(scene_dir, args) is None and scene_done(scene_dir):
            continue
        if _render_running_for(scene_dir):
            # The owning queue may be long gone; what matters is that work is
            # still in flight for this scene.
            log(f"seed {claim.name} still has a live render; leaving it")
            continue
        if _claim_owner_alive(claim):
            # Another instance is working this seed right now. The shell queue
            # this pattern came from could assume "nothing is rendering at
            # startup" because it was the only instance; running two of these
            # side by side breaks that, and releasing here would hand a live
            # scene to a second worker.
            log(f"seed {claim.name} is claimed by a live process; leaving it")
            continue
        shutil.rmtree(claim, ignore_errors=True)
        released += 1

    log(f"seeds={len(seeds)} gpus={gpus} frames/scene={expected_frames} "
        f"total={len(seeds) * expected_frames} released_stale_claims={released}")
    log(f"{args.width}x{args.height} hfov={args.hfov_deg} spp={args.spp}/{args.nir_spp} "
        f"poses={args.pose_count} important={args.important_count} "
        f"nir={'class_prior' if args.nir_class_prior else 'pseudo'} "
        f"format={args.channel_format} hosts={args.hosts} props={args.props}")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _reap)
    results: dict[int, bool] = {}
    threads = [threading.Thread(target=worker, args=(gpu, seeds, claims, args, expected_frames, results))
               for gpu in gpus]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    done = [s for s in seeds if scene_done(args.out_root / f"{args.prefix}_{s:04d}")]
    failed = sorted(s for s, ok in results.items() if not ok)

    # Completeness and integrity are separate questions and only one of them is
    # answered by counting frames. A scene whose bundles have gone still counts
    # every frame it ever rendered, so without this a run over a broken corpus
    # reports complete=N/N and exits 0.
    broken = []
    for seed in seeds:
        scene_dir = args.out_root / f"{args.prefix}_{seed:04d}"
        if not (scene_dir / "scene_manifest.json").is_file():
            continue
        ok, why = scene_intact(scene_dir)
        if not ok:
            broken.append((seed, why))
    if broken:
        log(f"BROKEN {len(broken)} scenes have a manifest whose paths no longer resolve:")
        for seed, why in broken[:8]:
            log(f"    {args.prefix}_{seed:04d}: {why}")
        log("    these count as complete by frame count and are not buildable; "
            "the shared asset cache is the usual cause")

    log(f"complete={len(done)}/{len(seeds)} failed={failed} broken={len(broken)}")
    summary = {"seeds": seeds, "complete": done, "failed": failed,
               "broken": [{"seed": seed, "why": why} for seed, why in broken],
               "frames_per_scene": expected_frames,
               "settings": {k: (str(v) if isinstance(v, Path) else v)
                            for k, v in vars(args).items()}}
    (args.out_root / "queue_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if not failed and not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
