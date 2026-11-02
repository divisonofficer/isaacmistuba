#!/usr/bin/env python3
"""Mark the material ids whose surfaces a metallic-roughness GT cannot describe.

The PBR target models opaque dielectrics and conductors. A transmissive surface
-- a bottle, a lampshade, a mesh panel -- has no base colour and roughness that
reproduce it, so a pixel showing one is not a training example of anything; it
is a wrong label wearing a confident mask.

The pipeline already knows how to exclude such a surface. `prepare` computes
`pbr_training_valid = training_valid and not glass`, and decides `glass` from
the material name containing "glass" or a `KHR_materials_transmission` factor
above threshold. Both tests come from HSSD, where architectural glass is named
and often declared. Measured across this corpus:

    material slots                        5,021
    transmission_factor > 0                   0     ABO does not use the extension
    alphaMode BLEND                         155
    alphaMode MASK                           15
    caught by the current rule                1     one material happens to be named

So 154 transmissive materials render with a PBR target they cannot have, and
`glass_mask` reads 0.00% on every frame in the corpus -- a mask that is not
wrong about anything it says, and says nothing.

Flagging every BLEND material would over-correct. `alphaMode: BLEND` declares
that alpha should be honoured, not that any of it is below 1. Measured on the
58 distinct (asset, material) pairs here: 37 carry real transparency and 21 are
effectively opaque, so the declaration alone would discard a third of them for
nothing. This reads the actual alpha -- the base colour factor, and the alpha
channel of the base colour texture -- and flags on evidence.

Why a table rather than a re-render: `material_id` is a per-pixel AOV and
`material_remediation.json` records, per scene, which id belongs to which
material. That pair already resolves transparency per pixel for all 200
rendered scenes, at no render cost. The pipeline should also learn this for
future renders, which is a separate change to the shared `prepare`; this makes
the existing corpus usable now.

    valid = pbr_validity & (layer_count <= 1) & ~transparent[material_id]

The middle term is a different question -- whether the pixel sees one surface
at all -- and neither implies the other.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

SCHEMA = "robomituba.abo_transparency_mask.v1"
#: Below this, the base colour factor's alpha is itself declaring transparency.
FACTOR_THRESHOLD = 0.95
#: A texture needs more than a rim of soft alpha before the surface counts as
#: transmissive; antialiased cutout edges alone are not a transparent material.
TEXTURE_FRACTION_THRESHOLD = 0.02
TEXTURE_ALPHA_THRESHOLD = 0.95


def texture_alpha_fraction(gltf_path: Path, document: dict, texture_index: int | None) -> float | None:
    """Fraction of the base colour texture's pixels that are not fully opaque.

    None when there is no texture or it carries no alpha channel at all, which
    is different from measuring zero: one is "no evidence", the other is
    "evidence of opacity".
    """
    if texture_index is None:
        return None
    textures = document.get("textures") or []
    if texture_index >= len(textures):
        return None
    source = textures[texture_index].get("source")
    images = document.get("images") or []
    if source is None or source >= len(images):
        return None
    uri = images[source].get("uri")
    if not uri:
        return None
    path = gltf_path.parent / uri
    if not path.is_file():
        return None
    try:
        image = Image.open(path)
        if image.mode not in ("RGBA", "LA", "PA"):
            return None
        alpha = np.asarray(image.convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    except OSError:
        return None
    return float((alpha < TEXTURE_ALPHA_THRESHOLD).mean())


def classify(record: dict, bundle: Path | None) -> dict[str, Any]:
    """Decide whether one material's surface can carry a PBR target."""
    source = record.get("source_mr") or {}
    mode = source.get("alpha_mode", "OPAQUE")
    transmission = float(source.get("transmission_factor") or 0.0)
    name = str(record.get("material_name", "")).lower()

    evidence: list[str] = []
    factor = None
    fraction = None

    if transmission > 0.0:
        evidence.append(f"transmission_factor={transmission:.3f}")
    if "glass" in name and "border" not in name and "frame" not in name:
        evidence.append("material_name:glass")

    if mode in ("BLEND", "MASK") and bundle is not None and bundle.is_file():
        document = json.loads(bundle.read_text(encoding="utf-8"))
        materials = document.get("materials") or []
        index = record.get("material_index")
        material = materials[index] if isinstance(index, int) and index < len(materials) else {}
        pbr = material.get("pbrMetallicRoughness") or {}
        factor = float((pbr.get("baseColorFactor") or [1.0, 1.0, 1.0, 1.0])[3])
        fraction = texture_alpha_fraction(bundle, document,
                                          (pbr.get("baseColorTexture") or {}).get("index"))
        if factor < FACTOR_THRESHOLD:
            evidence.append(f"baseColorFactor.a={factor:.3f}")
        if fraction is not None and fraction > TEXTURE_FRACTION_THRESHOLD:
            evidence.append(f"texture_alpha_below_{TEXTURE_ALPHA_THRESHOLD}={fraction:.3f}")

    return {
        "material_id": record.get("material_id"),
        "asset_id": record.get("asset_id"),
        "material_name": record.get("material_name"),
        "alpha_mode": mode,
        "base_color_factor_alpha": factor,
        "texture_alpha_fraction": fraction,
        "transparent": bool(evidence),
        "evidence": evidence,
        # Recorded so a reader can see that declaring BLEND was not sufficient,
        # rather than having to trust that it was checked.
        "declared_blend_but_opaque": mode in ("BLEND", "MASK") and not evidence,
    }


