#!/usr/bin/env python3
"""One-argument launcher for the resumable Infinigen structural-specular IR dataset.

Typical use::

    python3 apps/run_infinigen_ir_quickstart.py \
      data/infinigen_generated/outputs/kr_20260730_single_room_kitchen/full/scene.blend

The launcher intentionally owns the operational defaults for the Ubuntu
OptiX-7 ×8-GPU host.  It discovers the already-imported OpticalNav scene,
reuses a matching IR output root when one exists, then advances only the
incomplete portion of the pipeline:

* no Stage-1 artifacts → strict GLB/PBR + semantic LOD (Stages 1 and 2);
* published Stage-1 manifest + derived blend but no profile → Stage-2/profile
  finalization only;
* published profile → GPU observations (Stage 3), Mitsuba primary-hit/property
  GT (Stage 4), Blender ARMN GT (Stage 5), and final assembly (Stage 6).

The original ``.blend`` remains read-only.  A source OpticalNav scene must
already exist; use ``--scene-dir`` only when its name cannot be inferred from
the standard Infinigen output directory name.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
IR_DATASET_ROOT = REPO_ROOT / "out" / "ir_dataset"
OPTICALNAV_ROOT = REPO_ROOT / "out" / "opticalnav"
PROFILE_NAME = "ir_geometry_profile.json"
PROFILE = "ir_semantic_lod_v1"
SCENE_MATERIALIZER_CONTRACT = "opticalnav-scene-materializer-v2"
SURFACE_DOMAIN = "structural_specular_pbr"
PROFILE_BUILDER = REPO_ROOT / "apps" / "build_ir_geometry_profile.py"
RENDER_QUEUE = REPO_ROOT / "apps" / "render_ir_dataset_queue.py"
PROPERTY_GT_QUEUE = REPO_ROOT / "apps" / "render_ir_property_gt_queue.py"
BLENDER_LAUNCHER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
BLENDER_GT_SCRIPT = REPO_ROOT / "tools" / "infinigen" / "blender_render_kitchen_gt_aov.py"
ASSEMBLE_APP = REPO_ROOT / "apps" / "assemble_ir_dataset.py"
_DERIVED_IR_SOURCE_SIDECARS = (
    "render_scene.xml",
    "xml_scene_index.json",
    "render_scene_material_policy.json",
    "material_canonical.json",
    "authoring_map.json",
    "viewpoint_graph.json",
)


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _source_id_from_blend(blend: Path) -> str:
    """Return ``kr_...`` source id from the conventional ``.../<id>/full/scene.blend``."""
    if blend.name == "scene.blend" and blend.parent.name == "full":
        return blend.parent.parent.name
    return blend.stem


def _scene_name_candidates(source_id: str) -> list[str]:
    """Map common Infinigen source IDs to their OpticalNav scene names."""
    candidates = [source_id, f"infinigen_{source_id}"]
    # ``kr_20260730_single_room_kitchen`` historically imported as
    # ``infinigen_single_room_kitchen_20260730``.  Keep the original spelling
    # candidates too: older scenes (e.g. kr_20260625) use that form.
    pieces = source_id.split("_", 2)
    if len(pieces) == 3 and pieces[0] == "kr" and len(pieces[1]) == 8 and pieces[1].isdigit():
        candidates.insert(0, f"infinigen_{pieces[2]}_{pieces[1]}")
    return list(dict.fromkeys(candidates))


def _scene_dirs_for_candidates(candidates: Iterable[str]) -> list[Path]:
    wanted = set(candidates)
    found: list[Path] = []
    if not OPTICALNAV_ROOT.is_dir():
        return found
    for project_dir in sorted(OPTICALNAV_ROOT.iterdir()):
        scenes = project_dir / "scenes"
        if not scenes.is_dir():
            continue
        for name in wanted:
            candidate = scenes / name
            if (candidate / "viewpoint_graph.json").is_file() and (candidate / "render_scene.xml").is_file():
                found.append(candidate.resolve())
    return found


def _discover_scene_dir(blend: Path) -> Path:
    source_id = _source_id_from_blend(blend)
    candidates = _scene_name_candidates(source_id)
    matches = _scene_dirs_for_candidates(candidates)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            "could not find an imported OpticalNav scene for "
            f"{blend}; tried {', '.join(candidates)} below {OPTICALNAV_ROOT}. "
            "Import/compile the scene first, or pass --scene-dir explicitly."
        )
    rendered = ", ".join(str(match) for match in matches)
    raise RuntimeError(f"blend maps to multiple OpticalNav scenes: {rendered}; pass --scene-dir explicitly")


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _matching_output_roots(blend: Path, scene_dir: Path) -> list[Path]:
    """Find previous output roots for exactly this source blend + authoring scene.

    A successful Stage 1 writes its own manifest before the separate Stage-2
    profile is published.  Looking at that manifest as well as the final
    profile means an interruption in that narrow window remains one-command
    resumable.
    """
    if not IR_DATASET_ROOT.is_dir():
        return []
    matched: list[Path] = []
    for candidate in sorted(IR_DATASET_ROOT.iterdir()):
        geometry_root = candidate / "ir_geometry"
        profile_path = geometry_root / PROFILE_NAME
        profile = _read_json(profile_path)
        if profile is not None:
            try:
                profile_blend = _resolved(Path(str(profile.get("source_blend") or "")))
                profile_scene = _resolved(Path(str(profile.get("source_scene_dir") or "")))
            except (OSError, RuntimeError):
                continue
            if profile_blend == blend and profile_scene == scene_dir:
                matched.append(candidate.resolve())
                continue

        # Stage 1 is the durable checkpoint for a build interrupted before
        # ``ir_geometry_profile.json`` exists.  It records the exact blend;
        # the domain sidecar records the source scene used to form the
        # effective structural scene.  Require both when they are available.
        stage1 = _read_json(geometry_root / "stage1" / "scene_manifest.json")
        domain = _read_json(geometry_root / "source_structural_domain" / "ir_scene_domain.json")
        if stage1 is None or domain is None:
            continue
        try:
            stage1_blend = _resolved(Path(str(stage1.get("source_blend") or "")))
            domain_scene = _resolved(Path(str(domain.get("source_scene_dir") or "")))
        except (OSError, RuntimeError):
            continue
        if stage1_blend == blend and domain_scene == scene_dir:
            matched.append(candidate.resolve())
    return list(dict.fromkeys(matched))


def _default_output_root(blend: Path, scene_dir: Path) -> Path:
    matches = _matching_output_roots(blend, scene_dir)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        rendered = ", ".join(str(match) for match in matches)
        raise RuntimeError(f"multiple existing IR outputs match this blend: {rendered}; pass --out explicitly")
    return IR_DATASET_ROOT / f"{scene_dir.name}_structural_specular_lod"


def _stage_state(geometry_root: Path) -> str:
    profile = geometry_root / PROFILE_NAME
    stage1_manifest = geometry_root / "stage1" / "scene_manifest.json"
    derived_blend = geometry_root / "derived_ir_semantic_lod.blend"
    if profile.is_file():
        payload = _read_json(profile)
        derived_scene = Path(str((payload or {}).get("derived_scene_dir") or ""))
        if (
            (payload or {}).get("scene_materializer_contract") == SCENE_MATERIALIZER_CONTRACT
            and derived_scene
            and all((derived_scene / name).is_file() for name in _DERIVED_IR_SOURCE_SIDECARS)
        ):
            return "profile_ready"
        # Older profiles can predate the Stage-2 material canonicalization
        # contract.  Their expensive Stage-1 mesh export is still good; only
        # rerun Stage 2/profile finalization.
        if stage1_manifest.is_file() and derived_blend.is_file():
            return "profile_contract_incomplete"
    if stage1_manifest.is_file() and derived_blend.is_file():
        return "stage1_published"
    if (geometry_root / "stage1").exists():
        return "stage1_incomplete"
    return "new"


def _run(command: list[str]) -> None:
    print("[quickstart] $ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _jsonl_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _queue_frame_count(out: Path) -> int:
    manifest = _read_json(out / "queue_manifest.json") or {}
    count = manifest.get("frame_count")
    if not isinstance(count, int) or count < 1:
        raise RuntimeError(f"Stage 3 queue manifest is absent or invalid: {out / 'queue_manifest.json'}")
    return count


def _observation_stage_progress(out: Path) -> tuple[int, int] | None:
    """Return published Stage-3 progress without treating scratch as complete."""
    manifest = _read_json(out / "queue_manifest.json") or {}
    total = manifest.get("frame_count")
    if not isinstance(total, int) or total < 1:
        return None
    state = _read_json(out / "rolling_queue_state.json") or {}
    frames = state.get("frames")
    if not isinstance(frames, dict):
        return 0, total
    complete = sum(1 for entry in frames.values() if isinstance(entry, dict) and entry.get("status") == "complete")
    return complete, total


def _blender_gt_complete(blender_out: Path, expected_frames: int) -> bool:
    """Require all authoritative ARMN rows, rather than a merely existing directory."""
    if not (blender_out / "material_table.json").is_file():
        return False
    index = blender_out / "index.jsonl"
    if _jsonl_count(index) != expected_frames:
        return False
    required = {"base_color_rgb", "roughness", "metallic", "normal_shading_camera", "pbr_validity"}
    try:
        rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return False
    return all(
        required <= set(paths := dict(row.get("paths") or {}))
        and all(Path(str(paths[name])).is_file() for name in required)
        for row in rows
    )


def _mitsuba_property_gt_complete(out: Path, expected_frames: int) -> bool:
    """Check primary-hit geometry/NIR and semantic masks, not only a state file."""
    index = out / "index.jsonl"
    if _jsonl_count(index) != expected_frames:
        return False
    domain = _read_json(out / "ir_effective_scene" / "ir_scene_domain.json") or {}
    surface_domain = str(domain.get("surface_domain") or "")
    required_gt = {
        "rgb_albedo", "nir_albedo", "roughness_perceptual", "metallic", "depth", "range",
        "normal_geometry_world", "normal_shading_world", "normal_tangent",
    }
    required_masks = {"material_id", "object_id", "valid_mask", "replacement_mask"}
    if surface_domain in {"specular_masked_pbr", "structural_specular_pbr"}:
        required_masks.update({"window_glass", "object_glass", "glass", "mirror"})
    try:
        rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return False
    return all(
        required_gt <= set(gt := dict(row.get("gt_paths") or {}))
        and required_masks <= set(masks := dict(row.get("mask_paths") or {}))
        and all(Path(str(gt[name])).is_file() for name in required_gt)
        and all(Path(str(masks[name])).is_file() for name in required_masks)
        for row in rows
    )


def _assembly_complete(out: Path, expected_frames: int) -> bool:
    payload = _read_json(out / "ir_dataset_assembly.json")
    return bool(payload and int(payload.get("frame_count", -1)) == expected_frames)


def _record_pbr_stage(out: Path, **values: object) -> None:
    """Keep quickstart's explicit post-observation stages visible to resume/UI tools."""
    path = out / "queue_manifest.json"
    manifest = _read_json(path) or {}
    stage = dict(manifest.get("blender_gt") or {})
    stage.update(values)
    stage["updated_at"] = _utc_now()
    manifest["blender_gt"] = stage
    manifest["updated_at"] = _utc_now()
    _atomic_json(path, manifest)


