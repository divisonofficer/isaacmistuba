#!/usr/bin/env python3
"""Large-scale benchmark: one resident scene serving many viewpoints via
sensor-pose + band-weight updates, vs reloading the scene per (viewpoint×band).

This is the scaled-up version of the 2026-07-27 comparison. It renders a real
viewpoint-graph sweep (up to N viewpoints) of one production indoor scene on the
discrete-band ``cuda_ad_rgb_polarized`` Stokes carrier, and for every render
extracts the full modality set from a single Stokes pass:

    RGB (visible S0) · NIR (nir_854 S0) · DoLP · AoLP · S1/S0 · S2/S0

Modes (each in its own process so GPU peak-memory is clean):
  new         load scene ONCE, then for each viewpoint set PerspectiveCamera.to_world
              and the band selector weight via params.update() — no reload.
  old_sample  reload the scene fresh for K (viewpoint×band) pairs to measure the
              real per-reload cost; the driver projects it to the full sweep.

Env (Device 1, WSL2 + RTX 5090):
  LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib
  PYTHONPATH=build/mitsuba3-optix7/python
  python = ~/miniconda3/envs/openusd_pip/bin/python
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SCENE_XML = REPO / "out/discrete_band_bridge_2026-07-18/scene_band.xml"
GRAPH_JSON = REPO / "out/opticalnav/opticalnav-v0.2/scenes/infinigen_kr_20260625/viewpoint_graph.json"
OUT_DIR = REPO / "dev_report/images/band_sweep_2026-07-28"
VARIANT = "cuda_ad_rgb_polarized"
WEIGHT_RE = re.compile(r"^shared_bsdf_[0-9a-f]+\.weight\.value$")
CAM_KEY = "PerspectiveCamera.to_world"
CAM_HEIGHT_M = 1.0
BANDS = [("visible", 0.0), ("nir_854", 1.0)]
# viewpoints for which we persist full-modality npz + PNG panels
PANEL_EVERY = None  # set in main from n_viewpoints -> ~3 panels


# --------------------------------------------------------------------------- #
# GPU memory sampler (device-level; WSL has no per-process attribution)
# --------------------------------------------------------------------------- #
def _device_used_mib() -> int:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
        return int(float(out.strip().splitlines()[0]))
    except Exception:
        return 0


class GpuMemSampler(threading.Thread):
    def __init__(self, period_s: float = 0.05):
        super().__init__(daemon=True)
        self.period = period_s
        self.peak_mib = 0
        self._stop_evt = threading.Event()

    def run(self):
        while not self._stop_evt.is_set():
            self.peak_mib = max(self.peak_mib, _device_used_mib())
            time.sleep(self.period)

    def stop(self) -> int:
        self.peak_mib = max(self.peak_mib, _device_used_mib())
        self._stop_evt.set()
        self.join(timeout=2)
        return self.peak_mib


# --------------------------------------------------------------------------- #
# Viewpoints
# --------------------------------------------------------------------------- #
def sample_viewpoints(n: int) -> list[dict]:
    """Evenly sample n (node, heading) pairs from the scene viewpoint graph.

    Position AND heading are varied: nodes are taken evenly across the graph and
    each is assigned a rotating heading, so the sweep exercises the room broadly.
    """
    g = json.loads(GRAPH_JSON.read_text())
    nodes = g["nodes"]
    if not nodes:
        raise SystemExit("empty viewpoint graph")
    idxs = np.linspace(0, len(nodes) - 1, num=min(n, len(nodes))).round().astype(int)
    # if n exceeds node count, cycle nodes with different headings
    out = []
    k = 0
    while len(out) < n:
        node = nodes[idxs[k % len(idxs)]]
        headings = node.get("headings") or [{"yaw_deg": 0.0, "heading_id": "h_000"}]
        h = headings[(k // len(idxs) + k) % len(headings)]
        pos = node["position"]
        out.append({
            "node_id": node["node_id"], "heading_id": h.get("heading_id", "h"),
            "x": float(pos[0]), "y": float(pos[1]), "yaw_deg": float(h["yaw_deg"]),
        })
        k += 1
    return out[:n]


def to_world_rows(x: float, y: float, yaw_deg: float, height: float = CAM_HEIGHT_M):
    """Row-major 4x4 matching sensor_sweep._mat4_from_xy_yaw (translation x,h,y;
    yaw=0 looks +Z, as the baked bridge sensor does)."""
    yaw = math.radians(yaw_deg)
    c, s = math.cos(yaw), math.sin(yaw)
    return [[c, 0.0, s, x], [0.0, 1.0, 0.0, height], [-s, 0.0, c, y], [0.0, 0.0, 0.0, 1.0]]


# --------------------------------------------------------------------------- #
# Stokes -> modalities
# --------------------------------------------------------------------------- #
_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)


def stokes_modalities(img_np: np.ndarray) -> dict:
    """15-channel Stokes image -> full modality set (luminance-weighted)."""
    assert img_np.shape[2] >= 15, img_np.shape
    s0_rgb = img_np[:, :, 3:6].astype(np.float32)
    S0 = np.clip((s0_rgb * _LUM).sum(2), 1e-8, None)
    S1 = (img_np[:, :, 6:9] * _LUM).sum(2)
    S2 = (img_np[:, :, 9:12] * _LUM).sum(2)
    s1_over = np.clip(S1 / S0, -1, 1)
    s2_over = np.clip(S2 / S0, -1, 1)
    dolp = np.clip(np.sqrt(S1 * S1 + S2 * S2) / S0, 0, 1)
    aolp = 0.5 * np.degrees(np.arctan2(S2, S1))  # [-90, 90]
    return {"s0_rgb": s0_rgb, "s1_over_s0": s1_over.astype(np.float32),
            "s2_over_s0": s2_over.astype(np.float32), "dolp": dolp.astype(np.float32),
            "aolp": aolp.astype(np.float32)}


# --------------------------------------------------------------------------- #
# run_mode
# --------------------------------------------------------------------------- #
def run_mode(mode: str, spp: int, viewpoints: list[dict], panel_idx: set[int],
             out_json: Path, old_sample_k: int, panel_spp: int = 0) -> None:
    baseline_mib = _device_used_mib()
    import mitsuba as mi
    mi.set_variant(VARIANT)
    sampler = GpuMemSampler()
    sampler.start()

    def load():
        t = time.time()
        sc = mi.load_file(str(SCENE_XML))
        return sc, time.time() - t

    def band_keys(params):
        return [k for k in params.keys() if WEIGHT_RE.match(k)]

    seed = 12345
    result = {"mode": mode, "spp": spp, "variant": VARIANT,
              "n_viewpoints": len(viewpoints), "renders": []}

    if mode == "new":
        scene, t_load = load()
        params = mi.traverse(scene)
        wk = band_keys(params)
        result["weight_keys"] = len(wk)
        result["load_scene_s"] = [t_load]
        compiled = False
        for vi, vp in enumerate(viewpoints):
            T = mi.Transform4f(to_world_rows(vp["x"], vp["y"], vp["yaw_deg"]))
            t = time.time()
            params[CAM_KEY] = T
            params.update()
            pose_ms = (time.time() - t) * 1e3
            for band, w in BANDS:
                t = time.time()
                for k in wk:
                    params[k] = mi.Float(w)
                params.update()
                flip_ms = (time.time() - t) * 1e3
                # Panel (showcase) viewpoints render at higher spp for clean
                # modality images; the throughput/timing columns use `spp` and
                # exclude these so the sweep cost stays comparable across renders.
                is_panel = vi in panel_idx
                use_spp = panel_spp if (is_panel and panel_spp) else spp
                t = time.time()
                arr = np.array(mi.render(scene, spp=use_spp, seed=seed))
                render_s = time.time() - t
                mod = stokes_modalities(arr)
                rec = {"vi": vi, "node": vp["node_id"], "heading": vp["heading_id"],
                       "band": band, "pose_update_ms": pose_ms if band == BANDS[0][0] else 0.0,
                       "flip_ms": flip_ms, "render_s": render_s, "spp": use_spp,
                       "is_panel": is_panel,
                       "first_render_compile": not compiled,
                       "s0_mean": float(mod["s0_rgb"].mean()),
                       "dolp_mean": float(mod["dolp"].mean())}
                compiled = True
                result["renders"].append(rec)
                if vi in panel_idx:
                    np.savez(OUT_DIR / f"vp{vi:02d}_{band}.npz", **mod)
        result["panel_viewpoints"] = [
            {"vi": vi, **viewpoints[vi]} for vi in sorted(panel_idx)]

    elif mode == "old_sample":
        # Reload the scene fresh for K (viewpoint x band) pairs -> real per-reload cost.
        loads, renders = [], []
        pairs = []
        for vp in viewpoints[:max(1, old_sample_k // len(BANDS))]:
            for band, w in BANDS:
                pairs.append((vp, band, w))
        pairs = pairs[:old_sample_k]
        for vp, band, w in pairs:
            scene, t_load = load()
            params = mi.traverse(scene)
            wk = band_keys(params)
            params[CAM_KEY] = mi.Transform4f(to_world_rows(vp["x"], vp["y"], vp["yaw_deg"]))
            for k in wk:
                params[k] = mi.Float(w)
            params.update()
            t = time.time()
            _ = np.array(mi.render(scene, spp=spp, seed=seed))
            renders.append(time.time() - t)
            loads.append(t_load)
            del scene
        result["load_scene_s"] = loads
        result["render_s_samples"] = renders
        result["per_reload_load_s"] = float(np.median(loads))
        result["per_render_s"] = float(np.median(renders))
    else:
        raise SystemExit(mode)

    result["gpu_baseline_mib"] = baseline_mib
    result["peak_gpu_mib"] = sampler.stop()
    result["gpu_attributable_mib"] = max(0, result["peak_gpu_mib"] - baseline_mib)
    out_json.write_text(json.dumps(result, indent=2))
    print(f"[{mode}] renders={len(result.get('renders', result.get('render_s_samples', [])))} "
          f"attributable={result['gpu_attributable_mib']} MiB")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def _child_env() -> dict:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = "/home/jinnyeong/driver-dist:/usr/lib/wsl/lib:" + env.get("LD_LIBRARY_PATH", "")
    env["PYTHONPATH"] = str(REPO / "build/mitsuba3-optix7/python")
    return env


def drive(n_vp: int, spp: int, old_sample_k: int, panel_spp: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    viewpoints = sample_viewpoints(n_vp)
    (OUT_DIR / "viewpoints.json").write_text(json.dumps(viewpoints, indent=2))
    # ~3 evenly spaced panel viewpoints
    panel = sorted(set(np.linspace(0, n_vp - 1, num=min(3, n_vp)).round().astype(int).tolist()))
    (OUT_DIR / "_panel.json").write_text(json.dumps(panel))

    for m in ("new", "old_sample"):
        j = OUT_DIR / f"_run_{m}.json"
        cmd = [sys.executable, __file__, "--mode", m, "--spp", str(spp),
               "--n-viewpoints", str(n_vp), "--old-sample-k", str(old_sample_k),
               "--panel-spp", str(panel_spp), "--out-json", str(j)]
        subprocess.run(cmd, env=_child_env(), check=True, cwd=str(REPO))

    new = json.loads((OUT_DIR / "_run_new.json").read_text())
    old = json.loads((OUT_DIR / "_run_old_sample.json").read_text())

    # projected old cost for the full sweep = (n_vp * n_bands) reloads
    n_renders = n_vp * len(BANDS)
    proj_old_wall = n_renders * (old["per_reload_load_s"] + old["per_render_s"])
    # actual NEW wall (includes the few hi-spp showcase panels)
    new_wall_actual = sum(new["load_scene_s"]) + sum(r["render_s"] for r in new["renders"]) \
        + sum(r["flip_ms"] + r["pose_update_ms"] for r in new["renders"]) / 1e3
    # comparable NEW wall at sweep spp (exclude hi-spp panels so both sides use `spp`)
    sweep_renders = [r for r in new["renders"] if not r.get("is_panel")]
    mean_sweep_render_s = float(np.mean([r["render_s"] for r in sweep_renders])) if sweep_renders else \
        float(np.mean([r["render_s"] for r in new["renders"]]))
    overhead_s = sum(r["flip_ms"] + r["pose_update_ms"] for r in new["renders"]) / 1e3
    new_wall = sum(new["load_scene_s"]) + n_renders * mean_sweep_render_s + overhead_s
    new_render_only = n_renders * mean_sweep_render_s

    agg = {
        "scene": str(SCENE_XML.relative_to(REPO)),
        "graph": str(GRAPH_JSON.relative_to(REPO)),
        "n_viewpoints": n_vp, "n_bands": len(BANDS), "n_renders": n_renders, "spp": spp,
        "new": {
            "load_scene_s": new["load_scene_s"],
            "weight_keys": new["weight_keys"],
            "wall_s": new_wall, "wall_s_actual": new_wall_actual, "render_only_s": new_render_only,
            "mean_render_s": mean_sweep_render_s, "sweep_spp": spp,
            "mean_pose_update_ms": float(np.mean([r["pose_update_ms"] for r in new["renders"] if r["pose_update_ms"] > 0])),
            "mean_flip_ms": float(np.mean([r["flip_ms"] for r in new["renders"] if r["flip_ms"] > 0])),
            "gpu_attributable_mib": new["gpu_attributable_mib"],
            "gpu_baseline_mib": new["gpu_baseline_mib"], "peak_gpu_mib": new["peak_gpu_mib"],
            "panel_viewpoints": new["panel_viewpoints"],
            "throughput_vp_per_min": n_vp / (new_wall / 60.0),
        },
        "old_projected": {
            "per_reload_load_s": old["per_reload_load_s"], "per_render_s": old["per_render_s"],
            "sample_k": len(old["load_scene_s"]), "sample_loads_s": old["load_scene_s"],
            "reloads": n_renders, "wall_s": proj_old_wall,
            "resident_required_mib": len(BANDS) * new["gpu_attributable_mib"],  # if held resident
            "vram_total_mib": _device_used_mib() and None,
        },
        "speedup_wall": proj_old_wall / max(new_wall, 1e-6),
        "band_means": _band_means(new),
    }
    # vram total
    try:
        agg["old_projected"]["vram_total_mib"] = int(float(subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            text=True).strip().splitlines()[0]))
    except Exception:
        agg["old_projected"]["vram_total_mib"] = None

    _save_panels(panel)
    (OUT_DIR / "metrics.json").write_text(json.dumps(agg, indent=2))
    print(f"\nwrote {OUT_DIR/'metrics.json'}")
    print(f"NEW wall {new_wall:.0f}s ({n_vp} vp) | OLD projected {proj_old_wall:.0f}s "
          f"| speedup {agg['speedup_wall']:.1f}x | mem {new['gpu_attributable_mib']} MiB constant")


def _band_means(new: dict) -> dict:
    out = {}
    for band, _ in BANDS:
        s0 = [r["s0_mean"] for r in new["renders"] if r["band"] == band]
        dl = [r["dolp_mean"] for r in new["renders"] if r["band"] == band]
        out[band] = {"s0_mean": float(np.mean(s0)), "dolp_mean": float(np.mean(dl))}
    return out


# --------------------------------------------------------------------------- #
# Colormaps (matplotlib-free) + panel PNGs
# --------------------------------------------------------------------------- #
_VIRIDIS = np.array([
    [0.267, 0.005, 0.329], [0.283, 0.141, 0.458], [0.254, 0.265, 0.530],
    [0.207, 0.372, 0.553], [0.164, 0.471, 0.558], [0.128, 0.567, 0.551],
    [0.135, 0.659, 0.518], [0.267, 0.749, 0.441], [0.478, 0.821, 0.318],
    [0.741, 0.873, 0.150], [0.993, 0.906, 0.144]], np.float32)


def _lut(v01: np.ndarray, lut: np.ndarray) -> np.ndarray:
    idx = np.clip(v01, 0, 1) * (len(lut) - 1)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, len(lut) - 1)
    f = (idx - lo)[..., None]
    return ((lut[lo] * (1 - f) + lut[hi] * f) * 255).astype(np.uint8)


def _tonemap(rgb: np.ndarray) -> np.ndarray:
    x = np.clip(rgb, 0, None)
    x = x / (1.0 + x)
    return (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)


def _viridis(v: np.ndarray, vmax: float) -> np.ndarray:
    return _lut(v / max(vmax, 1e-6), _VIRIDIS)


def _diverging(v: np.ndarray) -> np.ndarray:
    # v in [-1,1]: blue(neg)-white(0)-red(pos)
    t = (np.clip(v, -1, 1) + 1) / 2
    lut = np.array([[0.23, 0.30, 0.75], [1, 1, 1], [0.75, 0.15, 0.15]], np.float32)
    return _lut(t, lut)


def _aolp_hsv(aolp_deg: np.ndarray, dolp: np.ndarray) -> np.ndarray:
    # hue = angle (cyclic), value modulated by dolp so unpolarized reads dark
    h = ((aolp_deg + 90.0) / 180.0) % 1.0
    import colorsys
    flat_h = h.ravel()
    val = np.clip(dolp.ravel() / max(dolp.max(), 1e-6), 0, 1)
    rgb = np.array([colorsys.hsv_to_rgb(float(hh), 1.0, float(vv)) for hh, vv in zip(flat_h, val)], np.float32)
    return (rgb.reshape(*aolp_deg.shape, 3) * 255).astype(np.uint8)


def _save_panels(panel_idx: list[int]) -> None:
    from PIL import Image
    # shared DoLP scale across panels/bands
    vmax = 0.0
    for vi in panel_idx:
        for band, _ in BANDS:
            f = OUT_DIR / f"vp{vi:02d}_{band}.npz"
            if f.is_file():
                vmax = max(vmax, float(np.percentile(np.load(f)["dolp"], 99)))
    vmax = max(vmax, 1e-3)
    for vi in panel_idx:
        v = OUT_DIR / f"vp{vi:02d}_visible.npz"
        n = OUT_DIR / f"vp{vi:02d}_nir_854.npz"
        if not v.is_file():
            continue
        zv = np.load(v)
        Image.fromarray(_tonemap(zv["s0_rgb"])).save(OUT_DIR / f"vp{vi:02d}_rgb.png")
        if n.is_file():
            Image.fromarray(_tonemap(np.load(n)["s0_rgb"])).save(OUT_DIR / f"vp{vi:02d}_nir.png")
        Image.fromarray(_viridis(zv["dolp"], vmax)).save(OUT_DIR / f"vp{vi:02d}_dolp.png")
        Image.fromarray(_aolp_hsv(zv["aolp"], zv["dolp"])).save(OUT_DIR / f"vp{vi:02d}_aolp.png")
        Image.fromarray(_diverging(zv["s1_over_s0"])).save(OUT_DIR / f"vp{vi:02d}_s1s0.png")
        Image.fromarray(_diverging(zv["s2_over_s0"])).save(OUT_DIR / f"vp{vi:02d}_s2s0.png")
    (OUT_DIR / "panel_meta.json").write_text(json.dumps({"dolp_vmax": vmax, "panel": panel_idx}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["new", "old_sample"])
    ap.add_argument("--n-viewpoints", type=int, default=50)
    ap.add_argument("--spp", type=int, default=128)
    ap.add_argument("--old-sample-k", type=int, default=6)
    ap.add_argument("--panel-spp", type=int, default=0)
    ap.add_argument("--out-json", type=Path)
    a = ap.parse_args()
    if a.mode:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        vps = sample_viewpoints(a.n_viewpoints)
        panel = set(np.linspace(0, a.n_viewpoints - 1, num=min(3, a.n_viewpoints)).round().astype(int).tolist())
        run_mode(a.mode, a.spp, vps, panel, a.out_json or OUT_DIR / f"_run_{a.mode}.json",
                 a.old_sample_k, panel_spp=a.panel_spp)
    else:
        drive(a.n_viewpoints, a.spp, a.old_sample_k, a.panel_spp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
