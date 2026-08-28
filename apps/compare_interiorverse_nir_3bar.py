#!/usr/bin/env python3
"""Create one reproducible CCS three-bar pseudo-NIR comparison sample."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.interiorverse_nir import (  # noqa: E402
    atomic_write_exr, atomic_write_json, axial_depth_to_points, ccs_ldl_3bar_bank,
    ccs_ldl_3bar_direct, colocated_light, ggx_direct, Light, load_frame, material_aware_passive_nir,
    pseudo_nir_albedo, shadow_visibility, visible_point_center,
)


def _stats(value: np.ndarray, valid: np.ndarray) -> dict[str, float]:
    x = np.asarray(value, np.float32)[valid]
    return {"mean": float(x.mean()), "p50": float(np.percentile(x, 50)),
            "p95": float(np.percentile(x, 95)), "p99_5": float(np.percentile(x, 99.5))}


def _preview(value: np.ndarray, valid: np.ndarray, exposure: float) -> np.ndarray:
    mapped = np.clip(np.maximum(value, 0.0) / max(exposure, 1e-8), 0.0, 1.0) ** (1.0 / 2.2)
    mapped[~valid] = 0.0
    return np.repeat(np.rint(mapped * 255.0).astype(np.uint8)[..., None], 3, axis=2)


def _preview_rgb(value: np.ndarray, valid: np.ndarray) -> np.ndarray:
    x = np.maximum(np.asarray(value, np.float32), 0.0)
    exposure = float(np.percentile(x[valid], 99.5)) if np.any(valid) else 1.0
    mapped = np.clip(x / max(exposure, 1e-8), 0.0, 1.0) ** (1.0 / 2.2)
    mapped[~valid] = 0.0
    return np.rint(mapped * 255.0).astype(np.uint8)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, default=Path("/bean/datasets/interiorverse_85_raw"))
    p.add_argument("--scene", default="L3D124S8ENDIMGPVYYUI5NYALUF3P3WK888")
    p.add_argument("--frame", default="009")
    p.add_argument("--out", type=Path, default=Path("/bean/datasets/interiorverse_85_nir_3bar_sample_v1"))
    p.add_argument("--shadow-map-size", type=int, default=512)
    p.add_argument("--samples-per-bar", type=int, default=3)
    p.add_argument("--relative-flux-per-bar", type=float, default=1.0,
                   help="pseudo-NIR scale; 12 W total vs three 2.3 W bars is 12/6.9=1.73913")
    p.add_argument("--visibility-mode", choices=("bank_center", "per_sample"), default="bank_center")
    p.add_argument("--geometry-mode", choices=("far_field_centroid", "quadrature"), default="far_field_centroid")
    p.add_argument("--angular-model", choices=("spot", "lambertian"), default="spot")
    args = p.parse_args()
    from mitsuba_converter.interiorverse_nir import FramePaths
    source = {name: args.source_root / args.scene / f"{args.frame}_{name}.exr"
              for name in ("im", "mask", "albedo", "depth", "material", "normal")}
    data = load_frame(FramePaths(args.scene, args.frame, source))
    points = axial_depth_to_points(data.depth_mm); points[~data.valid] = 0.0
    target = visible_point_center(points, data.valid)
    albedo = pseudo_nir_albedo(data.albedo_rgb); albedo[~data.valid] = 0.0
    passive, diffuse_shading, passive_confidence, passive_meta = material_aware_passive_nir(
        data.image_rgb, data.albedo_rgb, albedo, data.roughness, data.metallic,
        data.normal, data.depth_mm, data.valid,
    )
    legacy_light = colocated_light(target)
    legacy_visibility = shadow_visibility(points, data.valid, legacy_light, map_size=args.shadow_map_size)
    legacy_direct = ggx_direct(points, data.normal, data.roughness, data.metallic, albedo,
                               data.valid, legacy_light, legacy_visibility)
    total_relative_flux = 3.0 * args.relative_flux_per_bar
    full_power_spot = Light(
        position=legacy_light.position, direction=legacy_light.direction,
        intensity=total_relative_flux, beam_degrees=45.0, cutoff_degrees=52.0,
    )
    full_power_spot_direct = ggx_direct(
        points, data.normal, data.roughness, data.metallic, albedo, data.valid,
        full_power_spot, legacy_visibility,
    )
    full_power_lambertian = Light(
        position=legacy_light.position, direction=legacy_light.direction, intensity=total_relative_flux,
        beam_degrees=85.0, cutoff_degrees=85.0,
    )
    full_power_lambertian_visibility = shadow_visibility(
        points, data.valid, full_power_lambertian, map_size=args.shadow_map_size,
    )
    full_power_lambertian_direct = ggx_direct(
        points, data.normal, data.roughness, data.metallic, albedo, data.valid,
        full_power_lambertian, full_power_lambertian_visibility, emission_model="lambertian",
    )
    bank = ccs_ldl_3bar_bank(
        target, samples_per_bar=args.samples_per_bar,
        relative_flux_per_bar=args.relative_flux_per_bar,
    )
    bank_direct, bank_meta = ccs_ldl_3bar_direct(points, data.normal, data.roughness, data.metallic,
                                                  albedo, data.valid, bank,
                                                  shadow_map_size=args.shadow_map_size,
                                                  visibility_mode=args.visibility_mode,
                                                  geometry_mode=args.geometry_mode,
                                                  angular_model=args.angular_model)
    out = args.out / args.scene; out.mkdir(parents=True, exist_ok=True)
    atomic_write_exr(out / f"{args.frame}_nir_active_colocated_recomputed.exr", passive + legacy_direct)
    atomic_write_exr(out / f"{args.frame}_nir_active_point_spot_fullpower.exr", passive + full_power_spot_direct)
    atomic_write_exr(out / f"{args.frame}_nir_active_point_lambertian_fullpower.exr", passive + full_power_lambertian_direct)
    atomic_write_exr(out / f"{args.frame}_nir_active_ccs_ldl_3bar.exr", passive + bank_direct)
    atomic_write_exr(out / f"{args.frame}_nir_active_ccs_ldl_3bar_delta.exr", bank_direct - legacy_direct)
    atomic_write_exr(out / f"{args.frame}_nir_passive_material_aware.exr", passive)
    atomic_write_exr(out / f"{args.frame}_rgb_diffuse_shading.exr", diffuse_shading)
    diffuse_rgb = (1.0 - data.metallic[..., None]) * data.albedo_rgb
    atomic_write_exr(out / f"{args.frame}_rgb_diffuse_reconstruction.exr", diffuse_rgb * diffuse_shading[..., None])
    exposure = float(np.percentile(np.maximum(passive + bank_direct, 0.0)[data.valid], 99.5))
    montage = np.concatenate((
        _preview(passive + legacy_direct, data.valid, exposure),
        _preview(passive + full_power_spot_direct, data.valid, exposure),
        _preview(passive + full_power_lambertian_direct, data.valid, exposure),
        _preview(passive + bank_direct, data.valid, exposure),
    ), axis=1)
    cv2.imwrite(str(out / f"{args.frame}_nir_3bar_compare.png"), montage[..., ::-1])
    rgb_nir_montage = np.concatenate((
        _preview_rgb(data.image_rgb, data.valid),
        _preview(diffuse_shading, data.valid, float(np.percentile(diffuse_shading[data.valid], 99.5))),
        _preview(passive, data.valid, float(np.percentile(passive[data.valid], 99.5))),
        _preview(passive + bank_direct, data.valid, exposure),
    ), axis=1)
    cv2.imwrite(str(out / f"{args.frame}_rgb_diffuse_nir_compare.png"), rgb_nir_montage[..., ::-1])
    payload = {"scene": args.scene, "frame": args.frame, "target_camera_m": target.tolist(),
               "legacy_direct": _stats(legacy_direct, data.valid),
               "point_spot_fullpower_direct": _stats(full_power_spot_direct, data.valid),
               "point_lambertian_fullpower_direct": _stats(full_power_lambertian_direct, data.valid),
               "three_bar_direct": _stats(bank_direct, data.valid),
               "active_delta": _stats(bank_direct - legacy_direct, data.valid), "preview_exposure": exposure,
               "montage_columns": ["legacy_point_spot", "fullpower_point_spot", "fullpower_point_lambertian", f"three_bar_{args.angular_model}"],
               "electrical_input_assumption_w": 12.0 if abs(args.relative_flux_per_bar - 12.0 / 6.9) < 1e-6 else None,
               "passive_model": {**passive_meta, "confidence": _stats(passive_confidence, data.valid)},
               "rgb_diffuse_shading": _stats(diffuse_shading, data.valid),
               "outputs": {
                   "nir_passive_material_aware": f"{args.frame}_nir_passive_material_aware.exr",
                   "rgb_diffuse_shading": f"{args.frame}_rgb_diffuse_shading.exr",
                   "rgb_diffuse_reconstruction": f"{args.frame}_rgb_diffuse_reconstruction.exr",
               },
               "three_bar": bank_meta}
    atomic_write_json(out / f"{args.frame}_nir_3bar_compare.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
