"""Turn the generated museum artwork in data/venue_refs/museum_art/src/ into the textures museum_shell reads (pure PIL + numpy; run with any python3):

    python3 -m room_planner.museum_art_ingest            # or: python3 museum_art_ingest.py

  src/fresco_dome.png  (a circular fresco seen from below, centred on a square canvas)  ->  fresco_dome.png   a polar strip 2048x512: u = angle, v = 0 at the dome base .. 1 at
                                                                                       the oculus, sampled at radius cos(0.97 pi/2 v) (the dome's own top-down projection)
  src/frieze.png       (a wide mural strip)                                           ->  frieze_strip.png  4096 x h, as is (the shell repeats it 3x round the octagon)
  src/floor_mosaic.png (top-down square mosaic)                                       ->  floor_mosaic.png  2048 square, as is
Missing sources are skipped; museum_shell falls back to the generated abstract art (gen_museum_art.py) when an output is absent.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

ART = Path("/jarvis/project/robomituba/data/venue_refs/museum_art")


def polar_strip(src, w=2048, h=512, edge=0.95, centre=(0.49805, 0.48926), grade=True):
    im = np.asarray(Image.open(src).convert("RGB")); H, W = im.shape[:2]; cx, cy, R = W * centre[0], H * centre[1], min(W, H) / 2 * edge        # the oculus centre measured on the generated fresco (manifest: 0.49805, 0.48926 for the rough fresco; 0.49967 for the first)
    ang = np.linspace(0, 2 * math.pi, w, endpoint=False)[None, :]
    v = 1.0 - (np.arange(h)[:, None] + 0.5) / h                         # image row 0 = top = the oculus end (v = 1)
    rho = 0.5 * np.cos(0.97 * math.pi / 2 * v) + 0.5 * (1.0 - 0.97 * v)          # half true top-down projection, half equidistant: pure cosine smeared the dome base into vertical streaks
    x = np.clip((cx + rho * R * np.cos(ang)).astype(int), 0, W - 1); y = np.clip((cy + rho * R * np.sin(ang)).astype(int), 0, H - 1)
    out = im[y, x].astype(np.float32)
    if not grade:                                                                                      # the blue fresco already has the wanted tones
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    g = out.mean(axis=2, keepdims=True); out = g + (out - g) * 0.92                                   # near the generated saturation
    out = out * np.array([0.93, 1.0, 1.14], dtype=np.float32)                                          # cool it: pale blue sky tones (S25 A/B flipped: 'bright, light BLUE watercolour')
    out = 255.0 * np.clip(out / 255.0, 0, 1) ** 0.75                                                   # lift the midtones: bright, not dark heavy orange-brown
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def main():
    s = ART / "src"; done = []
    pick = lambda n: next((s / f for f in (f"{n}_blue.png", f"{n}_rough.png", f"{n}.png") if (s / f).exists()), None)     # the painterly 'rough' version wins when present
    if pick("fresco_dome"):
        blue = pick("fresco_dome").name.endswith("_blue.png")
        polar_strip(pick("fresco_dome"), centre=(0.500326, 0.486979) if blue else (0.49805, 0.48926), grade=not blue).save(ART / "fresco_dome.png"); done.append(f"fresco_dome<-{pick('fresco_dome').name}")
    if pick("frieze"):
        Image.open(pick("frieze")).convert("RGB").save(ART / "frieze_strip.png"); done.append(f"frieze_strip<-{pick('frieze').name}")
    if (s / "floor_mosaic.png").exists():
        Image.open(s / "floor_mosaic.png").convert("RGB").resize((2048, 2048), Image.LANCZOS).save(ART / "floor_mosaic.png"); done.append("floor_mosaic")
    print("ingested:", done or "nothing (no sources yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
