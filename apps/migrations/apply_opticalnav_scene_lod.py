#!/usr/bin/env python3
"""Apply the IR semantic LOD ladder to one existing OpticalNav Infinigen scene.

The migration is deliberately source-preserving: full-resolution GLBs stay in the
import snapshot, while UV/material-preserving meshoptimizer GLBs are written below
the scene directory and authoring_map.json is atomically redirected to them.  Tiny
pathological shelf decorations are removed instead of spending a BVH budget on
them.  A timestamped authoring-map backup makes the operation reversible.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT = "opticalnav-v0.2"
MIN_TRIANGLES = 50_000
TINY_MAX_EXTENT_M = 0.15
TINY_MIN_TRIANGLES = 250_000
TINY_FACTORY = "NatureShelfTrinketsFactory"
GLTFPACK_POLICY_VERSION = "ir_semantic_lod_gltfpack_v2_no_se1"


def _ratio(triangles: int) -> float:
    if triangles >= 5_000_000:
        return 0.01
    if triangles >= 1_000_000:
        return 0.03
    if triangles >= 250_000:
        return 0.10
    return 0.30


def _tiny_decoration(unit: dict[str, Any]) -> bool:
    dimensions = unit.get("dimensions") or unit.get("place_size_m") or []
    try:
        extent = max(float(value) for value in dimensions)
    except (TypeError, ValueError):
        return False
    return (
        str(unit.get("factory") or "") == TINY_FACTORY
        and str(unit.get("semantic_type") or "") == "shelf"
        and extent <= TINY_MAX_EXTENT_M
        and int(unit.get("triangles") or 0) >= TINY_MIN_TRIANGLES
    )


def _glb_triangles(path: Path) -> int:
    with path.open("rb") as stream:
        magic, version, _length = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2:
            raise ValueError(f"not a GLB v2 file: {path}")
        json_length, json_type = struct.unpack("<II", stream.read(8))
        if json_type != 0x4E4F534A:
            raise ValueError(f"GLB has no JSON first chunk: {path}")
        document = json.loads(stream.read(json_length))
    accessors = document.get("accessors") or []
    total = 0
    for mesh in document.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            mode = int(primitive.get("mode", 4))
            if mode not in {4, 5, 6}:
                continue
            index = primitive.get("indices")
            if isinstance(index, int) and 0 <= index < len(accessors):
                count = int(accessors[index].get("count") or 0)
            else:
                attrs = primitive.get("attributes") or {}
                position = attrs.get("POSITION")
                if isinstance(position, int) and 0 <= position < len(accessors):
                    count = int(accessors[position].get("count") or 0)
                else:
                    count = 0
            total += count // 3 if mode == 4 else max(0, count - 2)
    return total


def _source_path(obj: dict[str, Any]) -> Path:
    metadata = obj.get("metadata") or {}
    value = metadata.get("source_ref_full") or metadata.get("glb_ref") or obj.get("source_ref")
    path = Path(str(value or ""))
    return path if path.is_absolute() else REPO_ROOT / path


def _build_one(job: dict[str, Any], *, gltfpack: Path, cache_dir: Path) -> dict[str, Any]:
    source = Path(job["source"])
    digest = hashlib.sha256(
        (GLTFPACK_POLICY_VERSION + "\0" + str(source.resolve()) + f"\0{job['ratio']:.6f}").encode()
    ).hexdigest()[:20]
    output = cache_dir / f"{digest}_r{int(round(job['ratio'] * 100)):02d}.glb"
    if output.is_file() and output.stat().st_size > 0:
        actual = _glb_triangles(output)
        if 0 < actual < int(job["triangles"]):
            return {**job, "output": str(output), "actual_triangles": actual, "cached": True}
    temporary = output.with_suffix(f".tmp.{os.getpid()}.glb")
    command = [
        str(gltfpack), "-i", str(source), "-o", str(temporary),
        "-si", f"{job['ratio']:.9f}", "-sa",
        "-noq", "-km", "-kn", "-kv", "-vpf", "-vtf", "-vnf",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if completed.returncode or not temporary.is_file():
        detail = (completed.stderr or completed.stdout or "no output").strip()
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"gltfpack failed for {job['object_id']}: {detail[-800:]}")
    actual = _glb_triangles(temporary)
    if actual <= 0 or actual >= int(job["triangles"]):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"gltfpack did not reduce {job['object_id']}: {job['triangles']} -> {actual}"
        )
    os.replace(temporary, output)
    return {**job, "output": str(output), "actual_triangles": actual, "cached": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--texture-max-resolution", type=int, default=512,
        help="scene texture cap (256 is the safe default for spectral-polarized RTX 3090 rendering)",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--gltfpack", type=Path, default=Path("/root/robomituba-build/meshoptimizer/gltfpack"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    scene_dir = REPO_ROOT / "out" / "opticalnav" / args.project / "scenes" / args.scene
    authoring_path = scene_dir / "authoring_map.json"
    authoring = json.loads(authoring_path.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    units = {str(unit.get("id")): unit for unit in manifest.get("units") or []}
    objects = list(authoring.get("objects") or [])
    tiny_ids = {
        str(obj.get("id")) for obj in objects
        if (unit := units.get(str(obj.get("id")))) is not None and _tiny_decoration(unit)
    }
    jobs: list[dict[str, Any]] = []
    for obj in objects:
        object_id = str(obj.get("id") or "")
        unit = units.get(object_id)
        if unit is None or object_id in tiny_ids:
            continue
        triangles = int(unit.get("triangles") or 0)
        if triangles < MIN_TRIANGLES or not obj.get("source_ref"):
            continue
        source = _source_path(obj)
        if not source.is_file() or source.suffix.lower() != ".glb":
            raise FileNotFoundError(f"LOD source is not a GLB for {object_id}: {source}")
        jobs.append({
            "object_id": object_id, "source": str(source),
            "triangles": triangles, "ratio": _ratio(triangles),
        })

    tiny_triangles = sum(int(units[oid].get("triangles") or 0) for oid in tiny_ids)
    estimated = sum(max(1, round(job["triangles"] * job["ratio"])) for job in jobs)
    print(
        f"scene={args.scene} objects={len(objects)} tiny_drop={len(tiny_ids)} "
        f"tiny_triangles={tiny_triangles:,} lod_jobs={len(jobs)} "
        f"lod_triangles={sum(j['triangles'] for j in jobs):,}->{estimated:,} "
        f"texture=max{args.texture_max_resolution}", flush=True,
    )
    if not args.apply:
        print("dry-run only; pass --apply to materialize LOD GLBs and update authoring_map.json")
        return 0
    if not args.gltfpack.is_file() or not os.access(args.gltfpack, os.X_OK):
        raise FileNotFoundError(f"gltfpack is unavailable: {args.gltfpack}")

    cache_dir = scene_dir / "lod_glb_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(_build_one, job, gltfpack=args.gltfpack, cache_dir=cache_dir): job
            for job in jobs
        }
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            results[result["object_id"]] = result
            if index % 10 == 0 or index == len(futures):
                print(f"[lod] {index}/{len(futures)}", flush=True)

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = scene_dir / "manual_backups" / f"{timestamp}_scene_lod"
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(authoring_path, backup_dir / "authoring_map.json")
    retained: list[dict[str, Any]] = []
    for obj in objects:
        object_id = str(obj.get("id") or "")
        if object_id in tiny_ids:
            continue
        result = results.get(object_id)
        if result is not None:
            metadata = dict(obj.get("metadata") or {})
            metadata.setdefault("source_ref_full", obj.get("source_ref"))
            output = Path(result["output"])
            ref = output.relative_to(REPO_ROOT).as_posix()
            obj["source_ref"] = ref
            metadata["glb_ref"] = ref
            metadata["geometry_lod"] = {
                "policy": "ir_semantic_lod_v1",
                "backend": "meshoptimizer_gltfpack",
                "triangles_before": result["triangles"],
                "triangles_after": result["actual_triangles"],
                "target_ratio": result["ratio"],
            }
            obj["metadata"] = metadata
        retained.append(obj)
    authoring["objects"] = retained
    settings = dict(authoring.get("settings") or {})
    settings["render_texture_max_resolution"] = int(args.texture_max_resolution)
    authoring["settings"] = settings
    metadata = dict(authoring.get("metadata") or {})
    metadata["scene_geometry_profile"] = {
        "policy": "ir_semantic_lod_v1",
        "applied_at": timestamp,
        "tiny_objects_removed": len(tiny_ids),
        "tiny_triangles_removed": tiny_triangles,
        "lod_objects": len(results),
        "triangles_before": sum(result["triangles"] for result in results.values()),
        "triangles_after": sum(result["actual_triangles"] for result in results.values()),
        "texture_max_resolution": int(args.texture_max_resolution),
        "backup": str(backup_dir.relative_to(REPO_ROOT)),
    }
    authoring["metadata"] = metadata
    temporary = authoring_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(authoring, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, authoring_path)
    report = metadata["scene_geometry_profile"] | {
        "scene": args.scene,
        "removed_object_ids": sorted(tiny_ids),
        "lod_records": [results[key] for key in sorted(results)],
    }
    (scene_dir / "scene_geometry_profile.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"applied: objects {len(objects)}->{len(retained)}, triangles "
        f"{sum(r['triangles'] for r in results.values()):,}->"
        f"{sum(r['actual_triangles'] for r in results.values()):,}; backup={backup_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
