#!/usr/bin/env python3
"""Benchmark: resident band-flip renderer vs per-modality scene reload.

Compares two ways to produce a multi-band (visible + NIR) polarized capture of
the SAME production indoor scene, using the discrete-band ``cuda_ad_rgb_polarized``
Stokes carrier:

  new           load scene ONCE, render visible, params.update() to flip the
                band selector to NIR, render NIR. One OptiX/JIT compile.
  old_reload    load the scene fresh for each band (free between), render.
                Two full scene loads + two kernel compiles. Trades memory for time.
  old_resident  load the scene fresh for each band and KEEP both resident
                (the "one memory per modality" pattern). Two live scenes.

Each mode runs in its OWN process (via ``--mode``) so the GPU peak-memory sample
is clean. The driver (no ``--mode``) spawns all three, aggregates timing +
memory, checks new==old render equivalence, and writes metrics.json + preview
PNGs under dev_report/images/band_bench_2026-07-27/.

Env (Device 1, WSL2 + RTX 5090):
  LD_LIBRARY_PATH=/usr/lib/wsl/lib  PYTHONPATH=build/mitsuba3-optix7/python
  python = ~/miniconda3/envs/openusd_pip/bin/python
"""
from __future__ import annotations

import argparse
import json
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
OUT_DIR = REPO / "dev_report/images/band_bench_2026-07-27"
VARIANT = "cuda_ad_rgb_polarized"
# Top-level band selector = a uniform-float blendbsdf weight, exposed by
# mi.traverse() as "<id>.weight.value" (280 of them). Nested metallic-map
# blendbsdfs use a bitmap weight ("...weight.data") and are intentionally excluded.
WEIGHT_RE = re.compile(r"^shared_bsdf_[0-9a-f]+\.weight\.value$")

# Bands rendered by every mode. visible = band selector weight 0, nir = weight 1.
BANDS = [("visible", 0.0), ("nir_854", 1.0)]


