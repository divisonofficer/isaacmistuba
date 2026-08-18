#!/usr/bin/env python3
"""Compile an untextured, Y-up GLB proxy for the IR dataset 3D overview."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLENDER_LAUNCHER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
PROXY_SCRIPT = REPO_ROOT / "tools" / "infinigen" / "blender_export_ir_overview_proxy.py"
SCHEMA = "robomituba.ir_scene_overview_proxy.v1"
COMPILER_VERSION = "ir-scene-overview-proxy-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry-profile-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--triangle-target", type=int, default=25_000)
    parser.add_argument("--triangle-cap", type=int, default=50_000)
    return parser.parse_args()


def main() -> int:
    args = _args()
    if args.triangle_target < 1_000 or args.triangle_target > args.triangle_cap or args.triangle_cap > 50_000:
        raise ValueError("triangle target/cap must satisfy 1000 <= target <= cap <= 50000")
    profile_dir = args.geometry_profile_dir.resolve()
    profile = json.loads((profile_dir / "ir_geometry_profile.json").read_text(encoding="utf-8"))
    blend = Path(str(profile.get("derived_blend") or profile_dir / "derived_ir_semantic_lod.blend")).resolve()
    manifest = profile_dir / "stage1" / "scene_manifest.json"
    if not blend.is_file() or not manifest.is_file():
        raise FileNotFoundError("overview proxy requires a published Stage 1 blend and manifest")
    out = args.out.resolve()
    if out.exists():
        existing = out / "overview_proxy_manifest.json"
        if existing.is_file():
            payload = json.loads(existing.read_text(encoding="utf-8"))
            if (payload.get("compiler_version") == COMPILER_VERSION
                    and payload.get("source_geometry_digest") == profile.get("geometry_digest")
                    and int(payload.get("triangle_target") or 0) == args.triangle_target
                    and int(payload.get("triangle_cap") or 0) == args.triangle_cap
                    and (out / "overview_proxy.glb").is_file()):
                print(f"[overview-proxy] reuse verified proxy: {out}")
                return 0
        raise RuntimeError("existing overview proxy does not match Stage 1; choose a new output directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging-", dir=out.parent))
    try:
        summary = staging / "overview_proxy_manifest.json"
        command = [sys.executable, str(BLENDER_LAUNCHER), "--background", str(blend), "--python", str(PROXY_SCRIPT), "--",
                   "--stage1-manifest", str(manifest), "--out", str(staging / "overview_proxy.glb"),
                   "--summary", str(summary), "--triangle-target", str(args.triangle_target),
                   "--triangle-cap", str(args.triangle_cap)]
        print("[overview-proxy] $ " + " ".join(command), flush=True)
        if subprocess.run(command, cwd=REPO_ROOT).returncode:
            return 1
        if not summary.is_file():
            raise RuntimeError("Blender overview proxy exporter exited without a summary")
        payload = json.loads(summary.read_text(encoding="utf-8"))
        proxy = staging / "overview_proxy.glb"
        if payload.get("schema") != SCHEMA or not proxy.is_file() or int(payload.get("triangles") or 0) > args.triangle_cap:
            raise RuntimeError("overview proxy exporter produced an invalid proxy")
        payload.update({"compiler_version": COMPILER_VERSION, "source_geometry_digest": profile.get("geometry_digest"),
                        "source_stage1_manifest_sha256": _sha256(manifest), "glb_sha256": _sha256(proxy),
                        "byte_count": proxy.stat().st_size, "triangle_target": args.triangle_target,
                        "triangle_cap": args.triangle_cap})
        summary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(staging, out)
        print(f"[overview-proxy] ready triangles={payload['triangles']} -> {out}")
        return 0
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    raise SystemExit(main())
