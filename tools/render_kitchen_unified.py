#!/usr/bin/env python3
"""Kitchen QA via the UNIFIED discrete-band Stokes carrier.

Replaces the old 3-separate-passes harness (RGB passive · pseudo-NIR-albedo-swap flash ·
polar) with the unified pipeline: ONE band carrier scene (material_pipeline.spectral_band
wraps every material into blendbsdf(weight, __vis, __nir)) is loaded once under
cuda_ad_rgb_polarized; per viewpoint we flip the per-material band weight (0 = visible,
1 = NIR) via mi.traverse params — no reload — and render Stokes, giving RGB, NIR and
DoP/AoLP for both bands from the SAME BSDF + physical params (only the diffuse albedo
differs per band: __nir carries the hybrid NIR reflectance). Metals/glass keep their
Fresnel, and both bands share the same passive lighting + max_depth 8, so glass transmits
and metal reflects consistently — no flash / max_depth artifacts.

    LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib \
    PYTHONPATH=build/mitsuba3-optix7/python python tools/render_kitchen_unified.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
for m in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO / "modules" / m / "src"))
sys.path.insert(0, str(REPO / "tools"))

from render_kitchen_multimodal import cam_for, EYE_H, aolp_to_rgb, save_png  # noqa: E402
from mitsuba_converter.material_pipeline.spectral_band import build_band_scene  # noqa: E402
from robomituba_bridge import resolve_viewpoint_pose  # noqa: E402

SCENES = REPO / "out/opticalnav/opticalnav-v0.2/scenes"
VARIANT = "cuda_ad_rgb_polarized"
_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)
WEIGHT_RE = re.compile(r"^.*\.weight\.value$")
BAND_WEIGHT = {"visible": 0.0, "nir": 1.0}


def _declutter_fireflies(s0: np.ndarray, ratio: float = 3.0) -> np.ndarray:
    """PREVIEW-PNG-ONLY cosmetic. Replace any pixel exceeding `ratio`× its 3×3 local
    median with that median, to calm the active-flash caustic specks in a contact-sheet
    thumbnail. NEVER applied to the raw float EXR: the raw GT/observation must stay
    unclamped (clamping cuts bright-path energy and falsifies both the inverse-rendering
    target and the sensor-faithful observation). Off by default; --preview-despeckle only."""
    try:
        from scipy.ndimage import median_filter
        med = median_filter(s0, size=3)
    except Exception:
        p = np.pad(s0, 1, mode="edge")
        med = np.median(np.stack([p[i:i + s0.shape[0], j:j + s0.shape[1]]
                                  for i in range(3) for j in range(3)]), axis=0)
    mask = s0 > med * ratio + 1e-4
    return np.where(mask, med, s0)


def save_exr(arr: np.ndarray, path) -> None:
    """Write an UNCLAMPED float32 EXR (raw GT/observation). HxW → Y, HxWxC → multichannel.
    Signed values (e.g. ΔI = I_on − I_off) are preserved verbatim."""
    import mitsuba as mi
    a = np.ascontiguousarray(np.asarray(arr, np.float32))
    if a.ndim == 2:
        a = a[..., None]
    mi.Bitmap(a).write(str(path))


def _nir_preview_png(s0: np.ndarray, path, despeckle: bool = False) -> None:
    """p99-normalized gamma preview of a NIR intensity field. Despeckle is cosmetic and
    off by default; the raw EXR beside it is the untouched signal."""
    v = _declutter_fireflies(s0) if despeckle else s0
    vn = np.clip(v / max(np.percentile(v, 99), 1e-6), 0, 1)
    Image.fromarray((vn ** (1 / 2.2) * 255).astype(np.uint8)).save(path)


def stokes(arr: np.ndarray) -> dict:
    s0_rgb = arr[:, :, 3:6].astype(np.float32)
    S0 = np.clip((s0_rgb * _LUM).sum(2), 1e-8, None)
    S1 = (arr[:, :, 6:9] * _LUM).sum(2)
    S2 = (arr[:, :, 9:12] * _LUM).sum(2)
    dolp = np.clip(np.sqrt(S1 * S1 + S2 * S2) / S0, 0, 1)
    aolp = np.degrees(0.5 * np.arctan2(S2, S1))
    return {"s0_rgb": s0_rgb, "S0": S0, "dolp": dolp.astype(np.float32),
            "aolp": np.nan_to_num(aolp).astype(np.float32)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scene-id", default="infinigen_single_room_kitchen_20260730")
    ap.add_argument("--viewpoints", default="vp_000005@180,vp_000009@180,vp_000016@240,vp_000012@180")
    ap.add_argument("--out", default="dev_report/images/kitchen_multimodal_2026-07-31")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fov", type=float, default=60.0)
    ap.add_argument("--spp", type=int, default=256)
    ap.add_argument("--band", type=int, default=854)
    ap.add_argument("--max-depth", type=int, default=8,
                    help="path max_depth for the OBSERVATION passes (RGB/NIR passive/active); "
                         "8 = glass transmits. The flash-only GT uses a `direct` integrator.")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the band carrier scene")
    ap.add_argument("--nir-flash", action="store_true",
                    help="active-NIR flash protocol: renders NIR passive (I_off), NIR active "
                         "(I_on = ambient+flash), ΔI = I_on−I_off, and a flash-only `direct` GT")
    ap.add_argument("--nir-radiance", type=float, default=400.0,
                    help="point-intensity-equivalent; converted to area radiance = I/(4·half²)")
    ap.add_argument("--nir-half", type=float, default=0.015, help="NIR flash rectangle half-size (m)")
    ap.add_argument("--drop-dielectric", action="store_true",
                    help="remove ALL dielectric (glass) objects — a glass-free scenario whose "
                         "flash observation avoids the high-risk glass caustic firefly source")
    ap.add_argument("--no-gt-direct", action="store_true",
                    help="skip the flash-only `direct` GT pass (clean specular target); still "
                         "emits the on/off pair + ΔI from the path observation scene")
    ap.add_argument("--preview-despeckle", action="store_true",
                    help="cosmetic firefly median-replace on the NIR PREVIEW PNG only — the raw "
                         "float EXR beside it is ALWAYS left unclamped (GT/observation)")
    ap.add_argument("--no-polar", action="store_true",
                    help="skip polarization: plain integrator in cuda_ad_rgb, RGB/NIR only "
                         "(no DoP/AoLP) — ~2x faster, less GPU memory")
    ap.add_argument("--index-base", type=int, default=0)
    a = ap.parse_args()

    import mitsuba as mi
    variant = "cuda_ad_rgb" if a.no_polar else VARIANT
    mi.set_variant(variant)

    scene_dir = SCENES / a.scene_id
    flash_L = a.nir_radiance / (4.0 * a.nir_half ** 2)   # point intensity → area radiance
    canonical = None

    def build(intg: str, name: str) -> Path:
        nonlocal canonical
        if canonical is None:
            canonical = json.loads((scene_dir / "material_canonical.json").read_text())
        xml = scene_dir / name
        summ = build_band_scene(scene_dir / "render_scene.xml", canonical, xml,
                                band=a.band, nir_flash=a.nir_flash, nir_flash_half_m=a.nir_half,
                                max_depth=a.max_depth, integrator=intg,
                                drop_dielectric=a.drop_dielectric, polarized=not a.no_polar)
        print(f"[band] built {xml.name}: integ={summ['integrator']} flash={summ['nir_flash']} "
              f"wrapped={summ['materials_wrapped']} dropped_glass={summ['dropped_dielectric']}", flush=True)
        return xml

    sfx = "_noglass" if a.drop_dielectric else ""   # keep glass / no-glass variants distinct
    # PATH scene = global-illumination observation carrier (RGB/NIR passive+active).
    path_xml = scene_dir / f"scene_band{sfx}.xml"
    if a.rebuild or a.nir_flash or not path_xml.is_file():
        path_xml = build("path", f"scene_band{sfx}.xml")
    # DIRECT scene = flash-only clean specular GT (no indirect → firefly-free by construction).
    want_gt = a.nir_flash and not a.no_gt_direct
    direct_xml = build("direct", f"scene_band{sfx}_direct.xml") if want_gt else None

    def load(xml: Path):
        t0 = time.time()
        sc = mi.load_file(str(xml))
        p = mi.traverse(sc)
        keys = {
            "cam": next(k for k in p.keys() if k.endswith(".to_world") and "nir_flash" not in k),
            "fov": next((k for k in p.keys() if k.endswith(".x_fov")), None),
            "w": [k for k in p.keys() if WEIGHT_RE.match(k)],
            "flash_r": next((k for k in p.keys() if "nir_flash" in k and k.endswith(".radiance.value")), None),
            "flash_tw": next((k for k in p.keys() if "nir_flash" in k and k.endswith(".to_world")), None),
        }
        rad = [k for k in p.keys() if k.endswith(".radiance.value")]
        keys["amb"] = [k for k in rad if k != keys["flash_r"]]          # ambient = all radiance minus flash
        keys["orig_amb"] = {k: np.array(p[k], np.float32).ravel() for k in keys["amb"]}
        print(f"[band] loaded {xml.name} {time.time()-t0:.1f}s · {len(keys['w'])} band weights · "
              f"{len(keys['amb'])} ambient emitters{' · flash' if keys['flash_r'] else ''}", flush=True)
        return sc, p, keys

    graph = json.loads((scene_dir / "viewpoint_graph.json").read_text())
    byid = {n["node_id"]: n for n in graph["nodes"]}
    out = REPO / a.out
    out.mkdir(parents=True, exist_ok=True)

    # Precompute each viewpoint's look-at once; both phases reuse it.
    vps = []
    for k, spec in enumerate(a.viewpoints.split(",")):
        nid, _, yaw_s = spec.partition("@")
        nid = nid.strip(); yaw_deg = float(yaw_s or 0)
        node = byid[nid]
        pose = resolve_viewpoint_pose(node["position"], yaw_deg, eye_height_m=EYE_H)
        o = np.asarray(pose.origin_mitsuba, dtype=np.float32)
        t = np.asarray(pose.target_mitsuba, dtype=np.float32)
        u = np.asarray(pose.up_mitsuba, dtype=np.float32)
        vps.append((a.index_base + k, nid, o, t, u))

    def _amb(vals):
        v = [float(x) for x in vals]
        return mi.Color3f(v[0], v[1], v[2]) if len(v) >= 3 else mi.Color3f(float(v[0]))

    def render(sc, p, keys, o, t, u, band, *, flash_on, ambient_on):
        look = mi.ScalarTransform4f().look_at(origin=list(o), target=list(t), up=list(u))
        p[keys["cam"]] = mi.Transform4f(look.matrix)
        if keys["fov"]:
            p[keys["fov"]] = float(a.fov)
        for wk in keys["w"]:
            p[wk] = mi.Float(BAND_WEIGHT[band])
        if keys["flash_tw"]:                              # headlamp: rectangle at camera, facing view
            p[keys["flash_tw"]] = mi.Transform4f(look.scale(a.nir_half).matrix)
        if keys["flash_r"]:
            r = flash_L if flash_on else 0.0
            p[keys["flash_r"]] = mi.Color3f(r, r, r)
        for k in keys["amb"]:                             # ambient sky + ceiling lights on/off
            p[k] = _amb(keys["orig_amb"][k]) if ambient_on else mi.Color3f(0.0, 0.0, 0.0)
        p.update()
        _t = time.time()
        img = np.array(mi.render(sc, spp=a.spp, seed=7))
        dt = time.time() - _t
        if a.no_polar:                                    # plain integrator: (H,W,3) RGB
            s0_rgb, m = img[..., :3].astype(np.float32), None
            S0 = np.clip((np.clip(s0_rgb, 0, None) * _LUM).sum(2), 1e-8, None)
        else:
            m = stokes(img); s0_rgb, S0 = m["s0_rgb"], m["S0"]
        return {"rgb": s0_rgb, "S0": S0, "m": m, "dt": dt}

    # --- Phase A: PATH observation scene (kept resident ALONE — two full band scenes at
    # once exhausts GPU memory and triggers Dr.Jit malloc-cache thrash). Renders RGB/NIR
    # passive + NIR active + ΔI for every viewpoint, then is freed before the GT scene loads.
    scP, pP, kP = load(path_xml)
    for vi, nid, o, t, u in vps:
        stem = f"vp{vi}_{nid}"

        # 1. RGB passive — ambient only, visible band. Standard passive observation.
        r = render(scP, pP, kP, o, t, u, "visible", flash_on=False, ambient_on=True)
        save_exr(r["rgb"], out / f"{stem}_rgb.exr")                     # unclamped HDR linear
        save_png(r["rgb"], out / f"{stem}_rgb.png", "linear_gamma")
        print(f"  [{stem} rgb_passive ] {r['dt']:5.1f}s S0 {r['S0'].mean():.3f}", flush=True)

        # 2. NIR passive  I_off — ambient only, NIR band (flash OFF).
        off = render(scP, pP, kP, o, t, u, "nir", flash_on=False, ambient_on=True)
        save_exr(off["S0"], out / f"{stem}_nir_passive.exr")
        _nir_preview_png(off["S0"], out / f"{stem}_nir_passive.png", a.preview_despeckle)
        print(f"  [{stem} nir_passive ] {off['dt']:5.1f}s S0 {off['S0'].mean():.3f}", flush=True)

        if a.nir_flash:
            # 3. NIR active  I_on — ambient + flash, path GI. The full network OBSERVATION:
            #    highlight+shadow+wall bounce+glass+indirect+caustic. Fireflies are LEGITIMATE
            #    sensor content → raw EXR stays unclamped, never despeckled.
            on = render(scP, pP, kP, o, t, u, "nir", flash_on=True, ambient_on=True)
            save_exr(on["S0"], out / f"{stem}_nir_active.exr")
            _nir_preview_png(on["S0"], out / f"{stem}_nir_active.png", a.preview_despeckle)
            if not a.no_polar:                            # active-sensing DoP/AoLP (NIR Stokes)
                save_png(on["m"]["dolp"], out / f"{stem}_dop.png", "dop")
                Image.fromarray((aolp_to_rgb(on["m"]["aolp"], on["m"]["dolp"]) * 255).astype(np.uint8)).save(
                    out / f"{stem}_aolp.png")
            print(f"  [{stem} nir_active ] {on['dt']:5.1f}s S0 {on['S0'].mean():.3f} "
                  f"raw_max {float(on['S0'].max()):.1f}", flush=True)

            # 4. ΔI = I_on − I_off — the active-light response in linear image space (exactly
            #    the flash/no-flash differential a real sensor computes). Signed EXR verbatim.
            dI = (on["S0"] - off["S0"]).astype(np.float32)
            save_exr(dI, out / f"{stem}_nir_dflash.exr")
            _nir_preview_png(np.clip(dI, 0, None), out / f"{stem}_nir_dflash.png", a.preview_despeckle)
            print(f"  [{stem} nir_dflash ] ΔI mean {float(dI.mean()):.3f} max {float(dI.max()):.1f}", flush=True)

    del scP, pP, kP                                       # free the path scene before Phase B
    import gc; gc.collect()
    try:
        import drjit as dr; dr.flush_malloc_cache()
    except Exception:
        pass

    # --- Phase B: flash-only DIRECT GT scene (flash on, ambient OFF, `direct` integrator).
    # No indirect paths → firefly-free by construction: the clean specular-recovery target.
    if want_gt:
        scD, pD, kD = load(direct_xml)
        for vi, nid, o, t, u in vps:
            stem = f"vp{vi}_{nid}"
            gt = render(scD, pD, kD, o, t, u, "nir", flash_on=True, ambient_on=False)
            save_exr(gt["S0"], out / f"{stem}_nir_flash_direct.exr")
            _nir_preview_png(gt["S0"], out / f"{stem}_nir_flash_direct.png", a.preview_despeckle)
            if not a.no_polar:
                save_png(gt["m"]["dolp"], out / f"{stem}_flash_dop.png", "dop")
            print(f"  [{stem} flash_direct] {gt['dt']:5.1f}s S0 {gt['S0'].mean():.3f} "
                  f"raw_max {float(gt['S0'].max()):.1f}", flush=True)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
