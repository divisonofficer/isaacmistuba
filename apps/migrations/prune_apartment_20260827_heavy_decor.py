#!/usr/bin/env python3
"""Remove high-poly small decorative shapes from apartment_20260827 render XMLs.

The scene saturates a 32 GB GPU (31.2 GB resident) and geometry dominates that
footprint: shapes under 0.5 m carry 91% of the scene's 18.5M faces.  The 58
shapes pruned here are all decorative factories (plant containers, shelf
trinkets, cups, plates, a vase) with > 50k faces each — together 60.4% of all
faces and 3.06 GB of OBJ data — and are navigation-irrelevant.

Both render_scene.xml and render_scene_perturbed.xml are patched; originals are
kept as timestamped .bak siblings.  mesh_cache files are untouched, so
restoring the .bak fully restores the scene.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENE_DIR = REPO_ROOT / "out/opticalnav/opticalnav-v0.2/scenes/infinigen_apartment_natural_v1_20260827"
CANDIDATES_JSON = Path(
    "/tmp/claude-1000/-jarvis-project-robomituba/df000722-2bff-46db-ba5f-d7d0ce5cfee4/scratchpad/prune_candidates.json"
)
# Guard against accidentally running with a stale/edited candidate list: every
# id must belong to one of these decorative factories.
ALLOWED_FAMILIES = (
    "LargePlantContainerFactory", "NatureShelfTrinketsFactory",
    "VaseFactory", "CupFactory", "PlateFactory",
)


def prune_xml(xml_path: Path, prune_ids: set[str], *, apply: bool) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    removed: list[str] = []
    # shapes are direct children of <scene> in these staged XMLs, but walk all
    # parents to stay correct if any are nested.
    parents = {child: parent for parent in root.iter() for child in parent}
    for shape in list(root.iter("shape")):
        sid = shape.get("id") or ""
        if sid in prune_ids:
            parents[shape].remove(shape)
            removed.append(sid)
    if apply and removed:
        stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = xml_path.with_name(f"{xml_path.name}.{stamp}.bak")
        shutil.copy2(xml_path, backup)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        return {"xml": str(xml_path), "removed": len(removed), "backup": str(backup)}
    return {"xml": str(xml_path), "removed": len(removed), "backup": None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually write; default is dry-run")
    args = parser.parse_args()

    prune_ids = set(json.loads(CANDIDATES_JSON.read_text()))
    bad = [i for i in prune_ids if not any(f in i for f in ALLOWED_FAMILIES)]
    if bad:
        raise SystemExit(f"refusing: {len(bad)} candidate ids are not decorative factories: {bad[:5]}")
    print(f"prune candidates: {len(prune_ids)}")

    for name in ("render_scene.xml", "render_scene_perturbed.xml"):
        result = prune_xml(SCENE_DIR / name, prune_ids, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN"
        print(f"[{mode}] {result['xml']}: removed {result['removed']} shapes"
              + (f" (backup: {result['backup']})" if result["backup"] else ""))


if __name__ == "__main__":
    main()
