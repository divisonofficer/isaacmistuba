#!/usr/bin/env python3
"""Camera-rig debug render — render EVERY sensor a camera rig defines, all
modalities, from ONE resident scene load on the discrete-band Stokes carrier.

Why a rule: a debug render only tells you whether the *intended optical system*
is correct if it follows the actual camera-rig definition — every sensor at its
mount pose / fov, in its modality's spectrum, with the rig's active lights. So the
debug render reads the rig JSON (out/control_plane_cache/camera_rigs/<rig>.json,
schema validated by render_daemon._normalize_camera_rig) and reproduces it.

Per sensor it produces the full panel:
    S0 intensity (RGB and/or NIR spectrum)
  + per spectrum: DoP (red-black) · AoLP · S1/S0 · S2/S0 · S3/S0
Spectra come from sensor_type: rgb_camera→[visible], nir_camera→[nir],
polar_camera→[visible,nir] (one resident scene serves both bands via the
blendbsdf weight flip — the whole point of the unified spectral-polar scene).

Env (Device 1): LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib
  PYTHONPATH=build/mitsuba3-optix7/python  python=~/miniconda3/envs/openusd_pip/bin/python

    python tools/debug_render_rig.py --rig ranger_mini_default \
        --scene out/discrete_band_bridge_2026-07-18/scene_band.xml --spp 256
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from benchmark_band_sweep import sample_viewpoints  # noqa: E402
import math  # noqa: E402

RIG_DIR = REPO / "out/control_plane_cache/camera_rigs"
OUT = REPO / "dev_report/images/debug_render_rig"
VARIANT = "cuda_ad_rgb_polarized"
CAM = "PerspectiveCamera.to_world"
FOV = "PerspectiveCamera.x_fov"
FILM = "PerspectiveCamera.film.size"
WEIGHT_RE = re.compile(r"^shared_bsdf_[0-9a-f]+\.weight\.value$")
_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)
# blendbsdf weight: 0 = visible band, 1 = nir band (project_discrete_band_render)
BAND_WEIGHT = {"visible": 0.0, "nir": 1.0}
SENSOR_SPECTRA = {"rgb_camera": ["visible"], "nir_camera": ["nir"],
                  "polar_camera": ["visible", "nir"], "lidar_3d": []}


def _mat4_from_xy_yaw(x, y, yaw_rad, height_m):
    """EXACT mirror of navigation_dataset.sensor_sweep._mat4_from_xy_yaw
    (column-major flat 16) -> row-major 4x4 for mi.Transform4f. yaw about +Y,
    translation (x, height, y). Using the production formula guarantees a debug
    camera pose IS the pose the real sweep renders."""
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    flat = [c, 0.0, -s, 0.0,  0.0, 1.0, 0.0, 0.0,  s, 0.0, c, 0.0,  float(x), float(height_m), float(y), 1.0]
    return np.asarray(flat, np.float32).reshape(4, 4).T   # col-major flat -> row-major matrix


def sensor_pose(x, y, yaw_rad, mount, fallback_height_m, convention="zup") -> np.ndarray:
    """Robot base (x,y,yaw) + sensor mount -> camera_to_world.

    convention="pipeline": EXACT mirror of sensor_sweep._sensor_pose_from_xy_yaw —
      mount.xyz_m = [lateral_x, HEIGHT_y, forward_z]. This is what the production
      sweep does today; for the ranger rig ([-0.2,0.1,1.5]) it puts the camera at
      0.1 m (floor) / 1.5 m forward.
    convention="zup" (default): interpret the mount as ROS base_link z-up
      [lateral_x, forward_y, HEIGHT_z] — the author's intent (camera at 1.5 m). The
      difference between the two is exactly the z-up<->y-up mismatch this debug
      render surfaced; "zup" is the physically-sensible eye-height view.
    """
    mount = mount or {}
    xyz = mount.get("xyz_m") or [0.0, 0.0, fallback_height_m]
    rpy = mount.get("rpy_deg") or [0.0, 0.0, 0.0]
    ax, ay, az = float(xyz[0]), float(xyz[1]), float(xyz[2])
    if convention == "zup":
        lateral, forward, height = ax, ay, az          # base_link z-up
    else:
        lateral, height, forward = ax, ay, az          # pipeline y-up
    if ax == 0.0 and ay == 0.0 and az == 0.0:
        height = fallback_height_m
    mount_yaw = math.radians(float(rpy[2]))
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    wx = x + c * lateral - s * forward
    wz = y + s * lateral + c * forward
    return _mat4_from_xy_yaw(wx, wz, yaw_rad + mount_yaw, height_m=height)


# ------------------------------------------------------------- modality maths --
def modalities(arr) -> dict:
    a = np.nan_to_num(np.asarray(arr))
    s0 = a[:, :, 3:6]
    S0 = np.clip((s0 * _LUM).sum(2), 1e-8, None)
    S1 = (a[:, :, 6:9] * _LUM).sum(2); S2 = (a[:, :, 9:12] * _LUM).sum(2)
    S3 = (a[:, :, 12:15] * _LUM).sum(2) if a.shape[2] >= 15 else np.zeros_like(S0)
    dop = np.clip(np.sqrt(S1 ** 2 + S2 ** 2 + S3 ** 2) / S0, 0, 1)   # full DoP incl circular
    aolp = 0.5 * np.degrees(np.arctan2(S2, S1))
    return {"s0_rgb": s0, "S0": S0, "dop": dop, "aolp": aolp,
            "s1s0": np.clip(S1 / S0, -1, 1), "s2s0": np.clip(S2 / S0, -1, 1),
            "s3s0": np.clip(S3 / S0, -1, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rig", default="ranger_mini_default")
    ap.add_argument("--scene", default=str(REPO / "out/discrete_band_bridge_2026-07-18/scene_band.xml"))
    ap.add_argument("--spp", type=int, default=4000)
    ap.add_argument("--res", type=int, nargs=2, default=[480, 384])
    ap.add_argument("--viewpoints", default="4,8,12", help="comma list of graph viewpoint indices (base robot poses)")
    ap.add_argument("--height", type=float, default=1.0, help="fallback height when mount is all-zero")
    ap.add_argument("--mount-convention", choices=["zup", "pipeline"], default="zup",
                    help="zup=author intent [lateral,forward,height]; pipeline=current sweep [lateral,height,forward]")
    a = ap.parse_args()

    import mitsuba as mi
    OUT.mkdir(parents=True, exist_ok=True)
    rig = json.loads((RIG_DIR / f"{a.rig}.json").read_text())
    sensors = [s for s in rig.get("sensors", []) if s.get("enabled", True)]
    active_lights = rig.get("active_lights", [])
    vp_idxs = [int(x) for x in str(a.viewpoints).split(",") if x.strip() != ""]
    vps = sample_viewpoints(max(vp_idxs) + 1)

    mi.set_variant(VARIANT)
    t0 = time.time()
    scene = mi.load_file(a.scene)
    params = mi.traverse(scene)
    wkeys = [k for k in params.keys() if WEIGHT_RE.match(k)]
    params[FILM] = mi.ScalarPoint2u(a.res[0], a.res[1]); params.update()
    load_s = round(time.time() - t0, 1)
    print(f"rig {a.rig}: {len(sensors)} sensors, {len(active_lights)} active_lights, "
          f"{len(vp_idxs)} viewpoints, mount={a.mount_convention} | "
          f"scene loaded {load_s}s, {len(wkeys)} band-weight keys", flush=True)

    result = {"rig": a.rig, "scene": a.scene, "load_scene_s": load_s, "spp": a.spp,
              "res": a.res, "mount_convention": a.mount_convention,
              "n_active_lights": len(active_lights), "viewpoints": []}
    n_render = 0
    for vi in vp_idxs:
        vp = vps[vi]; yaw_rad = math.radians(float(vp["yaw_deg"]))
        vprec = {"vi": vi, "x": round(vp["x"], 2), "y": round(vp["y"], 2),
                 "yaw_deg": round(vp["yaw_deg"], 1), "sensors": []}
        for s in sensors:
            stype = s.get("sensor_type", "rgb_camera")
            spectra = SENSOR_SPECTRA.get(stype, ["visible"])
            c2w = sensor_pose(vp["x"], vp["y"], yaw_rad, s.get("mount"), a.height, a.mount_convention)
            fov = float((s.get("intrinsics") or {}).get("fov_h_deg", 70.0))
            params[CAM] = mi.Transform4f(c2w.tolist()); params[FOV] = fov
            srec = {"sensor_id": s["sensor_id"], "sensor_type": stype,
                    "modalities": s.get("modalities", []), "fov_h_deg": fov, "spectra": spectra,
                    "mount": (s.get("mount") or {}).get("xyz_m"), "bands": {}}
            for band in spectra:
                for k in wkeys:
                    params[k] = mi.Float(BAND_WEIGHT[band])
                params.update()
                arr = np.array(mi.render(scene, spp=a.spp, seed=7)); n_render += 1
                m = modalities(arr)
                _save_panel(mi, m, OUT / f"vp{vi}_{s['sensor_id']}_{band}", band)
                lit = m["S0"] > 0.05 * m["S0"].max()
                srec["bands"][band] = {"s0_mean": float(m["S0"].mean()),
                                       "dop_mean": float(m["dop"][lit].mean())}
                print(f"  [vp{vi} {s['sensor_id']:22s} {band:7s}] S0 {srec['bands'][band]['s0_mean']:.4f} "
                      f"DoP {srec['bands'][band]['dop_mean']:.3f}", flush=True)
            vprec["sensors"].append(srec)
        result["viewpoints"].append(vprec)
    result["n_render"] = n_render
    (OUT / "debug_render.json").write_text(json.dumps(result, indent=1))
    print(f"\n{n_render} renders from 1 resident scene load -> {OUT/'debug_render.json'}")
    return 0


def _save_panel(mi, m, stem: Path, band: str):
    from PIL import Image

    def tm(rgb):
        x = np.clip(rgb, 0, None); x = x / (1 + x)
        return (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)

    def gray(v):
        x = np.clip(v, 0, None); x = x / (1 + x)
        return (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)

    def redblack(d):
        d = np.clip(d, 0, 1)
        return np.stack([(d * 255).astype(np.uint8), np.zeros_like(d, np.uint8), np.zeros_like(d, np.uint8)], -1)

    def hsv(a):  # AoLP -> hue
        import colorsys
        h = ((a + 90) / 180.0) % 1.0
        flat = h.ravel(); rgb = np.array([colorsys.hsv_to_rgb(x, 1, 1) for x in flat])
        return (rgb.reshape(*h.shape, 3) * 255).astype(np.uint8)

    def div(v):  # -1..1 blue-white-red
        t = (np.clip(v, -1, 1) + 1) / 2
        lut = np.array([[0.23, 0.30, 0.75], [1, 1, 1], [0.75, 0.15, 0.15]], np.float32)
        idx = t * 2; lo = np.clip(idx.astype(int), 0, 1); fr = (idx - lo)[..., None]
        return ((lut[lo] * (1 - fr) + lut[np.clip(lo + 1, 0, 2)] * fr) * 255).astype(np.uint8)

    # S0: RGB tonemap for visible, grayscale intensity for nir
    s0img = tm(m["s0_rgb"]) if band == "visible" else gray(m["S0"])
    for name, img in [("s0", s0img), ("dop", redblack(m["dop"])), ("aolp", hsv(m["aolp"])),
                      ("s1s0", div(m["s1s0"])), ("s2s0", div(m["s2s0"])), ("s3s0", div(m["s3s0"]))]:
        Image.fromarray(img).save(f"{stem}_{name}.png")


if __name__ == "__main__":
    raise SystemExit(main())
