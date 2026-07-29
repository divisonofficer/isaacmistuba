#!/usr/bin/env python3
"""Animated multi-modality Malus visualization: rotate the polarized SOURCE
0->360 deg. Each frame shows S0 · DoLP · AoLP · S1/S0 · S2/S0 side by side.

The four fixed analyzers (0/45/90/135) modulate S0 by cos^2(theta_src - theta_ana)
so the extinction patch cycles round the grid; in the background (no analyzer) the
AoLP / S1S0 / S2S0 rotate with the source, while behind each analyzer they stay
pinned to that analyzer's angle -> both effects visible at once.

Env: LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib,
PYTHONPATH=build/mitsuba3-optix7/python, python=~/miniconda3/envs/openusd_pip/bin/python
"""
from __future__ import annotations
import argparse
import importlib.util as _u
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "dev_report/images/polar_qualify"
_spec = _u.spec_from_file_location("q", str(Path(__file__).parent / "qualify.py"))
q = _u.module_from_spec(_spec); _spec.loader.exec_module(q)
_LUM = q._LUM
_DIV = np.array([[0.23, 0.30, 0.75], [1, 1, 1], [0.75, 0.15, 0.15]], np.float32)
MODS = ["S0", "DoLP", "AoLP", "S1/S0", "S2/S0"]


def _tonemap(s0_rgb):
    x = np.clip(s0_rgb, 0, None); x = x / (1 + x)
    return (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)


def modality_imgs(arr):
    a = np.nan_to_num(arr)
    s0 = a[:, :, 3:6]
    S0 = np.clip((s0 * _LUM).sum(2), 1e-8, None)
    S1 = (a[:, :, 6:9] * _LUM).sum(2); S2 = (a[:, :, 9:12] * _LUM).sum(2)
    dolp = np.clip(np.sqrt(S1 ** 2 + S2 ** 2) / S0, 0, 1)
    aolp = 0.5 * np.degrees(np.arctan2(S2, S1))
    h = (((aolp + 90) / 180) % 1.0); val = np.clip(dolp / max(dolp.max(), 1e-6), 0, 1)
    return [
        _tonemap(s0),                                                   # S0
        q._lut(dolp, q._REDBLACK),                                      # DoLP red-black
        (q._hsv(h, np.ones_like(h), val) * 255).astype(np.uint8),       # AoLP (hue), val=DoLP
        q._lut((np.clip(S1 / S0, -1, 1) + 1) / 2, _DIV),                # S1/S0 BwR
        q._lut((np.clip(S2 / S0, -1, 1) + 1) / 2, _DIV),                # S2/S0 BwR
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--spp", type=int, default=2000)
    ap.add_argument("--res", type=int, default=180)
    ap.add_argument("--duration", type=int, default=100)
    a = ap.parse_args()

    import mitsuba as mi
    from PIL import Image, ImageDraw
    mi.set_variant(q.VARIANT)
    OUT.mkdir(parents=True, exist_ok=True)
    R, pad, top = a.res, 6, 22
    W = 5 * R + 6 * pad
    Hh = top + R + 16

    frames = []
    for k in range(a.frames):
        th = k * 360.0 / a.frames
        scene, _ = q._malus_grid_scene(mi, res=R, src_theta=th)
        arr = np.array(mi.render(mi.load_dict(scene), spp=a.spp))
        panels = modality_imgs(arr)
        canvas = Image.new("RGB", (W, Hh), (15, 18, 22))
        d = ImageDraw.Draw(canvas)
        for i, (name, panel) in enumerate(zip(MODS, panels)):
            x = pad + i * (R + pad)
            canvas.paste(Image.fromarray(panel), (x, top))
            d.text((x + 2, 4), name, fill=(210, 210, 220))
        d.text((pad, Hh - 14), f"source pol = {th:5.0f}°   (analyzers TL0 TR45 BL90 BR135; background = source pol)",
               fill=(255, 235, 120))
        frames.append(canvas)
        print(f"  frame {k+1}/{a.frames}  {th:.0f}deg", flush=True)

    gif = OUT / "malus_rotation.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=a.duration, loop=0, optimize=True)
    print(f"wrote {gif}  ({gif.stat().st_size/1024:.0f} KB, {len(frames)} frames, {W}x{Hh})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
