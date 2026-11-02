"""Generated artwork for the science-museum scene (docs/space_museum_design_proposal.md): NO real artwork, people or text is reproduced.

    python3 gen_museum_art.py [out_dir]        # default data/venue_refs/museum_art

  nebula_red.png     2048 x 1024  a red/pink emission nebula on a star field (full-wall panel)
  nebula_blue.png    1024 x 1280  a blue cluster-like nebula with bright stars (framed picture)
  nebula_ring.png    1024 x 1280  a ring nebula (teal core, orange rim) (framed picture)
  earth_limb.png     1600 x 900   a blue planet limb with a thin green aurora (monitor)
  fresco_dome.png    4096 x 2048  an abstract celestial fresco: pale sky, planets, moons, orbit arcs, star dust (dome texture; figures NOT drawn)
  frieze_0..7.png    1536 x 512   abstract geometric frieze panels in earth tones (stand in for the painted wall panels)
Pure numpy + PIL, seeded and deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path("/jarvis/project/robomituba/data/venue_refs/museum_art")


def fbm(h, w, rng, octaves=6, base=4):
    """Fractal value noise in [0, 1]."""
    acc = np.zeros((h, w), np.float32); amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        g = rng.random((n + 1, int(n * w / h) + 2)).astype(np.float32)
        im = Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        acc += amp * np.asarray(im, np.float32) / 255.0; tot += amp; amp *= 0.5
    return acc / tot


def stars(h, w, rng, n, bright=1.0):
    im = Image.new("L", (w, h)); d = ImageDraw.Draw(im)
    for _ in range(n):
        x, y = rng.integers(0, w), rng.integers(0, h); r = rng.choice((0, 0, 0, 1, 1, 2)); v = int(rng.integers(120, 255) * bright)
        d.ellipse((x - r, y - r, x + r, y + r), fill=v)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(0.7)), np.float32) / 255.0


def to_img(a):
    return Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8), "RGB")


def nebula(h, w, seed, c_core, c_rim, c_bg=(0.02, 0.02, 0.05)):
    rng = np.random.default_rng(seed)
    n1, n2 = fbm(h, w, rng, 7, 3), fbm(h, w, rng, 6, 5)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32); cx, cy = w * rng.uniform(0.4, 0.6), h * rng.uniform(0.4, 0.6)
    r = np.sqrt(((xx - cx) / w) ** 2 + ((yy - cy) / h) ** 2)
    m = np.clip(1.4 - r * 2.4 + (n1 - 0.5) * 1.6, 0, 1) ** 1.6
    filament = np.clip(1.0 - np.abs(n2 - 0.5) * 7.0, 0, 1) * m
    col = np.zeros((h, w, 3), np.float32) + np.array(c_bg, np.float32)
    col += m[..., None] * (np.array(c_rim, np.float32) * 0.8) + (m ** 3)[..., None] * np.array(c_core, np.float32) + filament[..., None] * 0.5
    col += stars(h, w, rng, int(h * w / 2200))[..., None] * 0.9
    return col


def earth_limb(h, w, seed):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy = h * 2.6; R = h * 2.0; d = np.sqrt((xx - w / 2) ** 2 + (yy - cy) ** 2)
    planet = (d < R).astype(np.float32); edge = np.clip(1 - np.abs(d - R) / (h * 0.03), 0, 1)
    cloud = fbm(h, w, rng, 6, 4)
    col = np.zeros((h, w, 3), np.float32) + np.array((0.0, 0.0, 0.01), np.float32)
    col += planet[..., None] * (np.array((0.05, 0.25, 0.6), np.float32) * (0.5 + cloud[..., None]))
    col += edge[..., None] * np.array((0.3, 0.55, 1.0), np.float32) * 0.8
    aur = np.clip(1 - np.abs(d - (R + h * 0.05)) / (h * 0.06), 0, 1) * (0.4 + 0.6 * fbm(h, w, rng, 4, 12))
    col += aur[..., None] * np.array((0.1, 0.9, 0.35), np.float32) * 0.7
    col += stars(h, w, rng, 400)[..., None] * (1 - planet[..., None])
    return col


def fresco(h, w, seed):
    """An abstract celestial dome: pale cream-blue sky with large soft planets, moons, orbit arcs and star dust. No figures."""
    rng = np.random.default_rng(seed)
    n = fbm(h, w, rng, 7, 3)
    col = np.zeros((h, w, 3), np.float32)
    sky_a, sky_b = np.array((0.88, 0.84, 0.76), np.float32), np.array((0.5, 0.62, 0.78), np.float32)
    col += sky_a * (1 - n[..., None]) + sky_b * n[..., None]
    im = to_img(col); d = ImageDraw.Draw(im, "RGBA")
    for _ in range(9):                                                  # planets: a disc, a soft shadow side, a ring on some
        cx, cy, r = rng.integers(0, w), rng.integers(h // 8, h - h // 8), rng.integers(h // 14, h // 6)
        base = tuple(int(c) for c in rng.choice(((190, 150, 110), (120, 150, 190), (210, 190, 150), (90, 120, 170), (200, 120, 90))))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*base, 235)); d.ellipse((cx - r * 0.2, cy - r, cx + r, cy + r), fill=(20, 30, 60, 70))
        if rng.random() < 0.4:
            d.ellipse((cx - r * 1.7, cy - r * 0.35, cx + r * 1.7, cy + r * 0.35), outline=(230, 210, 160, 220), width=max(3, r // 14))
    for _ in range(14):                                                 # orbit arcs
        cx, cy, r = rng.integers(0, w), rng.integers(0, h), rng.integers(h // 4, h // 1.2)
        a0 = int(rng.integers(0, 360)); d.arc((cx - r, cy - r, cx + r, cy + r), a0, a0 + int(rng.integers(40, 140)), fill=(250, 245, 225, 160), width=int(rng.integers(3, 9)))
    for _ in range(40):                                                 # small suns / moons
        x, y, r = rng.integers(0, w), rng.integers(0, h), rng.integers(8, 34); d.ellipse((x - r, y - r, x + r, y + r), fill=(250, 235, 190, 190))
    a = np.asarray(im, np.float32) / 255.0
    a += stars(h, w, rng, 6000)[..., None] * 0.25
    return a


def frieze(w, h, seed):
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (w, h), tuple(int(c) for c in rng.choice(((60, 80, 90), (110, 90, 60), (50, 60, 80), (120, 100, 80)))))
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(26):
        x, y = rng.integers(0, w), rng.integers(0, h); s = int(rng.integers(40, 220))
        col = (*[int(c) for c in rng.choice(((200, 160, 90), (170, 70, 50), (60, 110, 120), (230, 220, 190), (90, 130, 80)))], 215)
        k = rng.integers(0, 3)
        if k == 0:
            d.ellipse((x, y, x + s, y + s), fill=col)
        elif k == 1:
            d.rectangle((x, y, x + s, y + s // 2), fill=col)
        else:
            d.polygon([(x, y + s), (x + s // 2, y), (x + s, y + s)], fill=col)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255.0


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    out.mkdir(parents=True, exist_ok=True)
    to_img(np.clip(nebula(1024, 2048, 1, (1.0, 0.75, 0.8), (0.9, 0.2, 0.3)), 0, 1)).save(out / "nebula_red.png")
    to_img(np.clip(nebula(1280, 1024, 2, (0.9, 0.95, 1.0), (0.2, 0.35, 0.9)), 0, 1)).save(out / "nebula_blue.png")
    to_img(np.clip(nebula(1280, 1024, 3, (0.3, 0.9, 0.8), (0.95, 0.5, 0.25)), 0, 1)).save(out / "nebula_ring.png")
    to_img(np.clip(earth_limb(900, 1600, 4), 0, 1)).save(out / "earth_limb.png")
    to_img(np.clip(fresco(2048, 4096, 5), 0, 1)).save(out / "fresco_dome.png")
    for k in range(8):
        to_img(np.clip(frieze(1536, 512, 10 + k), 0, 1)).save(out / f"frieze_{k}.png")
    print("wrote", len(list(out.glob("*.png"))), "images to", out)


if __name__ == "__main__":
    main()
