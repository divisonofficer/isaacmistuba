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


# ------------------------------------------------------ depth + lidar ------- #
_SEQ = np.array([[0.27, 0.00, 0.33], [0.13, 0.57, 0.55], [0.99, 0.91, 0.14]], np.float32)  # viridis-ish


def _seq_cmap(v, valid=None, lo=None, hi=None):
    """Sequential colormap (near→far) with NaN/miss → black. Percentile-normalized."""
    v = np.asarray(v, np.float32)
    m = np.isfinite(v) if valid is None else (valid & np.isfinite(v))
    out = np.zeros((*v.shape, 3), np.uint8)
    if not m.any():
        return out
    lo = np.percentile(v[m], 2) if lo is None else lo
    hi = np.percentile(v[m], 98) if hi is None else hi
    t = np.nan_to_num(np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1), nan=0.0)
    idx = t * 2
    a = np.clip(idx.astype(int), 0, 1); fr = (idx - a)[..., None]
    rgb = _SEQ[a] * (1 - fr) + _SEQ[np.clip(a + 1, 0, 2)] * fr
    out[m] = (np.clip(rgb, 0, 1)[m] * 255).astype(np.uint8)
    return out


def render_depth(mi, scene, spp=64) -> np.ndarray:
    """AOV camera depth (distance from pinhole) through the current sensor pose."""
    integ = mi.load_dict({"type": "aov", "aovs": "dd:depth",
                          "integrator": {"type": "path", "max_depth": 2}})
    img = np.array(integ.render(scene, spp=spp))
    return np.nan_to_num(img[:, :, -1], nan=0.0)   # last channel = depth


