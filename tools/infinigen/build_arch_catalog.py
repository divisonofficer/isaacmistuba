"""Catalogue of the approved texturecan wall / floor / ceiling sets for architecture_textures.py: lightness, saturation, roughness,
physical size, approved roles, per set. Reads the registries under /bean/ir_pbr_assets (no copying of the 2k maps); writes
data/venue_refs/arch_textures/catalog.json.

    python3 build_arch_catalog.py
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path("/bean/ir_pbr_assets")
REGS = ("texturecan_structural_extended_v3", "texturecan_environment_merged_v1", "texturecan_structural_extended_v2", "texturecan_structural_v1")
OUT = Path("/jarvis/project/robomituba/data/venue_refs/arch_textures/catalog.json")


def stats(p):
    im = Image.open(p).convert("RGB"); im.thumbnail((96, 96))
    a = np.asarray(im, float) / 255.0
    mx, mn = a.max(2), a.min(2)
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return float((lin @ np.array([0.2126, 0.7152, 0.0722])).mean()), float(((mx - mn) / np.maximum(mx, 1e-3)).mean()), float(a.std())


seen, out = set(), []
for reg in REGS:
    d = json.load(open(ROOT / reg / "registry.lock.json"))
    for m in d["materials"]:
        if m["id"] in seen:
            continue
        maps = {k: ROOT / reg / v for k, v in m["maps"].items()}
        if not all(p.is_file() for p in maps.values()) or not {"base_color", "roughness", "normal_gl"} <= set(maps):
            continue
        lum, sat, sd = stats(maps["base_color"])
        rough = float(np.asarray(Image.open(maps["roughness"]).convert("L").resize((64, 64)), float).mean() / 255.0)
        seen.add(m["id"])
        out.append({"id": m["id"], "category": m["category"], "roles": m.get("approved_roles", []), "lum": round(lum, 3), "sat": round(sat, 3),
                    "contrast": round(sd, 3), "rough": round(rough, 3), "size_m": m.get("physical_size_m", {}).get("width", 2.0),
                    "maps": {k: str(v) for k, v in maps.items()}, "title": m.get("title", "")})
OUT.write_text(json.dumps(out, indent=1))
import collections
print(len(out), dict(collections.Counter((x["category"], "wall" in x["roles"], "floor" in x["roles"]) for x in out).most_common(12)))
