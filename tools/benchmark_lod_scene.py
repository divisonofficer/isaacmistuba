#!/usr/bin/env python3
"""Semantic LOD — Step 6: full vs LOD scene render comparison.

Renders the FULL infinigen scene (render_scene.xml, ~27M polys) vs the decimated
LOD scene (render_scene_lod.xml) across N viewpoints on the discrete-band
``cuda_ad_rgb_polarized`` Stokes carrier, and reports:
  peak GPU memory · scene-load time · mean render time · DoLP/RGB parity + panels.

Each scene runs in its OWN subprocess so GPU peak memory is clean. Reuses the
viewpoint sampler + GpuMemSampler + Stokes helpers from benchmark_band_sweep.

    # one scene (subprocess-internal):
    python tools/benchmark_lod_scene.py --mode one --xml <scene.xml> --tag full --n-viewpoints 50 --spp 128
    # driver (spawns full + lod, writes comparison):
    python tools/benchmark_lod_scene.py --mode compare --n-viewpoints 50 --spp 128 --panel-spp 512

Env (Device 1): LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib
  PYTHONPATH=build/mitsuba3-optix7/python  python=~/miniconda3/envs/openusd_pip/bin/python
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_band_sweep import (  # noqa: E402
    GpuMemSampler, sample_viewpoints, to_world_rows, stokes_modalities, _device_used_mib)

REPO = Path(__file__).resolve().parents[1]
SDIR = REPO / "out/opticalnav/opticalnav-v0.2/scenes/infinigen_kr_20260625"
FULL_XML = SDIR / "render_scene.xml"
LOD_XML = SDIR / "render_scene_lod.xml"
OUT_DIR = REPO / "dev_report/images/lod_compare_2026-07-28"
VARIANT = "cuda_ad_rgb_polarized"


def _cam_key(params) -> str:
    tw = [k for k in params.keys() if k.endswith(".to_world")]
    for k in tw:                      # prefer the sensor/camera transform
        if "amera" in k or "ensor" in k:
            return k
    return tw[0]


def run_one(xml: Path, tag: str, spp: int, viewpoints, panel_idx, panel_spp: int) -> dict:
    import mitsuba as mi
    baseline = _device_used_mib()
    mi.set_variant(VARIANT)
    sampler = GpuMemSampler(); sampler.start()
    res = {"tag": tag, "xml": str(xml), "spp": spp, "variant": VARIANT,
           "baseline_mib": baseline, "n_viewpoints": len(viewpoints), "renders": []}
    try:
        t = time.time()
        scene = mi.load_file(str(xml))
        res["load_scene_s"] = round(time.time() - t, 2)
        # wrap the scene's path integrator in a stokes integrator so the polarized
        # variant actually emits the S1..S3 AOVs (the scene's hdrfilm alone = S0 only)
        integ = mi.load_dict({"type": "stokes", "nested": {"type": "path", "max_depth": 6}})
        params = mi.traverse(scene)
        cam = _cam_key(params); res["cam_key"] = cam
        for vi, vp in enumerate(viewpoints):
            params[cam] = mi.Transform4f(to_world_rows(vp["x"], vp["y"], vp["yaw_deg"]))
            params.update()
            use_spp = panel_spp if (vi in panel_idx and panel_spp) else spp
            t = time.time()
            arr = np.array(integ.render(scene, spp=use_spp, seed=12345))
            rs = time.time() - t
            mod = stokes_modalities(arr)
            res["renders"].append({"vi": vi, "node": vp["node_id"], "render_s": round(rs, 3),
                                   "spp": use_spp, "s0_mean": float(mod["s0_rgb"].mean()),
                                   "dolp_mean": float(mod["dolp"].mean())})
            if vi in panel_idx:
                np.savez(OUT_DIR / f"{tag}_vp{vi:02d}.npz", **mod)
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"
    res["peak_mib"] = sampler.stop()
    res["peak_over_baseline_mib"] = res["peak_mib"] - baseline
    body = [r for r in res["renders"] if not r.get("spp", 0) or r["spp"] == spp]
    res["mean_render_s"] = round(float(np.mean([r["render_s"] for r in body])), 3) if body else None
    res["total_render_s"] = round(float(sum(r["render_s"] for r in res["renders"])), 1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["one", "compare"], default="compare")
    ap.add_argument("--xml"); ap.add_argument("--tag")
    ap.add_argument("--n-viewpoints", type=int, default=50)
    ap.add_argument("--spp", type=int, default=128)
    ap.add_argument("--panel-spp", type=int, default=512)
    ap.add_argument("--panels", type=int, default=3)
    a = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if a.mode == "one":
        vps = sample_viewpoints(a.n_viewpoints)
        pidx = set(np.linspace(0, len(vps) - 1, a.panels).round().astype(int).tolist())
        res = run_one(Path(a.xml), a.tag, a.spp, vps, pidx, a.panel_spp)
        (OUT_DIR / f"result_{a.tag}.json").write_text(json.dumps(res, indent=1))
        print(f"[{a.tag}] peak +{res['peak_over_baseline_mib']} MiB  load {res.get('load_scene_s')}s  "
              f"mean {res.get('mean_render_s')}s  {res.get('error','ok')}")
        return 0

    # compare driver: run each scene in its own subprocess (clean peak memory)
    (OUT_DIR / "viewpoints.json").write_text(json.dumps(sample_viewpoints(a.n_viewpoints), indent=1))
    runs = {}
    for tag, xml in (("full", FULL_XML), ("lod", LOD_XML)):
        if not xml.is_file():
            print(f"SKIP {tag}: {xml} missing"); continue
        print(f"=== running {tag} ({xml.name}) ===", flush=True)
        cmd = [sys.executable, str(Path(__file__)), "--mode", "one", "--xml", str(xml),
               "--tag", tag, "--n-viewpoints", str(a.n_viewpoints), "--spp", str(a.spp),
               "--panel-spp", str(a.panel_spp), "--panels", str(a.panels)]
        subprocess.run(cmd, check=False)
        f = OUT_DIR / f"result_{tag}.json"
        if f.is_file():
            runs[tag] = json.loads(f.read_text())
    comp = {"n_viewpoints": a.n_viewpoints, "spp": a.spp, "runs": runs}
    if "full" in runs and "lod" in runs:
        f, l = runs["full"], runs["lod"]
        comp["summary"] = {
            "peak_mib_full": f["peak_over_baseline_mib"], "peak_mib_lod": l["peak_over_baseline_mib"],
            "mem_saving_pct": round(100 * (1 - l["peak_over_baseline_mib"] / max(f["peak_over_baseline_mib"], 1)), 1),
            "load_full_s": f.get("load_scene_s"), "load_lod_s": l.get("load_scene_s"),
            "mean_render_full_s": f.get("mean_render_s"), "mean_render_lod_s": l.get("mean_render_s"),
            "dolp_mean_full": round(float(np.mean([r["dolp_mean"] for r in f["renders"]])), 4),
            "dolp_mean_lod": round(float(np.mean([r["dolp_mean"] for r in l["renders"]])), 4),
        }
        s = comp["summary"]
        print(f"\n=== LOD comparison ({a.n_viewpoints} vp, spp {a.spp}) ===")
        print(f"peak GPU mem:  full +{s['peak_mib_full']} MiB  ->  lod +{s['peak_mib_lod']} MiB  (-{s['mem_saving_pct']}%)")
        print(f"scene load:    full {s['load_full_s']}s  ->  lod {s['load_lod_s']}s")
        print(f"mean render:   full {s['mean_render_full_s']}s  ->  lod {s['mean_render_lod_s']}s")
        print(f"DoLP mean:     full {s['dolp_mean_full']}  ->  lod {s['dolp_mean_lod']}  (polar parity)")
    (OUT_DIR / "comparison.json").write_text(json.dumps(comp, indent=1))
    print(f"\nwrote {OUT_DIR/'comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
