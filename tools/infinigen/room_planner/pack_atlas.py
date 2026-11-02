"""Packaging graphics atlas for procedural chilled / grocery products (pure PIL; run with the system python, the Blender python has no PIL).

    python3 pack_atlas.py [out.png]      -> data/venue_refs/pack_atlas/pack_atlas.png   10 x 10 cells of 256 px = 100 designs

Each cell is one wrap-around print: a coloured design with an abstract logo (circle / wave / leaf / stripes / burst), a wordmark made of glyph-like blocks (NO real letters, no brands), rows of tiny pseudo-text, a
nutrition-style table, a barcode, a recycle-style mark, a seal / seam line and a photo-like fruit or milk blob. High visual frequency is the point: nothing is meant to be readable."""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("/jarvis/project/robomituba/data/venue_refs/pack_atlas/pack_atlas.png")
N, C = 10, 256
PAL = [((0.9, 0.15, 0.12), (1, 1, 1)), ((0.1, 0.4, 0.8), (1, 0.95, 0.5)), ((0.15, 0.6, 0.25), (1, 1, 1)), ((0.98, 0.78, 0.15), (0.6, 0.1, 0.1)), ((0.95, 0.95, 0.92), (0.15, 0.45, 0.75)),
       ((0.95, 0.5, 0.15), (1, 1, 1)), ((0.5, 0.2, 0.55), (1, 0.9, 0.9)), ((0.08, 0.08, 0.1), (0.95, 0.75, 0.2)), ((0.95, 0.85, 0.8), (0.6, 0.15, 0.2)), ((0.7, 0.88, 0.95), (0.1, 0.3, 0.6)),
       ((0.55, 0.78, 0.35), (0.2, 0.35, 0.1)), ((0.85, 0.2, 0.4), (1, 1, 1))]
rgb = lambda c: tuple(int(max(0, min(1, v)) * 255) for v in c)


def glyphs(d, x, y, w, h, col, r):
    """A wordmark of glyph-like blocks: rectangles of random width / height with gaps and a few diagonal strokes."""
    cx = x
    while cx < x + w - 6:
        gw = r.randint(max(4, int(h * 0.3)), max(6, int(h * 0.7))); gh = h if r.random() < 0.8 else int(h * 0.7)
        t = r.random()
        if t < 0.5:
            d.rectangle([cx, y + h - gh, cx + gw, y + h], fill=col)
            if r.random() < 0.6:
                d.rectangle([cx + gw // 4, y + h - gh + h // 4, cx + gw - gw // 4, y + h - h // 4], fill=None, outline=None)
        elif t < 0.8:
            d.polygon([(cx, y + h), (cx + gw // 2, y + h - gh), (cx + gw, y + h)], fill=col)
        else:
            d.ellipse([cx, y + h - gh, cx + gw, y + h], fill=col)
        cx += gw + r.randint(2, 5)


def tiny_text(d, x, y, w, rows, col, r, lh=5):
    for k in range(rows):
        cx = x
        while cx < x + w - 4:
            ww = r.randint(4, 20)
            d.rectangle([cx, y + k * (lh + 2), min(cx + ww, x + w), y + k * (lh + 2) + lh - 2], fill=col)
            cx += ww + r.randint(2, 4)


def barcode(d, x, y, w, h, r):
    d.rectangle([x - 3, y - 3, x + w + 3, y + h + 3], fill=(250, 250, 248))
    cx = x
    while cx < x + w:
        bw = r.choice((1, 1, 2, 3)); d.rectangle([cx, y, cx + bw - 1, y + h], fill=(10, 10, 10)); cx += bw + r.choice((1, 1, 2))


def cell(seed):
    r = random.Random(seed)
    base, acc = r.choice(PAL)
    im = Image.new("RGB", (C, C), rgb(base)); d = ImageDraw.Draw(im)
    lay = r.randrange(5)
    if lay == 0:                                                         # colour block + big circle logo
        d.ellipse([C * 0.2, C * 0.1, C * 0.8, C * 0.55], fill=rgb(acc)); d.ellipse([C * 0.3, C * 0.2, C * 0.7, C * 0.45], fill=rgb(base))
    elif lay == 1:                                                       # horizontal stripes
        for k in range(r.randint(2, 4)):
            y0 = r.randint(10, 160); d.rectangle([0, y0, C, y0 + r.randint(10, 30)], fill=rgb(acc))
    elif lay == 2:                                                       # diagonal split
        d.polygon([(0, 0), (C, 0), (0, C * r.uniform(0.5, 0.9))], fill=rgb(acc))
    elif lay == 3:                                                       # wave band + fruit-like blob
        for x in range(0, C, 4):
            y = int(C * 0.45 + 20 * math.sin(x / 22.0 + seed)); d.rectangle([x, y, x + 4, C], fill=rgb(acc))
        d.ellipse([C * 0.55, C * 0.08, C * 0.9, C * 0.4], fill=rgb((acc[0] * 0.9, acc[1] * 0.6, acc[2] * 0.3)))
    else:                                                                # burst
        for k in range(14):
            a = k * math.pi / 7; d.polygon([(C * 0.5, C * 0.3), (C * 0.5 + 60 * math.cos(a - 0.1), C * 0.3 + 60 * math.sin(a - 0.1)), (C * 0.5 + 60 * math.cos(a + 0.1), C * 0.3 + 60 * math.sin(a + 0.1))], fill=rgb(acc))
    ink = rgb((0.05, 0.05, 0.06)) if sum(base) > 1.6 else (245, 245, 240)
    glyphs(d, 24, int(C * 0.58), C - 60, r.randint(22, 34), ink, r)                      # the wordmark
    glyphs(d, 40, int(C * 0.58) + 40, C - 100, 9, ink, r)                                 # a tagline
    tiny_text(d, 20, int(C * 0.78), 120, 3, ink, r)                                       # fine print
    for k in range(5):                                                                    # a nutrition-style table
        d.rectangle([150, int(C * 0.74) + k * 7, 236, int(C * 0.74) + k * 7 + 5], outline=ink)
        d.line([200, int(C * 0.74) + k * 7, 200, int(C * 0.74) + k * 7 + 5], fill=ink)
    barcode(d, 175 if r.random() < 0.5 else 20, 214, 56, 24, r)
    d.ellipse([228, 8, 246, 26], outline=ink, width=2); d.polygon([(237, 12), (242, 22), (232, 22)], outline=ink)   # a recycle-style mark
    d.line([0, 0, 0, C], fill=(int(base[0] * 150), int(base[1] * 150), int(base[2] * 150)), width=2)          # the label seam
    return im


def main(out=OUT):
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    at = Image.new("RGB", (N * C, N * C))
    for k in range(N * N):
        at.paste(cell(1000 + k), ((k % N) * C, (k // N) * C))
    at.save(out); print(out)


if __name__ == "__main__":
    main(*(sys.argv[1:2]))
