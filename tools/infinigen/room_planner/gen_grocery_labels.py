"""Invented gourmet-grocery label textures (muted kraft / black / cream packs, fictional brand words) into data/venue_refs/product_labels/gro_<kind>_NN.png.

    python3 gen_grocery_labels.py [out_dir]     # kinds: jar, can, bottle, box, bag; 6 each, 1024 x 1024
Used by realize when the venue is 'grocery' (LABEL_POOL override). The market photos show dark, matte, small-print gourmet packs, not the
bright cartoon pool of the snack shop.
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/jarvis/project/robomituba/data/venue_refs/product_labels")
FB = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"; FR = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"; FS = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
BRANDS = ("VELLORA", "TARNIX", "OSTRA", "PANOLA", "MENTOZA", "MARLOW", "DORIVA", "KESSEL", "LUMINA", "BRANDT", "ALTEA", "NOVARRA")
WHAT = {"jar": ("PEPPER JAM", "OLIVE TAPENADE", "HONEY", "PICKLED BEETS", "ARTICHOKE", "FIG SPREAD"), "can": ("TOMATO", "CHICKPEAS", "SARDINES", "COCONUT MILK", "SWEET CORN", "TUNA"),
        "bottle": ("OLIVE OIL", "BALSAMIC", "SPARKLING WATER", "COLD BREW", "TONIC", "APPLE JUICE"), "box": ("PENNE", "OAT BISCUITS", "GREEN TEA", "COUSCOUS", "RICE CRACKERS", "MUESLI"),
        "bag": ("SEA SALT CHIPS", "ROASTED ALMONDS", "TORTILLA", "KETTLE CORN", "SEAWEED", "GRANOLA")}
PAL = (((38, 36, 34), (236, 226, 204)), ((196, 160, 112), (40, 30, 22)), ((236, 228, 210), (150, 48, 36)), ((28, 62, 52), (240, 228, 196)), ((176, 52, 40), (246, 238, 222)),
       ((44, 66, 108), (242, 236, 220)))


def fit(d, text, path, w, size):
    while size > 20:
        f = ImageFont.truetype(path, size)
        if d.textlength(text, font=f) <= w:
            return f
        size -= 6
    return ImageFont.truetype(path, 20)


def one(kind, i):
    r = random.Random(sum(map(ord, kind)) * 31 + i); bg, fg = PAL[i % len(PAL)]; W = 1024
    im = Image.new("RGB", (W, W), bg); d = ImageDraw.Draw(im)
    d.rectangle((40, 40, W - 40, W - 40), outline=fg, width=6)
    brand = BRANDS[(i * 2 + len(kind)) % len(BRANDS)]; what = WHAT[kind][i % 6]
    d.text((W / 2, 250), brand, font=fit(d, brand, FB, 760, 190), fill=fg, anchor="mm")
    d.line((200, 360, W - 200, 360), fill=fg, width=5)
    d.text((W / 2, 520), what, font=fit(d, what, FS, 760, 120), fill=fg, anchor="mm")
    cx, cy = W // 2, 720
    k = i % 3
    if k == 0:
        d.ellipse((cx - 90, cy - 90, cx + 90, cy + 90), outline=fg, width=14)
    elif k == 1:
        d.polygon([(cx, cy - 100), (cx + 90, cy + 70), (cx - 90, cy + 70)], fill=fg)
    else:
        d.ellipse((cx - 110, cy - 50, cx + 110, cy + 50), fill=fg)
    for n in range(2):                                                  # small print bars
        d.rectangle((300, 870 + n * 36, 300 + r.randint(220, 420), 886 + n * 36), fill=fg)
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for kind in WHAT:
        for i in range(6):
            one(kind, i).save(OUT / f"gro_{kind}_{i + 1:02d}.png")
    print("wrote", len(WHAT) * 6, "labels to", OUT)
