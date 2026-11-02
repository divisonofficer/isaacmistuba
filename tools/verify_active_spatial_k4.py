#!/usr/bin/env python3
"""Certify a K=4 native-polar batch against equivalent K=1 renders.

The passive batch sensor is exact because all child cameras share the same
illumination.  A camera-aligned active light is different: a spatial batch
contains one emitter/polarizer for every child camera.  This utility renders
the four selected views once with exactly one local emitter (K=1 reference)
and once through the K=4 strip, compares RGB/S0/S1/S2/S3 arrays, and records
an immutable ``passed`` certificate.  The L3 submitter accepts
``--active-parity-certificate`` only when that certificate passed.

``--mode passive_heading`` instead chooses four planned headings of one pose;
that is the exact K=4 fast path used for base and perturbed renders.  It never
writes an OpticalNav observation or a render-ledger task.  Its output is
retained below the scene's ``validation/`` directory as audit evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from robomituba_bridge import AssistLightSpec, resolve_repo_path
from mitsuba_converter.multimodal import RenderConfig, render_ambient_stokes_heading_batch, render_modalities
from navigation_dataset.navigation_support import support_render_graph
from navigation_dataset.sensor_sweep import build_sweep_render_requests

from submit_support_polar_l3 import (
    POLAR_MODALITIES,
    PROJECT_ID,
    REPO_ROOT,
    SCENE_ID,
    _polar_camera_spec,
    _read_json,
    _render_settings,
    _scene_dir,
)


def _far_spatial_entries(plan: Mapping[str, Any], *, minimum_separation_m: float) -> list[dict[str, Any]]:
    poses = {
        str(item.get("motion_node_id")): tuple(float(value) for value in (item.get("position") or [])[:2])
        for item in plan.get("poses") or []
        if isinstance(item, Mapping) and len(item.get("position") or []) >= 2
    }
    # One representative plan entry per pose is enough for a spatial lighting
    # test.  Reusing several headings at a pose would put their local lights in
    # exactly the same world location and defeat the premise of this pilot.
    by_pose: dict[str, dict[str, Any]] = {}
    for raw in plan.get("render_entries") or []:
        if not isinstance(raw, Mapping):
            continue
        pose_id = str(raw.get("motion_node_id") or "")
        if pose_id in poses and pose_id not in by_pose and raw.get("heading_id"):
            by_pose[pose_id] = dict(raw)
    candidates = sorted(by_pose.values(), key=lambda item: (str(item["motion_node_id"]), str(item["heading_id"])))
    if len(candidates) < 4:
        raise ValueError("observation plan does not have four distinct poses")

    def point(entry: Mapping[str, Any]) -> tuple[float, float]:
        return poses[str(entry["motion_node_id"])]

    # Try every seed.  The graph has only O(10^2) support poses, so this is
    # deterministic and avoids an arbitrary hard-coded apartment coordinate.
    for seed_index, seed in enumerate(candidates):
        selected = [seed]
        remaining = candidates[:seed_index] + candidates[seed_index + 1:]
        while remaining and len(selected) < 4:
            compatible: list[tuple[float, int]] = []
            for index, candidate in enumerate(remaining):
                nearest = min(math.dist(point(candidate), point(member)) for member in selected)
                if nearest >= minimum_separation_m:
                    compatible.append((nearest, index))
            if not compatible:
                break
            _, selected_index = max(compatible, key=lambda item: (item[0], -item[1]))
            selected.append(remaining.pop(selected_index))
        if len(selected) == 4:
            return selected
    raise ValueError(f"no four-pose group satisfies {minimum_separation_m:.3f} m pairwise separation")


def _same_pose_heading_entries(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pick one planned K=4 heading cohort from a shared passive pose."""
    by_pose: dict[str, list[dict[str, Any]]] = {}
    for raw in plan.get("render_entries") or []:
        if not isinstance(raw, Mapping):
            continue
        pose_id, heading_id = str(raw.get("motion_node_id") or ""), str(raw.get("heading_id") or "")
        if pose_id and heading_id:
            by_pose.setdefault(pose_id, []).append(dict(raw))
    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for pose_id, entries in by_pose.items():
        entries.sort(key=lambda item: str(item["heading_id"]))
        if len(entries) >= 4:
            candidates.append((pose_id, entries[:4]))
    if not candidates:
        raise ValueError("observation plan has no pose with four native headings")
    return min(candidates, key=lambda item: item[0])[1]


def _active_assist_light() -> AssistLightSpec:
    return AssistLightSpec(
        mode="camera_aligned_rect",
        distance_m=0.12,
        size_world=[2.2, 1.6],
        spectrum_mode="rgb_white",
        polarized=True,
        polarizer_angle_deg=0.0,
        extras={"radiance": 18.0, "protocol": "rgb_stokes_12_active_polar_v1"},
    )


