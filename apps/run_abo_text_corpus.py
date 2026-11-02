#!/usr/bin/env python3
"""Build the ABO text-legibility corpus: scenes of labelled objects, hovered.

Coverage is the loop's job, not the batch size. A target that yields no take in
one scene is usually not unusable -- it was behind a table leg, or its label
faced a wall in that arrangement. Measured on the screen scenes, 8 of 24 targets
per scene produce a take, and the arc length barely moves that (5 at 50 degrees,
8 at 30, still 8 at 10), so the limit is the arrangement rather than the sweep.
Uncovered targets are therefore re-drawn into later scenes with a fresh seed,
the same way the hover planner revisits a subject it could not shoot the first
time, until every target has had `--attempts` chances.

Stages per scene are skipped on output existence, so an interrupted run resumes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "modules" / "hssd_blender_ir" / "tools"
LAUNCH = [sys.executable, str(REPO / "tools/infinigen/run_bundled_blender.py"),
          "--background", "--python-exit-code", "1"]


def run(cmd, log: Path, env=None) -> int:
    with log.open("a") as fh:
        fh.write(f"\n$ {' '.join(str(c) for c in cmd)}\n"); fh.flush()
        return subprocess.call(cmd, stdout=fh, stderr=fh,
                               env={**os.environ, **(env or {})}, cwd=str(REPO))


def covered(scene_dir: Path, name: str = "text_hover_poses.json") -> set[str]:
    sel = scene_dir / name
    if not sel.is_file():
        return set()
    try:
        traj = json.loads(sel.read_text(encoding="utf-8"))["hover"]["trajectories"]
    except (ValueError, KeyError):
        return set()
    return {t["source_id"] for t in traj}


def poses_name(args) -> str:
    return "text_hover_poses.json" if not args.round else f"text_hover_poses_r{args.round}.json"


def render_name(args) -> str:
    """A round gets its own render tree, and not for tidiness.

    Frame names are <scene>_p<NNN>_<variant>, numbered by position in the pose
    file. A second round rendered into the same tree would restart at p000 and
    --resume would skip those names as already done -- keeping round one's
    frames under round two's poses. The camera would be wrong and nothing would
    report it.
    """
    return "render" if not args.round else f"render_r{args.round}"


def render_scene(d: Path, args) -> int:
    """One scene's frames, from its planned text-hover poses."""
    return run(LAUNCH + [str(d / "ir_scene.blend"), "--python",
                         str(TOOLS / "blender_render_hssd_ir_sample.py"), "--",
                         "--out", str(d / render_name(args)), "--width", "720", "--height", "540",
                         "--hfov-deg", "44.98", "--spp", str(args.spp),
                         "--nir-spp", str(args.spp), "--max-bounces", "8", "--dataset",
                         "--pose-selection-file", str(d / poses_name(args)),
                         "--channel-format", "compact", "--resume"],
               d.parent / f"{d.name}.log",
               {"CUDA_VISIBLE_DEVICES": args.gpu, "HSSD_IR_SKIP_DIFFUSE_COMPONENT": "1",
                "HSSD_IR_BAND_BATCH": "8", "HSSD_IR_DENOISE_GPU": "1",
                "HSSD_IR_CLIP_START": "0.02",
                # Lossless on rgb only: 12/12 of this corpus's frames bit-exact
                # through cv2, 19.2% smaller. Not on scalar channels, where PIZ
                # came out 2.6x LARGER on HSSD's measurement.
                "HSSD_IR_RGB_EXR_CODEC": "PIZ"})


