#!/usr/bin/env python3
"""Polarization-render QUALIFICATION harness — the mandatory gate every object /
scene polarization experiment must pass FIRST.

Rationale (dev_report 2026-07-06): plausible-looking DoLP images can hide bugs in
the light source, the analyzer, material injection, or the render path
(roughdielectric mis-classified as polarizing, area-emitter+polarizer NEE issues,
S1/S2 swap, AoLP sign). Once the *pipeline* is certified, object experiments can
focus on the object.

Gated stages (a failing stage blocks the next):
  0 config      variant / forbidden-BSDF allowlist / NaN-Inf-negS0 guards
  1 source+analyzer   polarized source Stokes(cos2t/sin2t) + Malus cos^2 + cam-rot
  2 fresnel     flat dielectric Brewster DoLP rise + diffuse depolarization control
  3 spheres     single-material spheres, source-orbit + polarizer-rotation (visual)
  (4 asset-binding / 5 objects / 6 scenes are delegated to their own harnesses,
   which should REQUIRE a passing stage-0..3 qualification id.)

Run:  qualify.py --stages 0 1 2 3
Env:  LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib
      PYTHONPATH=build/mitsuba3-optix7/python  python=~/miniconda3/envs/openusd_pip/bin/python
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "dev_report/images/polar_qualify"
VARIANT = "cuda_ad_rgb_polarized"
FORBIDDEN_BSDF = ("roughdielectric", "thindielectric", "plastic", "roughplastic")
SUBST = {"roughdielectric": "dielectric", "thindielectric": "dielectric",
         "plastic": "pplastic", "roughplastic": "pplastic"}
_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)

# --- pass/fail tolerances (loose to start; tighten once HQ baselines settle) --
TOL = {"stokes_norm": 0.03, "malus": 0.03, "aolp_deg": 2.0, "extinction": 0.03,
       "dop_max": 1.05, "diffuse_dolp": 0.05}


def stokes(img: np.ndarray) -> dict:
    """15-ch stokes image -> luminance-weighted S0..S3, DoLP, AoLP over lit pixels."""
    img = np.nan_to_num(np.asarray(img), nan=0.0, posinf=1e4, neginf=0.0)
    S0 = (img[:, :, 3:6] * _LUM).sum(2)
    S1 = (img[:, :, 6:9] * _LUM).sum(2)
    S2 = (img[:, :, 9:12] * _LUM).sum(2)
    S3 = (img[:, :, 12:15] * _LUM).sum(2)
    m = S0 > (0.2 * S0.max() + 1e-8)  # bright region only
    s0 = float(S0[m].mean())
    s1 = float(S1[m].mean()); s2 = float(S2[m].mean()); s3 = float(S3[m].mean())
    dolp = math.sqrt(s1 * s1 + s2 * s2) / max(s0, 1e-8)
    dop = math.sqrt(s1 * s1 + s2 * s2 + s3 * s3) / max(s0, 1e-8)
    aolp = 0.5 * math.degrees(math.atan2(s2, s1))
    return {"S0": s0, "S1": s1, "S2": s2, "S3": s3, "s1n": s1 / max(s0, 1e-8),
            "s2n": s2 / max(s0, 1e-8), "s3n": s3 / max(s0, 1e-8),
            "DoLP": dolp, "DoP": dop, "AoLP": aolp, "min_S0": float(S0.min())}


# --- per-pixel modality maps + image saving (for visual debugging) --------- #
_VIRIDIS = np.array([[0.267, 0.005, 0.329], [0.254, 0.265, 0.53], [0.164, 0.471, 0.558],
                     [0.135, 0.659, 0.518], [0.478, 0.821, 0.318], [0.993, 0.906, 0.144]], np.float32)
_REDBLACK = np.array([[0, 0, 0], [1, 0, 0]], np.float32)  # DoLP: black 0 -> red 1 (dev_report 07-06 convention)


def _lut(v01, lut):
    idx = np.nan_to_num(np.clip(v01, 0, 1), nan=0.0) * (len(lut) - 1)
    lo = np.floor(idx).astype(int); hi = np.minimum(lo + 1, len(lut) - 1); f = (idx - lo)[..., None]
    return ((lut[lo] * (1 - f) + lut[hi] * f) * 255).astype(np.uint8)


def _hsv(h, s, v):
    i = np.floor(h * 6).astype(int) % 6; f = h * 6 - np.floor(h * 6)
    p = v * (1 - s); q = v * (1 - f * s); t = v * (1 - (1 - f) * s)
    r = np.select([i == j for j in range(6)], [v, q, p, p, t, v])
    g = np.select([i == j for j in range(6)], [t, v, v, q, p, p])
    b = np.select([i == j for j in range(6)], [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def save_modalities(name: str, img: np.ndarray, dolp_vmax: float = 1.0) -> str:
    """Save S0(tonemapped) · DoLP · AoLP · S1/S0 · S2/S0 PNGs for a 15-ch render."""
    try:
        from PIL import Image
    except Exception:
        return name
    a = np.nan_to_num(np.asarray(img), nan=0.0, posinf=1e4, neginf=0.0)
    s0 = np.clip(a[:, :, 3:6], 0, 1e4)
    S0 = np.clip((s0 * _LUM).sum(2), 1e-8, None)
    S1 = (a[:, :, 6:9] * _LUM).sum(2); S2 = (a[:, :, 9:12] * _LUM).sum(2)
    dolp = np.clip(np.sqrt(S1 * S1 + S2 * S2) / S0, 0, 1)
    aolp = 0.5 * np.degrees(np.arctan2(S2, S1))
    x = np.clip(s0, 0, None); x = x / (1 + x)
    rgb = (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(OUT_DIR / f"{name}_rgb.png")
    Image.fromarray(_lut(dolp / max(dolp_vmax, 1e-6), _REDBLACK)).save(OUT_DIR / f"{name}_dolp.png")
    h = (((aolp + 90) / 180) % 1.0); val = np.clip(dolp / max(dolp.max(), 1e-6), 0, 1)
    Image.fromarray((_hsv(h, np.ones_like(h), val) * 255).astype(np.uint8)).save(OUT_DIR / f"{name}_aolp.png")
    div = np.array([[0.23, 0.30, 0.75], [1, 1, 1], [0.75, 0.15, 0.15]], np.float32)
    Image.fromarray(_lut((np.clip(S1 / S0, -1, 1) + 1) / 2, div)).save(OUT_DIR / f"{name}_s1s0.png")
    Image.fromarray(_lut((np.clip(S2 / S0, -1, 1) + 1) / 2, div)).save(OUT_DIR / f"{name}_s2s0.png")
    return name


# --------------------------------------------------------------------------- #
def _mi():
    import mitsuba as mi
    if mi.variant() != VARIANT:
        mi.set_variant(VARIANT)
    return mi


def _rect(mi, P, O, half, up=(0, 1, 0)):
    return (mi.ScalarTransform4f().look_at(origin=P, target=O, up=up)
            @ mi.ScalarTransform4f().scale([half, half, 1.0]))


def _integrator():
    return {"type": "stokes", "nested": {"type": "path", "max_depth": 6}}


def _camera(mi, origin, target, res=256, up=(0, 1, 0), roll_deg=0.0, fov=20.0):
    up = list(up)
    if roll_deg:
        r = math.radians(roll_deg)
        up = [math.sin(r), math.cos(r), 0.0]
    return {"type": "perspective", "fov": float(fov),
            "to_world": mi.ScalarTransform4f().look_at(origin=origin, target=target, up=up),
            "film": {"type": "hdrfilm", "width": res, "height": res, "pixel_format": "rgb"}}


# ------------------------------- STAGE 0 ----------------------------------- #
def stage0_config(mode: str = "self") -> dict:
    """Config-only guards: variant, forbidden-BSDF allowlist, and the substitution
    policy that must be enforced (never silently pass a DoLP=0 material as polarizing)."""
    checks = []
    # a) variant is a polarized variant
    try:
        mi = _mi()
        ok_variant = "polarized" in mi.variant()
    except Exception as exc:
        return {"stage": 0, "passed": False, "checks": [{"name": "variant", "passed": False, "err": str(exc)}]}
    checks.append({"name": "polarized_variant", "passed": ok_variant, "measured": mi.variant()})
    # b) forbidden BSDFs must map to a polarizing substitute (policy is defined)
    policy_ok = all(SUBST.get(b) is not None for b in FORBIDDEN_BSDF)
    checks.append({"name": "forbidden_bsdf_substitution_policy", "passed": policy_ok,
                   "measured": SUBST})
    # c) a smoke render is finite / non-negative S0 (guards NaN/Inf/negS0)
    sc = mi.load_dict({"type": "scene", "integrator": _integrator(),
                       "sensor": _camera(mi, [0, 0, 1.2], [0, 0, 0], res=32),
                       "l": {"type": "constant", "radiance": {"type": "rgb", "value": [0.5, 0.5, 0.5]}},
                       "s": {"type": "sphere", "radius": 0.15, "bsdf": {"type": "conductor", "material": "Al"}}})
    st = stokes(np.array(mi.render(sc, spp=16)))
    finite = np.isfinite(st["S0"]) and st["min_S0"] >= -1e-4 and st["DoP"] <= TOL["dop_max"]
    checks.append({"name": "finite_nonneg_S0_DoP<=1", "passed": bool(finite),
                   "measured": {"min_S0": st["min_S0"], "DoP": round(st["DoP"], 4)}})
    return {"stage": 0, "passed": all(c["passed"] for c in checks), "checks": checks}


# ------------------------------- STAGE 1 ----------------------------------- #
def _mirror_scene(mi, src_theta, ana_theta=None, res=128, roll_deg=0.0):
    """Polarized source (area emitter + linear polarizer at src_theta) illuminates a
    SMOOTH conductor sphere ('mirror'); the camera views the near-normal specular
    highlight, which carries the source's linear polarization. Optional analyzer
    (2nd polarizer at ana_theta) sits in front of the camera. (An area emitter is
    not camera-visible directly, so the source is probed via its mirror reflection.)"""
    O = [0, 0, 0]
    az = math.radians(30)
    P = [0.5 * math.sin(az), 0.18, 0.5 * math.cos(az)]
    d = np.array(O) - np.array(P); d = d / np.linalg.norm(d)
    Pp = (np.array(P) + 0.05 * d).tolist()
    scene = {"type": "scene", "integrator": _integrator(),
             "sensor": _camera(mi, [0, 0.04, 1.2], O, res=res, roll_deg=roll_deg),
             "amb": {"type": "constant", "radiance": {"type": "rgb", "value": [0.005, 0.005, 0.005]}},
             # polarized_area emitter emits already-polarized light -> NEE works,
             # no occluding polarizer surface, no Monte-Carlo streak noise.
             "flash": {"type": "rectangle", "to_world": _rect(mi, P, O, 0.1),
                       "emitter": {"type": "polarized_area", "radiance": {"type": "rgb", "value": [80, 80, 80]},
                                   "theta": float(src_theta)},
                       "bsdf": {"type": "null"}},
             "mirror": {"type": "sphere", "radius": 0.15,
                        "bsdf": {"type": "conductor", "material": "Al"}}}
    if ana_theta is not None:
        # analyzer just in front of the camera, facing the sphere
        scene["anapol"] = {"type": "rectangle", "to_world": _rect(mi, [0, 0.04, 0.9], O, 0.12),
                           "bsdf": {"type": "polarizer", "theta": float(ana_theta)}}
    return scene


def _malus_grid_scene(mi, res=256, src_theta=0.0):
    """Direct Malus (no reflection path): a large polarized_area emitter (source
    at 0 deg) fills the background, and FOUR analyzer polarizer patches at
    0/45/90/135 deg sit in front in a 2x2 grid. Camera pulled back so the polarized
    background AND the four patches show together -> the whole cos^2 extinction
    pattern in ONE render. No metal reflection, so no Mueller rotation asymmetry."""
    O = [0, 0, 0.5]
    scene = {"type": "scene", "integrator": _integrator(),
             "sensor": _camera(mi, [0, 0, 1.9], O, res=res, fov=45.0),
             # background = already-polarized source at 0 deg (NEE-clean, no occluder)
             # NO null bsdf here: the camera VIEWS this emitter directly, and a null
             # bsdf makes the ray pass through without registering emission (S0=0).
             "emit": {"type": "rectangle", "to_world": _rect(mi, [0, 0, 0.0], [0, 0, 1], 1.6),
                      "emitter": {"type": "polarized_area", "radiance": {"type": "rgb", "value": [6, 6, 6]},
                                  "theta": float(src_theta)}}}
    # 2x2 grid of analyzers; quadrant order matches image quadrants for sampling
    grid = [(-0.32, 0.32, 0.0), (0.32, 0.32, 45.0), (-0.32, -0.32, 90.0), (0.32, -0.32, 135.0)]
    for i, (x, y, th) in enumerate(grid):
        scene[f"ana{i}"] = {"type": "rectangle", "to_world": _rect(mi, [x, y, 0.7], [x, y, 1], 0.24),
                            "bsdf": {"type": "polarizer", "theta": th}}
    return scene, grid


def stage1_source_analyzer(spp=256) -> dict:
    mi = _mi()
    checks = []
    # 1-1 rotate source polarizer -> reflected light stays highly polarized (DoLP high,
    #     S3~0) and AoLP rotates ~1:1 with the source polarizer angle.
    ang = [0, 45, 90, 135]
    imgs = {}
    for t in ang:
        arr = np.array(mi.render(mi.load_dict(_mirror_scene(mi, t)), spp=spp))
        imgs[t] = arr
        save_modalities(f"s1_src{t}", arr)
    meas = {t: stokes(imgs[t]) for t in ang}
    images = [{"name": f"s1_src{t}", "label": f"광원 편광 {t}°"} for t in ang]
    dolp_ok = all(meas[t]["DoLP"] > 0.6 for t in ang)
    s3_ok = all(abs(meas[t]["s3n"]) < 0.15 for t in ang)
    # AoLP tracks source angle: unwrap the AoLP-vs-theta slope (pi-periodic) -> ~ +/-1
    a0 = meas[0]["AoLP"]
    dang = [((meas[t]["AoLP"] - a0 - t + 90) % 180) - 90 for t in ang]  # residual vs 1:1 tracking
    track_ok = all(abs(x) < 12 for x in dang)  # within 12 deg of 1:1
    checks.append({"name": "1-1_reflected_DoLP_high", "passed": bool(dolp_ok),
                   "measured": {t: round(meas[t]["DoLP"], 3) for t in ang}})
    checks.append({"name": "1-1_S3~0_linear", "passed": bool(s3_ok),
                   "measured": {t: round(meas[t]["s3n"], 3) for t in ang}})
    checks.append({"name": "1-1_AoLP_tracks_source_angle(1:1)", "passed": bool(track_ok),
                   "measured": {t: round(meas[t]["AoLP"], 1) for t in ang}})
    # 1-1b raw DoP (NO pre-clip): physical Stokes bound is S0 >= sqrt(S1^2+S2^2+S3^2)
    # i.e. DoP <= 1. Report raw max + 99.9th pct over lit pixels; MC noise can push a
    # few pixels slightly over 1 (display clipping only, never before the numeric judgment).
    a0 = np.nan_to_num(imgs[0])
    S0p = (a0[:, :, 3:6] * _LUM).sum(2); S1p = (a0[:, :, 6:9] * _LUM).sum(2)
    S2p = (a0[:, :, 9:12] * _LUM).sum(2); S3p = (a0[:, :, 12:15] * _LUM).sum(2)
    # bright region only (grazing rim pixels have tiny S0 -> the ratio is MC-unstable)
    lit = S0p > 0.4 * S0p.max()
    dop = np.sqrt(S1p ** 2 + S2p ** 2 + S3p ** 2) / np.clip(S0p, 1e-8, None)
    dop_max = float(dop[lit].max()); dop_999 = float(np.percentile(dop[lit], 99.9))
    DOP_EPS = 0.10  # MC noise can push a few bright pixels slightly over the DoP<=1 bound
    checks.append({"name": "1-1b_raw_DoP<=1+eps (pre-clip=none, bright region)", "passed": dop_999 <= 1 + DOP_EPS,
                   "measured": {"raw_max_DoP": round(dop_max, 4), "p99.9_DoP": round(dop_999, 4),
                                "epsilon": DOP_EPS}})
    # 1-2 Malus (DIRECT, no reflection): one render of a polarized background seen
    # through a 2x2 grid of analyzers at 0/45/90/135. Judged on LINEAR S0 means of
    # the four patch regions (not tonemapped PNG). cos^2: [1, 0.5, 0.5, 0] of I0.
    gscene, grid = _malus_grid_scene(mi, res=256)
    garr = np.array(mi.render(mi.load_dict(gscene), spp=spp))
    save_modalities("s1_malus_grid", garr)
    images.append({"name": "s1_malus_grid", "label": "Malus 그리드 0/45/90/135° (좌상→우상→좌하→우하)"})
    S0g = (np.nan_to_num(garr)[:, :, 3:6] * _LUM).sum(2)
    H, W = S0g.shape
    def patch(cx, cy, r=0.10):
        x0, x1 = int((cx - r) * W), int((cx + r) * W)
        y0, y1 = int((cy - r) * H), int((cy + r) * H)
        return float(S0g[y0:y1, x0:x1].mean())
    # sample the 4 image quadrant centres (each analyzer fills its quadrant)
    quads = [patch(0.28, 0.28), patch(0.72, 0.28), patch(0.28, 0.72), patch(0.72, 0.72)]
    I0 = max(quads); order = sorted(quads)
    Imin, mid1, mid2, Imax = order[0], order[1], order[2], order[3]
    n = lambda v: v / max(Imax, 1e-8)  # normalize by the brightest (parallel) patch
    malus_ok = (n(Imin) < 0.02 and abs(n(mid1) - 0.5) < 0.03 and abs(n(mid2) - 0.5) < 0.03
                and abs(n(mid1) - n(mid2)) < 0.03)
    checks.append({"name": "1-2_malus_grid_cos2 (linear, |I45,I135-0.5|<0.03, I90/I0<0.02)",
                   "passed": bool(malus_ok),
                   "measured": {"I90/I0": round(n(Imin), 4), "I45~": round(n(mid1), 4),
                                "I135~": round(n(mid2), 4), "|I45-I135|": round(abs(n(mid1) - n(mid2)), 4)}})
    # 1-3 camera roll 90deg: S0 & DoLP invariant, AoLP shifts with the frame
    st0 = stokes(np.array(mi.render(mi.load_dict(_mirror_scene(mi, 30)), spp=spp)))
    stR = stokes(np.array(mi.render(mi.load_dict(_mirror_scene(mi, 30, roll_deg=90)), spp=spp)))
    inv_ok = (abs(st0["S0"] - stR["S0"]) / max(st0["S0"], 1e-8) < 0.15
              and abs(st0["DoLP"] - stR["DoLP"]) < 0.10)
    checks.append({"name": "1-3_camroll_S0_DoLP_invariant", "passed": bool(inv_ok),
                   "measured": {"dS0_rel": round(abs(st0["S0"] - stR["S0"]) / max(st0["S0"], 1e-8), 3),
                                "dDoLP": round(abs(st0["DoLP"] - stR["DoLP"]), 3),
                                "AoLP_0": round(st0["AoLP"], 1), "AoLP_roll": round(stR["AoLP"], 1)}})
    return {"stage": 1, "passed": all(c["passed"] for c in checks), "checks": checks, "images": images}


# ------------------------------- STAGE 2 ----------------------------------- #
def _flat_fresnel_scene(mi, bsdf, inc_deg, res=96):
    """Unpolarized light hits a flat plane at incidence inc_deg; camera at the
    specular direction. Returns the reflected polarization."""
    inc = math.radians(inc_deg)
    d = 1.0
    # plane at origin, normal +Y (up). light and camera in the x-y plane at inc from normal.
    L = [-d * math.sin(inc), d * math.cos(inc), 0]
    C = [d * math.sin(inc), d * math.cos(inc), 0]
    scene = {"type": "scene", "integrator": _integrator(),
             "sensor": _camera(mi, C, [0, 0, 0], res=res, up=(0, 0, 1)),
             "plane": {"type": "rectangle",
                       "to_world": mi.ScalarTransform4f().rotate([1, 0, 0], -90).scale(2.0),
                       "bsdf": bsdf},
             # small unpolarized area light at L
             "light": {"type": "rectangle", "to_world": _rect(mi, L, [0, 0, 0], 0.25),
                       "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [30, 30, 30]}},
                       "bsdf": {"type": "null"}}}
    return scene


def stage2_fresnel(spp=512) -> dict:
    mi = _mi()
    checks = []
    angles = [10, 20, 40, 50, 56, 60, 70, 80]  # skip 0deg (degenerate light==camera)
    images = []
    # 2-1 dielectric: DoLP should rise to a peak near Brewster (~56 deg for n=1.5)
    diel = {}
    for t in angles:
        arr = np.array(mi.render(mi.load_dict(_flat_fresnel_scene(mi, {"type": "dielectric", "int_ior": 1.5}, t)), spp=spp))
        diel[t] = stokes(arr)["DoLP"]
        if t in (20, 56, 80):
            save_modalities(f"s2_diel{t}", arr)
            images.append({"name": f"s2_diel{t}", "label": f"유전체 입사 {t}° (Brewster≈56°)"})
    diel = {t: (v if np.isfinite(v) else 0.0) for t, v in diel.items()}
    peak_ang = max(diel, key=diel.get)
    brewster_ok = 45 <= peak_ang <= 70 and diel[peak_ang] > 0.6 and diel[angles[0]] < 0.25
    checks.append({"name": "2-1_dielectric_brewster_DoLP_peak", "passed": bool(brewster_ok),
                   "measured": {"peak_angle": peak_ang, "DoLP": {t: round(diel[t], 3) for t in angles}}})
    # 2-3 diffuse control: DoLP ~ 0 at all angles
    diff = {}
    for t in (20, 50, 70):
        arr = np.array(mi.render(mi.load_dict(
            _flat_fresnel_scene(mi, {"type": "diffuse", "reflectance": {"type": "rgb", "value": [0.5, 0.5, 0.5]}}, t)), spp=spp))
        diff[t] = stokes(arr)["DoLP"]
        if t == 50:
            save_modalities("s2_diffuse50", arr)
            images.append({"name": "s2_diffuse50", "label": "확산 대조군 50° (DoLP≈0)"})
    diffuse_ok = all(v < TOL["diffuse_dolp"] + 0.03 for v in diff.values())
    checks.append({"name": "2-3_diffuse_depolarizes", "passed": bool(diffuse_ok),
                   "measured": {t: round(v, 3) for t, v in diff.items()}})
    return {"stage": 2, "passed": all(c["passed"] for c in checks), "checks": checks, "images": images}


# ------------------------------- STAGE 3 ----------------------------------- #
def stage3_spheres(spp=512) -> dict:
    """Single-material spheres, source-orbit; metal high DoLP, diffuse ~0, glass
    specular-only. Qualitative + basic sign checks. Saves panels."""
    mi = _mi()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # coloured diffuse/pplastic so the S0 panel demonstrates RGB colour reproduction
    # CONTROLLED metrology scene: smooth materials, dark surround, single polarized
    # flash. Do NOT add environment/roughness here to make it pretty -- that weakens
    # the qualification's control. Natural appearance lives in Stage 3-V (non-gated).
    # Names are exact: lambertian = pure `diffuse` (must depolarize ~0, like the
    # Stage-2 flat diffuse control); coated_diffuse = `pplastic` (weak coating Fresnel
    # polarization, so NOT a zero control).
    mats = {"lambertian_red": {"type": "diffuse", "reflectance": {"type": "rgb", "value": [0.72, 0.16, 0.14]}},
            "coated_diffuse_red": {"type": "pplastic", "diffuse_reflectance": {"type": "rgb", "value": [0.72, 0.16, 0.14]}, "int_ior": 1.5},
            "coated_diffuse_green": {"type": "pplastic", "diffuse_reflectance": {"type": "rgb", "value": [0.18, 0.6, 0.22]}, "int_ior": 1.5},
            "metal": {"type": "roughconductor", "material": "Al", "alpha": 0.05},
            "gold": {"type": "roughconductor", "material": "Au", "alpha": 0.08},
            "glass": {"type": "dielectric", "int_ior": 1.5}}
    O = [0, 0, 0]
    az = math.radians(60)
    P = [0.5 * math.sin(az), 0.2, 0.5 * math.cos(az)]
    dvec = np.array(O) - np.array(P); dvec = dvec / np.linalg.norm(dvec)
    Pp = (np.array(P) + 0.05 * dvec).tolist()
    res = {}
    for name, bsdf in mats.items():
        scene = {"type": "scene", "integrator": _integrator(),
                 "sensor": _camera(mi, [0, 0.05, 1.2], O, res=192),
                 "amb": {"type": "constant", "radiance": {"type": "rgb", "value": [0.07, 0.07, 0.08]}},
                 "flash": {"type": "rectangle", "to_world": _rect(mi, P, O, 0.1),
                           "emitter": {"type": "polarized_area", "radiance": {"type": "rgb", "value": [80] * 3},
                                       "theta": 0.0},
                           "bsdf": {"type": "null"}},
                 "s": {"type": "sphere", "radius": 0.15, "bsdf": bsdf}}
        try:
            arr = np.array(mi.render(mi.load_dict(scene), spp=spp))
            st = stokes(arr)
            res[name] = round(st["DoLP"], 3)
            save_modalities(f"s3_{name}", arr)
        except Exception as exc:
            res[name] = f"ERR:{exc}"
    # NOTE: these DoLP values are measured under THIS polarized flash / camera setup
    # over the selected bright specular region -- they are not fixed material constants.
    checks = [
        {"name": "3_metal_specular_DoLP_high (this setup, selected region)", "passed": isinstance(res.get("metal"), float) and res["metal"] > 0.3, "measured": res.get("metal")},
        {"name": "3_lambertian_depolarizes(~0, pure diffuse control)", "passed": isinstance(res.get("lambertian_red"), float) and res["lambertian_red"] < 0.05,
         "measured": res.get("lambertian_red")},
        {"name": "3_coated_diffuse_weak_polar(pplastic coat)", "passed": all(isinstance(res.get(n), float) and 0.0 <= res[n] < 0.30 for n in ("coated_diffuse_red", "coated_diffuse_green")),
         "measured": {n: res.get(n) for n in ("coated_diffuse_red", "coated_diffuse_green")}},
        {"name": "3_glass_specular_polarizes (this setup)", "passed": isinstance(res.get("glass"), float) and res["glass"] > 0.1, "measured": res.get("glass")},
    ]
    images = [{"name": f"s3_{n}", "label": n} for n in mats if isinstance(res.get(n), float)]
    return {"stage": 3, "passed": all(c["passed"] for c in checks), "checks": checks, "dolp": res, "images": images}


# ------------------------------- STAGE 3-V --------------------------------- #
def _studio_env_exr(mi) -> str:
    """Procedural studio softbox environment (no external HDR / no license).
    Equirect gradient: warm-bright zenith -> mid horizon -> dark floor, plus a
    bright elliptical softbox high-front. Chrome/gold reflect this and finally
    read as METAL instead of a coloured glass blob. Written once to OUT_DIR."""
    p = OUT_DIR / "studio_env.exr"
    if p.is_file():
        return str(p)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    H, W = 128, 256
    el = np.linspace(1.0, -1.0, H)[:, None]              # +1 zenith .. -1 nadir
    az = np.linspace(-math.pi, math.pi, W)[None, :]
    base = np.where(el >= 0, 0.55 + 0.9 * np.clip(el, 0, None) ** 0.7, 0.14 + 0.06 * (1 + el))  # sky vs floor
    # soft elliptical key softbox, high and slightly front-left
    box = 1.8 * np.exp(-(((el - 0.55) / 0.28) ** 2 + ((az - (-0.5)) / 0.6) ** 2))
    lum = np.clip(base + box, 0.03, None).astype(np.float32)
    rgb = np.stack([lum * 1.0, lum * 0.99, lum * 0.97], -1)  # near-neutral, faint warm
    rgb = np.ascontiguousarray(rgb, np.float32)
    mi.Bitmap(rgb, mi.Bitmap.PixelFormat.RGB).write(str(p))
    return str(p)


def _studio_scene(mi, bsdf, polarized: bool, theta: float = 0.0, res=256):
    """Non-gated studio material-preview scene: a sphere on an 18% gray floor with a
    gray back cove, viewed 3/4. Metals need an environment to reflect, so this scene
    is DELIBERATELY dressed (unlike the controlled Stage-3 metrology scene) — a
    procedural softbox envmap gives chrome/gold full-sphere reflections.
      polarized=False -> envmap(full) + product 3-point (unpolarized) : appearance pass
      polarized=True  -> key is polarized_area(theta); env+fill/rim dimmed : polarization pass
        (env is unpolarized, so it is dimmed in the polar pass to keep DoLP source-driven.)
    Off-frame emitters use a null bsdf (illumination only; NEE unaffected)."""
    O = [0, 0, 0]
    key_rad = 14.0
    dim = 0.05 if polarized else 1.0
    env_scale = 0.12 if polarized else 1.0
    key_emitter = ({"type": "polarized_area", "radiance": {"type": "rgb", "value": [key_rad] * 3}, "theta": float(theta)}
                   if polarized else
                   {"type": "area", "radiance": {"type": "rgb", "value": [key_rad] * 3}})
    scene = {"type": "scene", "integrator": _integrator(),
             "sensor": _camera(mi, [0.34, 0.22, 0.9], O, res=res, fov=32.0),
             "env": {"type": "envmap", "filename": _studio_env_exr(mi), "scale": env_scale,
                     "to_world": mi.ScalarTransform4f().rotate([0, 1, 0], 150.0)},
             "floor": {"type": "rectangle",
                       "to_world": mi.ScalarTransform4f().translate([0, -0.16, 0]).rotate([1, 0, 0], -90).scale(3.0),
                       "bsdf": {"type": "diffuse", "reflectance": {"type": "rgb", "value": [0.18] * 3}}},
             "cove": {"type": "rectangle",
                      "to_world": mi.ScalarTransform4f().translate([0, 0.4, -0.7]).scale(3.0),
                      "bsdf": {"type": "diffuse", "reflectance": {"type": "rgb", "value": [0.2] * 3}}},
             "key": {"type": "rectangle", "to_world": _rect(mi, [-0.55, 0.55, 0.6], O, 0.3),
                     "emitter": key_emitter, "bsdf": {"type": "null"}},
             "fill": {"type": "rectangle", "to_world": _rect(mi, [0.6, 0.1, 0.7], O, 0.28),
                      "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [key_rad * 0.25 * dim] * 3}},
                      "bsdf": {"type": "null"}},
             "rim": {"type": "rectangle", "to_world": _rect(mi, [0.2, 0.55, -0.45], O, 0.16),
                     "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [key_rad * 0.6 * dim] * 3}},
                     "bsdf": {"type": "null"}},
             # black card opposite the key -> dark reflection band that reads curvature on metal
             "blackcard": {"type": "rectangle", "to_world": _rect(mi, [0.7, 0.15, 0.9], O, 0.4),
                           "bsdf": {"type": "diffuse", "reflectance": {"type": "rgb", "value": [0.02] * 3}}},
             "s": {"type": "sphere", "radius": 0.15, "bsdf": bsdf}}
    return scene


def stage3v_studio(spp=4000) -> dict:
    """INFO (non-gated): studio material preview, appearance vs polarization passes.
    Appearance pass = natural metal/glass look (S0); polarization pass = DoLP/AoLP.
    Does NOT affect the gate PASS/FAIL."""
    mi = _mi()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mats = {"metal_Al": {"type": "roughconductor", "material": "Al", "alpha": 0.12},
            "gold_Au": {"type": "roughconductor", "material": "Au", "alpha": 0.2},
            "glass": {"type": "dielectric", "int_ior": 1.5},
            "coated_diffuse_red": {"type": "pplastic", "diffuse_reflectance": {"type": "rgb", "value": [0.72, 0.16, 0.14]}, "int_ior": 1.5}}
    images = []
    for name, bsdf in mats.items():
        # A: appearance (unpolarized 3-point) -> S0 only
        try:
            aA = np.array(mi.render(mi.load_dict(_studio_scene(mi, bsdf, polarized=False)), spp=spp))
            save_modalities(f"s3v_{name}_appear", aA)
        except Exception as exc:
            print(f"  [3v {name} appear] ERR {exc}")
        # B: polarization (polarized key) -> S0/DoLP/AoLP/S1S0/S2S0
        try:
            aB = np.array(mi.render(mi.load_dict(_studio_scene(mi, bsdf, polarized=True, theta=0.0)), spp=spp))
            save_modalities(f"s3v_{name}_polar", aB)
        except Exception as exc:
            print(f"  [3v {name} polar] ERR {exc}")
        images.append({"name": name})
    return {"stage": "3V", "passed": True, "info": True,
            "checks": [{"name": "3V_studio_preview (INFO, non-gated)", "passed": True,
                        "measured": "appearance vs polarization passes rendered", "note": "visual only"}],
            "studio_images": images}


STAGES = {0: stage0_config, 1: stage1_source_analyzer, 2: stage2_fresnel, 3: stage3_spheres,
          "3V": stage3v_studio}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", nargs="*", type=int, default=[0, 1, 2, 3])
    ap.add_argument("--no-gate", action="store_true", help="run all stages even if one fails")
    ap.add_argument("--spp", type=int, default=None, help="override spp for stages 1-3 (report-quality images, e.g. 10000)")
    a = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {"variant": VARIANT, "spp": a.spp, "stages": []}
    overall = True
    for s in sorted(a.stages):
        t = time.time()
        r = STAGES[s](spp=a.spp) if (a.spp and s != 0) else STAGES[s]()
        r["seconds"] = round(time.time() - t, 1)
        results["stages"].append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[stage {s}] {status} ({r['seconds']}s)")
        for c in r["checks"]:
            print(f"    {'ok' if c['passed'] else 'XX'}  {c['name']}: {c.get('measured')}")
        if not r["passed"]:
            overall = False
            if not a.no_gate:
                print(f"  -> GATE: stage {s} failed, halting (downstream experiments must not run)")
                break
    results["passed"] = overall
    results["qualification_id"] = f"polqual-{'PASS' if overall else 'FAIL'}"
    (OUT_DIR / "qualification.json").write_text(json.dumps(results, indent=2))
    print(f"\nqualification: {'PASS' if overall else 'FAIL'} -> {OUT_DIR/'qualification.json'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
