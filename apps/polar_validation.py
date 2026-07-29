#!/usr/bin/env python3
"""Polarization render CORRECTNESS validation (absolute, not relative).

The A/B report shows "changed vs legacy" and "closer to measured" -- both are
*relative*. Correctness needs checking against an analytic ground truth, bottom-up:

  0. realizability + Stokes/frame convention   (realize)
  1. dielectric Fresnel / Brewster  DoLP(theta) (sphere --dielectric)
  2. conductor DoLP(theta) per metal (eta-k)    (sphere --metal Au ...)
  3. AoLP must be DoLP-masked (circular error)  (aolp)
  4. measured pBRDF quantitative error          (aolp ... on injected vs measured)

Analytic Fresnel is the ground truth: for an unpolarized source and a single
specular reflection, DoLP(theta)=|Rs-Rp|/(Rs+Rp); dielectric n=1.5 -> DoLP=1 at
Brewster theta_B=atan(n)~=56.3 deg. Metals (complex n+ik) peak below 1.

RUN (standard build env):
    PYTHONPATH=...:/home/jinnyeong/robomituba-build/mitsuba3/python \
    LD_LIBRARY_PATH=/usr/lib/wsl/lib /usr/bin/python3.10 apps/polar_validation.py <cmd> ...
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
POLAR_VARIANT = "cuda_ad_spectral_polarized"

# representative n,k at ~550 nm (green) for the analytic overlay (the render is
# spectral+luminance-weighted, so conductors are approximate; dielectric n=1.5 is
# wavelength-flat -> exact).
METAL_NK = {
    "Al": (0.96, 6.69), "Au": (0.35, 2.72), "Ag": (0.14, 3.47),
    "Cr": (3.13, 3.33), "Cu": (0.83, 2.46), "Ni_palik": (1.90, 3.40),
}


# --- analytic Fresnel DoLP(theta) -------------------------------------------

def fresnel_dielectric_dolp(theta_deg, n: float):
    ti = np.radians(np.asarray(theta_deg, float))
    st = np.clip(np.sin(ti) / n, -1, 1)
    tt = np.arcsin(st)
    ci, ct = np.cos(ti), np.cos(tt)
    Rs = ((ci - n * ct) / (ci + n * ct)) ** 2
    Rp = ((ct - n * ci) / (ct + n * ci)) ** 2
    return np.abs(Rs - Rp) / np.maximum(Rs + Rp, 1e-12)


def fresnel_conductor_dolp(theta_deg, n: float, k: float):
    ti = np.radians(np.asarray(theta_deg, float))
    n2 = complex(n, k)
    ci = np.cos(ti).astype(complex)
    st = np.sin(ti).astype(complex) / n2
    ct = np.sqrt(1 - st * st)
    Rs = np.abs((ci - n2 * ct) / (ci + n2 * ct)) ** 2
    Rp = np.abs((n2 * ci - ct) / (n2 * ci + ct)) ** 2
    return np.abs(Rs - Rp) / np.maximum(Rs + Rp, 1e-12)


# --- helpers ----------------------------------------------------------------

def load_stokes(path_or_dir) -> dict:
    p = Path(path_or_dir)
    if p.is_dir():
        hits = list(p.rglob("stokes_data.npz"))
        if not hits:
            raise SystemExit(f"no stokes_data.npz under {p}")
        p = hits[0]
    z = np.load(p)
    return {k: z[k] for k in z.files}


def _aolp_circular_diff(a, b):
    """AoLP wraps at pi: error = min(|d|, pi-|d|). Inputs in radians."""
    d = np.abs(np.mod(a, np.pi) - np.mod(b, np.pi))
    return np.minimum(d, np.pi - d)


# --- 0. realizability -------------------------------------------------------

def cmd_realize(a):
    for src in a.inputs:
        s = load_stokes(src)
        s0 = np.asarray(s.get("s0_l", s.get("s0")), float)
        s1 = np.asarray(s.get("s1_l", s.get("s1")), float)
        s2 = np.asarray(s.get("s2_l", s.get("s2")), float)
        s3 = np.asarray(s.get("s3_l", s.get("s3", np.zeros_like(s0))), float)
        dop = np.asarray(s["dop"], float)
        lit = s0 > (a.s0_floor * np.nanmax(s0))
        p = np.sqrt(s1 ** 2 + s2 ** 2 + s3 ** 2)
        ratio = p / np.maximum(s0, 1e-9)                 # must be <= 1
        dop_lit = dop[lit]
        print(f"\n=== realizability: {src} ===")
        print(f"  lit pixels (S0>{a.s0_floor:.2g}*max): {100*lit.mean():.1f}%")
        print(f"  DoLP: max={np.nanmax(dop):.4f} · max(lit)={np.nanmax(dop_lit):.4f} · "
              f"> 1.001 on {100*np.mean(dop_lit>1.001):.3f}% of lit")
        print(f"  ||(S1,S2,S3)||/S0: max(lit)={np.nanmax(ratio[lit]):.4f} · "
              f"> 1.001 on {100*np.mean(ratio[lit]>1.001):.3f}% of lit  (physical Stokes: <=1)")
        verdict = "OK" if np.nanmax(dop_lit) <= 1.02 and np.nanmax(ratio[lit]) <= 1.02 else "VIOLATION"
        print(f"  verdict: {verdict}")


# --- 3/4. DoLP-masked circular AoLP error + DoLP RMSE ------------------------

def cmd_aolp(a):
    A = load_stokes(a.a)
    B = load_stokes(a.b)
    dopA, dopB = np.asarray(A["dop"], float), np.asarray(B["dop"], float)
    aA, aB = np.asarray(A["aolp"], float), np.asarray(B["aolp"], float)
    if np.nanmax(aA) > 3.2:  # stored in degrees -> radians
        aA, aB = np.radians(aA), np.radians(aB)
    mask = (dopA > a.thresh) & (dopB > a.thresh)
    print(f"\n=== AoLP/DoLP error: {a.a}  vs  {a.b}  (DoLP>{a.thresh}) ===")
    print(f"  masked pixels: {100*mask.mean():.1f}%")
    # DoLP RMSE (all + masked)
    dd = dopB - dopA
    print(f"  DoLP RMSE all={np.sqrt(np.mean(dd**2)):.4f} · masked={np.sqrt(np.mean(dd[mask]**2)):.4f}")
    # AoLP circular error: naive (all) vs masked vs DoLP-weighted
    ce = np.degrees(_aolp_circular_diff(aA, aB))
    ce_all = ce.mean()
    ce_masked = ce[mask].mean() if mask.any() else float("nan")
    w = np.minimum(dopA, dopB)[mask]
    ce_w = np.average(ce[mask], weights=w) if mask.any() and w.sum() > 0 else float("nan")
    print(f"  AoLP circular error (deg): naive-all={ce_all:.2f}  masked={ce_masked:.2f}  "
          f"DoLP-weighted={ce_w:.2f}")
    print("  -> 'naive-all' includes low-DoLP noise pixels (AoLP undefined there);"
          " masked/weighted is the physically meaningful number.")


# --- 1/2. sphere DoLP(theta) vs analytic Fresnel ----------------------------

def _sphere_xml(path: Path, bsdf: str) -> None:
    path.write_text(
        '<scene version="3.0.0">\n'
        '  <integrator type="path"><integer name="max_depth" value="8"/></integrator>\n'
        '  <emitter type="constant"><rgb name="radiance" value="1.0"/></emitter>\n'
        f'  <shape type="sphere"><point name="center" x="0" y="0" z="0"/>'
        f'<float name="radius" value="1"/>{bsdf}</shape>\n</scene>\n', encoding="utf-8")


def cmd_sphere(a):
    from mitsuba_converter.multimodal import (
        RenderConfig, render_modalities, camera_to_world_from_lookat)
    out = Path(a.out or f"out/bsdf_compare/validate_{a.metal or 'dielectric'}")
    out.mkdir(parents=True, exist_ok=True)

    if a.metal:
        n, k = METAL_NK[a.metal]
        bsdf = f'<bsdf type="roughconductor"><string name="material" value="{a.metal}"/><float name="alpha" value="0.006"/></bsdf>'
        analytic = fresnel_conductor_dolp
        label = f"{a.metal} (n={n}, k={k})"
        args = (n, k)
    else:  # dielectric: near-pure specular pplastic (tiny diffuse) so DoLP ~= Fresnel
        n = a.ior
        bsdf = (f'<bsdf type="pplastic"><rgb name="diffuse_reflectance" value="0.006 0.006 0.006"/>'
                f'<float name="int_ior" value="{n}"/><float name="alpha" value="0.003"/></bsdf>')
        analytic = fresnel_dielectric_dolp
        label = f"dielectric n={n}"
        args = (n,)

    xml = out / "sphere.xml"
    _sphere_xml(xml, bsdf)
    # Far camera + tiny fov -> near-orthographic, so theta=arcsin(r/R) is accurate.
    cam = camera_to_world_from_lookat([0, 0, 45], [0, 0, 0], [0, 1, 0])
    cfg = RenderConfig(width=a.res, height=a.res, path_spp=a.spp, polar_spp=a.spp, ambient_radiance=1.0)
    render_modalities(xml, cam, 2.7, ["rgb", "dop"], out_dir=out, config=cfg, variant=POLAR_VARIANT)

    s = load_stokes(out)
    dop = np.asarray(s["dop"], float)
    s0 = np.asarray(s.get("s0_l", s.get("s0")), float)
    H, W = dop.shape[:2]
    lit = s0 > 0.02 * np.nanmax(s0)
    # sphere image center + radius from the lit mask
    ys, xs = np.where(lit)
    cx, cy = xs.mean(), ys.mean()
    R = 0.5 * (xs.max() - xs.min())
    # sample along the central horizontal row; theta_i = arcsin(r/R)
    row = int(round(cy))
    band = lit[max(0, row - 2):row + 3, :].any(0)
    cols = np.where(band)[0]
    prof_theta, prof_dop = [], []
    for x in cols:
        r = (x - cx) / max(R, 1e-6)
        if abs(r) >= 0.985:
            continue
        theta = np.degrees(np.arcsin(np.clip(abs(r), 0, 1)))
        prof_theta.append(theta)
        prof_dop.append(float(np.nanmedian(dop[max(0, row - 2):row + 3, x])))
    prof_theta = np.asarray(prof_theta); prof_dop = np.asarray(prof_dop)
    order = np.argsort(prof_theta)
    prof_theta, prof_dop = prof_theta[order], prof_dop[order]
    ana = analytic(prof_theta, *args)
    valid = prof_theta < a.max_theta
    rmse = float(np.sqrt(np.mean((prof_dop[valid] - ana[valid]) ** 2)))
    print(f"\n=== sphere DoLP(theta) vs analytic: {label} ===")
    print(f"  DoLP RMSE (theta<{a.max_theta} deg) = {rmse:.4f}")
    if not a.metal:
        i = int(np.argmax(ana)); print(f"  analytic Brewster peak: theta={prof_theta[i]:.1f} deg (expect atan(n)={np.degrees(np.arctan(n)):.1f})")
        j = int(np.argmax(prof_dop)); print(f"  rendered  DoLP peak:  theta={prof_theta[j]:.1f} deg, DoLP={prof_dop[j]:.3f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure(figsize=(6, 4))
        plt.plot(prof_theta, ana, "k-", lw=2, label="analytic Fresnel")
        plt.plot(prof_theta, prof_dop, "r.", ms=3, alpha=0.6, label="rendered (sphere meridian)")
        plt.xlabel("incidence angle theta (deg)"); plt.ylabel("DoLP")
        plt.title(f"{label}  ·  RMSE={rmse:.3f}"); plt.ylim(-0.02, 1.02); plt.grid(alpha=0.3); plt.legend()
        plt.tight_layout(); plt.savefig(out / "dolp_vs_theta.png", dpi=110)
        print(f"  plot -> {out/'dolp_vs_theta.png'}")
    except Exception as e:
        print("  plot skipped:", e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("realize", help="0. realizability (DoLP<=1, ||S||<=S0)")
    r.add_argument("inputs", nargs="+"); r.add_argument("--s0-floor", type=float, default=0.02)
    r.set_defaults(fn=cmd_realize)
    al = sub.add_parser("aolp", help="3/4. DoLP-masked circular AoLP error + DoLP RMSE")
    al.add_argument("a"); al.add_argument("b"); al.add_argument("--thresh", type=float, default=0.05)
    al.set_defaults(fn=cmd_aolp)
    sp = sub.add_parser("sphere", help="1/2. sphere DoLP(theta) vs analytic Fresnel")
    sp.add_argument("--metal", choices=list(METAL_NK), default=None)
    sp.add_argument("--ior", type=float, default=1.5)
    sp.add_argument("--spp", type=int, default=256); sp.add_argument("--res", type=int, default=700)
    sp.add_argument("--max-theta", type=float, default=85.0); sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_sphere)
    a = ap.parse_args()
    return a.fn(a) or 0


if __name__ == "__main__":
    raise SystemExit(main())
