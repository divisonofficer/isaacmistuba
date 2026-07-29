#!/usr/bin/env python3
"""Overnight batch: legacy-vs-injected BSDF comparison across many viewpoints /
scenes, ranked by how visibly IOR/metal injection improves the render.

For every candidate viewpoint it renders both ``legacy`` (hardcoded int_ior=1.5 /
material="Al") and ``injected`` (per-material IOR + real metal eta-k), computes an
improvement score from the Stokes products (DoLP/AoLP change) + RGB colour
restoration, writes a 4-col × 3-row montage, and appends to a manifest so the
report step can pick the top-N examples.

RUN IN THE MITSUBA ENV:
    PYTHONPATH=modules/robomituba_bridge/src:modules/mitsuba_converter/src:\
modules/navigation_dataset/src:/home/jinnyeong/robomituba-build/mitsuba3/python \
    LD_LIBRARY_PATH=/usr/lib/wsl/lib \
    /usr/bin/python3.10 apps/batch_bsdf_examples.py --per-scene 10 --spp 32 --res 448
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PROJECT = "opticalnav-v0.2"
OUT_ROOT = REPO / "out" / "bsdf_compare_batch"

# Scenes to sweep. The three infinigen_kr rooms are the richest (most objects /
# saved viewpoints) and the injection path is validated on them.
DEFAULT_SCENES = [
    "infinigen_kr_20000221",
    "infinigen_kr_20260627",
    "infinigen_kr_20260625",
]


def pick_requests(scene: str, k: int) -> list[Path]:
    """Return up to k saved RenderRequest json paths spread across viewpoints/headings."""
    jobs = sorted(glob.glob(str(REPO / f"out/bridge_jobs/opticalnav-{scene}-template-vp_*-rgb")))
    by_key: dict[str, Path] = {}
    for j in jobs:
        reqs = sorted(glob.glob(j + "/requests/*.json"))
        if not reqs:
            continue
        m = re.search(r"(vp_\w+?)-h_(\d+)", Path(j).name)
        key = f"{m.group(1)}_{m.group(2)}" if m else Path(j).name
        by_key.setdefault(key, Path(reqs[0]))
    keys = sorted(by_key)
    if not keys:
        return []
    # even spread across the sorted (vp, heading) space
    if len(keys) <= k:
        chosen = keys
    else:
        step = len(keys) / k
        chosen = [keys[int(i * step)] for i in range(k)]
    return [by_key[key] for key in chosen]


def _free_gpu() -> None:
    """Release GPU allocations between renders so big scenes don't accumulate → OOM."""
    import gc
    gc.collect()
    try:
        import drjit as dr
        dr.flush_malloc_cache()
    except Exception:
        pass


