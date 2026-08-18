#!/usr/bin/env python3
"""Merge effective-scene Mitsuba records with authoritative Blender PBR AOV GT."""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.material_pipeline import uses_specular_semantic_masks, validate_ir_effective_scene  # noqa: E402


_BLENDER_PBR = {
    "base_color_rgb": ("gt_paths", "rgb_albedo"),
    "roughness": ("gt_paths", "roughness_perceptual"),
    "metallic": ("gt_paths", "metallic"),
    "normal_shading_camera": ("gt_paths", "normal_shading_camera"),
    "pbr_validity": ("mask_paths", "valid_mask"),
}


def _read_binary_mask(path: Path) -> np.ndarray:
    import cv2
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"failed to read mask: {path}")
    if value.ndim == 3:
        value = value[..., 0]
    return np.asarray(value) > 0


def _write_final_pbr_validity(out: Path, frame_id: str, *, blender_validity: Path, glass: Path, mirror: Path) -> tuple[Path, dict[str, int]]:
    import cv2
    valid = _read_binary_mask(blender_validity)
    glass_mask = _read_binary_mask(glass)
    mirror_mask = _read_binary_mask(mirror)
    if valid.shape != glass_mask.shape or valid.shape != mirror_mask.shape:
        raise ValueError(
            f"{frame_id}: PBR validity/special-mask shape mismatch "
            f"valid={valid.shape} glass={glass_mask.shape} mirror={mirror_mask.shape}"
        )
    special = glass_mask | mirror_mask
    final = valid & ~special
    target = out / "valid_mask" / f"{frame_id}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target), np.where(final, 255, 0).astype(np.uint8)):
        raise OSError(f"{frame_id}: failed to write final PBR validity: {target}")
    return target.resolve(), {
        "blender_valid_pixels": int(valid.sum()),
        "glass_pixels": int(glass_mask.sum()),
        "mirror_pixels": int(mirror_mask.sum()),
        "excluded_special_pixels": int((valid & special).sum()),
        "final_valid_pixels": int(final.sum()),
    }


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _frame_json(row: dict[str, Any]) -> Path:
    explicit = row.get("frame_metadata_path")
    if explicit:
        return Path(str(explicit)).resolve()
    observations = dict(row.get("observation_paths") or {})
    rgb = observations.get("rgb")
    if not rgb:
        raise ValueError(f"{row.get('frame_id')}: RGB observation path is absent")
    return Path(rgb).resolve().parent / "frame.json"


def _validate_camera_contract(frame_id: str, observation: dict[str, Any], blender: dict[str, Any]) -> None:
    if blender.get("pose_source") != "observation_manifest":
        raise ValueError(f"{frame_id}: Blender GT did not use the observation pose manifest")
    observed = np.asarray(observation.get("camera_to_world"), dtype=np.float64)
    rendered = np.asarray(blender.get("camera_to_world_mitsuba"), dtype=np.float64)
    if observed.shape != (4, 4) or rendered.shape != (4, 4):
        raise ValueError(f"{frame_id}: camera_to_world must be a 4x4 matrix")
    if not np.all(np.isfinite(observed)) or not np.all(np.isfinite(rendered)):
        raise ValueError(f"{frame_id}: camera_to_world contains non-finite values")
    if not np.allclose(observed, rendered, rtol=1e-6, atol=1e-6):
        error = float(np.max(np.abs(observed - rendered)))
        raise ValueError(f"{frame_id}: Mitsuba/Blender camera pose differs (max_abs={error:.3g})")
    intrinsics = dict(observation.get("intrinsics") or {})
    expected = (int(intrinsics.get("width") or 0), int(intrinsics.get("height") or 0), float(intrinsics.get("fov_deg") or 0.0))
    actual = (int(blender.get("width") or 0), int(blender.get("height") or 0), float(blender.get("fov_deg") or 0.0))
    if expected[:2] != actual[:2] or not np.isclose(expected[2], actual[2], rtol=0.0, atol=1e-7):
        raise ValueError(f"{frame_id}: Mitsuba/Blender intrinsics differ: {expected} != {actual}")


