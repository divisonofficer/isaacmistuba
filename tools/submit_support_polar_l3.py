#!/usr/bin/env python3
"""Submit the complete L3 native-polar coverage for one V4 support scene.

The support plans are intentionally submitted as two immutable contracts:
L0 action-required observations followed by L3's *additional* native headings.
For every contract the queue receives the three scene variants in strict
base -> perturbed -> perturbed-active-polar order.  The daemon owns each
predecessor barrier, so this command may exit once the six batch ids are
durably registered.

The command is dry-run by default.  ``--apply`` is the only mode that writes a
queue submission.  Passive base/perturbed observations use K=4. Camera-aligned
active observations deliberately remain K=1: spatial K>1 failed a certified
K=1 parity check because each camera owns a local polarized emitter.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "opticalnav-v0.2"
SCENE_ID = "infinigen_apartment_20260811"
POLAR_MODALITIES = [
    "polar_rgb_preview", "s1_over_s0", "s2_over_s0", "dop", "aolp", "s1", "s2",
]
SCENE_VARIANTS = ("base", "perturbed", "perturbed_active_polar")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _scene_dir(project_id: str, scene_id: str) -> Path:
    return REPO_ROOT / "out" / "opticalnav" / project_id / "scenes" / scene_id


def _polar_camera_spec() -> dict[str, Any]:
    """Return the canonical 512² polar camera payload used by the WebUI."""
    rig = _read_json(REPO_ROOT / "out" / "control_plane_cache" / "camera_rigs" / "ranger_mini_default.json")
    sensor = next(
        (item for item in rig.get("sensors", []) if isinstance(item, Mapping) and item.get("sensor_id") == "polar_cam"),
        None,
    )
    if not isinstance(sensor, Mapping):
        raise ValueError("ranger_mini_default.json does not define polar_cam")
    intrinsics = sensor.get("intrinsics") if isinstance(sensor.get("intrinsics"), Mapping) else {}
    mount = sensor.get("mount") if isinstance(sensor.get("mount"), Mapping) else {}
    source_xyz = list(mount.get("xyz_m") or [0.0, 0.1, 1.5])
    if len(source_xyz) != 3:
        raise ValueError("polar_cam mount must be a three-vector")
    # camera_rig_v1 mount is x/forward/up; the sweep convention is x/up/forward.
    robot_mount = {
        "parent_frame": str(mount.get("parent_frame") or "base_link"),
        "xyz_m": [float(source_xyz[0]), float(source_xyz[2]), float(source_xyz[1])],
        "rpy_deg": [float(value) for value in list(mount.get("rpy_deg") or [0.0, 0.0, 0.0])],
        "source_schema": "camera_rig_v1",
    }
    resolution = list(intrinsics.get("resolution") or [512, 512])
    if resolution != [512, 512]:
        raise ValueError(f"expected polar_cam 512x512, got {resolution}")
    return {
        "camera_id": "polar_cam",
        "name": str(sensor.get("label") or "polar_cam"),
        # The graph-sweep builder composes this placeholder with robot_mount.
        "camera_to_world": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, robot_mount["xyz_m"][1], 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "fov_deg": float(intrinsics.get("fov_h_deg") or 75.0),
        "resolution": resolution,
        "sensor_modality": "polarization",
        "sensor_sync_group": "camera_rig",
        "calibration_ref": None,
        "extras": {
            "robot_mount": robot_mount,
            "camera_rig_id": str(rig.get("rig_id") or "ranger_mini_default"),
            "base_frame": robot_mount["parent_frame"],
            "source_sensor_modality": "polarization",
            "render_modality": "polar_rgb_preview",
            "camera_rig_source": "global_json_preset",
            "canonical_sensor_type": "polar_camera",
            "canonical_modalities": list(POLAR_MODALITIES),
            "render_modalities": list(POLAR_MODALITIES),
            "polarization": dict(sensor.get("polarization") or {}),
            "render": {
                "path_spp": 4096,
                "aov_spp": 16,
                "polar_spp": 1024,
                "polar_transport": "physical",
                "polar_visualization_policy": "raw_stokes_aolp_v1",
            },
        },
    }


def _render_settings(*, active_batch_policy: str | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "path_spp": 4096,
        "aov_spp": 16,
        "polar_spp": 1024,
        # K strips must use a fixed sample count to keep child comparisons fair.
        "polar_adaptive_spp_min": None,
        "polar_adaptive_spp_max": None,
        "polar_adaptive_noise_threshold": None,
        "samples_per_pass": None,
        "polar_color_mode": "rgb_stokes_12",
        "polar_transport": "physical",
        "polar_visualization_policy": "raw_stokes_aolp_v1",
    }
    if active_batch_policy is not None:
        settings["active_polar_batch_policy"] = active_batch_policy
        settings["active_polar_batch_min_separation_m"] = 6.0
    return settings


def _check_plan(plan: Mapping[str, Any], *, expected_count: int, scene_id: str, digest: str) -> None:
    if str(plan.get("profile_id") or "") != "adaptive_navigation_support_v4":
        raise ValueError("plan is not an adaptive_navigation_support_v4 observation plan")
    if str(plan.get("scene_id") or "") != scene_id:
        raise ValueError("observation plan scene_id mismatch")
    if str(plan.get("profile_digest") or "") != digest or str(plan.get("validation_digest") or "") != digest:
        raise ValueError("observation plan validation digest mismatch")
    entries = plan.get("render_entries")
    if not isinstance(entries, list) or len(entries) != expected_count:
        raise ValueError(f"expected {expected_count} render entries, got {len(entries) if isinstance(entries, list) else 'non-list'}")
    missing = [entry for entry in entries if not isinstance(entry, Mapping) or not entry.get("motion_node_id") or not entry.get("heading_id")]
    if missing:
        raise ValueError(f"observation plan has {len(missing)} malformed render entries")


def _post_json(url: str, body: Mapping[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"POST {url} failed: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("batch_id"):
        raise RuntimeError(f"queue did not return a batch id: {payload}")
    return payload


def _parse_variants(value: str) -> tuple[str, ...]:
    variants = tuple(item.strip() for item in str(value).split(",") if item.strip())
    if not variants:
        raise ValueError("at least one scene variant is required")
    invalid = [item for item in variants if item not in SCENE_VARIANTS]
    if invalid:
        raise ValueError(f"unknown scene variant(s): {', '.join(invalid)}")
    if len(set(variants)) != len(variants):
        raise ValueError("scene variants must not be repeated")
    order = {name: index for index, name in enumerate(SCENE_VARIANTS)}
    if list(variants) != sorted(variants, key=order.__getitem__):
        raise ValueError("scene variants must keep base → perturbed → perturbed_active_polar order")
    return variants


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--scene", default=SCENE_ID)
    parser.add_argument(
        "--texture-profile-override", type=int, default=512,
        help="per-worker max texture resolution; max512 is the memory-safe K=4 profile for this scene",
    )
    parser.add_argument(
        "--levels", choices=("all", "l0", "l3"), default="all",
        help="submit the complete contract, or only L0 / L3 additional coverage",
    )
    parser.add_argument(
        "--rerender-all", action="store_true",
        help=(
            "do not inherit completed observations from an earlier render version; "
            "use after a renderer or Stokes-basis change"
        ),
    )
    parser.add_argument(
        "--variants", default=",".join(SCENE_VARIANTS),
        help=(
            "comma-separated ordered subset of base,perturbed,perturbed_active_polar; "
            "use a non-base subset to continue a completed base without submitting it again"
        ),
    )
    parser.add_argument(
        "--previous-batch-id", default=None,
        help="optional completed predecessor batch id for the first selected variant",
    )
    parser.add_argument(
        "--plan-dir", default=".",
        help=(
            "scene-relative directory containing support_observation_plan.json and the L3 context; "
            "use navigation_support_archives/<digest> only to finish an already validated archived contract"
        ),
    )
    parser.add_argument("--apply", action="store_true", help="actually submit the selected durable render batches")
    args = parser.parse_args()
    if not 64 <= args.texture_profile_override <= 4096:
        parser.error("--texture-profile-override must be in [64, 4096]")

    scene_dir = _scene_dir(args.project, args.scene).resolve()
    try:
        plan_dir = (scene_dir / args.plan_dir).resolve()
        plan_dir.relative_to(scene_dir)
    except (OSError, ValueError) as exc:
        parser.error(f"--plan-dir must stay inside the scene directory: {exc}")
    l0_path = plan_dir / "support_observation_plan.json"
    l3_path = plan_dir / "support_observation_expansion_l3_context_45.json"
    l0, l3 = _read_json(l0_path), _read_json(l3_path)
    support_ref = str(l0.get("support_graph_ref") or "navigation_support_graph.json")
    try:
        support_path = (scene_dir / support_ref).resolve()
        support_path.relative_to(scene_dir)
    except (OSError, ValueError) as exc:
        parser.error(f"support_graph_ref must stay inside the scene directory: {exc}")
    support = _read_json(support_path)
    digest = str((support.get("validation") or {}).get("digest") or "")
    if not digest:
        raise SystemExit("navigation support validation digest is missing")
    l0_ref = l0_path.relative_to(scene_dir).as_posix()
    l3_ref = l3_path.relative_to(scene_dir).as_posix()
    _check_plan(l0, expected_count=2454, scene_id=args.scene, digest=digest)
    _check_plan(l3, expected_count=1250, scene_id=args.scene, digest=digest)
    camera = _polar_camera_spec()
    root = args.url.rstrip("/")
    endpoint = f"{root}/api/opticalnav/projects/{args.project}/scenes/{args.scene}/render-plan/submit"
    selected_stages = [("l0", l0_ref, 2454), ("l3", l3_ref, 1250)]
    if args.levels != "all":
        selected_stages = [item for item in selected_stages if item[0] == args.levels]
    selected_views_per_variant = sum(count for _level, _ref, count in selected_stages)
    submission_group = (
        f"support-l3-{args.scene}-{args.levels}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    )
    try:
        variants = _parse_variants(args.variants)
    except ValueError as exc:
        parser.error(str(exc))
    summary = {
        "project": args.project,
        "scene": args.scene,
        "profile_digest": digest,
        "plan_dir": plan_dir.relative_to(scene_dir).as_posix(),
        "coverage": {
            "selected_levels": [level for level, _ref, _count in selected_stages],
            "selected_views_per_variant": selected_views_per_variant,
            "l0": 2454,
            "l3_additional": 1250,
            "l3_total_per_variant": 3704,
        },
        "variants": list(variants),
        "total_views": selected_views_per_variant * len(variants),
        "polar_camera": {"id": camera["camera_id"], "resolution": camera["resolution"], "fov_deg": camera["fov_deg"]},
        "texture_profile_override": args.texture_profile_override,
        "active_batch_policy": "k1",
        "previous_batch_id": args.previous_batch_id,
        "reuse_existing_observations": not bool(args.rerender_all),
        "apply": bool(args.apply),
        "batches": [],
    }
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    previous_batch_id = str(args.previous_batch_id or "").strip() or None
    ordered = [(level, ref, count, variant) for level, ref, count in selected_stages for variant in variants]
    for sequence, (level, plan_ref, count, variant) in enumerate(ordered):
        active_policy = "k1" if variant == "perturbed_active_polar" else None
        body = {
            "observation_plan_ref": plan_ref,
            "profile_digest": digest,
            "backend": "daemon",
            "camera_height_m": 1.5,
            "sensor_scope": "selected",
            "sensor_ids": ["polar_cam"],
            "camera_specs": [camera],
            "modalities": list(POLAR_MODALITIES),
            "render_settings": _render_settings(active_batch_policy=active_policy),
            "texture_profile_override": args.texture_profile_override,
            "only_missing": not args.rerender_all,
            "skip_existing_observations": not args.rerender_all,
            "reuse_existing_observations": not args.rerender_all,
            "scene_variant_key": variant,
            "submission_group_id": submission_group,
            "variant_sequence_index": sequence,
            "variant_sequence_total": len(ordered),
            **({"previous_variant_batch_id": previous_batch_id} if previous_batch_id else {}),
        }
        response = _post_json(endpoint, body)
        batch_id = str(response["batch_id"])
        summary["batches"].append({
            "level": level,
            "plan_ref": plan_ref,
            "view_count": count,
            "variant": variant,
            "batch_id": batch_id,
            "previous_variant_batch_id": previous_batch_id,
        })
        previous_batch_id = batch_id
    report = scene_dir / f"support_l3_submission_{submission_group}.json"
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary, "report": str(report)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
