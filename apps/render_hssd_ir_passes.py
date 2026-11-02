#!/usr/bin/env python3
"""Render a scene through the HSSD renderer twice: rgb + passive, then the flash.

Three passes, not four, because the fourth was redundant: transport is linear in
emission, so `nir_active` is `nir_passive + nir_direct` and rendering it costs a
full NIR pass per frame to reproduce a sum. The loader adds them; this writes the
two independent terms.

Dropping it also disposes of the `active_minus_passive` channel and everything
that was wrong with it. That channel came from the `NIR_FLASH` light group of the
active render, and a light-group pass is a fraction of the total radiance -- the
flash is one emitter among the windows, lamps, sun and sky, so it collects about
that share of the light samples and carries the variance to match. Rendering the
flash alone gives it the whole sample budget: relative noise 2.6% against 9.6%.

What the flash pass needs in exchange is that its camera be current. It runs
`--active-only`, so no earlier pass in that frame evaluates the view layer, and
`_flash()` reads `camera.matrix_world` -- which is stale in background mode until
something does. Measured before the fix: 57% of walk frames and 23% of hover
frames had the flash cone displaced, worst 0.64 of the frame width, and in hover
the worst were the first frame of each take. So the renderer must carry
`bpy.context.view_layer.update()` at the top of `_flash()` for this layout to be
correct at all, and this script refuses to run without it.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RENDERER = REPO / "modules/hssd_blender_ir/tools/blender_render_hssd_ir_sample.py"
LAUNCHER = REPO / "tools/infinigen/run_bundled_blender.py"
TRIMMER = REPO / "tools/infinigen/trim_walk_selection.py"
#: Not produced any more -- the lit pass no longer renders the active frame the
#: light group came from -- but older trees have it, and it is the one channel
#: this corpus must not ship. Left in the quarantine list so a re-run cleans up
#: after a previous one.
QUARANTINE = ("active_minus_passive",)

# hssd_blender_ir.pose_gates carries a frame-depth gate -- a pose is rejected when
# the median distance in frame is under 0.8 m or more than 35% of it is nearer
# than 0.6 m -- and `coverage` and `object_closeup` are both checked against it.
# `_walking_poses` is not: it applies only the geometric preflight, so a pose
# whose body fits but whose view is a wall survives. Measured on a 53-frame walk
# of this apartment: the last seven frames run 0.89 m down to 0.45 m of median
# depth with up to 100% of pixels inside 1 m -- the take ends by walking into a
# surface. 12 of 53 frames fail the gate that the other pose modes enforce.
#
# Applying it here costs the render of the frames it drops, which is why the gate
# belongs upstream in pose selection; this is the half that needs no agreement.
WALK_MIN_MEDIAN_DEPTH_M = 0.8
WALK_MAX_NEAR_FRACTION = 0.35
WALK_NEAR_DISTANCE_M = 0.6


def require_flash_sync() -> None:
    """Refuse to render until the renderer refreshes the camera before the flash.

    A missing line here does not fail, it renders: the flash simply aims where
    the camera was on the previous frame, and every channel but nir_direct looks
    correct while it happens. That is worth a guard rather than a comment.
    """
    source = (REPO / "modules/hssd_blender_ir/tools/blender_render_hssd_ir_sample.py").read_text()
    body = source[source.index("def _flash("):]
    body = body[:body.index("\ndef ", 1)]
    if "view_layer.update()" not in body:
        raise SystemExit(
            "blender_render_hssd_ir_sample.py:_flash() does not call "
            "bpy.context.view_layer.update(), so the flash pass would be aimed with the "
            "previous frame's camera. Measured: 57% of walk frames displaced, worst 0.64 "
            "of frame width. Refusing to render.")



class Stager:
    """Render to local disk and move each finished frame to the real out as it lands.

    Writing straight to the dataset root costs 3.85 s of every 25.96 s frame --
    that root is nfs4 with rsize=32768 and a frame is about 30 MB across a dozen
    EXRs. Staging on local disk and moving afterwards would pay the same bytes at
    the end; moving each frame while the next one renders pays them under the
    GPU instead.

    Two details make it safe rather than merely fast:

    - A frame is moved when the renderer SAYS it finished it, not when its files
      look quiet. `frame_complete` is already on stdout, and a timeout heuristic
      would eventually copy a half-written frame on a slow write.
    - What stays behind is a symlink to the moved directory, because `--resume`
      decides a frame is done by stat-ing its EXRs under the out root. Move them
      away and a resumed run silently re-renders everything it already has.
    """

    def __init__(self, stage_root: Path, final_root: Path):
        self.stage, self.final = stage_root, final_root
        # A symlink left over from a previous run whose target has since gone --
        # the flash tree is deleted after every successful merge -- reads as
        # neither a finished frame nor an absent one: `--resume` stats through it
        # and decides the frame is missing, then the renderer fails to create a
        # directory that already exists as a link. Clear them before anything
        # looks at this tree.
        #
        # Clearing only the DANGLING ones is not enough, and the gap cost 160
        # frames of flash render: a link whose target still exists (an earlier
        # aborted run's output) survives the sweep, and then `offer()` skips it
        # for being a symlink -- so that frame renders, is never moved, and the
        # merge 160 frames later dies on the one file that never arrived. Every
        # symlink in here is this class's own "already moved" marker from a
        # previous run, and a new run must not trust a previous run's markers.
        self.cleared = 0
        if stage_root.is_dir():
            for path in stage_root.rglob("*"):
                if path.is_symlink():
                    path.unlink()
                    self.cleared += 1
        self.queue: queue.Queue = queue.Queue()
        self.moved = self.failed = 0
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _move(self, directory: Path) -> None:
        target = self.final / directory.relative_to(self.stage)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(directory), str(target))     # cross-device: copy then unlink
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.symlink_to(target, target_is_directory=True)
        self.moved += 1

    def _sync_top_level(self) -> None:
        """Copy the small per-mode files across as soon as they exist.

        pose_selection.json is written before the first frame renders and is what
        a reader groups takes by; manifest.json arrives at the end. Moving them
        only at finish() left a live run looking like an empty one -- 101 frames
        on disk and a board reporting "0 poses", because it had no selection to
        read. Copy rather than move: the renderer may still append to them.
        """
        for path in sorted(self.stage.glob("*.json")):
            target = self.final / path.name
            # Never overwrite an existing pose_selection.json. It is the ONLY
            # record of which camera each frame was shot from -- the per-frame
            # manifests carry no camera -- so the newer-mtime rule below would
            # trade the cameras 158 rendered frames belong to for the ones a
            # fresh selection happens to produce. A resume that staged into an
            # empty directory did exactly that.
            if path.name == "pose_selection.json" and target.exists():
                continue
            try:
                if not target.exists() or target.stat().st_mtime < path.stat().st_mtime:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
            except OSError:
                pass

    def _drain(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            try:
                self._move(item)
                self._sync_top_level()
            except OSError as exc:
                self.failed += 1
                print(f"[stager] could not move {item}: {exc}", file=sys.stderr, flush=True)

    def offer(self, frame: str) -> None:
        for directory in sorted(self.stage.glob(f"shard_*/{frame}")) + [self.stage / frame]:
            if directory.is_dir() and not directory.is_symlink():
                self.queue.put(directory)
                return

    def finish(self) -> dict:
        """Drain the queue, then move whatever is left -- manifests and any frame
        whose completion line never arrived, so nothing is stranded locally."""
        self.queue.put(None)
        self.thread.join()
        left = []
        for path in sorted(self.stage.rglob("*")):
            if path.is_symlink() or not path.is_dir():
                continue
            if any(path.glob("*0001.exr")) or any(path.glob("*0001.png")):
                left.append(path)
        for directory in left:
            try:
                self._move(directory)
            except OSError as exc:
                self.failed += 1
                print(f"[stager] could not move {directory}: {exc}", file=sys.stderr, flush=True)
        for path in sorted(self.stage.iterdir()) if self.stage.is_dir() else []:
            if path.is_file():
                target = self.final / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
        return {"frames_moved": self.moved, "move_failures": self.failed,
                "swept_at_end": len(left), "stale_links_cleared": self.cleared}


#: Blender's own thread count (-t). 0 leaves Blender's default of every core, which is what a
#: lone worker wants; several workers on one box (HSSD runs three per GPU with 8) need a cap.
THREADS = 0


def _render(blend: Path, out: Path, *, extra: list[str], common: list[str],
            stager: "Stager | None" = None) -> None:
    cmd = [sys.executable, str(LAUNCHER), *(["-t", str(THREADS)] if THREADS else []),
           "--background", str(blend),
           "--python-exit-code", "1", "--python", str(RENDERER), "--",
           "--dataset", "--out", str(out), *common, *extra]
    if stager is None:
        subprocess.run(cmd, cwd=REPO, check=True)
        return
    # Read stdout so a frame can be handed to the stager the moment the renderer
    # says it is done, and pass every line through unchanged -- the log a corpus
    # run leaves behind must not become this script's summary of it.
    process = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in process.stdout:
        sys.stdout.write(line)
        if '"frame_complete"' in line:
            try:
                stager.offer(json.loads(line)["frame"])
            except (ValueError, KeyError):
                pass
    if process.wait() != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)


def plan_walk(blend: Path, out: Path, common: list[str], log=None) -> dict | None:
    """Choose the walk poses, cut the ones that end in a wall, and render those.

    Two cheap calls before the expensive one. `--max-new-frames 0` makes the
    renderer do its pose selection and write pose_selection.json without drawing
    a frame; the trimmer then ray-casts each pose and removes take tails that
    fail the pose_gates depth thresholds; `--pose-selection-file` hands the
    result back. Measured on one apartment, that is 12 of 188 poses never drawn
    instead of drawn and quarantined -- and ten of the twelve were the last
    frames of a take, walking into a surface.

    Returns the trimmed selection's path, or None when there is nothing to cut.
    """
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(LAUNCHER), "--background", str(blend),
                    "--python-exit-code", "1", "--python", str(RENDERER), "--",
                    "--dataset", "--out", str(out), *common, "--max-new-frames", "0"],
                   cwd=REPO, check=True, stdout=log, stderr=subprocess.STDOUT)
    selection = out / "pose_selection.json"
    if not selection.is_file():
        return None
    trimmed = out / "pose_selection.trimmed.json"
    subprocess.run([sys.executable, str(LAUNCHER), "--background", str(blend),
                    "--python-exit-code", "1", "--python", str(TRIMMER), "--",
                    "--selection", str(selection), "--out", str(trimmed)],
                   cwd=REPO, check=True, stdout=log, stderr=subprocess.STDOUT)
    return trimmed if trimmed.is_file() else None


def _poses(out: Path) -> list:
    payload = json.loads((out / "pose_selection.json").read_text())
    return [(p["position"], p["target"]) for p in payload["all"]]


def _frames(out: Path) -> dict[str, Path]:
    return {p.name: p for p in out.glob("shard_*/*") if p.is_dir()}


def merge(main: Path, flash: Path) -> dict:
    """Move each flash-only Combined in as `nir_direct`, by exact filename."""
    # The two runs choose poses independently. They agree because selection is
    # deterministic on the same geometry -- but "should agree" is how frames get
    # silently crossed, so it is checked before anything is copied.
    if _poses(main) != _poses(flash):
        raise RuntimeError("the two runs did not select the same poses; refusing to merge")
    merged, quarantined = 0, 0
    for name, directory in sorted(_frames(main).items()):
        source = flash / directory.relative_to(main)
        # nir_active is exr16 under compact and exr32 under legacy -- never a
        # PNG -- so the extension is stable across both formats.
        src = source / f"{name}_nir_active0001.exr"
        if not src.is_file():
            raise RuntimeError(f"flash-only render has no nir_active for {name}")
        shutil.copy2(src, directory / f"{name}_nir_direct0001.exr")
        merged += 1
        hold = directory / "quarantine"
        for channel in QUARANTINE:
            stale = directory / f"{name}_{channel}0001.exr"
            if stale.is_file():
                hold.mkdir(exist_ok=True)
                shutil.move(str(stale), hold / stale.name)
                quarantined += 1
    return {"frames_merged": merged, "quarantined_files": quarantined,
            "quarantined_channels": list(QUARANTINE),
            "why_quarantined": "light-group pass damaged by the denoiser; corr 0.470 with the "
                               "true flash term, -0.054 on one pose"}


def depth_gate(main: Path) -> dict:
    """Quarantine frames whose view is a surface, by the renderer's own numbers."""
    import numpy as np
    import imageio.v3 as iio

    dropped = []
    for name, directory in sorted(_frames(main).items()):
        path = directory / f"{name}_depth0001.exr"
        if not path.is_file():
            continue
        depth = np.asarray(iio.imread(path), dtype=np.float32)[..., 0]
        # Cycles writes ~1e10 where a ray hits nothing, but --channel-format
        # compact stores depth as half float, whose maximum is 65504 -- so the
        # sentinel arrives CLAMPED and a `< 1e9` test calls the background
        # foreground. 65504 catches both: the clamped value exactly, and 1e10
        # because it is larger still.
        seen = depth < 65504.0
        if not seen.any():
            continue
        median = float(np.median(depth[seen]))
        near = float((depth[seen] < WALK_NEAR_DISTANCE_M).mean())
        if median >= WALK_MIN_MEDIAN_DEPTH_M and near <= WALK_MAX_NEAR_FRACTION:
            continue
        hold = main / "rejected_by_depth_gate"
        hold.mkdir(exist_ok=True)
        shutil.move(str(directory), hold / directory.name)
        dropped.append({"frame": name, "median_depth_m": round(median, 3),
                        "near_fraction": round(near, 3)})
    return {"rejected": len(dropped), "frames": dropped[:12],
            "thresholds": {"min_median_depth_m": WALK_MIN_MEDIAN_DEPTH_M,
                           "max_near_fraction": WALK_MAX_NEAR_FRACTION}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lit-blend", type=Path, required=True)
    ap.add_argument("--flash-blend", type=Path, required=True,
                    help="the same scene adapted with --flash-only")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flash-out", type=Path,
                    help="where the flash-only pass lands (default: <out>.flash)")
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--height", type=int, default=360)
    # 256, not 512: measured on this corpus with seed pairs, halving the RGB
    # budget moves relative noise 4.13% -> 4.77%, a factor of 1.16 where the
    # sampling theory alone says 1.41 -- the denoiser absorbs the difference.
    # It buys 3 s of an 11.2 s pass. 128 breaks that (5.93%), so this is the knee.
    ap.add_argument("--spp", type=int, default=256)
    # Left at 512. The same halving costs the flash term 1.19% -> 1.39%, and
    # that channel is the one the research question rests on; 3 s is not worth
    # 17% more noise in it while a Stage-1 bake, not the render, is the bottleneck.
    ap.add_argument("--nir-spp", type=int, default=512)
    ap.add_argument("--max-bounces", type=int, default=4)
    ap.add_argument("--hfov-deg", type=float, default=None,
                    help="camera horizontal FOV, passed to the renderer; omitted keeps its legacy 26 mm framing (sq512 renders use 49.6 = the 512x384 vertical FOV)")
    ap.add_argument("--pose-mode", default="walking")
    ap.add_argument("--pose-count", type=int, default=40)
    # The renderer calls it --hover-sequences, but walking reads the same value:
    # it caps how many rooms get walked, so it is the take count for both modes.
    ap.add_argument("--sequences", type=int, default=1,
                    help="number of takes (hover arcs, or walked rooms)")
    ap.add_argument("--keep-flash-dir", action="store_true")
    # Blender can die mid-run on a native fault inside a TBB worker -- one such
    # SIGSEGV killed the flash pass of this apartment at frame 58 of 170 with no
    # Python frame in the dump. The renderer skips frames it has already written,
    # so resuming costs only what was lost rather than the whole pass.
    ap.add_argument("--channel-format", choices=("compact", "legacy"), default="compact")
    ap.add_argument("--walk-multi", action=argparse.BooleanOptionalAction, default=True,
                    help="use the v2 walk planner, which gates walls, void and empty rooms "
                         "structurally at selection")
    ap.add_argument("--trim-walk", action=argparse.BooleanOptionalAction, default=False,
                    help="v1 only: plan walk poses first and drop take tails that end in a wall. "
                         "v2 splits the take at the failing frame itself, so this is redundant "
                         "there and is off by default")
    ap.add_argument("--stage-dir", type=Path,
                    help="render here and move frames to --out as they finish; defaults to a "
                         "local directory beside --out's name when --out is on a network mount")
    ap.add_argument("--stage", action=argparse.BooleanOptionalAction, default=True,
                    help="stage renders on local disk (17%% of a frame is the NFS write)")
    ap.add_argument("--resume", action="store_true",
                    help="skip frames already written in either pass")
    ap.add_argument("--skip-lit", action="store_true",
                    help="the lit pass is already finished in --out: go straight to the flash pass. The renderer's own --resume "
                         "cannot see that in the compact layout (it asks for albedo_rgb0001.exr, which is written as .png), "
                         "so a resumed stage whose flash pass crashed would draw every lit frame again")
    ap.add_argument("--pose-indices",
                    help="comma-separated pose indices to render, in BOTH passes. For extending a finished "
                         "scene: its pose_selection.json is placed in --out first (the extended selection), "
                         "and only the new indices are drawn, so the old frames are neither re-rendered nor "
                         "touched -- the flash tree of a finished scene is gone, and --resume alone would "
                         "draw every old flash frame again")
    ap.add_argument("--threads", type=int, default=0,
                    help="Blender -t for every launch (0 = Blender's default)")
    ap.add_argument("--depth-gate", action=argparse.BooleanOptionalAction, default=True,
                    help="quarantine frames whose view is a surface (pose_gates thresholds)")
    args = ap.parse_args()
    global THREADS
    THREADS = args.threads

    require_flash_sync()

    def staged(out: Path):
        """A stager for `out`, or None when staging is off or pointless."""
        if not args.stage:
            return None, out
        if args.resume and any(out.glob("shard_*/*/")):
            # The renderer skips a frame by finding it in its own output
            # directory. Staging points that at an empty local dir, so a resume
            # re-renders everything it was told to skip -- measured: a 160-frame
            # hover with all 160 on disk started again at p000. Staging buys 17%
            # of a frame; a resume needs correctness, so the real directory wins.
            print(json.dumps({"event": "staging_disabled_for_resume",
                              "out": str(out)}), flush=True)
            return None, out
        local = args.stage_dir or Path(os.environ.get("TMPDIR", "/tmp")) / "hssd_ir_stage" / out.name
        if local.resolve() == out.resolve():
            return None, out
        local.mkdir(parents=True, exist_ok=True)
        return Stager(local, out), local

    flash_out = args.flash_out or args.out.with_suffix(args.out.suffix + ".flash")
    common = ["--width", str(args.width), "--height", str(args.height),
              "--spp", str(args.spp), "--nir-spp", str(args.nir_spp),
              "--max-bounces", str(args.max_bounces),
              # half EXR for radiance and depth, PNG16 for the bounded channels.
              # Measured 2.3x smaller by the renderer's own note; on top of the
              # diffuse passes already turned off this takes a frame from 30 MB
              # to well under 10.
              "--channel-format", args.channel_format,
              "--pose-mode", args.pose_mode, "--pose-count", str(args.pose_count),
              "--hover-sequences", str(args.sequences), "--important-count", "0"]
    if args.hfov_deg is not None:
        common += ["--hfov-deg", str(args.hfov_deg)]
    if args.walk_multi and args.pose_mode == "walking":
        # v2. It rejects a frame failing the same depth thresholds and SPLITS the
        # take there rather than trimming after the fact, drops frames over 20%
        # void, and discards a take averaging fewer than 4 distinct materials a
        # frame -- the "walked through an empty room" case my own measurement
        # found (3063 distinct material ids against 4468-7794) but could only
        # have caught after rendering it.
        common.append("--walk-multi")
    resume = ["--resume"] if args.resume else []
    if args.pose_indices:
        resume = [*resume, "--pose-indices", args.pose_indices]
    staging = {}
    plan = []
    if args.trim_walk and args.pose_mode == "walking" and not args.resume:
        # Only on a fresh run: a resume must keep the selection the rendered
        # frames were shot against, or pose indices stop meaning what their
        # names say.
        trimmed = plan_walk(args.lit_blend, args.out, common)
        if trimmed is not None:
            plan = ["--pose-selection-file", str(trimmed)]
            report_plan = json.loads(trimmed.read_text()).get("trimmed_by", {})
            print(json.dumps({"event": "walk_trimmed",
                              "before": report_plan.get("poses_before"),
                              "after": report_plan.get("poses_after")}), flush=True)
    # No --include-active: that pass renders nir_active, which is the sum of the
    # two terms rendered below and either side of it.
    lit_stager, lit_target = staged(args.out)
    if not args.skip_lit:
        _render(args.lit_blend, lit_target, extra=[*resume, *plan], common=common, stager=lit_stager)
    if lit_stager is not None:
        staging["lit"] = lit_stager.finish()
    flash_stager, flash_target = staged(flash_out)
    # Pin the flash pass to the cameras the lit pass actually shot.
    #
    # The renderer caches its pose selection per OUTPUT directory, and the two
    # passes have different ones -- so the flash pass recomputes. Inside one run
    # that lands on the same poses because the selector is deterministic, which
    # is why this has never been visible. It stops being true the moment the two
    # passes run against different code: the adapter now installs a sun, moves
    # portals inside the glass and tags asset roles, and pose gates read all of
    # it. `merge()` pairs the passes by exact filename, so a drifted selection
    # does not fail -- it files one camera's flash under another camera's name.
    # Copying the lit selection across makes the flash pass read it as a cache
    # hit and removes the whole class.
    lit_selection = args.out / "pose_selection.json"
    if lit_selection.is_file():
        for directory in {flash_target, flash_out}:
            directory.mkdir(parents=True, exist_ok=True)
            shutil.copy2(lit_selection, directory / "pose_selection.json")
        print(json.dumps({"event": "flash_selection_pinned",
                          "poses": len(json.loads(lit_selection.read_text()).get("all", []))}),
              flush=True)
        # A lit selection short of the requested takes reads as a short cache to the flash pass, which then
        # extends it with poses the lit pass never rendered and merge() refuses. HSSD_IR_FLASH_SELECTION_FILE=1
        # hands the file over as --pose-selection-file instead, which is never extended (unset = old behaviour).
        if os.environ.get("HSSD_IR_FLASH_SELECTION_FILE") == "1" and not plan:
            plan = ["--pose-selection-file", str(lit_selection)]
    _render(args.flash_blend, flash_target, extra=["--active-only", *resume, *plan],
            common=common, stager=flash_stager)
    if flash_stager is not None:
        staging["flash"] = flash_stager.finish()
    report = merge(args.out, flash_out)
    if staging:
        report["staging"] = staging
    report["depth_gate"] = depth_gate(args.out) if args.depth_gate else {"mode": "off"}
    if not args.keep_flash_dir:
        shutil.rmtree(flash_out)
        # and its staging tree, or the next resume walks into links pointing at
        # what was just deleted.
        if flash_stager is not None:
            shutil.rmtree(flash_stager.stage, ignore_errors=True)
        report["flash_dir"] = "removed"
    (args.out / "four_pass.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
