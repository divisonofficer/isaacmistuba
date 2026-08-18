#!/usr/bin/env python3
"""Validate an IR dataset and optionally run a deterministic RGB rerender gate."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.multimodal import camera_to_world_to_lookat  # noqa: E402
from mitsuba_converter.material_pipeline import uses_specular_semantic_masks, validate_ir_effective_scene  # noqa: E402

WEIGHT_RE = re.compile(r"^.*\.weight\.value$")


def _read_exr(path: Path) -> np.ndarray:
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    import cv2
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"failed to read EXR: {path}")
    if value.ndim == 3 and value.shape[2] == 3:
        value = value[..., ::-1]
    return np.asarray(value, np.float32)


def _read_png(path: Path, encoding: str | None) -> np.ndarray:
    import cv2
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"failed to read PNG: {path}")
    if value.ndim == 3 and value.shape[2] == 3:
        value = value[..., ::-1]  # BGR -> RGB
    array = np.asarray(value)
    if encoding in {"linear_unorm16", "perceptual_roughness_unorm16", "unorm16",
                    "roughness_metallic_validity_unorm16"}:
        return array.astype(np.float32) / 65535.0
    if encoding == "xyz_signed_to_unorm16":
        decoded = array.astype(np.float32) / 65535.0 * 2.0 - 1.0
        if decoded.ndim == 3:
            norm = np.linalg.norm(decoded, axis=-1, keepdims=True)
            decoded = np.where(norm > 1e-8, decoded / np.maximum(norm, 1e-8), decoded)
        return decoded
    if encoding == "millimeters_u16":
        return array.astype(np.float32) / 1000.0
    if encoding == "uint16_plus_one":
        return array.astype(np.int32) - 1
    if encoding == "uint16":
        return array.astype(np.int32)
    if encoding == "binary_mask_u8":
        return (array > 0).astype(np.float32)
    return array.astype(np.float32)


def _read_artifact(path: Path, encoding: str | None) -> np.ndarray:
    if path.suffix.lower() == ".exr":
        return _read_exr(path)
    if path.suffix.lower() == ".png":
        return _read_png(path, encoding)
    raise ValueError(f"unsupported artifact extension: {path}")


def _static_validation(dataset: Path, scene_dir: Path) -> dict:
    rows = [json.loads(line) for line in (dataset / "index.jsonl").read_text().splitlines() if line.strip()]
    contract_path = dataset / "gt_artifact_contract.json"
    contract = json.loads(contract_path.read_text()) if contract_path.is_file() else {}
    artifact_specs = dict(contract.get("artifacts") or {})
    aliases = dict(contract.get("aliases") or {})
    domain_error: Exception | None = None
    try:
        domain = validate_ir_effective_scene(scene_dir)
    except Exception as exc:
        domain = {}
        domain_error = exc

    def artifact_encoding(name: str) -> str | None:
        canonical = aliases.get(name, name)
        spec = artifact_specs.get(canonical) or artifact_specs.get(name) or {}
        return spec.get("encoding")
    required_obs = {"rgb", "nir_ambient", "nir_flash_direct", "nir_active", "nir_dflash"}
    required_gt = {"base_color", "rgb_albedo", "nir_albedo", "roughness_perceptual", "metallic",
                   "normal_geometry_world", "normal_shading_world", "normal_tangent", "depth", "range"}
    required_masks = {"material_id", "object_id", "valid_mask", "replacement_mask"}
    if uses_specular_semantic_masks(str(domain.get("surface_domain") or "")):
        required_masks.update({"window_glass", "object_glass", "glass", "mirror"})
    failures: list[str] = []
    if domain_error is not None:
        failures.append(f"effective scene validation failed: {domain_error}")
    frame_stats = []
    for row in rows:
        row_required_obs = set(required_obs)
        if bool((row.get("render_config") or {}).get("polarized")):
            row_required_obs.update({"dop", "aolp"})
        for group, required in (("observation_paths", row_required_obs), ("gt_paths", required_gt),
                                ("mask_paths", required_masks)):
            missing = required - set(row.get(group) or {})
            if missing:
                failures.append(f"{row['frame_id']}: {group} missing {sorted(missing)}")
        arrays = {}
        for group in ("observation_paths", "gt_paths", "mask_paths"):
            for name, value in (row.get(group) or {}).items():
                path = Path(value)
                if not path.is_file():
                    failures.append(f"{row['frame_id']}: missing {path}")
                    continue
                array = _read_artifact(path, artifact_encoding(name)); arrays[name] = array
                if not np.isfinite(array).all():
                    failures.append(f"{row['frame_id']}: non-finite {name}")
        shape = (int(row["intrinsics"]["height"]), int(row["intrinsics"]["width"]))
        for name, array in arrays.items():
            if array.shape[:2] != shape:
                failures.append(f"{row['frame_id']}: {name} shape {array.shape} != {shape}")
        for name in ("roughness_perceptual", "metallic", "valid_mask", "replacement_mask", "window_glass", "object_glass", "glass", "mirror"):
            if name in arrays and (arrays[name].min() < -1e-6 or arrays[name].max() > 1 + 1e-6):
                failures.append(f"{row['frame_id']}: {name} outside [0,1]")
        hit = arrays.get("depth", np.zeros(shape)) > 0
        valid = arrays.get("valid_mask", np.zeros(shape)) > 0.5
        special = np.zeros(shape, dtype=bool)
        if uses_specular_semantic_masks(str(domain.get("surface_domain") or "")):
            window = arrays.get("window_glass", np.zeros(shape)) > 0.5
            object_glass = arrays.get("object_glass", np.zeros(shape)) > 0.5
            glass = arrays.get("glass", np.zeros(shape)) > 0.5
            mirror = arrays.get("mirror", np.zeros(shape)) > 0.5
            if np.any(window & object_glass) or np.any(window & mirror) or np.any(object_glass & mirror):
                failures.append(f"{row['frame_id']}: special-surface masks overlap")
            if not np.array_equal(glass, window | object_glass):
                failures.append(f"{row['frame_id']}: glass mask is not window/object-glass union")
            special = glass | mirror
            if np.any(valid & special):
                failures.append(f"{row['frame_id']}: final PBR validity includes glass/mirror pixels")

        missing_hit = float((hit & ~valid & ~special).mean())
        if missing_hit > 1e-6:
            failures.append(f"{row['frame_id']}: non-special hit pixels without valid GT={missing_hit:.6f}")
        frame_stats.append({"frame_id": row["frame_id"], "hit_coverage": float(hit.mean()),
                            "valid_coverage": float(valid.mean()),
                            "replacement_coverage": float((arrays.get("replacement_mask", 0) > 0.5).mean()),
                            "glass_coverage": float((arrays.get("glass", 0) > 0.5).mean()),
                            "mirror_coverage": float((arrays.get("mirror", 0) > 0.5).mean())})

    effective_digest = str(domain.get("effective_scene_digest") or "")
    for row in rows:
        if effective_digest and row.get("effective_scene_digest") != effective_digest:
            failures.append(f"{row['frame_id']}: effective scene digest mismatch")
        if domain and row.get("surface_domain") != domain.get("surface_domain"):
            failures.append(f"{row['frame_id']}: surface domain mismatch")
    audit_path = dataset / "render_input_audit.json"
    render_input_audit = json.loads(audit_path.read_text()) if audit_path.is_file() else None
    if render_input_audit is not None:
        if render_input_audit.get("effective_scene_digest") != effective_digest:
            failures.append("render input audit effective-scene digest mismatch")
        if domain and render_input_audit.get("surface_domain") != domain.get("surface_domain"):
            failures.append("render input audit surface-domain mismatch")
        geometry_audit = dict(render_input_audit.get("geometry") or {})
        decimation = str(geometry_audit.get("ir_materializer_decimation") or "none")
        if decimation not in {"none", "ir_semantic_lod_v1"}:
            failures.append(f"unsupported render geometry profile: {decimation}")
        if decimation == "ir_semantic_lod_v1":
            if not geometry_audit.get("common_geometry") or not geometry_audit.get("derived_geometry_digest"):
                failures.append("IR LOD render input audit lacks common-geometry provenance")
            if geometry_audit.get("source_triangles_before_structural_removal") is None or geometry_audit.get("triangles_after_lod") is None:
                failures.append("IR LOD render input audit lacks structural/LOD triangle accounting")
        any_polar = any(bool((row.get("render_config") or {}).get("polarized")) for row in rows)
        if bool(render_input_audit.get("polarized_render_requested")) != any_polar:
            failures.append("render input audit polarized setting differs from frame records")
        for build in render_input_audit.get("band_scene_builds") or []:
            if domain.get("surface_domain") == "opaque_pbr" and int(build.get("measured_leaf_count_after_policy", 0)) != 0:
                failures.append("opaque-PBR band scene retained measured BSDF leaves")
    assembly_path = dataset / "ir_dataset_assembly.json"
    assembly = json.loads(assembly_path.read_text()) if assembly_path.is_file() else None
    if assembly is not None and assembly.get("effective_scene_digest") != effective_digest:
        failures.append("IR assembly effective-scene digest mismatch")
    if uses_specular_semantic_masks(str(domain.get("surface_domain") or "")):
        expected_policy = "blender_pbr_validity_and_not_first_hit_glass_or_mirror_v1"
        if assembly is None or assembly.get("pbr_validity_policy") != expected_policy:
            failures.append("specular-masked dataset is missing final PBR validity assembly policy")
    root = ET.parse(scene_dir / "render_scene.xml").getroot()
    forbidden = [b.get("type") for b in root.iter("bsdf")
                 if b.get("type") in {"dielectric", "roughdielectric", "thindielectric",
                                       "measured", "measured_polarized", "measured_polarized_rgb"}]
    if domain.get("surface_domain") == "opaque_pbr" and forbidden:
        failures.append(f"effective scene retained forbidden opaque-PBR leaves: {forbidden[:12]}")
    return {"frame_count": len(rows), "frames": frame_stats,
            "surface_domain": domain.get("surface_domain"),
            "effective_scene_digest": effective_digest,
            "forbidden_top_level_bsdf_count": len(forbidden),
            "render_input_audit_present": render_input_audit is not None,
            "failures": failures, "passed": not failures}


def _rerender(dataset: Path, frame_id: str, spp: int, *, max_mae: float, min_psnr: float) -> dict:
    import mitsuba as mi
    mi.set_variant("cuda_ad_spectral")
    label = json.loads((dataset / frame_id / "frame.json").read_text())
    scene = mi.load_file(str(dataset / "scene_band_passive.xml"))
    params = mi.traverse(scene)
    camera_key = next(k for k in params.keys() if k.endswith(".to_world"))
    fov_key = next((k for k in params.keys() if k.endswith(".x_fov")), None)
    camera = np.asarray(label["camera_to_world"], np.float32)
    origin, target, up = camera_to_world_to_lookat(camera)
    look = mi.ScalarTransform4f().look_at(origin=list(origin), target=list(target), up=list(up))
    params[camera_key] = mi.Transform4f(look.matrix)
    if fov_key:
        params[fov_key] = float(label["intrinsics"]["fov_deg"])
    for key in params.keys():
        if WEIGHT_RE.match(key):
            params[key] = mi.Float(0.0)
    params.update()
    rendered = np.asarray(mi.render(scene, spp=int(spp), seed=7))[..., :3].astype(np.float32)
    reference = _read_exr(Path(label["observation_paths"]["rgb"]))
    diff = rendered - reference
    mse = float(np.mean(diff * diff)); peak = max(float(np.max(np.abs(reference))), 1e-8)
    mae = float(np.mean(np.abs(diff)))
    psnr = float(20 * math.log10(peak / max(math.sqrt(mse), 1e-12)))
    return {"frame_id": frame_id, "spp": int(spp), "mae": mae,
            "rmse": math.sqrt(mse), "max_abs": float(np.max(np.abs(diff))),
            "psnr_db": psnr, "thresholds": {"max_mae": max_mae, "min_psnr_db": min_psnr},
            "passed": bool(mae <= max_mae and psnr >= min_psnr)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--rerender-frame")
    parser.add_argument("--spp", type=int, default=8)
    parser.add_argument("--max-mae", type=float, default=0.03)
    parser.add_argument("--min-psnr", type=float, default=20.0)
    args = parser.parse_args()
    report = {"schema": "robomituba.ir_validation.v1",
              "static": _static_validation(args.dataset, args.scene_dir)}
    if args.rerender_frame:
        report["rerender_gate"] = _rerender(
            args.dataset, args.rerender_frame, args.spp,
            max_mae=args.max_mae, min_psnr=args.min_psnr,
        )
    report["passed"] = report["static"]["passed"] and report.get("rerender_gate", {"passed": True})["passed"]
    path = args.dataset / "validation.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