def _record_property_gt_stage(out: Path, **values: object) -> None:
    """Expose independent Mitsuba property readout state in the run manifest."""
    path = out / "queue_manifest.json"
    manifest = _read_json(path) or {}
    stage = dict(manifest.get("mitsuba_property_gt") or {})
    stage.update(values)
    stage["updated_at"] = _utc_now()
    manifest["mitsuba_property_gt"] = stage
    manifest["updated_at"] = _utc_now()
    _atomic_json(path, manifest)


def _run_pbr_gt_and_assembly(
    *, out: Path, derived_blend: Path, width: int, height: int, fov: float, blender_samples: int,
    gpu_indices: str, parallel_workers: int, texture_max_resolution: int, texture_cache_dir: Path,
) -> None:
    """Stages 4–6: Mitsuba property GT, Blender ARMN GT, then merge records."""
    expected_frames = _queue_frame_count(out)
    effective_scene = out / "ir_effective_scene"
    graph = effective_scene / "viewpoint_graph.json"
    domain = effective_scene / "ir_scene_domain.json"
    if not graph.is_file() or not domain.is_file():
        raise RuntimeError("Stage 3 did not publish the immutable effective scene required for Blender PBR GT")
    if not _mitsuba_property_gt_complete(out, expected_frames):
        _record_property_gt_stage(
            out, status="running", provider="mitsuba_primary_ray_readout", expected_frames=expected_frames,
            artifacts=["depth", "range", "base_color_nir", "normal_geometry_world", "semantic_masks"],
        )
        print(
            f"[quickstart] Stage 4 Mitsuba property/semantic GT: {expected_frames} views "
            "(NIR / depth / normals / IDs / glass-mirror masks)",
            flush=True,
        )
        _run([
            sys.executable, str(PROPERTY_GT_QUEUE), "--dataset", str(out), "--effective-scene", str(effective_scene),
            "--gpus", str(gpu_indices), "--parallel-workers", str(parallel_workers),
            "--width", str(width), "--height", str(height), "--fov", str(fov),
            "--subpixel", "2", "--band", "854",
            "--texture-max-resolution", str(texture_max_resolution),
            "--texture-cache-dir", str(texture_cache_dir), "--mitsuba-runtime", "optix7",
        ])
    else:
        print("[quickstart] Stage 4 Mitsuba property/semantic GT already complete", flush=True)
    if not _mitsuba_property_gt_complete(out, expected_frames):
        raise RuntimeError("Mitsuba property GT stage returned without complete geometry/mask artifacts")
    _record_property_gt_stage(
        out, status="complete", provider="mitsuba_primary_ray_readout", expected_frames=expected_frames,
        completed_at=_utc_now(),
    )
    blender_out = out / "blender_gt"
    if not _blender_gt_complete(blender_out, expected_frames):
        _record_pbr_stage(
            out, status="running", provider="blender_aov", path=str(blender_out.resolve()),
            expected_frames=expected_frames, artifacts=[
                "base_color_rgb", "roughness", "metallic", "normal_shading_camera", "pbr_validity",
            ],
        )
        print(
            f"[quickstart] Stage 5 Blender PBR AOV GT: {expected_frames} views "
            "(base_color_rgb / roughness / metallic / normal_shading_camera)",
            flush=True,
        )
        _run([
            sys.executable, str(BLENDER_LAUNCHER), "--background", str(derived_blend),
            "--python", str(BLENDER_GT_SCRIPT), "--",
            "--scene-graph", str(graph), "--out", str(blender_out),
            "--width", str(width), "--height", str(height), "--fov", str(fov),
            "--samples", str(blender_samples), "--ir-scene-domain", str(domain),
            "--pose-manifest", str(out / "index.jsonl"),
            "--require-pose-manifest", "--resume",
        ])
    else:
        print(f"[quickstart] Stage 5 Blender PBR AOV GT already complete: {blender_out}", flush=True)
    if not _blender_gt_complete(blender_out, expected_frames):
        raise RuntimeError("Blender PBR GT stage returned without a complete ARMN artifact set")
    _record_pbr_stage(
        out, status="complete", provider="blender_aov", path=str(blender_out.resolve()),
        expected_frames=expected_frames, completed_at=_utc_now(),
    )
    if _assembly_complete(out, expected_frames):
        print("[quickstart] Stage 6 IR assembly already complete", flush=True)
        return
    print("[quickstart] Stage 6 merge Blender PBR GT with Mitsuba observations/masks", flush=True)
    _run([
        sys.executable, str(ASSEMBLE_APP), "--dataset", str(out),
        "--blender-gt", str(blender_out), "--effective-scene", str(effective_scene),
    ])