def merge(dataset: Path, blender_gt: Path, effective_scene: Path, out: Path) -> dict[str, Any]:
    contract = validate_ir_effective_scene(effective_scene)
    digest = str(contract["effective_scene_digest"])
    out.mkdir(parents=True, exist_ok=True)
    requires_specular_masks = uses_specular_semantic_masks(str(contract.get("surface_domain") or ""))
    base = {str(row["frame_id"]): row for row in _rows(dataset / "index.jsonl")}
    blender = {str(row["frame_id"]): row for row in _rows(blender_gt / "index.jsonl")}
    table_path = blender_gt / "material_table.json"
    if not table_path.is_file():
        raise FileNotFoundError(f"Blender GT material table is absent: {table_path}")
    face_exclusion = dict(json.loads(table_path.read_text(encoding="utf-8")).get("face_exclusion") or {})
    requested = face_exclusion.get("requested_selector_count")
    resolved = face_exclusion.get("resolved_selector_count")
    unresolved = face_exclusion.get("unresolved_selector_count")
    if requested is not None and (int(unresolved or 0) != 0 or int(resolved or 0) != int(requested)):
        raise ValueError("Blender GT did not resolve every IR dielectric face selector")
    missing = sorted(set(base) ^ set(blender))
    if missing:
        raise ValueError(f"Mitsuba/Blender frame sets differ: {missing[:12]}")
    merged: list[dict[str, Any]] = []
    validity_stats: dict[str, dict[str, int]] = {}
    for frame_id in sorted(base):
        row = dict(base[frame_id])
        brow = blender[frame_id]
        if brow.get("effective_scene_digest") != digest:
            raise ValueError(f"{frame_id}: Blender GT effective scene digest differs")
        if row.get("effective_scene_digest") != digest:
            raise ValueError(f"{frame_id}: Mitsuba record effective scene digest differs")
        _validate_camera_contract(frame_id, row, brow)
        paths = dict(brow.get("paths") or {})
        missing_paths = sorted(set(_BLENDER_PBR) - set(paths))
        if missing_paths:
            raise ValueError(f"{frame_id}: Blender PBR artifacts missing {missing_paths}")
        for source, (group, target) in _BLENDER_PBR.items():
            artifact = Path(paths[source])
            if not artifact.is_file():
                raise FileNotFoundError(f"{frame_id}: Blender artifact missing {artifact}")
            row.setdefault(group, {})[target] = str(artifact.resolve())
        if requires_specular_masks:
            special_paths = dict(row.get("mask_paths") or {})
            missing_special = {"window_glass", "object_glass", "glass", "mirror"} - set(special_paths)
            if missing_special:
                raise ValueError(f"{frame_id}: special-surface masks missing {sorted(missing_special)}")
            special_artifacts = {name: Path(special_paths[name]) for name in ("window_glass", "object_glass", "glass", "mirror")}
            for name, artifact in special_artifacts.items():
                if not artifact.is_file():
                    raise FileNotFoundError(f"{frame_id}: special-surface mask missing {name}={artifact}")
            final_validity, stats = _write_final_pbr_validity(
                out, frame_id,
                blender_validity=Path(paths["pbr_validity"]),
                glass=special_artifacts["glass"],
                mirror=special_artifacts["mirror"],
            )
            row.setdefault("mask_paths", {})["valid_mask"] = str(final_validity)
            row["pbr_validity_policy"] = {
                "policy": "blender_pbr_validity_and_not_first_hit_glass_or_mirror_v1",
                "source_blender_validity": str(Path(paths["pbr_validity"]).resolve()),
                "special_mask_semantics": "primary_ray_first_geometric_hit_v1",
            }
            validity_stats[frame_id] = stats
        row.setdefault("gt_paths", {})["base_color"] = row["gt_paths"]["rgb_albedo"]
        row["schema"] = "robomituba.ir_frame.v3"
        row["surface_domain"] = contract["surface_domain"]
        row["effective_scene_digest"] = digest
        row["ir_scene_domain_ref"] = str((effective_scene / "ir_scene_domain.json").resolve())
        row["artifact_providers"] = {
            "blender_aov": ["rgb_albedo", "roughness_perceptual", "metallic", "normal_shading_camera"],
            "mitsuba_property": [
                key for key in sorted((row.get("gt_paths") or {}))
                if key not in {"base_color", "rgb_albedo", "roughness_perceptual", "metallic", "normal_shading_camera"}
            ],
            "mitsuba_primary_hit": ["window_glass", "object_glass", "glass", "mirror"] if requires_specular_masks else [],
            "derived": ["valid_mask"] if requires_specular_masks else [],
        }
        frame_json = _frame_json(row)
        _atomic_json(frame_json, row)
        merged.append(row)
    index = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in merged)
    temp = out / "index.jsonl.tmp"
    temp.write_text(index, encoding="utf-8")
    os.replace(temp, out / "index.jsonl")
    provenance = {
        "schema": "robomituba.ir_dataset_assembly.v1",
        "frame_count": len(merged),
        "surface_domain": contract["surface_domain"],
        "effective_scene_digest": digest,
        "effective_scene_ref": str(effective_scene.resolve()),
        "blender_gt_ref": str(blender_gt.resolve()),
        "pbr_provider": "blender_aov",
        "geometry_nir_provider": "mitsuba_property",
        "pbr_validity_policy": (
            "blender_pbr_validity_and_not_first_hit_glass_or_mirror_v1" if requires_specular_masks
            else "blender_pbr_validity"
        ),
        "frame_validity_stats": validity_stats,
    }
    _atomic_json(out / "ir_dataset_assembly.json", provenance)
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Mitsuba queue/run root")
    parser.add_argument("--blender-gt", type=Path, required=True)
    parser.add_argument("--effective-scene", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="defaults to --dataset and updates its final index")
    args = parser.parse_args()
    report = merge(args.dataset.resolve(), args.blender_gt.resolve(), args.effective_scene.resolve(), (args.out or args.dataset).resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
