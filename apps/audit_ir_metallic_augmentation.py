#!/usr/bin/env python3
"""Validate the continuous-metallic model against a rendered dataset's real GT.

Every input the augmentation needs is already stored per frame -- the binary
``metallic`` prior, ``roughness``, ``material_id`` and ``metallic_family_id``
as the semantic proxy, and ``base_color_rgb`` as albedo -- so the model can be
exercised on the true material distribution of an existing dataset without
spending a GPU-second.

The point is to check, *before* committing to a re-render, that on real data:

* metalness becomes genuinely continuous rather than the current 96 % binary
  split, and
* metalness stays correlated with but not determined by roughness, which is the
  property any "active NIR improved metallic estimation" claim rests on.

This is a read-only audit.  It never writes a label back into the dataset: the
RGB/NIR rasters were rendered with binary metalness, so an augmented label
would not describe the image that sits beside it.  Consistent labels come only
from re-rendering with the augmentation injected at the Stage-2 socket.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "navigation_dataset" / "src"))

from navigation_dataset.ir_metallic_composition import (  # noqa: E402
    correlation_report, composition_class, default_policy, hash_residual, luminance,
    material_seed, metallic_field, sample_coefficients, stable_digest,
)

SCHEMA = "robomituba.ir_metallic_augmentation_audit.v1"
#: ``metallic_family_id`` is a categorical uint8 AOV: 0 dielectric, 1 conductor,
#: 2 coverage_mixed.  Only the conductor-bearing families are augmented.
FAMILY_NAMES = {0: "dielectric", 1: "conductor", 2: "coverage_mixed"}


def _u16(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    return image.astype(np.float32) / 65535.0


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--policy", type=Path,
                        default=REPO_ROOT / "configs" / "ir_materials" / "metallic_composition_v1.json")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--sample-frames", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--metal-threshold", type=float, default=0.5,
                        help="authored metalness above which a pixel is treated as metal-bearing")
    return parser.parse_args()


def main() -> int:
    args = _args()
    dataset = args.dataset.resolve()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    policy_digest = stable_digest(policy)
    config = json.loads((dataset / "dataset_config.json").read_text(encoding="utf-8"))
    scene_id = str(config.get("scene_id") or dataset.name)

    rows = [json.loads(line) for line in (dataset / "index.jsonl").open(encoding="utf-8") if line.strip()]
    random.Random(args.seed).shuffle(rows)
    rows = rows[:args.sample_frames]

    source_all: list[np.ndarray] = []
    augmented_all: list[np.ndarray] = []
    roughness_all: list[np.ndarray] = []
    family_counts = {name: 0 for name in FAMILY_NAMES.values()}
    class_counts: dict[str, int] = {}
    frames_used = 0

    for row in rows:
        paths = row.get("paths") or {}
        metallic = _u16(dataset / paths["metallic"]) if paths.get("metallic") else None
        roughness = _u16(dataset / paths["roughness"]) if paths.get("roughness") else None
        if metallic is None or roughness is None:
            continue
        metallic = metallic[..., 0] if metallic.ndim == 3 else metallic
        roughness = roughness[..., 0] if roughness.ndim == 3 else roughness

        family = None
        if paths.get("metallic_family_id"):
            raw = cv2.imread(str(dataset / paths["metallic_family_id"]), cv2.IMREAD_UNCHANGED)
            if raw is not None:
                family = raw[..., 0] if raw.ndim == 3 else raw
        if family is None:
            # Without the family AOV, fall back to the authored value itself.
            family = np.where(metallic >= 0.5, 1, 0).astype(np.uint8)

        albedo = _u16(dataset / paths["base_color_rgb"]) if paths.get("base_color_rgb") else None
        lum = (luminance(albedo[..., :3]) if albedo is not None and albedo.ndim == 3
               else np.full(metallic.shape, 0.45, np.float32))

        material = None
        if paths.get("material_id"):
            raw = cv2.imread(str(dataset / paths["material_id"]), cv2.IMREAD_UNCHANGED)
            if raw is not None:
                material = raw[..., 0] if raw.ndim == 3 else raw

        for value, name in FAMILY_NAMES.items():
            family_counts[name] += int((family == value).sum())

        # Coverage-texture edge pixels carry a *coverage* fraction, not a
        # metalness.  Pooling them with real metal manufactures a roughness
        # correlation that does not exist on the pixels the label describes, so
        # the audited population is metal-bearing pixels only.
        conductor = np.isin(family, (1, 2)) & (metallic >= args.metal_threshold)
        if not bool(conductor.any()):
            frames_used += 1
            continue

        # Each distinct material id is one material slot, which is the unit the
        # coefficients are seeded per -- matching how Stage-2 would apply them.
        augmented = np.zeros_like(metallic)
        ids = np.unique(material[conductor]) if material is not None else np.array([0])
        for material_id in ids:
            mask = conductor & (material == material_id) if material is not None else conductor
            if not bool(mask.any()):
                continue
            unit_id = f"material_{int(material_id)}"
            family_name = "coverage_mixed" if int((family[mask] == 2).sum()) > int(mask.sum()) // 2 else "conductor"
            composition = composition_class(unit={"id": unit_id, "kind": "asset"},
                                            source_material=unit_id, source_family=family_name)
            class_counts[composition["class"]] = class_counts.get(composition["class"], 0) + 1
            seed = material_seed(policy_digest=policy_digest, scene_id=scene_id,
                                 unit_id=unit_id, slot=0, source_material=unit_id)
            coefficients = sample_coefficients(policy=policy, composition=composition["class"], seed=seed)
            augmented[mask] = metallic_field(
                source_metallic=metallic[mask], roughness=roughness[mask],
                albedo_luminance=lum[mask], residual=hash_residual(metallic[mask].shape, seed=seed),
                coefficients=coefficients, source_family=family_name,
            )
        source_all.append(metallic[conductor])
        augmented_all.append(augmented[conductor])
        roughness_all.append(roughness[conductor])
        frames_used += 1

    if not augmented_all:
        raise SystemExit(f"no metal-bearing pixels found in {frames_used} sampled frames of {dataset.name}")

    source = np.concatenate(source_all)
    augmented = np.concatenate(augmented_all)
    rough = np.concatenate(roughness_all)

    def _intermediate(values: np.ndarray) -> float:
        return round(float(((values > 0.02) & (values < 0.98)).mean()), 6)

    family_total = max(sum(family_counts.values()), 1)
    payload = {
        "schema": SCHEMA,
        "dataset": dataset.name,
        "dataset_fingerprint": config.get("dataset_fingerprint"),
        "policy_id": policy.get("policy_id"),
        "policy_digest": policy_digest,
        "sampled_frame_count": frames_used,
        "metal_bearing_pixel_count": int(source.size),
        "metal_threshold": float(args.metal_threshold),
        "family_pixel_fraction": {name: round(count / family_total, 6)
                                  for name, count in family_counts.items()},
        "composition_class_slot_counts": dict(sorted(class_counts.items())),
        "source_intermediate_fraction": _intermediate(source),
        "augmented_intermediate_fraction": _intermediate(augmented),
        "source_quantiles": {f"p{q}": round(float(np.percentile(source, q)), 6)
                             for q in (1, 10, 50, 90, 99)},
        "augmented_quantiles": {f"p{q}": round(float(np.percentile(augmented, q)), 6)
                                for q in (1, 10, 50, 90, 99)},
        "correlation": correlation_report(augmented, rough),
        "note": ("read-only audit; the rendered RGB/NIR used binary metalness so these labels are "
                 "diagnostic only and must not be written back as training targets"),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in (
        "dataset", "metal_bearing_pixel_count", "source_intermediate_fraction",
        "augmented_intermediate_fraction",
    )} | {"pearson": payload["correlation"]["pearson"],
          "r_squared": payload["correlation"]["r_squared"],
          "min_conditional_std": payload["correlation"]["min_conditional_std"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
