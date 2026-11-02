"""Generate invented medicine-box label textures (no brands, no readable text: grey bars stand for print) into data/venue_refs/product_labels/med_box_NN.png.

    python3 gen_med_labels.py [out_dir]        # 12 files, 512 x 512: a white pack with a coloured band, a cross / drop / leaf emblem, ruled 'text' bars
Used by realize when the venue is a pharmacy (LABEL_POOL override).
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/jarvis/project/robomituba/data/venue_refs/product_labels")
BANDS = ((30, 120, 200), (40, 160, 90), (230, 140, 30), (210, 70, 110), (20, 150, 160), (110, 80, 180), (200, 40, 40), (60, 170, 60))


def one(i):
    r = random.Random(900 + i); W = 512; band = BANDS[i % len(BANDS)]
    im = Image.new("RGB", (W, W), (248, 248, 246)); d = ImageDraw.Draw(im)
    if i % 3 == 0:                                                      # coloured top band
        d.rectangle((0, 0, W, 150), fill=band)
    elif i % 3 == 1:                                                    # coloured left stripe
        d.rectangle((0, 0, 120, W), fill=band)
    else:                                                               # coloured bottom band
        d.rectangle((0, W - 140, W, W), fill=band)
    cx, cy = (330, 270) if i % 3 == 1 else (256, 290 if i % 3 == 0 else 190)
    kind = i % 4
    if kind == 0:                                                       # cross
        d.rectangle((cx - 20, cy - 60, cx + 20, cy + 60), fill=band); d.rectangle((cx - 60, cy - 20, cx + 60, cy + 20), fill=band)
    elif kind == 1:                                                     # drop
        d.polygon([(cx, cy - 70), (cx + 45, cy + 20), (cx, cy + 60), (cx - 45, cy + 20)], fill=band)
    elif kind == 2:                                                     # leaf
        d.ellipse((cx - 60, cy - 35, cx + 60, cy + 35), fill=band); d.line((cx - 60, cy + 35, cx + 60, cy - 35), fill=(248, 248, 246), width=6)
    else:                                                               # ring
        d.ellipse((cx - 55, cy - 55, cx + 55, cy + 55), outline=band, width=18)
    y = 360 if i % 3 != 2 else 270
    for k in range(5):                                                  # ruled print bars
        x0 = 150 if i % 3 == 1 else 40
        d.rectangle((x0, y + k * 26, x0 + r.randint(180, 320 - (60 if i % 3 == 1 else 0)), y + k * 26 + 10), fill=(120, 124, 128))
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for i in range(12):
        one(i).save(OUT / f"med_box_{i + 1:02d}.png")
    print("wrote 12 med_box labels to", OUT)
