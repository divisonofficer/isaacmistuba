#!/usr/bin/env python3
"""Render a small diagnostic set for indoor wall grain/chromatic speckle.

The probe answers four questions on one saved OpticalNav RenderRequest:

* Is albedo already noisy?  -> texture/material issue.
* Is direct lighting clean while path is noisy? -> indirect Monte Carlo noise.
* Does 64/256/1024 spp improve roughly by sqrt? -> normal MC convergence.
* Is RGB cleaner than spectral/polarized? -> spectral reconstruction/channel noise.

It writes all outputs under out/diagnostics/indoor_noise_probe by default and
never edits the source scene. For softbox-only sanity checks it creates a temp
XML with non-softbox emitters removed; if the scene has no light_softbox_* shapes,
the check is skipped and the inventory says so.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
for _src in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from mitsuba_converter.multimodal import (  # noqa: E402
    _pbrdf_band_policy_inventory,
    RenderConfig,
    render_modalities,
)
from mitsuba_converter.observation_bridge import render_config_from_payload  # noqa: E402
from robomituba_bridge import render_request_from_payload, resolve_repo_path  # noqa: E402


DEFAULT_REQUEST = (
    REPO_ROOT
    / "out/bridge_jobs/opticalnav-indoor_seed2-template-vp_000251-h_150-rgb"
    / "requests/indoor_seed2_vp_000251_h_150.json"
)


def _parse_spp_csv(raw: str) -> list[int]:
    values = [int(part.strip()) for part in str(raw).split(",") if part.strip()]
    if not values:
        raise argparse.ArgumentTypeError("expected at least one spp value")
    return values


def _luminance(rgb: np.ndarray) -> np.ndarray:
    a = np.asarray(rgb, dtype=np.float32)
    if a.ndim == 2:
        return a
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def _box3_mean(a: np.ndarray) -> np.ndarray:
    acc = np.zeros_like(a, dtype=np.float32)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            acc += np.roll(np.roll(a, dy, axis=0), dx, axis=1)
    return acc / 9.0


def _array_metrics(arr: np.ndarray) -> dict[str, Any]:
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 2:
        rgb = np.repeat(a[:, :, None], 3, axis=2)
    elif a.ndim == 3 and a.shape[2] >= 3:
        rgb = a[:, :, :3]
    else:
        flat = a.reshape(-1)
        return {
            "shape": list(a.shape),
            "finite_ratio": float(np.mean(np.isfinite(flat))),
            "mean": float(np.nanmean(flat)),
            "std": float(np.nanstd(flat)),
        }

    finite = np.isfinite(rgb).all(axis=2)
    lum = _luminance(np.where(np.isfinite(rgb), rgb, 0.0))
    lum_valid = lum[finite]
    if lum_valid.size == 0:
        return {"shape": list(a.shape), "finite_ratio": 0.0}
    p = np.percentile(lum_valid, [1, 10, 50, 90, 99, 99.9])
    local = _box3_mean(lum)
    hf = lum - local
    mid = finite & (lum >= p[1]) & (lum <= p[4])
    if np.count_nonzero(mid) < 16:
        mid = finite
    rgb_safe = np.clip(rgb, 0.0, None)
    chroma = rgb_safe / np.maximum(lum[:, :, None], 1e-6)
    chroma_mid = chroma[mid]
    med = np.maximum(float(p[2]), 1e-6)
    return {
        "shape": list(a.shape),
        "finite_ratio": float(np.mean(finite)),
        "luminance": {
            "mean": float(np.mean(lum_valid)),
            "std": float(np.std(lum_valid)),
            "p01": float(p[0]),
            "p10": float(p[1]),
            "p50": float(p[2]),
            "p90": float(p[3]),
            "p99": float(p[4]),
            "p999": float(p[5]),
            "p999_over_p50": float(p[5] / med),
        },
        "hf_luminance_std": float(np.std(hf[mid])),
        "hf_luminance_std_over_mean": float(np.std(hf[mid]) / max(float(np.mean(lum[mid])), 1e-6)),
        "chroma_std_mid": [float(x) for x in np.std(chroma_mid, axis=0)],
        "chroma_std_mid_mean": float(np.mean(np.std(chroma_mid, axis=0))),
    }


def _scene_emitter_inventory(scene_path: Path) -> dict[str, Any]:
    root = ET.parse(scene_path).getroot()
    shapes = []
    top_emitters = 0
    for child in list(root):
        if child.tag == "emitter":
            top_emitters += 1
    for shape in root.findall("./shape"):
        emitter = shape.find("./emitter")
        if emitter is None:
            continue
        rad = emitter.find("./rgb[@name='radiance']")
        shapes.append({
            "id": shape.attrib.get("id"),
            "type": shape.attrib.get("type"),
            "emitter_type": emitter.attrib.get("type"),
            "radiance": rad.attrib.get("value") if rad is not None else None,
        })
    return {
        "top_level_emitters": top_emitters,
        "shape_emitters": len(shapes),
        "rectangle_emitters": sum(1 for s in shapes if s.get("type") == "rectangle"),
        "cube_emitters": sum(1 for s in shapes if s.get("type") == "cube"),
        "softbox_emitters": sum(1 for s in shapes if "light_softbox_" in str(s.get("id") or "")),
        "emitters": shapes,
    }


def _write_softbox_only_scene(scene_path: Path, out_path: Path, *, keep_environment: bool) -> dict[str, Any]:
    tree = ET.parse(scene_path)
    root = tree.getroot()
    removed_shape_emitters = 0
    kept_shape_emitters = 0
    removed_top_emitters = 0
    if not keep_environment:
        for child in list(root):
            if child.tag == "emitter":
                root.remove(child)
                removed_top_emitters += 1
    for shape in root.findall("./shape"):
        emitter = shape.find("./emitter")
        if emitter is None:
            continue
        sid = str(shape.attrib.get("id") or "")
        if "light_softbox_" in sid:
            kept_shape_emitters += 1
            continue
        shape.remove(emitter)
        removed_shape_emitters += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return {
        "softbox_only_scene": str(out_path),
        "kept_shape_emitters": kept_shape_emitters,
        "removed_shape_emitters": removed_shape_emitters,
        "removed_top_emitters": removed_top_emitters,
    }


def _write_analytic_measured_scene(scene_path: Path, out_path: Path) -> dict[str, Any]:
    """Replace measured BSDFs in a temp XML so wall/noise probes avoid channel-split OOM."""
    tree = ET.parse(scene_path)
    root = tree.getroot()
    replaced = 0
    for bsdf in root.findall(".//bsdf"):
        if bsdf.attrib.get("type") not in {"measured", "measured_polarized", "measured_polarized_rgb"}:
            continue
        bsdf.attrib["type"] = "roughconductor"
        for child in list(bsdf):
            bsdf.remove(child)
        ET.SubElement(bsdf, "string", attrib={"name": "material", "value": "Al"})
        ET.SubElement(bsdf, "string", attrib={"name": "distribution", "value": "ggx"})
        ET.SubElement(bsdf, "float", attrib={"name": "alpha", "value": "0.20"})
        replaced += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return {"analytic_scene": str(out_path), "measured_bsdfs_replaced": replaced}


def _make_config(
    base: RenderConfig,
    *,
    spp: int,
    width: int | None,
    height: int | None,
    denoise: bool,
    pbrdf_band_mode: str,
) -> RenderConfig:
    kwargs = {
        "path_spp": int(spp),
        "aov_spp": min(max(8, int(spp)), max(8, base.aov_spp)),
        "use_firefly_clamp": False,
        "use_optix_denoiser": bool(denoise),
        "write_raw_npz": False,
        "pbrdf_band_mode": str(pbrdf_band_mode),
    }
    if width and height:
        kwargs["width"] = int(width)
        kwargs["height"] = int(height)
    return replace(base, **kwargs)


def _run_case(
    *,
    name: str,
    scene_path: Path,
    camera_to_world: np.ndarray,
    fov_deg: float,
    modalities: list[str],
    config: RenderConfig,
    variant: str,
    out_root: Path,
) -> dict[str, Any]:
    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    try:
        result = render_modalities(
            scene_path,
            camera_to_world,
            fov_deg,
            modalities,
            out_dir=out_dir,
            config=config,
            variant=variant,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics should continue
        return {
            "name": name,
            "status": "error",
            "variant": variant,
            "scene": str(scene_path),
            "modalities": modalities,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_s": time.perf_counter() - start,
        }
    records = {}
    for modality, item in result.results.items():
        records[modality] = {
            "artifacts": item.artifacts,
            "timing": item.timing,
            "metrics": _array_metrics(item.array),
            "metadata": item.metadata,
        }
    return {
        "name": name,
        "status": "ok",
        "variant": variant,
        "scene": str(scene_path),
        "modalities": modalities,
        "elapsed_s": time.perf_counter() - start,
        "results": records,
        "pass_records": result.pass_records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "out/diagnostics/indoor_noise_probe")
    ap.add_argument("--spp", type=_parse_spp_csv, default=_parse_spp_csv("64,256,1024"))
    ap.add_argument("--compare-spp", type=int, default=256)
    ap.add_argument("--variant", default="cuda_rgb", help="Variant for albedo/direct/path ladder.")
    ap.add_argument("--rgb-variant", default="cuda_rgb")
    ap.add_argument("--spectral-variant", default="cuda_ad_spectral")
    ap.add_argument("--pbrdf-band-mode", choices=["single", "hybrid", "rgb"], default="single")
    ap.add_argument("--scene-mode", choices=["original", "analytic-measured"], default="original")
    ap.add_argument("--skip-albedo-direct", action="store_true")
    ap.add_argument("--skip-ladder", action="store_true")
    ap.add_argument("--skip-variant-compare", action="store_true")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--denoise", action="store_true", help="Enable OptiX denoise for filtered preview outputs.")
    ap.add_argument("--inspect-only", action="store_true")
    ap.add_argument("--softbox-only", action="store_true", help="Also render softbox-only direct/path cases if softboxes exist.")
    ap.add_argument("--keep-environment-in-softbox-only", action="store_true")
    ap.add_argument("--clear-staged-cache", action="store_true")
    args = ap.parse_args()

    payload = json.loads(args.request.read_text(encoding="utf-8"))
    request = render_request_from_payload(payload)
    if not request.camera_specs:
        raise SystemExit("request has no camera_specs")
    camera = request.camera_specs[0]
    source_scene_path = resolve_repo_path(REPO_ROOT, request.scene_state.mitsuba_scene_ref)
    scene_path = source_scene_path
    scene_dir = source_scene_path.parent
    if args.clear_staged_cache:
        shutil.rmtree(scene_dir / ".staged_mitsuba", ignore_errors=True)
    base_config = render_config_from_payload(request.render_settings)
    if camera.resolution and not (args.width and args.height):
        base_config = replace(base_config, width=int(camera.resolution[0]), height=int(camera.resolution[1]))
    camera_to_world = np.asarray(camera.camera_to_world, dtype=np.float32).reshape(4, 4)

    run_tag = f"{request.scene_state.scene_id}_{request.frame_id}_{int(time.time())}"
    out_root = args.out.resolve() / run_tag
    out_root.mkdir(parents=True, exist_ok=True)

    scene_transform: dict[str, Any] | None = None
    if args.scene_mode == "analytic-measured":
        scene_path = out_root / "scenes/analytic_measured.xml"
        scene_transform = _write_analytic_measured_scene(source_scene_path, scene_path)

    inventory = _scene_emitter_inventory(scene_path)
    band_policy_counts = _pbrdf_band_policy_inventory(scene_path)
    summary: dict[str, Any] = {
        "request": str(args.request),
        "source_scene": str(source_scene_path),
        "scene": str(scene_path),
        "scene_mode": args.scene_mode,
        "scene_transform": scene_transform,
        "scene_id": request.scene_state.scene_id,
        "frame_id": request.frame_id,
        "camera_id": camera.camera_id,
        "resolution": [args.width or base_config.width, args.height or base_config.height],
        "pbrdf_band_mode": args.pbrdf_band_mode,
        "rgb_render_mode": "one_pass_single" if args.pbrdf_band_mode == "single" else "rgb_plugin_or_channel_split",
        "band_policy_counts": band_policy_counts,
        "wall_material_policy": {
            "wall_plaster_ceiling_floor": "expected_analytic_or_single_band_albedo_scale",
            "normal_map": "not_inspected",
            "bump_map": "not_inspected",
        },
        "emitter_inventory": inventory,
        "cases": [],
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.inspect_only:
        print(json.dumps(summary, indent=2))
        return 0

    def add(case: dict[str, Any]) -> None:
        summary["cases"].append(case)
        (out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"[probe] {case['name']}: {case['status']} ({case.get('elapsed_s', 0.0):.1f}s)", flush=True)

    probe_spp = max(16, min(args.spp))
    if not args.skip_albedo_direct:
        cfg_probe = _make_config(
            base_config,
            spp=probe_spp,
            width=args.width,
            height=args.height,
            denoise=args.denoise,
            pbrdf_band_mode=args.pbrdf_band_mode,
        )
        add(_run_case(
            name=f"t1_albedo_t2_direct_{probe_spp}spp",
            scene_path=scene_path,
            camera_to_world=camera_to_world,
            fov_deg=float(camera.fov_deg),
            modalities=["albedo", "direct_light_map"],
            config=cfg_probe,
            variant=args.variant,
            out_root=out_root,
        ))

    if not args.skip_ladder:
        for spp in args.spp:
            cfg = _make_config(
                base_config,
                spp=spp,
                width=args.width,
                height=args.height,
                denoise=args.denoise,
                pbrdf_band_mode=args.pbrdf_band_mode,
            )
            add(_run_case(
                name=f"t3_path_{spp}spp",
                scene_path=scene_path,
                camera_to_world=camera_to_world,
                fov_deg=float(camera.fov_deg),
                modalities=["rgb"],
                config=cfg,
                variant=args.variant,
                out_root=out_root,
            ))

    if not args.skip_variant_compare:
        cfg_cmp = _make_config(
            base_config,
            spp=args.compare_spp,
            width=args.width,
            height=args.height,
            denoise=args.denoise,
            pbrdf_band_mode=args.pbrdf_band_mode,
        )
        for label, variant in (("rgb_variant", args.rgb_variant), ("spectral_variant", args.spectral_variant)):
            add(_run_case(
                name=f"t4_{label}_{args.compare_spp}spp",
                scene_path=scene_path,
                camera_to_world=camera_to_world,
                fov_deg=float(camera.fov_deg),
                modalities=["rgb"],
                config=cfg_cmp,
                variant=variant,
                out_root=out_root,
            ))

    if args.softbox_only:
        if inventory.get("softbox_emitters", 0) <= 0:
            summary["softbox_only"] = {"status": "skipped", "reason": "no light_softbox_* emitters in compiled scene"}
            (out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print("[probe] softbox-only skipped: no light_softbox_* emitters in compiled scene", flush=True)
        else:
            soft_scene = out_root / "scenes/softbox_only.xml"
            summary["softbox_only"] = _write_softbox_only_scene(
                scene_path,
                soft_scene,
                keep_environment=args.keep_environment_in_softbox_only,
            )
            cfg_soft = _make_config(
                base_config,
                spp=probe_spp,
                width=args.width,
                height=args.height,
                denoise=args.denoise,
                pbrdf_band_mode=args.pbrdf_band_mode,
            )
            add(_run_case(
                name=f"softbox_only_direct_{probe_spp}spp",
                scene_path=soft_scene,
                camera_to_world=camera_to_world,
                fov_deg=float(camera.fov_deg),
                modalities=["direct_light_map"],
                config=cfg_soft,
                variant=args.variant,
                out_root=out_root,
            ))

    print(f"[probe] wrote {out_root / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