def plan_poses(d: Path, args, log: Path) -> None:
    if (d / poses_name(args)).is_file():
        return
    run([sys.executable, str(REPO / "apps/build_abo_text_hover.py"),
         "--scene", str(d), "--bboxes", str(d / "scene_bboxes.json"),
         "--targets", str(args.targets), "--anchors", str(args.anchors),
         "--out", str(d / poses_name(args)), "--frames", str(args.frames),
         "--target-px", str(args.target_px),
         "--azimuth-span-deg", str(args.azimuth_span_deg),
         "--takes-per-target", str(args.takes_per_target),
         "--emit-from", str(1 if args.round else 0)], log)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--targets", type=Path, default=REPO / "configs" / "abo_text_targets.json")
    ap.add_argument("--anchors", type=Path, required=True)
    ap.add_argument("--index", default="/bean/ir_dataset/abo_v1/abo_object_index.json")
    ap.add_argument("--registry", default="/bean/ir_pbr_assets/texturecan_environment_merged_v1/registry.lock.json")
    ap.add_argument("--asset-cache", default="/bean/ir_dataset/abo_cornell_video_v1/_asset_cache")
    ap.add_argument("--props", type=int, default=24)
    ap.add_argument("--hosts", type=int, default=3)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--target-px", type=float, default=38.0)
    ap.add_argument("--azimuth-span-deg", type=float, default=30.0)
    ap.add_argument("--attempts", type=int, default=3,
                    help="how many scenes a target may appear in before it is given up on")
    ap.add_argument("--max-scenes", type=int, default=40)
    ap.add_argument("--spp", type=int, default=512)
    ap.add_argument("--gpu", default="4")
    ap.add_argument("--round", type=int, default=0,
                    help="additional take round: plans into text_hover_poses_rN.json "
                         "and renders into render_rN/, emitting only takes the "
                         "earlier rounds did not shoot")
    ap.add_argument("--takes-per-target", type=int, default=1)
    ap.add_argument("--plan-only", action="store_true",
                    help="compose, build, prepare and PLAN, but do not render. "
                         "Coverage is known after planning; rendering is the 20 h part.")
    args = ap.parse_args()

    reg = json.loads(args.targets.read_text(encoding="utf-8"))
    excluded = set(reg.get("excluded") or {})
    wanted = [t for t in sorted(reg["targets"]) if t not in excluded]
    args.out_root.mkdir(parents=True, exist_ok=True)

    seen: dict[str, int] = {}
    done: set[str] = set()
    # Directories only. Each scene also writes abo_text_NNN.log beside its
    # directory, and counting those doubled the scene count -- which read as
    # "already at the limit" and quietly rendered nothing at all.
    existing = sorted(d for d in args.out_root.glob("abo_text_*") if d.is_dir())
    for d in existing:
        done |= covered(d)      # round one's coverage is what "already shot" means
    scene_n = len(existing)

    # A later round adds takes to scenes that already exist, and those scenes
    # never reach the compose loop below (it starts at scene_n == len(existing)),
    # so plan the round's poses here. Without this, round 2 planned nothing and
    # rendered nothing, and exited in 4 s.
    if args.round:
        for d in existing:
            if (d / "scene_bboxes.json").is_file():
                plan_poses(d, args, args.out_root / f"{d.name}.log")

    # Scenes planned by an earlier --plan-only run still need their frames.
    if not args.plan_only:
        for d in existing:
            if not covered(d, poses_name(args)) or (d / render_name(args) / "manifest.json").is_file():
                continue
            print(f"{d.name}: rendering {len(covered(d))} planned takes", flush=True)
            render_scene(d, args)

    while scene_n < args.max_scenes:
        pool = [t for t in wanted if t not in done and seen.get(t, 0) < args.attempts]
        if not pool:
            break
        batch = pool[:args.props]
        sid = f"abo_text_{scene_n:03d}"
        d = args.out_root / sid
        log = args.out_root / f"{sid}.log"
        d.mkdir(parents=True, exist_ok=True)
        ids_file = d / "include_ids.json"
        ids_file.write_text(json.dumps(batch))
        for t in batch:
            seen[t] = seen.get(t, 0) + 1

        if not (d / "scene_manifest.json").is_file():
            # The composer draws hosts and luminaires at random, and a handful of
            # ABO products keep their textures OUTSIDE the GLB, which the bundler
            # refuses. That is a property of the drawn cast, not of this scene's
            # targets, so a different seed usually gets a clean one: retry rather
            # than lose 24 targets to someone else's table.
            for attempt in range(4):
                code = run([sys.executable, str(REPO / "apps/build_abo_cornell_scene.py"),
                            "--index", args.index, "--registry", args.registry,
                            "--out", str(d), "--scene-id", sid,
                            "--seed", str(5000 + scene_n + 911 * attempt),
                            "--include-ids", str(ids_file), "--min-prop-extent-m", "0.05",
                            "--hosts", str(args.hosts), "--props", str(len(batch)),
                            "--luminaires", "1", "--asset-cache", args.asset_cache], log)
                if code == 0:
                    break
                print(f"{sid}: compose attempt {attempt + 1} failed", flush=True)
            else:
                print(f"{sid}: compose FAILED after 4 seeds", flush=True)
                scene_n += 1
                continue
        stages = (("source.blend", ["--python", str(TOOLS / "blender_build_scene.py"), "--",
                                    "--manifest", str(d / "scene_manifest.json"),
                                    "--out-blend", str(d / "source.blend")]),
                  ("ir_scene.blend", [str(d / "source.blend"), "--python",
                                      str(TOOLS / "blender_prepare_hssd_ir.py"), "--",
                                      "--source-blend", str(d / "source.blend"),
                                      "--out-blend", str(d / "ir_scene.blend"),
                                      "--manifest", str(d / "scene_manifest.json"),
                                      "--hssd-semantics", str(d / "abo_semantics.csv")]),
                  ("scene_bboxes.json", [str(d / "ir_scene.blend"), "--python",
                                         str(REPO / "apps/dump_abo_scene_bboxes.py"), "--",
                                         str(d / "scene_bboxes.json")]))
        failed = False
        for marker, cmd in stages:
            if (d / marker).is_file():
                continue
            if run(LAUNCH + cmd, log, {"CUDA_VISIBLE_DEVICES": args.gpu}) != 0:
                print(f"{sid}: {marker} FAILED", flush=True); failed = True; break
        if failed:
            scene_n += 1; continue

        plan_poses(d, args, log)
        got = covered(d, poses_name(args))
        done |= got
        print(f"{sid}: {len(got)}/{len(batch)} targets gave a take; "
              f"{len(done)}/{len(wanted)} covered", flush=True)

        if not args.plan_only and got:
            render_scene(d, args)
        scene_n += 1

    left = [t for t in wanted if t not in done]
    print(f"\n[corpus] scenes {scene_n}  covered {len(done)}/{len(wanted)}  "
          f"uncovered {len(left)}", flush=True)
    (args.out_root / "coverage.json").write_text(json.dumps(
        {"covered": sorted(done), "uncovered": left, "scenes": scene_n}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