def render_lidar(mi, scene, origin, yaw_rad, n_rings=128, n_az=1024, vfov_deg=45.0,
                 specular_bounces=6):
    """Spinning-LiDAR range image (Ouster OS1-128-like) by ray-casting the resident
    scene from `origin`. Azimuth 0 aligned to robot heading (yaw).

    Physical specular behaviour (specular_bounces>0): a real LiDAR beam does NOT stop at
    a mirror/glass surface — it reflects/refracts and ranges the geometry it reaches via
    that folded path. So on a **delta** (perfect mirror / smooth dielectric) hit we
    follow the sampled specular direction and keep accumulating path length until a
    diffuse/rough return; only then is the range recorded. specular_bounces=0 reproduces
    the naive 'stops at first surface' cast (recognises mirrors as opaque — not physical).

    Returns (range[n_rings×n_az] metres NaN=no return, spec_mask[...] = went through ≥1
    specular bounce). NOTE: geometric ranging — TRUE transient ToF LiDAR (depth_transient)
    still needs mitransient + a transient variant (unavailable in the OptiX7 build)."""
    import drjit as dr
    el = np.deg2rad(np.linspace(vfov_deg / 2, -vfov_deg / 2, n_rings))[:, None]
    az = np.deg2rad(np.linspace(0, 360, n_az, endpoint=False))[None, :] + yaw_rad
    dx = (np.cos(el) * np.sin(az)).ravel().astype("float32")
    dy = np.broadcast_to(np.sin(el), (n_rings, n_az)).ravel().astype("float32")
    dz = (np.cos(el) * np.cos(az)).ravel().astype("float32")
    n = dx.size
    o = mi.Point3f(np.full(n, float(origin[0]), "float32"),
                   np.full(n, float(origin[1]), "float32"),
                   np.full(n, float(origin[2]), "float32"))
    ray = mi.Ray3f(o, mi.Vector3f(dx, dy, dz))
    ctx = mi.BSDFContext()
    total = dr.zeros(mi.Float, n)          # accumulated path length
    rng = dr.full(mi.Float, dr.inf, n)     # recorded range at first diffuse return
    spec = dr.zeros(mi.Float, n)           # 1 if a specular bounce happened
    active = dr.full(mi.Bool, True, n)
    for b in range(int(specular_bounces) + 1):
        si = scene.ray_intersect(ray, active)
        hit = si.is_valid() & active
        total = dr.select(hit, total + si.t, total)
        bs, _ = si.bsdf().sample(ctx, si, 0.0, mi.Point2f(0.0, 0.0), hit)
        is_delta = mi.has_flag(bs.sampled_type, mi.BSDFFlags.Delta) & hit
        # diffuse/rough return (or last allowed bounce) -> record range here
        finalize = hit & (~is_delta | (b == int(specular_bounces)))
        rng = dr.select(finalize, total, rng)
        spec = dr.select(is_delta, mi.Float(1.0), spec)
        wo_w = si.to_world(bs.wo)
        ray = mi.Ray3f(si.p + wo_w * 1e-4, wo_w)
        active = is_delta & (mi.UInt32(b) < int(specular_bounces))
        if not bool(dr.any(active)):
            break
    r = np.array(rng); r = np.where(np.isfinite(r) & (r < 1e30), r, np.nan)
    return r.reshape(n_rings, n_az), np.array(spec).reshape(n_rings, n_az) > 0.5


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
    ap.add_argument("--no-depth", action="store_true", help="skip per-sensor AOV depth map")
    ap.add_argument("--no-lidar", action="store_true", help="skip per-viewpoint geometric LiDAR range cast")
    ap.add_argument("--lidar-rings", type=int, default=128, help="LiDAR vertical channels (OS1-128=128)")
    ap.add_argument("--lidar-az", type=int, default=1024, help="LiDAR azimuth samples per revolution")
    ap.add_argument("--lidar-height", type=float, default=1.0, help="LiDAR mount height (m) above the viewpoint")
    ap.add_argument("--lidar-specular", type=int, default=6,
                    help="follow N specular (mirror/glass) bounces so LiDAR ranges reflected geometry (0=naive, stops at first surface)")
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
            # depth (AOV) — same sensor pose, band-independent
            if not a.no_depth:
                from PIL import Image
                dep = render_depth(mi, scene, spp=min(a.spp, 256))
                Image.fromarray(_seq_cmap(dep, valid=dep > 0)).save(OUT / f"vp{vi}_{s['sensor_id']}_depth.png")
                dv = dep[dep > 0]
                srec["depth"] = {"valid_frac": round(float((dep > 0).mean()), 3),
                                 "min_m": round(float(dv.min()), 2) if dv.size else None,
                                 "max_m": round(float(dv.max()), 2) if dv.size else None}
                print(f"  [vp{vi} {s['sensor_id']:22s} depth  ] valid {srec['depth']['valid_frac']*100:.0f}% "
                      f"{srec['depth']['min_m']}–{srec['depth']['max_m']} m", flush=True)
            vprec["sensors"].append(srec)
        # LiDAR (geometric spinning range cast) — one per viewpoint from robot origin
        if not a.no_lidar:
            from PIL import Image
            lorigin = _mat4_from_xy_yaw(vp["x"], vp["y"], yaw_rad, height_m=a.lidar_height)[:3, 3]
            rng, spec = render_lidar(mi, scene, lorigin, yaw_rad, n_rings=a.lidar_rings,
                                     n_az=a.lidar_az, specular_bounces=a.lidar_specular)
            Image.fromarray(_seq_cmap(rng, valid=np.isfinite(rng))).save(OUT / f"vp{vi}_lidar.png")
            # specular overlay: red-tint the returns that came via a mirror/glass bounce
            base = _seq_cmap(rng, valid=np.isfinite(rng)).astype(np.float32)
            base[spec] = base[spec] * 0.4 + np.array([210, 40, 40], np.float32) * 0.6
            Image.fromarray(base.astype(np.uint8)).save(OUT / f"vp{vi}_lidar_specular.png")
            rv = rng[np.isfinite(rng)]
            vprec["lidar"] = {"rings": a.lidar_rings, "az": a.lidar_az,
                              "specular_bounces": a.lidar_specular,
                              "hit_frac": round(float(np.isfinite(rng).mean()), 3),
                              "specular_frac": round(float(spec.mean()), 3),
                              "min_m": round(float(rv.min()), 2) if rv.size else None,
                              "max_m": round(float(rv.max()), 2) if rv.size else None}
            print(f"  [vp{vi} LiDAR {a.lidar_rings}x{a.lidar_az} spec{a.lidar_specular}] hit "
                  f"{vprec['lidar']['hit_frac']*100:.0f}% specular {vprec['lidar']['specular_frac']*100:.1f}% "
                  f"{vprec['lidar']['min_m']}–{vprec['lidar']['max_m']} m", flush=True)
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
