#!/usr/bin/env python3
"""Procedural material-mapping pipeline runner — one stage at a time, inspectable.

Each stage reads the previous stage's artifact from the scene dir and writes its own
sibling JSON so intermediate results can be eyeballed and diffed:

    python apps/material_pipeline.py extract      --scene <scene_id|path>
    python apps/material_pipeline.py canonicalize --scene <scene_id|path>

`--scene` accepts a scene id (resolved under out/opticalnav/opticalnav-v0.2/scenes/)
or a path to the scene dir / render_scene.xml.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for m in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO / "modules" / m / "src"))

from robomituba_bridge import canonical_document                       # noqa: E402
from mitsuba_converter.material_pipeline import (                      # noqa: E402
    extract_material_slots, load_material_slots, canonicalize_materials,
)
from mitsuba_converter.material_pipeline.extract import write_material_slots  # noqa: E402

DEFAULT_SCENES = REPO / "out/opticalnav/opticalnav-v0.2/scenes"


def resolve_scene(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    cand = DEFAULT_SCENES / arg
    if cand.exists():
        return cand
    raise SystemExit(f"scene not found: {arg} (looked in {cand})")


def _tier_histogram(materials) -> dict:
    from collections import Counter
    c: Counter = Counter()
    invalid = 0
    for m in materials:
        for p in m.parameters.values():
            if p.valid:
                c[f"tier{p.tier}"] += 1
            else:
                invalid += 1
    return {**dict(sorted(c.items())), "invalid": invalid}


def cmd_extract(scene: Path) -> int:
    doc = extract_material_slots(scene)
    out = write_material_slots(scene, doc)
    s = doc["summary"]
    print(f"[extract] {out}")
    print(f"  materials={s['material_count']} shapes={s['shape_count']} "
          f"unassigned={s['unassigned_shapes']}")
    return 0


def cmd_canonicalize(scene: Path) -> int:
    slots = load_material_slots(scene)
    if slots is None:
        print("[canonicalize] material_slots.json missing — running extract first")
        slots = extract_material_slots(scene)
        write_material_slots(scene, slots)
    materials = canonicalize_materials(slots)
    doc = canonical_document(slots["scene_id"], materials)
    scene_dir = scene.parent if scene.is_file() else scene
    out = scene_dir / "material_canonical.json"
    out.write_text(json.dumps(doc, indent=2))
    bsdf_hist: dict = {}
    for m in materials:
        bsdf_hist[m.canonical_bsdf] = bsdf_hist.get(m.canonical_bsdf, 0) + 1
    print(f"[canonicalize] {out}")
    print(f"  materials={len(materials)} canonical_bsdf={bsdf_hist}")
    print(f"  parameter provenance tiers={_tier_histogram(materials)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["extract", "canonicalize"])
    ap.add_argument("--scene", required=True, help="scene id or path to scene dir / render_scene.xml")
    a = ap.parse_args()
    scene = resolve_scene(a.scene)
    return {"extract": cmd_extract, "canonicalize": cmd_canonicalize}[a.stage](scene)


if __name__ == "__main__":
    raise SystemExit(main())