def pick_graph_items(scene: str, k: int, headings: list[float], eye_h: float) -> list[dict]:
    """Synthesize cameras from a scene's viewpoint_graph.json (for scenes with no
    saved RenderRequests). Uses the pipeline pose→camera convention:
    forward=[sin(yaw),0,cos(yaw)], eye=[x, eye_h, y] (Y-up render space)."""
    import math
    from mitsuba_converter.multimodal import camera_to_world_from_lookat
    gp = REPO / "out" / "opticalnav" / PROJECT / "scenes" / scene / "viewpoint_graph.json"
    if not gp.exists():
        return []
    nodes = json.loads(gp.read_text()).get("nodes", [])
    if not nodes:
        return []
    step = max(1, len(nodes) // max(1, k))
    picked = nodes[::step][:k]
    items = []
    for node in picked:
        pos = node.get("position") or [0, 0, 0]
        x, y = float(pos[0]), float(pos[1])
        for yaw_deg in headings:
            yaw = math.radians(yaw_deg)
            eye = [x, eye_h, y]
            fwd = [math.sin(yaw), 0.0, math.cos(yaw)]
            target = [eye[0] + fwd[0], eye[1], eye[2] + fwd[2]]
            c2w = camera_to_world_from_lookat(eye, target, [0, 1, 0])
            items.append(dict(id=f"{node['node_id']}_h{int(yaw_deg):03d}", cam=c2w, fov=70.0))
    return items


def score_pair(ldir: Path, idir: Path) -> dict:
    import numpy as np
    ls = np.load(ldir / "stokes_data.npz")
    iss = np.load(idir / "stokes_data.npz")
    s0l = np.asarray(ls["s0"], float)
    s0i = np.asarray(iss["s0"], float)
    if s0l.ndim == 3:                       # s0 is (H,W,3) — collapse to luminance
        s0l = s0l.mean(-1)
    if s0i.ndim == 3:
        s0i = s0i.mean(-1)
    mask = (s0l > 1e-4) & (s0i > 1e-4)
    if mask.sum() < 200:
        mask = np.ones_like(mask, dtype=bool)

    dl = np.asarray(ls["dop"], float)
    di = np.asarray(iss["dop"], float)
    dd = np.abs(di - dl)
    frac = float((dd[mask] > 0.05).mean())
    dolp_mean = float(dd[mask].mean())
    dolp_max = float(dd[mask].max())

    al = np.asarray(ls["aolp"], float)
    ai = np.asarray(iss["aolp"], float)
    da = np.abs(ai - al)
    da = np.minimum(da, np.pi - da)          # AoLP is pi-periodic
    w = np.minimum(dl, di)                     # weight by DoLP (masks noise)
    denom = float(w[mask].sum()) + 1e-6
    aolp_masked = float((da[mask] * w[mask]).sum() / denom)

    rl = np.asarray(ls["rgb"], float)
    ri = np.asarray(iss["rgb"], float)

    def sat(x):
        mx = x.max(-1)
        mn = x.min(-1)
        return (mx - mn) / (mx + 1e-6)

    chroma_gain = float(sat(ri)[mask].mean() - sat(rl)[mask].mean())
    rgb_l1 = float(np.abs(ri - rl).mean())

    score = (100.0 * frac) + (50.0 * aolp_masked) + (30.0 * max(chroma_gain, 0.0)) + (10.0 * min(rgb_l1, 1.0))
    return dict(
        score=score, frac_dolp=frac, dolp_mean=dolp_mean, dolp_max=dolp_max,
        aolp_masked=aolp_masked, chroma_gain=chroma_gain, rgb_l1=rgb_l1,
        valid_frac=float(mask.mean()),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenes", nargs="+", default=DEFAULT_SCENES)
    ap.add_argument("--per-scene", type=int, default=10)
    ap.add_argument("--spp", type=int, default=32)
    ap.add_argument("--res", type=int, default=448)
    ap.add_argument("--ambient", type=float, default=1.0)
    ap.add_argument("--rescore-only", action="store_true",
                    help="skip rendering; score + montage every already-rendered viewpoint on disk")
    ap.add_argument("--from-graph", action="store_true",
                    help="synthesize cameras from viewpoint_graph.json (for scenes with no saved requests)")
    ap.add_argument("--graph-headings", nargs="+", type=float, default=[0.0, 90.0, 180.0, 270.0],
                    help="yaw angles (deg) sampled per graph node in --from-graph mode")
    ap.add_argument("--eye-height", type=float, default=1.5)
    ap.add_argument("--regen-injected", action="store_true",
                    help="rebuild injected XML instead of copying the scene's production render_scene.xml (~7 min/scene)")
    a = ap.parse_args()

    import apps.compare_bsdf_modes as C

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_ROOT / "manifest.json"
    records: list[dict] = []
    if manifest_path.exists():
        try:
            records = json.loads(manifest_path.read_text())
        except Exception:
            records = []
    done = {(r["scene"], r["request"]) for r in records}

    if a.rescore_only:
        records = []
        for sdir in sorted(p for p in OUT_ROOT.iterdir() if p.is_dir()):
            for vp in sorted(p for p in sdir.iterdir() if p.is_dir()):
                lp, ip = vp / "legacy" / "stokes_data.npz", vp / "injected" / "stokes_data.npz"
                if not (lp.exists() and ip.exists()):
                    continue
                try:
                    metrics = score_pair(vp / "legacy", vp / "injected")
                    montage = vp / "montage.png"
                    C._assemble_montage({"legacy": vp / "legacy", "injected": vp / "injected"}, montage)
                    records.append(dict(scene=sdir.name, request=vp.name + ".json",
                                        request_path="", montage=str(montage), **metrics))
                    print(f"  [rescore] {sdir.name}/{vp.name} score={metrics['score']:.2f} "
                          f"frac_dolp={metrics['frac_dolp']:.3f} aolp={metrics['aolp_masked']:.4f} "
                          f"chroma={metrics['chroma_gain']:+.3f}", flush=True)
                except Exception:
                    print(f"[error] rescore {sdir.name}/{vp.name}:\n{traceback.format_exc()}", flush=True)
        records.sort(key=lambda r: r["score"], reverse=True)
        manifest_path.write_text(json.dumps(records, indent=2))
        print(f"\n[rescore] {len(records)} viewpoints. Top 12:", flush=True)
        for r in records[:12]:
            print(f"  {r['score']:6.2f}  {r['scene']:24s} {r['request']}  "
                  f"frac={r['frac_dolp']:.3f} aolp={r['aolp_masked']:.4f} chroma={r['chroma_gain']:+.3f}", flush=True)
        return 0

    for scene in a.scenes:
        scene_dir = REPO / "out" / "opticalnav" / PROJECT / "scenes" / scene
        if not scene_dir.exists():
            print(f"[skip] scene not found: {scene}", flush=True)
            continue
        if a.from_graph:
            items = pick_graph_items(scene, a.per_scene, a.graph_headings, a.eye_height)
        else:
            items = [dict(id=r.stem, cam=None, fov=None, request_path=str(r)) for r in pick_requests(scene, a.per_scene)]
        print(f"[{scene}] {len(items)} viewpoints selected ({'graph' if a.from_graph else 'saved-request'})", flush=True)
        if not items:
            continue

        sout = OUT_ROOT / scene
        sout.mkdir(parents=True, exist_ok=True)
        xmls: dict[str, Path] = {}
        try:
            import shutil
            prod_xml = REPO / "out" / "opticalnav" / PROJECT / "scenes" / scene / "render_scene.xml"
            for mode in ("legacy", "injected"):
                xp = sout / f"render_scene_{mode}.xml"
                # The production render_scene.xml is already the injected build, so copy
                # it (paths are absolute) and skip the ~7 min rebuild; legacy regenerates.
                if mode == "injected" and not a.regen_injected and prod_xml.exists():
                    shutil.copyfile(prod_xml, xp)
                else:
                    C.regenerate_xml(PROJECT, scene, mode, xp)
                xmls[mode] = xp
                hist = C._bsdf_material_histogram(xp)
                print(f"  [{scene}/{mode}] metals={hist['materials']} int_ior={hist['int_ior']}", flush=True)
        except Exception:
            print(f"[error] XML regen failed for {scene}:\n{traceback.format_exc()}", flush=True)
            continue

        for item in items:
            iid = item["id"]
            req_name = iid + ".json"
            if (scene, req_name) in done:
                print(f"  [cached] {iid}", flush=True)
                continue
            vp_out = sout / iid
            try:
                if item.get("cam") is not None:
                    cam, fov = item["cam"], item["fov"]
                else:
                    cam, fov = C._load_camera_from_request(Path(item["request_path"]))
                for mode in ("legacy", "injected"):
                    C.render_viewpoint(xmls[mode], cam, fov, vp_out / mode,
                                       spp=a.spp, res=a.res, ambient=a.ambient)
                    _free_gpu()
                metrics = score_pair(vp_out / "legacy", vp_out / "injected")
                mode_dirs = {"legacy": vp_out / "legacy", "injected": vp_out / "injected"}
                montage = vp_out / "montage.png"
                C._assemble_montage(mode_dirs, montage)
                rec = dict(scene=scene, request=req_name, request_path=item.get("request_path", ""),
                           montage=str(montage), **metrics)
                records.append(rec)
                done.add((scene, req_name))
                manifest_path.write_text(json.dumps(records, indent=2))
                print(f"  [ok] {iid} score={metrics['score']:.2f} "
                      f"frac_dolp={metrics['frac_dolp']:.3f} aolp={metrics['aolp_masked']:.4f} "
                      f"chroma={metrics['chroma_gain']:+.3f}", flush=True)
            except Exception:
                print(f"[error] render failed {scene}::{iid}:\n{traceback.format_exc()}", flush=True)
                continue

    records.sort(key=lambda r: r["score"], reverse=True)
    manifest_path.write_text(json.dumps(records, indent=2))
    print(f"\n[batch] {len(records)} viewpoints scored. Top 12:", flush=True)
    for r in records[:12]:
        print(f"  {r['score']:6.2f}  {r['scene']:24s} {r['request']}  "
              f"frac={r['frac_dolp']:.3f} aolp={r['aolp_masked']:.4f} chroma={r['chroma_gain']:+.3f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
