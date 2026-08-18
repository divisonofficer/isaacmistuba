#!/usr/bin/env python3
"""Create a material-stratified Stage-0 QC sheet from rendered modalities."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np


CATEGORIES = (
    "matte wall", "glossy cabinet", "metal appliance", "tile",
    "fallback", "window/mirror surrogate",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--material-contract", type=Path, required=True)
    parser.add_argument("--frame", help="frame id; defaults to the first index row")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--crop-size", type=int, default=180)
    return parser.parse_args()


def _read(path: Path) -> np.ndarray:
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise RuntimeError(f"cannot decode {path}")
    return value


def _unorm(image: np.ndarray) -> np.ndarray:
    if image.dtype == np.uint16:
        return image.astype(np.float32) / 65535.0
    if image.dtype == np.uint8:
        return image.astype(np.float32) / 255.0
    return image.astype(np.float32)


def _display(image: np.ndarray, *, hdr: bool = False) -> np.ndarray:
    value = _unorm(image)
    if value.ndim == 2:
        value = np.repeat(value[..., None], 3, axis=2)
    value = value[..., :3]
    if hdr:
        value = value / (1.0 + np.maximum(value, 0.0))
        value = np.maximum(value, 0.0) ** (1.0 / 2.2)
    return np.clip(value * 255.0, 0, 255).astype(np.uint8)


def _category(record: dict, rough: float, metal: float) -> str | None:
    text = " ".join((
        str(record.get("object_id", "")), str(record.get("blender_object", "")),
        str(record.get("source_material", "")), str(record.get("semantic_class", "")),
    )).lower()
    if record.get("fallback_channels"):
        return "fallback"
    if record.get("semantic_class") in {"window_glass", "mirror"}:
        return "window/mirror surrogate"
    if "wall" in text and rough >= 0.45:
        return "matte wall"
    if any(word in text for word in ("tile", "countertop", "backsplash")):
        return "tile"
    if metal >= 0.5 or any(word in text for word in ("oven", "microwave", "appliance")):
        return "metal appliance"
    if rough < 0.45 and any(word in text for word in ("cabinet", "kitchenspace", "shelf")):
        return "glossy cabinet"
    return None


def _crop_bounds(mask: np.ndarray, size: int) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    cy, cx = int(np.median(ys)), int(np.median(xs))
    half = max(8, size // 2)
    x0, y0 = max(0, cx - half), max(0, cy - half)
    x1, y1 = min(mask.shape[1], x0 + size), min(mask.shape[0], y0 + size)
    x0, y0 = max(0, x1 - size), max(0, y1 - size)
    return x0, y0, x1, y1


def _tile(image: np.ndarray, bounds, size: int) -> np.ndarray:
    x0, y0, x1, y1 = bounds
    return cv2.resize(image[y0:y1, x0:x1], (size, size), interpolation=cv2.INTER_NEAREST)


def main() -> int:
    args = _args()
    root = args.dataset.resolve()
    rows = [json.loads(line) for line in (root / "index.jsonl").read_text(encoding="utf-8").splitlines() if line]
    candidates = rows if not args.frame else [item for item in rows if item["frame_id"] == args.frame]
    if not candidates:
        raise ValueError(f"frame not present: {args.frame}")
    contract = json.loads(args.material_contract.read_text(encoding="utf-8"))
    records = {int(item["material_id"]): item for item in contract["materials"]}
    selected: dict[str, tuple[int, np.ndarray, dict[str, np.ndarray], dict]] = {}
    read_names = (
        "rgb", "nir_active", "base_color_rgb", "base_color_nir", "roughness", "metallic",
        "material_id", "source_valid_mask", "replacement_mask", "fallback_mask", "gt_defined_mask",
        "diffuse_shading_rgb", "diffuse_shading_nir",
    )
    for row in candidates:
        paths = row["paths"]
        raw = {name: _read(root / paths[name]) for name in read_names}
        if not all(value.shape[:2] == raw["rgb"].shape[:2] for value in raw.values()):
            raise RuntimeError(f"RGB/NIR/GT dimensions differ for {row['frame_id']}")
        rough = _unorm(raw["roughness"])
        metal = _unorm(raw["metallic"])
        material_ids = raw["material_id"].astype(np.int64)
        for material_id in np.unique(material_ids):
            mask = material_ids == material_id
            if int(mask.sum()) < 4 or int(material_id) not in records:
                continue
            category = _category(records[int(material_id)], float(rough[mask].mean()), float(metal[mask].mean()))
            if category and (category not in selected or int(mask.sum()) > int(selected[category][1].sum())):
                selected[category] = (int(material_id), mask, raw, row)

    display_labels = (
        "RGB", "Active NIR", "Base RGB", "Base NIR", "Roughness", "Metallic",
        "Shading RGB", "Shading NIR", "Replacement",
    )
    size = int(args.crop_size)
    header_h, info_h = 30, 55
    sheet = np.full((header_h + len(CATEGORIES) * (size + info_h), len(display_labels) * size, 3), 28, np.uint8)
    for column, label in enumerate(display_labels):
        cv2.putText(sheet, label, (column * size + 6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
    report = {
        "schema": "robomituba.ir_principled_stage0_qc.v1",
        "candidate_frames": [row["frame_id"] for row in candidates], "categories": {},
    }
    for index, category in enumerate(CATEGORIES):
        y = header_h + index * (size + info_h)
        if category not in selected:
            cv2.putText(sheet, f"{category}: not visible", (8, y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 160, 255), 1, cv2.LINE_AA)
            report["categories"][category] = {"visible": False}
            continue
        material_id, mask, raw, row = selected[category]
        paths = row["paths"]
        flash = _read(root / paths["qc_nir_flash"]) if paths.get("qc_nir_flash") else None
        displays = (
            _display(raw["rgb"], hdr=True), _display(raw["nir_active"], hdr=True),
            _display(raw["base_color_rgb"]), _display(raw["base_color_nir"]),
            _display(raw["roughness"]), _display(raw["metallic"]),
            _display(raw["diffuse_shading_rgb"], hdr=True), _display(raw["diffuse_shading_nir"], hdr=True),
            _display(raw["replacement_mask"]),
        )
        bounds = _crop_bounds(mask, size)
        for column, image in enumerate(displays):
            sheet[y:y + size, column * size:(column + 1) * size] = _tile(image, bounds, size)
        nir = raw["nir_active"]
        nir = nir[..., :3].mean(axis=2) if nir.ndim == 3 else nir
        values = nir[mask].astype(np.float32)
        replacement_ratio = float((_unorm(raw["replacement_mask"])[mask] > 0.5).mean())
        source_ratio = float((_unorm(raw["source_valid_mask"])[mask] > 0.5).mean())
        flash_ratio = None
        if flash is not None:
            flash_scalar = flash[..., :3].mean(axis=2) if flash.ndim == 3 else flash
            denominator = float(np.maximum(values, 0).sum())
            flash_ratio = float(np.maximum(flash_scalar[mask], 0).sum() / denominator) if denominator > 1e-12 else 0.0
        stats = {
            "visible": True, "frame_id": row["frame_id"], "material_id": material_id, "pixel_count": int(mask.sum()),
            "nir_mean": float(values.mean()), "nir_p95": float(np.percentile(values, 95)),
            "flash_contribution_ratio": flash_ratio,
            "saturation_ratio_gt_1": float((values > 1.0).mean()),
            "source_valid_ratio": source_ratio, "replacement_ratio": replacement_ratio,
        }
        report["categories"][category] = stats
        text = (
            f"{category} {row['frame_id']} id={material_id} NIR mean/p95={stats['nir_mean']:.3g}/{stats['nir_p95']:.3g} "
            f"flash={flash_ratio if flash_ratio is not None else 'n/a'} sat={stats['saturation_ratio_gt_1']:.3f} "
            f"src/repl={source_ratio:.3f}/{replacement_ratio:.3f}"
        )
        cv2.putText(sheet, text, (8, y + size + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (235, 235, 235), 1, cv2.LINE_AA)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.out), sheet):
        raise RuntimeError(f"failed to write {args.out}")
    report_path = args.out.with_suffix(".json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ir-principled-qc] frames={len(candidates)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
