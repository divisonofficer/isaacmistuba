#!/usr/bin/env python3
"""Build a verified common-geometry profile for inverse-rendering datasets.

The source OpticalNav scene remains untouched.  The IR profile re-exports the
source Blender scene through the Stage-1 GLB/PBR exporter with the strict
``ir_semantic_lod_v1`` policy, saves that decimated Blender scene, and imports
it into a separate generated OpticalNav scene.  Both paths are recorded in a
small immutable profile consumed by the IR queue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.material_pipeline import (
    STRUCTURAL_SPECULAR_PBR_DOMAIN, materialize_ir_effective_scene, source_scene_digest,
)
from mitsuba_converter.scene_materialization import SCENE_MATERIALIZER_CONTRACT_VERSION

sys.path.insert(0, str(REPO_ROOT / "tools" / "infinigen"))
from small_highpoly_filter import SMALL_HIGH_POLY_POLICY_VERSION  # noqa: E402

BLENDER_LAUNCHER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
BLENDER_EXPORT = REPO_ROOT / "tools" / "infinigen" / "blender_export_scene.py"
IMPORT_APP = REPO_ROOT / "apps" / "import_infinigen_scene.py"
MATERIAL_PIPELINE_APP = REPO_ROOT / "apps" / "material_pipeline.py"
PROFILE_NAME = "ir_geometry_profile.json"
PROFILE_SCHEMA = "robomituba.ir_geometry_profile.v1"
PROFILE_VERSION = "ir-semantic-lod-v1"
_GRAPH_SIDECARS = (
    "viewpoint_graph.json", "nav_graph.json", "scene_annotation.json",
    "render_readiness.json", "authoring_map.json",
)
# These are the minimum input contract for ``materialize_ir_effective_scene``.
# Stage 2 used to publish a renderable derived scene but omit the canonical
# material document, which made the first Stage-3 invocation fail late.
_DERIVED_IR_SOURCE_SIDECARS = (
    "render_scene.xml",
    "xml_scene_index.json",
    "render_scene_material_policy.json",
    "material_canonical.json",
    "authoring_map.json",
    "viewpoint_graph.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _project_id(scene_dir: Path) -> str:
    parts = scene_dir.resolve().parts
    try:
        return parts[parts.index("opticalnav") + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"cannot infer OpticalNav project from {scene_dir}") from exc


def _derived_scene_id(scene_dir: Path, profile: str) -> str:
    return f"{scene_dir.name}__{profile}"


def _validate_stage1(manifest_path: Path, *, profile: str) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    stage1_profile = str(payload.get("stage1_profile") or "strict-pbr-v1")
    if stage1_profile not in {"strict-pbr-v1", "strict-pbr-v2-slot-aware"}:
        raise ValueError("authoritative IR geometry requires a strict PBR Stage-1 output")
    units = list(payload.get("units") or [])
    failures: list[str] = []
    structural_exclusion = dict(payload.get("ir_face_exclusion") or {})
    removed_structural_triangles = int(structural_exclusion.get("removed_triangle_count") or 0)
    decimated: list[dict[str, Any]] = []
    triangles_before_total = 0
    triangles_after_total = 0
    for unit in units:
        pbr = dict(unit.get("pbr") or {})
        if pbr.get("status") != "ok" or pbr.get("appearance_authoritative") is False:
            failures.append("{}: missing authoritative PBR atlas contract".format(unit.get("id")))
        if stage1_profile == "strict-pbr-v2-slot-aware":
            used_slots = {str(int(index)) for index in (unit.get("decimation") or {}).get("geometry_validation", {}).get("derived_used_material_indices", [])}
            if not used_slots:
                # Decimation metadata is absent for some tiny geometry; source
                # slots are still a valid conservative expectation.
                used_slots = {str(index) for index, _slot in enumerate(unit.get("material_slots") or [])}
            by_slot = dict(unit.get("pbr_by_slot") or pbr.get("pbr_by_slot") or {})
            for slot in used_slots:
                record = dict(by_slot.get(slot) or {})
                # GLB validation represents a mesh with no authored Blender
                # material slots as primitive material index 0.  In that case
                # the exporter intentionally stores the authoritative default
                # constant contract at unit.pbr (there is no real slot record
                # to populate).  Treat that implicit default slot as the same
                # effective material rather than rejecting an otherwise valid
                # structural mesh during Stage-2 finalization.
                if (
                    not record and slot == "0" and not (unit.get("material_slots") or [])
                    and pbr.get("status") == "ok" and pbr.get("appearance_authoritative") is not False
                ):
                    record = pbr
                if not record or record.get("status") != "ok" or record.get("appearance_authoritative") is False:
                    failures.append("{}: slot {} lacks authoritative PBR atlas contract".format(unit.get("id"), slot))
        decimation = dict(unit.get("decimation") or {})
        if not decimation:
            failures.append("{}: missing decimation record".format(unit.get("id")))
            continue
        before = int(decimation.get("triangles_before") or decimation.get("faces_before") or 0)
        after = int(decimation.get("triangles_after") or decimation.get("faces_after") or 0)
        triangles_before_total += before
        triangles_after_total += after
        status = str(decimation.get("status") or "")
        if status in {"no_effect", "error"}:
            failures.append("{}: {}".format(unit.get("id"), decimation.get("error")))
        if before >= 50000 and status != "reduced":
            failures.append("{}: eligible mesh not reduced (status={})".format(unit.get("id"), status))
        if decimation.get("decimated"):
            maximum = int(decimation.get("target_max_triangles") or decimation.get("target_max_faces") or before)
            if before and after > maximum:
                failures.append("{}: {}>{}".format(unit.get("id"), after, maximum))
            geometry_validation = dict(decimation.get("geometry_validation") or {})
            if geometry_validation.get("passed") is not True:
                failures.append("{}: derived geometry validation failed".format(unit.get("id")))
            decimated.append({
                "object_id": unit.get("id"), "triangles_before": before,
                "triangles_after": after, "target_ratio": decimation.get("target_ratio"),
                "geometry_validation": geometry_validation,
            })
    if failures:
        raise ValueError("strict IR LOD Stage-1 validation failed: " + "; ".join(failures[:12]))
    return {
        "profile": profile,
        "stage1_profile": stage1_profile,
        "unit_count": len(units),
        "decimated_unit_count": len(decimated),
        "triangles_before_total": triangles_before_total,
        "source_triangles_before_structural_removal": triangles_before_total + removed_structural_triangles,
        "triangles_after_structural_removal_before_lod": triangles_before_total,
        "removed_object_glass_triangles": removed_structural_triangles,
        "triangles_after_total": triangles_after_total,
        "retained_triangle_ratio": (triangles_after_total / triangles_before_total) if triangles_before_total else 1.0,
        "decimated_units": decimated,
        "structural_exclusion": structural_exclusion,
        "manifest_sha256": _sha256(manifest_path),
    }


def _copy_graph_sidecars(source: Path, derived: Path) -> None:
    for name in _GRAPH_SIDECARS:
        candidate = source / name
        if candidate.is_file():
            shutil.copy2(candidate, derived / name)


def _has_derived_ir_source_contract(scene_dir: Path) -> bool:
    """Whether Stage 3 may safely materialize an effective scene from it."""
    return all((scene_dir / name).is_file() for name in _DERIVED_IR_SOURCE_SIDECARS)


def _ensure_derived_material_contract(scene_dir: Path) -> None:
    """Create the material-slot and canonical sidecars after the derived import.

    ``import_infinigen_scene.py`` creates the XML/policy sidecars but deliberately
    does not run the independently inspectable material pipeline.  IR rendering
    consumes the canonical document, so doing this here makes a published
    geometry profile genuinely Stage-3-ready rather than merely renderable.
    """
    for stage in ("extract", "canonicalize"):
        command = [sys.executable, str(MATERIAL_PIPELINE_APP), stage, "--scene", str(scene_dir)]
        print(f"[ir-lod] Stage 2 material {stage}", flush=True)
        subprocess.run(command, cwd=REPO_ROOT, check=True)
    missing = [name for name in _DERIVED_IR_SOURCE_SIDECARS if not (scene_dir / name).is_file()]
    if missing:
        raise RuntimeError(
            "derived scene did not publish the IR material source contract: " + ", ".join(missing)
        )


def _existing_matches(path: Path, *, source_digest: str, source_blend_sha256: str, profile: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("schema") != PROFILE_SCHEMA:
        return None
    if payload.get("profile") != profile:
        return None
    if payload.get("scene_materializer_contract") != SCENE_MATERIALIZER_CONTRACT_VERSION:
        return None
    if payload.get("source_scene_digest") != source_digest:
        return None
    if payload.get("source_blend_sha256") != source_blend_sha256:
        return None
    derived_scene = Path(str(payload.get("derived_scene_dir") or ""))
    derived_blend = Path(str(payload.get("derived_blend") or ""))
    if not _has_derived_ir_source_contract(derived_scene) or not derived_blend.is_file():
        return None
    return payload


def _run_bake_export_with_fallback(
    command: list[str], *, requested: str, fallback: str,
) -> tuple[str, bool]:
    """Run the authoritative bake and resume checkpoints once on device failure."""
    result = subprocess.run(command, cwd=REPO_ROOT)
    if not result.returncode:
        return requested, False
    if requested == fallback:
        raise subprocess.CalledProcessError(result.returncode, command)
    fallback_command = list(command)
    fallback_command[fallback_command.index("--cycles-device") + 1] = fallback
    if "--reuse-atlas" not in fallback_command:
        fallback_command.append("--reuse-atlas")
    print(
        f"[bake-device-fallback] {requested} exited {result.returncode}; "
        f"resuming verified units on {fallback}",
        flush=True,
    )
    subprocess.run(fallback_command, cwd=REPO_ROOT, check=True)
    return fallback, True


def build_profile(
    source_scene_dir: Path,
    source_blend: Path,
    out: Path,
    *,
    profile: str = "ir_semantic_lod_v1",
    force: bool = False,
    resume: bool = False,
    finalize_existing: bool = False,
    cycles_device: str = "CPU",
    cycles_fallback: str = "CPU",
    filter_small_high_poly: bool = False,
    small_high_poly_max_extent_m: float = 0.25,
    small_high_poly_min_triangles: int = 200_000,
    bake_samples: int | None = None,
    max_bake_res: int | None = None,
) -> dict[str, Any]:
    source_scene_dir = source_scene_dir.resolve()
    source_blend = source_blend.resolve()
    out = out.resolve()
    if profile not in {"ir_semantic_lod_v1", "full"}:
        raise ValueError(f"unsupported geometry profile: {profile}")
    cycles_device = str(cycles_device).upper()
    cycles_fallback = str(cycles_fallback).upper()
    if cycles_device not in {"CPU", "CUDA", "OPTIX"} or cycles_fallback not in {"CPU", "CUDA", "OPTIX"}:
        raise ValueError("Cycles device must be CPU, CUDA, or OPTIX")
    if not source_blend.is_file():
        raise FileNotFoundError(f"source blend does not exist: {source_blend}")
    source_digest = source_scene_digest(source_scene_dir)
    source_blend_sha256 = _sha256(source_blend)
    profile_path = out / PROFILE_NAME
    previous_payload: dict[str, Any] = {}
    if profile_path.is_file():
        try:
            previous_payload = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            previous_payload = {}
    filter_ready = True
    if filter_small_high_poly:
        try:
            stage1_meta = json.loads((out / "stage1" / "scene_manifest.json").read_text(encoding="utf-8"))
            cfg = stage1_meta.get("small_high_poly_filter") or {}
            filter_ready = (
                bool(cfg.get("enabled"))
                and cfg.get("policy_version") == SMALL_HIGH_POLY_POLICY_VERSION
                and float(cfg.get("max_extent_m", -1)) == float(small_high_poly_max_extent_m)
                and int(cfg.get("min_triangles", -1)) == int(small_high_poly_min_triangles)
            )
        except Exception:
            filter_ready = False
    if not force and not finalize_existing:
        existing = _existing_matches(
            profile_path, source_digest=source_digest,
            source_blend_sha256=source_blend_sha256, profile=profile,
        )
        if existing is not None and filter_ready:
            return existing

    reuse_published_stage1 = bool(
        not force
        and profile == "ir_semantic_lod_v1"
        and previous_payload.get("profile") == profile
        and previous_payload.get("source_scene_digest") == source_digest
        and previous_payload.get("source_blend_sha256") == source_blend_sha256
        and filter_ready
        and (out / "stage1" / "scene_manifest.json").is_file()
        and (out / "derived_ir_semantic_lod.blend").is_file()
    )

    out.mkdir(parents=True, exist_ok=True)
    if profile == "full":
        payload = {
            "schema": PROFILE_SCHEMA, "profile_version": PROFILE_VERSION,
            "scene_materializer_contract": SCENE_MATERIALIZER_CONTRACT_VERSION,
            "profile": "full", "source_scene_dir": str(source_scene_dir),
            "source_scene_digest": source_digest, "source_blend": str(source_blend),
            "source_blend_sha256": source_blend_sha256, "derived_scene_dir": str(source_scene_dir),
            "derived_blend": str(source_blend), "geometry_digest": source_digest,
            "geometry": {"decimation": "none", "common_geometry": True},
        }
        _atomic_json(profile_path, payload)
        return payload

    semantic_domain_dir = out / "source_structural_domain"
    semantic_domain = materialize_ir_effective_scene(
        source_scene_dir, semantic_domain_dir,
        surface_domain=STRUCTURAL_SPECULAR_PBR_DOMAIN,
        reuse_existing=not force,
    )
    semantic_domain_path = semantic_domain_dir / "ir_scene_domain.json"
    if not semantic_domain_path.is_file():
        raise RuntimeError("structural semantic domain did not publish its contract")
    stage1_dir = out / "stage1"
    derived_blend = out / "derived_ir_semantic_lod.blend"
    stage1_manifest = stage1_dir / "scene_manifest.json"
    if finalize_existing and not filter_ready:
        # The published Stage-1 geometry was produced by an older filtering
        # policy.  Finalizing it would preserve RGB-visible/PBR-untracked
        # props forever, so reuse verified per-unit checkpoints but republish
        # the manifest and derived blend under the current policy.
        print(
            "[ir-lod] Stage 1 small-detail policy changed; "
            "switching --finalize-existing to --resume",
            flush=True,
        )
        finalize_existing = False
        resume = True
    if (
        finalize_existing
        and stage1_dir.exists()
        and not (stage1_manifest.is_file() and derived_blend.is_file())
    ):
        # Older controllers used directory existence as the signal for
        # --finalize-existing.  A crash-safe Stage-1 export creates that
        # directory and per-unit checkpoints long before it atomically
        # publishes the manifest and derived blend.  Preserve those verified
        # units and continue baking instead of rejecting a recoverable build.
        print(
            "[ir-lod] Stage 1 is checkpointed but not published; "
            "switching --finalize-existing to --resume",
            flush=True,
        )
        finalize_existing = False
        resume = True
    if finalize_existing or reuse_published_stage1:
        # A Blender process may finish the atomic manifest + derived blend
        # publish, then fail while cleaning up temporary source-only meshes.
        # Never throw away that verified, expensive Stage-1 result just to run
        # Stage 2: validate it and continue from the published artifacts.
        if not stage1_manifest.is_file() or not derived_blend.is_file():
            raise RuntimeError(
                "--finalize-existing requires a published Stage-1 scene_manifest.json "
                "and derived_ir_semantic_lod.blend"
            )
        print("[ir-lod] Reusing verified published Stage 1; rebuilding Stage 2", flush=True)
    else:
        if stage1_dir.exists() and force and not resume:
            shutil.rmtree(stage1_dir)
        if stage1_dir.exists() and not resume:
            raise FileExistsError(f"existing incomplete geometry build: {stage1_dir}; pass --force to rebuild or --resume to reuse verified atlases")
        derived_scene_id = _derived_scene_id(source_scene_dir, profile)
        command = [
            sys.executable, str(BLENDER_LAUNCHER), "--background", str(source_blend), "--python-exit-code", "1",
            "--python", str(BLENDER_EXPORT), "--", "--out", str(stage1_dir),
            "--scene-id", derived_scene_id, "--stage1-profile", "strict-pbr-v2-slot-aware",
            "--bake", "--bake-pbr", "--cycles-device", cycles_device,
            "--ir-scene-domain", str(semantic_domain_path), "--decimate-policy", profile,
            "--decimate-min-polys", "50000", "--decimate-strict", "--save-derived-blend", str(derived_blend),
        ]
        if bake_samples is not None:
            if int(bake_samples) < 1:
                raise ValueError("bake_samples must be positive")
            command += ["--bake-samples", str(int(bake_samples))]
        if max_bake_res is not None:
            if int(max_bake_res) < 512:
                raise ValueError("max_bake_res must be >= 512")
            command += ["--max-bake-res", str(int(max_bake_res))]
        if filter_small_high_poly:
            command += ["--filter-small-high-poly", "--small-high-poly-max-extent-m", str(small_high_poly_max_extent_m),
                        "--small-high-poly-min-triangles", str(small_high_poly_min_triangles)]
        if resume:
            command.append("--reuse-atlas")
        print("[ir-lod] Stage 1 strict GLB/PBR export", flush=True)
        effective_bake_device, bake_fallback_used = _run_bake_export_with_fallback(
            command, requested=cycles_device, fallback=cycles_fallback,
        )
        if not stage1_manifest.is_file() or not derived_blend.is_file():
            raise RuntimeError("IR LOD Stage-1 did not publish both manifest and derived blend")
    if finalize_existing or reuse_published_stage1:
        stage1_payload = json.loads(stage1_manifest.read_text(encoding="utf-8"))
        device_record = dict(stage1_payload.get("bake_device") or {})
        effective_bake_device = str(device_record.get("effective") or cycles_device)
        bake_fallback_used = False
    derived_scene_id = _derived_scene_id(source_scene_dir, profile)
    stage1_audit = _validate_stage1(stage1_manifest, profile=profile)

    project_id = _project_id(source_scene_dir)
    import_command = [
        sys.executable, str(IMPORT_APP), "--manifest", str(stage1_manifest),
        "--scene-id", derived_scene_id, "--project-id", project_id,
        "--stage1-profile", str(stage1_audit.get("stage1_profile") or "strict-pbr-v1"),
        "--force", "--allow-object-id-churn",
    ]
    print("[ir-lod] Stage 2 derived scene materialization", flush=True)
    subprocess.run(import_command, cwd=REPO_ROOT, check=True)
    derived_scene_dir = REPO_ROOT / "out" / "opticalnav" / project_id / "scenes" / derived_scene_id
    if not (derived_scene_dir / "render_scene.xml").is_file():
        raise RuntimeError(f"derived scene was not materialized: {derived_scene_dir}")
    _copy_graph_sidecars(source_scene_dir, derived_scene_dir)
    _ensure_derived_material_contract(derived_scene_dir)

    digest = hashlib.sha256()
    digest.update(SCENE_MATERIALIZER_CONTRACT_VERSION.encode("utf-8"))
    for path in (
        stage1_manifest, derived_blend, derived_scene_dir / "render_scene.xml",
        derived_scene_dir / "xml_scene_index.json", derived_scene_dir / "render_scene_material_policy.json",
        derived_scene_dir / "material_canonical.json",
    ):
        digest.update(str(path.name).encode("utf-8"))
        digest.update(_sha256(path).encode("ascii"))
    payload = {
        "schema": PROFILE_SCHEMA, "profile_version": PROFILE_VERSION,
        "scene_materializer_contract": SCENE_MATERIALIZER_CONTRACT_VERSION,
        "profile": profile, "source_scene_dir": str(source_scene_dir),
        "source_scene_digest": source_digest, "source_blend": str(source_blend),
        "source_blend_sha256": source_blend_sha256, "derived_scene_dir": str(derived_scene_dir),
        "derived_blend": str(derived_blend), "geometry_digest": digest.hexdigest(),
        "stage1_manifest_ref": str(stage1_manifest), "stage1": stage1_audit,
        "bake_device": {
            "requested": cycles_device,
            "effective": effective_bake_device,
            "fallback": cycles_fallback,
            "fallback_used": bake_fallback_used,
            "assigned_gpu": os.environ.get("ROBOMITUBA_ASSIGNED_BAKE_GPU"),
        },
        "source_structural_domain_ref": str(semantic_domain_path),
        "source_structural_effective_digest": semantic_domain.get("effective_scene_digest"),
        "source_structural_removed_object_glass_shape_ids": (semantic_domain.get("exclusion") or {}).get("removed_object_glass_shape_ids", []),
        "geometry": {
            "decimation": profile, "min_triangles": 50000, "min_faces": 50000,
            "ladder": [0.01, 0.03, 0.10, 0.30], "strict": True,
            "triangle_measurement": True,
            "source_triangles_before_structural_removal": stage1_audit.get("source_triangles_before_structural_removal"),
            "triangles_after_lod": stage1_audit.get("triangles_after_total"),
            "common_geometry": True,
        },
    }
    _atomic_json(profile_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-scene-dir", type=Path, required=True)
    parser.add_argument("--source-blend", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profile", choices=("ir_semantic_lod_v1", "full"), default="ir_semantic_lod_v1")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="reuse and strictly validate completed Stage-1 atlases; bake only missing units")
    parser.add_argument("--finalize-existing", action="store_true",
                        help="validate a fully published Stage 1 and run only Stage 2/profile finalization")
    parser.add_argument("--cycles-device", choices=("CPU", "CUDA", "OPTIX"), default="CPU")
    parser.add_argument("--cycles-fallback", choices=("CPU", "CUDA", "OPTIX"), default="CPU")
    parser.add_argument("--filter-small-high-poly", action="store_true")
    parser.add_argument("--small-high-poly-max-extent-m", type=float, default=0.25)
    parser.add_argument("--small-high-poly-min-triangles", type=int, default=200_000)
    parser.add_argument("--bake-samples", type=int, default=None)
    parser.add_argument("--max-bake-res", type=int, default=None)
    parser.add_argument("--json", action="store_true",
                        help="print the full profile JSON (default prints one concise completion summary)")
    args = parser.parse_args()
    payload = build_profile(args.source_scene_dir, args.source_blend, args.out, profile=args.profile,
                            force=args.force, resume=args.resume,
                            finalize_existing=args.finalize_existing,
                            cycles_device=args.cycles_device, cycles_fallback=args.cycles_fallback,
                            filter_small_high_poly=args.filter_small_high_poly,
                            small_high_poly_max_extent_m=args.small_high_poly_max_extent_m,
                            small_high_poly_min_triangles=args.small_high_poly_min_triangles,
                            bake_samples=args.bake_samples, max_bake_res=args.max_bake_res)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        geometry = dict(payload.get("geometry") or {})
        stage1 = dict(payload.get("stage1") or {})
        print(
            "[ir-lod] profile ready "
            f"profile={payload.get('profile')} digest={str(payload.get('geometry_digest') or '')[:16]} "
            f"units={stage1.get('unit_count', 0)} "
            f"triangles={geometry.get('triangles_after_lod', 'n/a')} "
            f"derived={payload.get('derived_scene_dir')}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