def _select_requests(
    *,
    plan: Mapping[str, Any],
    scene_ref: str,
    camera: Mapping[str, Any],
    render_settings: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    active: bool,
) -> list[Any]:
    graph = support_render_graph(plan)
    allowed: dict[str, list[str]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for entry in entries:
        pose_id, heading_id = str(entry["motion_node_id"]), str(entry["heading_id"])
        allowed.setdefault(pose_id, []).append(heading_id)
        metadata[f"{pose_id}/{heading_id}"] = {
            key: entry[key]
            for key in ("tier", "available_heading_ids", "polar_batch_key", "polar_batch_size", "projection", "canonical")
            if key in entry
        }
    state = {
        "job_id": "active-spatial-k4-parity",
        "scene_id": str(plan["scene_id"]),
        "frame_id": "active_spatial_k4_parity",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scene_snapshot_ref": scene_ref,
        "mitsuba_scene_ref": scene_ref,
        "scene_version": "active_spatial_k4_parity",
    }
    sweep = build_sweep_render_requests(
        graph,
        scene_state_payload=state,
        camera_spec_payload=None,
        camera_specs_payload=[dict(camera)],
        sensor_scope="selected",
        sensor_ids=["polar_cam"],
        modalities=list(POLAR_MODALITIES),
        job_id_mode="per_heading",
        node_ids=sorted(allowed),
        heading_ids_by_node=allowed,
        view_metadata_by_key=metadata,
        camera_height_m=1.5,
        render_settings=dict(render_settings),
    )
    by_key = {(str(item.node_id), str(item.heading_id)): item for item in sweep}
    ordered = []
    for entry in entries:
        key = (str(entry["motion_node_id"]), str(entry["heading_id"]))
        item = by_key.get(key)
        if item is None:
            raise ValueError(f"failed to build pilot request for {key[0]}/{key[1]}")
        if active:
            item.request.assist_light = _active_assist_light()
        item.request.extras.update({"polar_active": active, "polar_pilot": True, "polar_color_mode": "rgb_stokes_12"})
        ordered.append(item)
    if len(ordered) != 4:
        raise ValueError("active spatial pilot must have exactly four requests")
    return ordered


def _metrics(reference: np.ndarray, candidate: np.ndarray, *, s0_p99_scale: float) -> dict[str, float]:
    finite = np.isfinite(reference) & np.isfinite(candidate)
    if not np.any(finite):
        return {"finite_ratio": 0.0, "nrmse_s0_p99": math.inf, "mean_abs_relative": math.inf}
    ref, candidate = reference[finite].astype(np.float64), candidate[finite].astype(np.float64)
    difference = candidate - ref
    # S1/S2/S3 can be physically close to zero.  Normalizing their difference
    # by their own p99 turns harmless Monte-Carlo noise into an arbitrarily
    # large number.  S0 is the actual radiometric scale of the same frame and
    # gives one stable, comparable error unit for all canonical components.
    scale = max(float(s0_p99_scale), 1e-7)
    mean_scale = max(float(np.mean(np.abs(ref))), scale * 1e-3, 1e-7)
    return {
        "finite_ratio": float(np.mean(finite)),
        "nrmse_s0_p99": float(np.sqrt(np.mean(difference * difference)) / scale),
        "mean_abs_relative": float(np.mean(np.abs(difference)) / mean_scale),
    }


def _certificate(
    *,
    output_root: Path,
    plan: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    minimum_separation_m: float,
    texture_profile_override: int,
    mode: str,
) -> dict[str, Any]:
    component_limits = {"rgb": 0.035, "s0": 0.035, "s1": 0.02, "s2": 0.02, "s3": 0.01}
    rows: list[dict[str, Any]] = []
    passed = True
    for index, entry in enumerate(entries):
        reference_path = output_root / "k1" / f"view_{index:02d}" / "stokes_data.npz"
        batch_path = output_root / "k4" / f"view_{index:02d}" / "stokes_data.npz"
        with np.load(reference_path) as reference, np.load(batch_path) as candidate:
            s0_p99_scale = max(float(np.quantile(np.abs(np.asarray(reference["s0"])), 0.99)), 1e-7)
            components = {
                key: _metrics(np.asarray(reference[key]), np.asarray(candidate[key]), s0_p99_scale=s0_p99_scale)
                for key in component_limits
            }
        component_passed = all(
            values["finite_ratio"] >= 0.999
            and values["nrmse_s0_p99"] <= component_limits[name]
            for name, values in components.items()
        )
        passed = passed and component_passed
        rows.append({
            "motion_node_id": str(entry["motion_node_id"]),
            "heading_id": str(entry["heading_id"]),
            "reference_npz": str(reference_path),
            "spatial_batch_npz": str(batch_path),
            "passed": component_passed,
            "reference_s0_p99": s0_p99_scale,
            "components": components,
        })
    return {
        "schema_version": "opticalnav.stokes_heading_k4_parity.v1",
        "passed": passed,
        "policy": "active_spatial_separation_candidate_v1" if mode == "active_spatial" else "passive_heading_batch_v1",
        "mode": mode,
        "scene_id": str(plan["scene_id"]),
        "profile_digest": str(plan.get("profile_digest") or ""),
        "coverage_digest": str(plan.get("coverage_digest") or ""),
        "minimum_separation_m": minimum_separation_m,
        "batch_size": 4,
        "variant": "cuda_ad_rgb_polarized",
        "polar_spp": 1024,
        "texture_profile_override": texture_profile_override,
        "tolerances_nrmse_s0_p99": component_limits,
        "views": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--scene", default=SCENE_ID)
    parser.add_argument("--minimum-separation-m", type=float, default=6.0)
    parser.add_argument(
        "--mode", choices=("active_spatial", "passive_heading"), default="active_spatial",
        help="active needs spatial separation; passive verifies the same-pose heading strip used in production",
    )
    parser.add_argument("--apply", action="store_true", help="run the K=1 and K=4 renders; default only selects views")
    args = parser.parse_args()
    if args.minimum_separation_m <= 0.0:
        parser.error("--minimum-separation-m must be positive")
    try:
        texture_profile_override = int(os.environ.get("ROBOMITUBA_TEXTURE_MAX_RESOLUTION", "1024"))
    except ValueError as exc:
        parser.error(f"ROBOMITUBA_TEXTURE_MAX_RESOLUTION must be an integer: {exc}")
    if not 64 <= texture_profile_override <= 4096:
        parser.error("ROBOMITUBA_TEXTURE_MAX_RESOLUTION must be in [64, 4096]")

    scene_dir = _scene_dir(args.project, args.scene)
    plan = _read_json(scene_dir / "support_observation_plan.json")
    active = args.mode == "active_spatial"
    entries = (
        _far_spatial_entries(plan, minimum_separation_m=float(args.minimum_separation_m))
        if active else _same_pose_heading_entries(plan)
    )
    output_root = scene_dir / "validation" / (
        f"{args.mode}_k4_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    summary = {
        "scene_id": args.scene,
        "profile_digest": plan.get("profile_digest"),
        "minimum_separation_m": args.minimum_separation_m,
        "mode": args.mode,
        "texture_profile_override": texture_profile_override,
        "views": [{"motion_node_id": item["motion_node_id"], "heading_id": item["heading_id"]} for item in entries],
        "output_root": str(output_root),
        "apply": bool(args.apply),
    }
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    variants = _read_json(scene_dir / "scene_variant.json")
    scene_ref = str(variants.get("perturbed_scene_xml_ref") or "")
    source_scene = resolve_repo_path(REPO_ROOT, scene_ref)
    if not scene_ref or not source_scene.is_file():
        raise SystemExit("perturbed scene XML is missing; Sync Render Scene before the active parity pilot")
    output_root.mkdir(parents=True, exist_ok=False)
    settings = _render_settings()
    camera = _polar_camera_spec()
    requests = _select_requests(
        plan=plan,
        scene_ref=scene_ref,
        camera=camera,
        render_settings=settings,
        entries=entries,
        active=active,
    )
    config = RenderConfig(
        width=512, height=512, path_spp=4096, aov_spp=16, polar_spp=1024,
        polar_adaptive_spp_min=None, polar_adaptive_spp_max=None,
        samples_per_pass=None, polar_color_mode="rgb_stokes_12",
        polar_transport="physical", polar_visualization_policy="raw_stokes_aolp_v1",
    )
    for index, item in enumerate(requests):
        camera_spec = item.request.camera_specs[0]
        render_modalities(
            source_scene,
            np.asarray(camera_spec.camera_to_world, dtype=np.float32).reshape(4, 4),
            camera_spec.fov_deg,
            list(POLAR_MODALITIES),
            out_dir=output_root / "k1" / f"view_{index:02d}",
            config=config,
            assist_light=item.request.assist_light,
            variant="cuda_ad_rgb_polarized",
        )
    render_ambient_stokes_heading_batch(
        source_scene,
        [np.asarray(item.request.camera_specs[0].camera_to_world, dtype=np.float32).reshape(4, 4) for item in requests],
        float(requests[0].request.camera_specs[0].fov_deg),
        list(POLAR_MODALITIES),
        out_dirs=[output_root / "k4" / f"view_{index:02d}" for index in range(4)],
        config=config,
        assist_lights=[item.request.assist_light for item in requests] if active else None,
        batch_mode="active_stokes_heading_spatial_batch_v1" if active else "ambient_stokes_heading_batch_v1",
        variant="cuda_ad_rgb_polarized",
    )
    certificate = _certificate(
        output_root=output_root, plan=plan, entries=entries,
        minimum_separation_m=float(args.minimum_separation_m),
        texture_profile_override=texture_profile_override,
        mode=args.mode,
    )
    certificate_path = output_root / "certificate.json"
    certificate_path.write_text(json.dumps(certificate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary, "certificate": str(certificate_path), "passed": certificate["passed"]}, ensure_ascii=False, indent=2))
    if not certificate["passed"]:
        raise SystemExit(f"{args.mode} K=4 parity failed; do not use this batch policy for the L3 submission")


if __name__ == "__main__":
    main()