def _prepare_geometry(*, blend: Path, scene_dir: Path, geometry_root: Path) -> None:
    state = _stage_state(geometry_root)
    common = [
        sys.executable, str(PROFILE_BUILDER),
        "--source-scene-dir", str(scene_dir),
        "--source-blend", str(blend),
        "--out", str(geometry_root),
        "--profile", PROFILE,
    ]
    if state == "profile_ready":
        print(f"[quickstart] Stage 1/2 already complete: {geometry_root / PROFILE_NAME}", flush=True)
        return
    if state in {"stage1_published", "profile_contract_incomplete"}:
        reason = "Stage-2 material contract incomplete" if state == "profile_contract_incomplete" else "Stage 1 published"
        print(f"[quickstart] {reason}; finalizing Stage 2/profile only", flush=True)
        _run(common + ["--finalize-existing"])
        return
    if state == "stage1_incomplete":
        print("[quickstart] resuming incomplete Stage 1, then Stage 2", flush=True)
        _run(common + ["--resume"])
        return
    print("[quickstart] starting Stage 1 strict GLB/PBR + LOD, then Stage 2", flush=True)
    _run(common)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("blend", type=Path, help="Infinigen source .blend")
    parser.add_argument("--scene-dir", type=Path, help="authoring OpticalNav scene; auto-discovered by default")
    parser.add_argument("--out", type=Path, help="IR dataset root; matching previous root is reused by default")
    parser.add_argument(
        "--geometry-profile-dir", type=Path,
        help="reuse a published ir_geometry profile from another output root (avoids rebuilding Stage 1/2 for a new render version)",
    )
    parser.add_argument(
        "--gpu-indices", "--gpus", dest="gpu_indices",
        default=os.environ.get("ROBOMITUBA_RENDER_GPU_INDICES", "0,1,2,3,4,5,6,7"),
        help="comma-separated GPU indices (alias: --gpus)",
    )
    parser.add_argument("--parallel-chunks", type=int, default=8)
    parser.add_argument("--scheduler", choices=("rolling", "chunked"), default="rolling")
    parser.add_argument("--lease-size", type=int, default=4,
                        help="rolling scheduler frames per dynamic lease")
    parser.add_argument("--render-batch-size", type=int, default=100,
                        help="chunked scheduler only: frames per renderer subprocess")
    parser.add_argument(
        "--spp", type=int,
        help="legacy common SPP; when supplied, unset pass-specific values inherit it",
    )
    parser.add_argument("--rgb-spp", type=int,
                        help="RGB passive SPP; default profile is 2000, otherwise inherits explicit --spp")
    parser.add_argument("--nir-ambient-spp", type=int,
                        help="NIR ambient SPP; default profile is 1500, otherwise inherits explicit --spp")
    parser.add_argument("--nir-direct-spp", type=int,
                        help="NIR flash-direct SPP; default profile is 384, otherwise inherits explicit --spp")
    parser.add_argument("--max-depth", type=int, default=8,
                        help="path-integrator maximum depth for all observation passes")
    parser.add_argument(
        "--texture-max-resolution", type=int,
        default=int(os.environ.get("ROBOMITUBA_TEXTURE_MAX_RESOLUTION", "256") or 256),
        help="host-local cached max texture edge for Stage 3 (default: 256)",
    )
    parser.add_argument(
        "--texture-cache-dir", type=Path,
        default=Path(os.environ.get(
            "ROBOMITUBA_TEXTURE_CACHE_DIR",
            str(Path.home() / "robomituba-cache" / "ir_texture_downsampled"),
        )),
        help="host-local shared cache for bounded Stage-3 texture copies",
    )
    parser.add_argument("--polar", action="store_true", help="include polarized observations/DoP/AoLP from the start")
    parser.add_argument("--observations-only", action="store_true", help="stop after Stage 3 GPU observations; defer Blender ARMN GT and final assembly")
    parser.add_argument("--blender-samples", type=int, default=1,
                        help="Cycles samples for deterministic Blender PBR AOV GT (default: 1)")
    parser.add_argument("--prepare-only", action="store_true", help="finish/resume only Stage 1/2; do not render")
    parser.add_argument("--plan-only", action="store_true", help="prepare the queue but do not dispatch GPU chunks")
    args = parser.parse_args()

    if args.texture_max_resolution < 0:
        parser.error("--texture-max-resolution must be non-negative")
    if args.lease_size < 1:
        parser.error("--lease-size must be positive")
    if args.render_batch_size < 1:
        parser.error("--render-batch-size must be positive")
    if args.blender_samples < 1:
        parser.error("--blender-samples must be positive")
    if args.spp is None:
        args.spp = 2000
        defaults = {"rgb_spp": 2000, "nir_ambient_spp": 1500, "nir_direct_spp": 384}
    else:
        defaults = {name: int(args.spp) for name in ("rgb_spp", "nir_ambient_spp", "nir_direct_spp")}
    for name in ("rgb_spp", "nir_ambient_spp", "nir_direct_spp"):
        if getattr(args, name) is None:
            setattr(args, name, defaults[name])
        value = getattr(args, name)
        if value is not None and value < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.max_depth == 0 or args.max_depth < -1:
        parser.error("--max-depth must be -1 (unlimited) or a positive integer")
    args.texture_cache_dir = _resolved(args.texture_cache_dir)
    if str(args.texture_cache_dir).startswith("/jarvis/"):
        parser.error("--texture-cache-dir must be host-local, not /jarvis/NAS")

    blend = _resolved(args.blend)
    if not blend.is_file():
        parser.error(f"blend not found: {blend}")
    scene_dir = _resolved(args.scene_dir) if args.scene_dir else _discover_scene_dir(blend)
    if not (scene_dir / "viewpoint_graph.json").is_file() or not (scene_dir / "render_scene.xml").is_file():
        parser.error(f"not an imported OpticalNav authoring scene: {scene_dir}")
    out = _resolved(args.out) if args.out else _default_output_root(blend, scene_dir)
    geometry_root = _resolved(args.geometry_profile_dir) if args.geometry_profile_dir else out / "ir_geometry"
    print(f"[quickstart] blend={blend}", flush=True)
    print(f"[quickstart] scene={scene_dir}", flush=True)
    print(f"[quickstart] out={out}", flush=True)
    if args.geometry_profile_dir:
        if _stage_state(geometry_root) != "profile_ready":
            parser.error(f"--geometry-profile-dir is not a published compatible profile: {geometry_root}")
        profile = _read_json(geometry_root / PROFILE_NAME) or {}
        try:
            profile_blend = _resolved(Path(str(profile.get("source_blend") or "")))
            profile_scene = _resolved(Path(str(profile.get("source_scene_dir") or "")))
        except (OSError, RuntimeError):
            parser.error(f"--geometry-profile-dir has invalid source provenance: {geometry_root}")
        if profile_blend != blend or profile_scene != scene_dir:
            parser.error("--geometry-profile-dir belongs to a different source blend or OpticalNav scene")
        print(f"[quickstart] reusing published Stage 1/2 profile: {geometry_root / PROFILE_NAME}", flush=True)
    else:
        _prepare_geometry(blend=blend, scene_dir=scene_dir, geometry_root=geometry_root)
    if args.prepare_only:
        print("[quickstart] Stage 1/2 ready; --prepare-only requested", flush=True)
        return 0

    profile = _read_json(geometry_root / PROFILE_NAME)
    if profile is None:
        parser.error(f"published geometry profile is missing: {geometry_root / PROFILE_NAME}")
    try:
        derived_blend = _resolved(Path(str(profile["derived_blend"])))
    except (KeyError, OSError, RuntimeError):
        parser.error(f"geometry profile lacks a valid derived Blender scene: {geometry_root / PROFILE_NAME}")
    if not derived_blend.is_file():
        parser.error(f"derived Blender scene is absent: {derived_blend}")

    queue = [
        sys.executable, str(RENDER_QUEUE),
        "--scene-dir", str(scene_dir),
        "--source-blend", str(blend),
        "--out", str(out),
        "--geometry-profile-dir", str(geometry_root),
        "--surface-domain", SURFACE_DOMAIN,
        "--pbr-gt-provider", "blender_aov",
        "--width", "684", "--height", "512", "--fov", "60",
        "--spp", str(args.spp),
        "--rgb-spp", str(args.rgb_spp),
        "--nir-ambient-spp", str(args.nir_ambient_spp),
        "--nir-direct-spp", str(args.nir_direct_spp),
        "--max-depth", str(args.max_depth),
        "--texture-max-resolution", str(args.texture_max_resolution),
        "--texture-cache-dir", str(args.texture_cache_dir),
        "--chunk-size", "100", "--scheduler", str(args.scheduler), "--lease-size", str(args.lease_size),
        "--render-batch-size", str(args.render_batch_size),
        "--gpu-indices", str(args.gpu_indices),
        "--parallel-chunks", str(args.parallel_chunks),
        "--gpu-cleanup-interval", "100", "--async-io",
        "--mitsuba-runtime", "optix7",
        # Stage 4/5 are explicit below. This prevents the queue from hiding
        # Blender AOV progress behind its final scheduler return path.
        "--observations-only",
    ]
    if args.polar:
        queue.append("--polar")
    if args.plan_only:
        queue.append("--plan-only")
    progress = _observation_stage_progress(out)
    if progress is None:
        print("[quickstart] Stage 3 GPU observations (new queue)", flush=True)
    elif progress[0] == progress[1]:
        print(f"[quickstart] Stage 3 already published: {progress[0]}/{progress[1]}; validating before Stage 4", flush=True)
    else:
        print(
            f"[quickstart] Stage 3 resume: {progress[0]}/{progress[1]} published; "
            f"dispatching only incomplete frames",
            flush=True,
        )
    _run(queue)
    if args.observations_only or args.plan_only:
        print("[quickstart] Stage 3 complete; PBR GT/assembly deferred by request", flush=True)
        return 0
    _run_pbr_gt_and_assembly(
        out=out, derived_blend=derived_blend, width=684, height=512, fov=60.0,
        blender_samples=args.blender_samples, gpu_indices=args.gpu_indices,
        parallel_workers=args.parallel_chunks, texture_max_resolution=args.texture_max_resolution,
        texture_cache_dir=args.texture_cache_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
