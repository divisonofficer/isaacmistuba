"""Leaf textures for the procedural plants (pure PIL; system python). python3 leaf_tex.py -> data/venue_refs/leaf_tex/leaf_ovate.png and leaf_blade.png (512 x 512).

u across the leaf (0 = left edge, 1 = right edge), v along it (0 = base, 1 = tip). ovate: a light midrib, 9 pairs of curved side veins, a dark-to-light green gradient from the edges to the middle, a fine
reticulate vein net and speckle. blade: parallel veins with a light central fold (palm leaflets, grasses). Colours are neutral greens; the material multiplies its own tint and a per-leaf vertex colour."""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path("/jarvis/project/robomituba/data/venue_refs/leaf_tex")
S = 512


def mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def ovate():
    r = random.Random(5); im = Image.new("RGB", (S, S)); px = im.load()
    for y in range(S):
        for x in range(S):
            u = x / (S - 1) * 2 - 1; t = y / (S - 1)
            edge = abs(u); g = mix((150, 205, 120), (60, 120, 50), min(1.0, edge ** 1.4 + 0.15 * t))
            px[x, y] = g
    d = ImageDraw.Draw(im)
    d.line([(S // 2, 0), (S // 2, S)], fill=(205, 235, 170), width=9)                                  # the midrib
    for k in range(1, 10):                                                                             # curved side veins
        y0 = int(S * (k / 10.0))
        for sg in (-1, 1):
            pts = [(S // 2 + sg * int(i * S * 0.46 / 20), y0 + int(S * 0.2 * (i / 20.0) ** 0.8)) for i in range(21)]
            d.line(pts, fill=(190, 225, 150), width=4)
    for _ in range(260):                                                                               # a fine vein net
        x0, y0 = r.randint(0, S), r.randint(0, S); a = r.uniform(0, 6.28); l = r.randint(12, 35)
        d.line([(x0, y0), (x0 + l * math.cos(a), y0 + l * math.sin(a))], fill=(120, 175, 95), width=1)
    im = im.filter(ImageFilter.GaussianBlur(0.8))
    px = im.load()
    for _ in range(3000):                                                                              # speckle
        x, y = r.randrange(S), r.randrange(S); c = px[x, y]; k = r.uniform(0.9, 1.08); px[x, y] = tuple(min(255, int(v * k)) for v in c)
    return im


def blade():
    r = random.Random(7); im = Image.new("RGB", (S, S)); px = im.load()
    for y in range(S):
        for x in range(S):
            u = abs(x / (S - 1) * 2 - 1); px[x, y] = mix((130, 195, 105), (65, 125, 55), u ** 1.2)
    d = ImageDraw.Draw(im)
    d.line([(S // 2, 0), (S // 2, S)], fill=(190, 225, 150), width=7)
    for k in range(-6, 7):
        if k:
            d.line([(S // 2 + k * 38, 0), (S // 2 + k * 38, S)], fill=(105, 165, 85), width=2)
    return im.filter(ImageFilter.GaussianBlur(0.6))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    ovate().save(OUT / "leaf_ovate.png"); blade().save(OUT / "leaf_blade.png"); print(OUT)