# --------------------------------------------------------------------------- #
# GPU memory sampler — process-attributable, via nvidia-smi compute-apps.
# --------------------------------------------------------------------------- #
def _device_used_mib() -> int:
    """Whole-device GPU memory used (MiB). WSL2 does not populate the
    per-process compute-apps list, so device-level used memory is the only
    signal available; we subtract a pre-CUDA baseline to attribute our own use."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
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
# Mitsuba helpers
# --------------------------------------------------------------------------- #
def _stokes_products(img_np: np.ndarray) -> dict:
    """Extract S0 RGB + DoLP from a developed Stokes image.

    The stokes integrator lays channels out as 15 = <root> radiance(3) then
    S0(3),S1(3),S2(3),S3(3). The leading <root> block duplicates S0; the true
    Stokes components start at channel 3.
    """
    c = img_np.shape[2]
    assert c >= 15, f"expected 15 stokes channels (root+S0..S3), got {c}"
    s0 = img_np[:, :, 3:6]
    s1 = img_np[:, :, 6:9]
    s2 = img_np[:, :, 9:12]
    # luminance-weighted Stokes (matches production polvis convention)
    w = np.array([0.2126, 0.7152, 0.0722], np.float32)
    S0 = np.clip((s0 * w).sum(2), 1e-8, None)
    S1 = (s1 * w).sum(2)
    S2 = (s2 * w).sum(2)
    dolp = np.sqrt(S1 * S1 + S2 * S2) / S0
    return {"s0_rgb": s0.astype(np.float32), "dolp": dolp.astype(np.float32)}


def run_mode(mode: str, spp: int, out_json: Path) -> None:
    # Baseline device memory BEFORE any CUDA context / scene allocation.
    baseline_mib = _device_used_mib()

    import mitsuba as mi
    mi.set_variant(VARIANT)

    sampler = GpuMemSampler()
    sampler.start()

    def load():
        t = time.time()
        scene = mi.load_file(str(SCENE_XML))
        return scene, time.time() - t

    def set_band(scene, weight: float):
        params = mi.traverse(scene)
        keys = [k for k in params.keys() if WEIGHT_RE.match(k)]
        t = time.time()
        for k in keys:
            params[k] = mi.Float(weight)
        params.update()
        return len(keys), time.time() - t

    def render(scene, seed: int):
        t = time.time()
        img = mi.render(scene, spp=spp, seed=seed)
        arr = np.array(img)  # forces evaluation
        return arr, time.time() - t

    result: dict = {"mode": mode, "spp": spp, "variant": VARIANT, "bands": {}}
    seed = 12345

    if mode == "new":
        scene, t_load = load()
        n_keys, _ = set_band(scene, BANDS[0][1])
        result["weight_keys"] = n_keys
        result["load_scene_s"] = [t_load]
        first = True
        for band, w in BANDS:
            if not first:
                _, t_flip = set_band(scene, w)
            else:
                t_flip = 0.0
            arr, t_render = render(scene, seed)
            prod = _stokes_products(arr)
            np.savez(OUT_DIR / f"{mode}_{band}.npz", **prod)
            result["bands"][band] = {
                "flip_ms": t_flip * 1e3,
                "render_s": t_render,
                "first_render_includes_compile": first,
                "s0_mean": float(prod["s0_rgb"].mean()),
                "dolp_mean": float(prod["dolp"].mean()),
            }
            first = False

    elif mode in ("old_reload", "old_resident"):
        loads = []
        keep = []
        for band, w in BANDS:
            scene, t_load = load()
            n_keys, _ = set_band(scene, w)
            result["weight_keys"] = n_keys
            loads.append(t_load)
            arr, t_render = render(scene, seed)
            prod = _stokes_products(arr)
            np.savez(OUT_DIR / f"{mode}_{band}.npz", **prod)
            result["bands"][band] = {
                "flip_ms": 0.0,
                "render_s": t_render,
                "first_render_includes_compile": True,
                "s0_mean": float(prod["s0_rgb"].mean()),
                "dolp_mean": float(prod["dolp"].mean()),
            }
            if mode == "old_resident":
                keep.append(scene)  # hold both scenes live -> memory pressure
            else:
                del scene
        result["load_scene_s"] = loads
        _ = keep  # keep alive until after peak sample
    else:
        raise SystemExit(f"unknown mode {mode}")

    result["total_wall_s"] = (
        sum(result["load_scene_s"])
        + sum(b["render_s"] for b in result["bands"].values())
        + sum(b["flip_ms"] for b in result["bands"].values()) / 1e3
    )
    peak = sampler.stop()
    result["gpu_baseline_mib"] = baseline_mib
    result["peak_gpu_mib"] = peak
    result["gpu_attributable_mib"] = max(0, peak - baseline_mib)
    out_json.write_text(json.dumps(result, indent=2))
    print(f"[{mode}] baseline={baseline_mib} peak={peak} attributable={result['gpu_attributable_mib']} MiB  wall={result['total_wall_s']:.2f}s")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def _child_env() -> dict:
    env = dict(os.environ)
    # WSL restarts overwrite /usr/lib/wsl/lib/libnvoptix.so.1 with a 10KB dxcore
    # shim; the real 105MB OptiX library must be found first or scene load fails
    # with "could not find symbol optixQueryFunctionTable".
    env["LD_LIBRARY_PATH"] = "/home/jinnyeong/driver-dist:/usr/lib/wsl/lib:" + env.get("LD_LIBRARY_PATH", "")
    env["PYTHONPATH"] = str(REPO / "build/mitsuba3-optix7/python")
    return env


def drive(spp: int, repeats: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    modes = ["new", "old_reload", "old_resident"]
    agg: dict = {"spp": spp, "repeats": repeats, "scene": str(SCENE_XML.relative_to(REPO)),
                 "modes": {}, "runs": {m: [] for m in modes}}
    for r in range(repeats):
        for m in modes:
            j = OUT_DIR / f"_run_{m}.json"
            cmd = [sys.executable, __file__, "--mode", m, "--spp", str(spp),
                   "--out-json", str(j)]
            subprocess.run(cmd, env=_child_env(), check=True, cwd=str(REPO))
            agg["runs"][m].append(json.loads(j.read_text()))
    # median-ish: take run with median total_wall_s per mode
    for m in modes:
        runs = sorted(agg["runs"][m], key=lambda x: x["total_wall_s"])
        agg["modes"][m] = runs[len(runs) // 2]

    # equivalence: new vs old_reload, per band
    equiv = {}
    for band, _ in BANDS:
        a = np.load(OUT_DIR / f"new_{band}.npz")
        b = np.load(OUT_DIR / f"old_reload_{band}.npz")
        d_s0 = float(np.abs(a["s0_rgb"] - b["s0_rgb"]).mean())
        d_dolp = float(np.abs(a["dolp"] - b["dolp"]).mean())
        equiv[band] = {"s0_mean_abs_diff": d_s0, "dolp_mean_abs_diff": d_dolp}
    agg["equivalence"] = equiv

    _save_previews()
    (OUT_DIR / "metrics.json").write_text(json.dumps(agg, indent=2))
    print(f"\nwrote {OUT_DIR/'metrics.json'}")
    _print_summary(agg)


def _tonemap(rgb: np.ndarray) -> np.ndarray:
    x = np.clip(rgb, 0, None)
    x = x / (1.0 + x)  # Reinhard
    return (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)


# viridis anchor colors (0..1) — matplotlib is unavailable in this env, so we
# interpolate a compact LUT with numpy for the DoLP heatmaps.
_VIRIDIS = np.array([
    [0.267, 0.005, 0.329], [0.283, 0.141, 0.458], [0.254, 0.265, 0.530],
    [0.207, 0.372, 0.553], [0.164, 0.471, 0.558], [0.128, 0.567, 0.551],
    [0.135, 0.659, 0.518], [0.267, 0.749, 0.441], [0.478, 0.821, 0.318],
    [0.741, 0.873, 0.150], [0.993, 0.906, 0.144],
], np.float32)


def _dolp_color(dolp: np.ndarray, vmax: float) -> np.ndarray:
    v = np.clip(dolp / max(vmax, 1e-6), 0, 1)
    idx = v * (len(_VIRIDIS) - 1)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, len(_VIRIDIS) - 1)
    frac = (idx - lo)[..., None]
    rgb = _VIRIDIS[lo] * (1 - frac) + _VIRIDIS[hi] * frac
    return (rgb * 255).astype(np.uint8)


def _save_previews() -> None:
    from PIL import Image
    vmax = 0.0
    for band, _ in BANDS:
        d = np.load(OUT_DIR / f"new_{band}.npz")["dolp"]
        vmax = max(vmax, float(np.percentile(d, 99)))
    for band, _ in BANDS:
        z = np.load(OUT_DIR / f"new_{band}.npz")
        Image.fromarray(_tonemap(z["s0_rgb"])).save(OUT_DIR / f"{band}_rgb.png")
        Image.fromarray(_dolp_color(z["dolp"], vmax)).save(OUT_DIR / f"{band}_dolp.png")
    (OUT_DIR / "preview_meta.json").write_text(json.dumps({"dolp_vmax": vmax}))


def _print_summary(agg: dict) -> None:
    n = agg["modes"]["new"]
    orl = agg["modes"]["old_reload"]
    ore = agg["modes"]["old_resident"]
    print("\n=== SUMMARY (median run) ===")
    print(f"{'metric':28} {'new':>12} {'old_reload':>12} {'old_resident':>14}")
    print(f"{'total wall (s)':28} {n['total_wall_s']:12.2f} {orl['total_wall_s']:12.2f} {ore['total_wall_s']:14.2f}")
    print(f"{'scene loads':28} {len(n['load_scene_s']):12d} {len(orl['load_scene_s']):12d} {len(ore['load_scene_s']):14d}")
    print(f"{'sum load (s)':28} {sum(n['load_scene_s']):12.2f} {sum(orl['load_scene_s']):12.2f} {sum(ore['load_scene_s']):14.2f}")
    print(f"{'peak GPU used (MiB)':28} {n['peak_gpu_mib']:12d} {orl['peak_gpu_mib']:12d} {ore['peak_gpu_mib']:14d}")
    print(f"{'attributable GPU (MiB)':28} {n['gpu_attributable_mib']:12d} {orl['gpu_attributable_mib']:12d} {ore['gpu_attributable_mib']:14d}")
    flips = [b["flip_ms"] for b in n["bands"].values() if b["flip_ms"] > 0]
    print(f"{'band flip (ms)':28} {(flips[0] if flips else 0):12.2f} {'-':>12} {'-':>14}")
    print("equivalence new vs old_reload:", agg["equivalence"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["new", "old_reload", "old_resident"])
    ap.add_argument("--spp", type=int, default=256)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out-json", type=Path)
    a = ap.parse_args()
    if a.mode:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        run_mode(a.mode, a.spp, a.out_json or OUT_DIR / f"_run_{a.mode}.json")
    else:
        drive(a.spp, a.repeats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
