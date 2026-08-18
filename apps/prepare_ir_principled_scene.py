#!/usr/bin/env python3
"""Build the immutable Blender Stage-2 scene for RGB/active-NIR rendering."""
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

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
NAV_SRC = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(NAV_SRC) not in sys.path:
    sys.path.insert(0, str(NAV_SRC))

from navigation_dataset.ir_principled import (  # noqa: E402
    MATERIAL_CONTRACT_SCHEMA, MATERIAL_CONTRACT_VERSION, STAGE2_COMPILER_VERSION,
    files_digest, matched_luminance_coefficients,
)


BLENDER_LAUNCHER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
PREPARE_SCRIPT = REPO_ROOT / "tools" / "infinigen" / "blender_prepare_ir_principled.py"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geometry-profile-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--flash-energy", type=float, default=40.0)
    parser.add_argument("--flash-reference-multiple", type=float, default=100.0)
    parser.add_argument("--flash-offset-y", type=float, default=-0.10)
    parser.add_argument("--flash-beam-width", type=float, default=22.0)
    parser.add_argument("--flash-cutoff-angle", type=float, default=30.0)
    parser.add_argument("--ambient-fill-energy", type=float, default=30.0)
    parser.add_argument("--ambient-fill-coverage", type=float, default=0.12)
    parser.add_argument("--ambient-fill-min-size", type=float, default=0.8)
    parser.add_argument("--ambient-fill-max-size", type=float, default=2.2)
    parser.add_argument("--ambient-fill-ceiling-gap", type=float, default=0.10)
    parser.add_argument("--illumination-manifest", type=Path)
    parser.add_argument("--structural-material-manifest", type=Path,
                        help="immutable external-PBR overlay for an independent rematerialized scene")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _validate_output(directory: Path) -> dict:
    blend = directory / "derived_ir_principled_v1.blend"
    contract_path = directory / "principled_material_contract.json"
    if not blend.is_file() or not contract_path.is_file():
        raise RuntimeError(f"incomplete Principled Stage 2: {directory}")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema") != MATERIAL_CONTRACT_SCHEMA:
        raise RuntimeError(f"unexpected material contract schema: {contract.get('schema')!r}")
    if contract.get("contract_version") != MATERIAL_CONTRACT_VERSION:
        raise RuntimeError(f"unexpected material contract version: {contract.get('contract_version')!r}")
    if contract.get("compiler_version") != STAGE2_COMPILER_VERSION:
        raise RuntimeError(f"unexpected Stage 2 compiler version: {contract.get('compiler_version')!r}")
    if not contract.get("materials"):
        raise RuntimeError("Principled Stage 2 contains no material records")
    required_effective = {
        "base_color_rgb", "base_color_nir", "roughness", "metallic",
        "normal_geometry_world", "normal_shading_world",
    }
    for record in contract["materials"]:
        effective = record.get("effective_inputs")
        if not isinstance(effective, dict) or set(effective) != required_effective:
            raise RuntimeError("Principled Stage 2 material lacks the effective-input audit")
        if not all(isinstance(effective[name], dict) and effective[name].get("route") for name in required_effective):
            raise RuntimeError("Principled Stage 2 material has an invalid effective-input audit")
    if not isinstance(contract.get("aov_semantics"), dict):
        raise RuntimeError("Principled Stage 2 lacks the v2 AOV semantics audit")
    return contract


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _luminance_ablation(stage1_dir: Path) -> tuple[dict[str, float], str]:
    """Fit the documented alternate formula on deterministic atlas samples."""
    texture_paths: set[Path] = set()
    for state_path in sorted((stage1_dir / ".stage1_unit_state").glob("*.json")):
        state = json.loads(state_path.read_text(encoding="utf-8"))
        channel = ((state.get("pbr") or {}).get("channels") or {}).get("base_color") or {}
        artifact = (state.get("artifacts") or {}).get("base_color") or channel.get("ref")
        if artifact:
            path = (stage1_dir / str(artifact)).resolve()
            if path.is_file():
                texture_paths.add(path)
    samples = []
    for path in sorted(texture_paths):
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RuntimeError(f"cannot decode Stage-1 base-color atlas: {path}")
        if image.ndim == 2:
            image = np.repeat(image[..., None], 3, axis=2)
        image = image[..., :3][..., ::-1]
        maximum = float(np.iinfo(image.dtype).max) if np.issubdtype(image.dtype, np.integer) else 1.0
        srgb = np.clip(image.astype(np.float32) / maximum, 0.0, 1.0)
        linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
        sample = cv2.resize(linear, (32, 32), interpolation=cv2.INTER_AREA)
        samples.append(sample.reshape(-1, 3))
    if not samples:
        samples.append(np.asarray([[0.5, 0.5, 0.5]], dtype=np.float32))
        corpus_digest = "no-atlas-neutral-reference"
    else:
        corpus_digest = files_digest(sorted(texture_paths), root=stage1_dir)
    return matched_luminance_coefficients(np.concatenate(samples, axis=0)), corpus_digest


