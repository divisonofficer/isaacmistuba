"""Reference-vs-render style metrics (non-home 20, 2026-10-16: the VLM critic needs numbers beside it that cannot be talked into a score).

    python style_metrics.py --ref R1.png R2.png --render A.png B.png [--json out.json]

Pools each image set's pixels in CIE Lab and reports, per set and as reference-vs-render distances:
  colour   per-channel 1-D Wasserstein distance (L in 0-100, a/b in their own units), mean warmth b*, mean chroma
  light    mean L, fraction of dark (L<20) and highlight (L>85) pixels, the p95/p5 L spread, mean local contrast (std of L in 16 px tiles)
Camera and layout differ between a reference photo and a render, so nothing here is per pixel: only distributions are compared.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
from PIL import Image


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[..., 1] - 16
    return np.stack([L, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def load(paths, size=256):
    labs = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        im.thumbnail((size, size))
        labs.append(srgb_to_lab(np.asarray(im, dtype=np.float64)))
    return labs


def stats(labs):
    px = np.concatenate([x.reshape(-1, 3) for x in labs])
    L = px[:, 0]
    contrast = []
    for x in labs:
        h, w = x.shape[:2]
        for i in range(0, h - 15, 16):
            for j in range(0, w - 15, 16):
                contrast.append(x[i:i + 16, j:j + 16, 0].std())
    return px, {"mean_L": float(L.mean()), "dark_frac": float((L < 20).mean()), "highlight_frac": float((L > 85).mean()),
                "L_p95_p5": float(np.percentile(L, 95) - np.percentile(L, 5)), "local_contrast": float(np.mean(contrast)),
                "warmth_b": float(px[:, 2].mean()), "chroma": float(np.hypot(px[:, 1], px[:, 2]).mean())}


def w1(a, b):
    """1-D Wasserstein distance between two samples (quantile matching)."""
    q = np.linspace(0, 1, 512)
    return float(np.mean(np.abs(np.quantile(a, q) - np.quantile(b, q))))


def compare(ref_paths, render_paths):
    rp, rs = stats(load(ref_paths)); gp, gs = stats(load(render_paths))
    dist = {f"w1_{c}": w1(rp[:, i], gp[:, i]) for i, c in enumerate("Lab")}
    dist["d_mean_L"] = gs["mean_L"] - rs["mean_L"]; dist["d_warmth"] = gs["warmth_b"] - rs["warmth_b"]
    dist["d_dark_frac"] = gs["dark_frac"] - rs["dark_frac"]; dist["d_contrast"] = gs["local_contrast"] - rs["local_contrast"]
    # calibrated on the café references (2026-10-16): two views of one style score ~8, two different styles ~0; brightness dominates
    dist["colour_score"] = float(min(10.0, max(0.0, 10 - dist["w1_L"] / 4.5 - (dist["w1_a"] + dist["w1_b"]) / 4)))
    return {"reference": rs, "render": gs, "distance": dist}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", nargs="+", required=True); ap.add_argument("--render", nargs="+", required=True); ap.add_argument("--json")
    a = ap.parse_args()
    out = compare(a.ref, a.render)
    print(json.dumps(out, indent=1))
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
