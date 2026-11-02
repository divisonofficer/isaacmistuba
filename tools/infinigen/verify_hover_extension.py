#!/usr/bin/env python3
"""Independent check of the LAST landing of apps/extend_apartment_hover.py in one scene.

    python3 tools/infinigen/verify_hover_extension.py <scene_id> [--mode hover|walk] [--since ISO8601] [--corpus DIR]

It re-derives every invariant from the live tree and does not call land()'s own assertions, so a bug there cannot hide
itself: the manifest and selection are consistent, the original poses are byte-identical, no pre-existing file was touched
(mtime before the extension started), every new frame carries exactly today's compact layout, nothing is empty or black,
and the depth-gate drops add up. Exit 1 on any FAIL.

--since defaults to the `started` of the status file of the last landing (the clock of the frames, also for a reused or
resumed stage). The layout constants below are spelled out again on purpose; they are not imported from the worker.
Unpaired brightness of old against new takes is printed as information only: they film different rooms, so it says
nothing about render bias (a paired re-render does).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps"))
from run_apartment_corpus_worker import rendered  # noqa: E402

LOGICAL = ("albedo_nir", "albedo_rgb", "depth", "layer_count", "material_id", "metallic", "nir_direct", "nir_passive",
           "normal", "pbr_invalid_mask", "rgb", "roughness")
PNG = {"albedo_nir", "albedo_rgb", "metallic", "normal", "pbr_invalid_mask", "roughness"}
COMPACT = sorted(f"{c}0001.{'png' if c in PNG else 'exr'}" for c in LOGICAL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--mode", choices=("hover", "walk"), default="hover", help="which tree's last landing to check")
    ap.add_argument("--since", help="ISO time the extension's frames started being written")
    ap.add_argument("--corpus", type=Path, default=Path("/bean/ir_dataset_work/hssd_ir_apartment_4pass"))
    args = ap.parse_args()
    root, scene = args.corpus, args.scene
    live = root / scene / args.mode
    js = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731
    ledger = js(root / f"{args.mode}_ext_ledger.json")
    last = ledger[scene][-1]
    if args.since:
        since_iso = args.since
    else:
        claims = root / ".claims_hoverext"
        starts = [js(f) for f in sorted(claims.glob(f"{scene}*.status.json"))]
        starts = [s for s in starts if (s.get("landing") or {}).get("at") == last["at"]]
        if not starts:
            sys.exit("no status file belongs to the last landing; pass --since")
        since_iso = starts[0]["started"]
    since = datetime.fromisoformat(since_iso.replace("Z", "+00:00")).timestamp()
    bad: list[str] = []

    def check(ok: bool, msg: str) -> None:
        print(("ok   " if ok else "FAIL ") + msg)
        if not ok:
            bad.append(msg)

    man, sel = js(live / "manifest.json"), js(live / "pose_selection.json")["all"]
    pre_sel = js(live / f".pre_{args.mode}_ext/pose_selection.json")["all"]
    has_four = (live / "four_pass.json").is_file()          # the oldest walk trees were merged by hand and never had one
    four = js(live / "four_pass.json") if has_four else {}
    pre_four = js(live / f".pre_{args.mode}_ext/four_pass.json") if has_four else {}
    marker = js(live / f".{args.mode}_ext.json")

    dirs = {d.name: d for s in sorted(live.glob("shard_*")) for d in s.iterdir() if d.is_dir()}
    pidx = {n: int(re.search(r"_p(\d+)_T0", n).group(1)) for n in dirs}
    rows = man["frames"]
    names = [r["frame"] for r in rows]
    had = last["poses"][0]                                   # first pose of the LAST landing (a scene may have several)
    old_dirs = {n for n, i in pidx.items() if i < had}
    new_names = sorted(n for n in dirs if pidx[n] >= had)
    check(man["pose_count"] == len(sel), f"manifest pose_count {man['pose_count']} == selection {len(sel)}")
    check(len(set(names)) == len(names), f"{len(names)} manifest rows, frame names unique")
    if {r["frame"] for r in rows} >= old_dirs:
        check(set(names) >= set(dirs), f"manifest enumerates its frames: every frame dir ({len(dirs)}) has a row")
    else:
        check(not any(pidx.get(n, -1) >= had for n in names),
              f"manifest never enumerated this scene's frames ({len(rows)} rows for {len(old_dirs)} older dirs): no row added for the new ones")
    check(json.dumps(sel[:len(pre_sel)]) == json.dumps(pre_sel), f"selection starts with the original {len(pre_sel)} poses, byte-identical")
    check(all(i < len(sel) for i in pidx.values()), "every frame dir's pose index is inside the selection")
    check(len(set(pidx.values())) == len(pidx), "one frame dir per pose index")
    missing = set(range(had, len(sel))) - {i for i in pidx.values() if i >= had}
    gate = [e.get("depth_gate", {}).get("rejected", 0) for e in four.get("extensions", [])] if has_four else [last["depth_gate_dropped"]]
    check(bool(gate) and len(missing) == gate[-1], f"new poses without a frame dir: {len(missing)} == depth gate rejected {gate[-1:]} (this landing)")
    if has_four:
        check(all(four.get(k) == v for k, v in pre_four.items() if k != "extensions"), "four_pass.json: every original key unchanged")
    else:
        check(not (live / "four_pass.json").exists(), "no four_pass.json was invented for a tree that never had one")
    check(bool(marker.get("landings")), f".{args.mode}_ext.json: {len(marker.get('landings', []))} landing(s)")
    check(rendered(root, scene), "rendered() still true")
    leftovers = [p.name for p in live.iterdir() if p.name.endswith((".ext_tmp", ".tmp"))]
    check(not leftovers, f"no temp leftovers {leftovers}")

    bad_layout, touched, stale, empty = [], [], [], []
    for n, d in dirs.items():
        files = sorted(p for p in d.iterdir() if p.is_file())
        is_new = pidx[n] >= had
        if is_new and [p.name[len(n) + 1:] for p in files] != COMPACT:
            bad_layout.append(n)
        for p in files:
            st = p.stat()
            empty += [p.name] if st.st_size == 0 else []
            touched += [p.name] if (not is_new and st.st_mtime >= since) else []
            stale += [p.name] if (is_new and st.st_mtime < since) else []
    check(not bad_layout, f"all {len(new_names)} new frames carry exactly today's {len(COMPACT)}-file layout ({bad_layout[:2]})")
    check(not touched, f"{len(old_dirs)} older frames: no file touched since the extension started ({touched[:2]})")
    check(not stale, f"{len(new_names)} new frames: every file written during the extension ({stale[:2]})")
    check(not empty, f"no empty files ({empty[:2]})")

    def mean_of(frame: str, chan: str) -> float:
        img = cv2.imread(str(next(dirs[frame].glob(f"*_{chan}0001.exr"))), cv2.IMREAD_UNCHANGED).astype(np.float64)
        return float(np.nanmean(img[..., :3] if img.ndim == 3 else img))

    rng = random.Random(7)
    for chan in ("rgb", "nir_passive", "nir_direct"):
        a = [mean_of(n, chan) for n in rng.sample(sorted(old_dirs), min(40, len(old_dirs)))]
        b = [mean_of(n, chan) for n in rng.sample(new_names, min(40, len(new_names)))]
        qa, qb = np.percentile(a, [10, 50, 90]), np.percentile(b, [10, 50, 90])
        print(f"info {chan}: frame-mean p10/p50/p90 older {qa.round(4).tolist()} new {qb.round(4).tolist()} (different rooms)")
        check(qb[2] > 0.01 and bool(np.isfinite(a + b).all()), f"{chan}: new frames are finite and not black (p90 {qb[2]:.3f})")

    print(f"\nselection {len(sel)} poses | frame dirs {len(dirs)} | older {len(old_dirs)} | new {len(new_names)} "
          f"(depth gate dropped {len(missing)}) | manifest rows {len(rows)}")
    print("RESULT:", "PASS" if not bad else f"FAIL ({len(bad)})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