def build(scene: Path) -> dict[str, Any] | None:
    remediation = scene / "material_remediation.json"
    manifest = scene / "scene_manifest.json"
    if not remediation.is_file() or not manifest.is_file():
        return None
    records = json.loads(remediation.read_text(encoding="utf-8")).get("materials") or []
    cache = (json.loads(manifest.read_text(encoding="utf-8")).get("asset_cache") or {})
    rows = []
    for record in records:
        entry = cache.get(record.get("asset_id")) or {}
        bundle = Path(entry["gltf"]) if entry.get("gltf") else None
        rows.append(classify(record, bundle))
    transparent = sorted(r["material_id"] for r in rows if r["transparent"])
    return {
        "schema": SCHEMA,
        "scene_id": scene.name,
        "how_to_use": ("material_id is a per-pixel AOV; exclude a pixel when its id is in "
                       "transparent_material_ids. Round it first -- about 4% of pixels fall "
                       "between two ids at a silhouette, and those are already covered by "
                       "layer_count > 1, which is a different question and not implied by "
                       "this one."),
        "transparent_material_ids": transparent,
        "material_count": len(rows),
        "transparent_count": len(transparent),
        "blend_declared_but_opaque": sum(r["declared_blend_but_opaque"] for r in rows),
        "materials": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out-name", default="transparent_materials.json",
                        help="written inside each scene directory")
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    scenes = sorted(p for p in args.root.glob("abo_cornell_*") if p.is_dir())
    totals = {"scenes": 0, "materials": 0, "transparent": 0, "blend_but_opaque": 0}
    affected = []
    for scene in scenes:
        result = build(scene)
        if result is None:
            continue
        totals["scenes"] += 1
        totals["materials"] += result["material_count"]
        totals["transparent"] += result["transparent_count"]
        totals["blend_but_opaque"] += result["blend_declared_but_opaque"]
        if result["transparent_count"]:
            affected.append((scene.name, result["transparent_count"]))
        if not args.dry_run:
            (scene / args.out_name).write_text(json.dumps(result, indent=1) + "\n",
                                               encoding="utf-8")
    print(f"[transparency] {totals['scenes']} scenes, {totals['materials']} materials")
    print(f"[transparency] transparent {totals['transparent']}, "
          f"declared BLEND/MASK but measured opaque {totals['blend_but_opaque']}")
    print(f"[transparency] scenes with at least one: {len(affected)}")
    if args.summary and not args.dry_run:
        args.summary.write_text(json.dumps(
            {"schema": SCHEMA, "totals": totals,
             "scenes_with_transparent_materials": dict(affected)}, indent=1), encoding="utf-8")
        print(f"[transparency] summary -> {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