def main() -> int:
    args = _args()
    if args.flash_energy <= 0 or args.flash_reference_multiple <= 0 or args.ambient_fill_energy <= 0:
        raise ValueError("flash and ambient-fill energy parameters must be positive")
    if not 0 < args.ambient_fill_coverage <= 0.5:
        raise ValueError("ambient-fill coverage must be in (0, 0.5]")
    profile_dir = args.geometry_profile_dir.resolve()
    profile_path = profile_dir / "ir_geometry_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    source_blend = Path(str(profile.get("derived_blend") or profile_dir / "derived_ir_semantic_lod.blend")).resolve()
    stage1_dir = profile_dir / "stage1"
    semantic = profile_dir / "source_structural_domain" / "specular_semantic_regions.json"
    derived_scene_dir = Path(str(profile.get("derived_scene_dir") or "")).resolve()
    room_manifest = derived_scene_dir / "authoring_map.json"
    for required in (source_blend, stage1_dir / "scene_manifest.json"):
        if not required.exists():
            raise FileNotFoundError(required)

    out = args.out.resolve()
    illumination_sha = _sha256(args.illumination_manifest.resolve()) if args.illumination_manifest else None
    structural_sha = _sha256(args.structural_material_manifest.resolve()) if args.structural_material_manifest else None
    if out.exists() and not args.force:
        contract = _validate_output(out)
        digest_paths = [stage1_dir / "scene_manifest.json", *sorted((stage1_dir / ".stage1_unit_state").glob("*.json"))]
        if semantic.is_file():
            digest_paths.append(semantic)
        if room_manifest.is_file():
            digest_paths.append(room_manifest)
        expected_stage1_digest = files_digest(digest_paths)
        if (
            contract.get("stage1_contract_digest") == expected_stage1_digest
            and contract.get("source_blend_sha256") == _sha256(source_blend)
            and contract.get("illumination_manifest_sha256") == illumination_sha
            and contract.get("structural_rematerialization_sha256") == structural_sha
        ):
            print(f"[ir-principled] reuse verified Stage 2: {out}")
            return 0
        raise RuntimeError(
            f"existing Stage 2 does not match current Stage 1 inputs: {out}; choose a new --out"
        )
    if out.exists() and args.force:
        raise RuntimeError(
            "--force does not delete an existing Stage 2 directory; choose a new --out or move it aside explicitly"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    luminance_coefficients, luminance_corpus_digest = _luminance_ablation(stage1_dir)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging-", dir=out.parent))
    try:
        command = [
            sys.executable, str(BLENDER_LAUNCHER), "--background", str(source_blend),
            "--python", str(PREPARE_SCRIPT), "--",
            "--stage1-dir", str(stage1_dir),
            "--out-blend", str(staging / "derived_ir_principled_v1.blend"),
            "--out-contract", str(staging / "principled_material_contract.json"),
            "--flash-energy", str(args.flash_energy),
            "--flash-reference-multiple", str(args.flash_reference_multiple),
            "--flash-offset-y", str(args.flash_offset_y),
            "--flash-beam-width", str(args.flash_beam_width),
            "--flash-cutoff-angle", str(args.flash_cutoff_angle),
            "--ambient-fill-energy", str(args.ambient_fill_energy),
            "--ambient-fill-coverage", str(args.ambient_fill_coverage),
            "--ambient-fill-min-size", str(args.ambient_fill_min_size),
            "--ambient-fill-max-size", str(args.ambient_fill_max_size),
            "--ambient-fill-ceiling-gap", str(args.ambient_fill_ceiling_gap),
            "--luminance-scale", str(luminance_coefficients["scale"]),
            "--luminance-bias", str(luminance_coefficients["bias"]),
            "--luminance-corpus-digest", luminance_corpus_digest,
        ]
        if args.illumination_manifest:
            command.extend(("--illumination-manifest", str(args.illumination_manifest.resolve())))
        if args.structural_material_manifest:
            command.extend(("--structural-material-manifest", str(args.structural_material_manifest.resolve())))
        if semantic.is_file():
            command.extend(("--semantic-regions", str(semantic)))
        if room_manifest.is_file():
            command.extend(("--room-manifest", str(room_manifest)))
        print("[ir-principled] $ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=REPO_ROOT)
        if result.returncode:
            return int(result.returncode)
        contract = _validate_output(staging)
        (staging / "stage2_profile_ref.json").write_text(json.dumps({
            "schema": "robomituba.ir_principled_stage2_profile_ref.v1",
            "geometry_profile": str(profile_path),
            "geometry_digest": profile.get("geometry_digest"),
            "profile": profile.get("profile"),
            "material_contract": contract.get("contract_version"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(staging, out)
        print(f"[ir-principled] Stage 2 ready -> {out}", flush=True)
        return 0
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    raise SystemExit(main())
