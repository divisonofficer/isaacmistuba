#!/usr/bin/env python3
"""Backfill compact polar RGB previews from existing lossless Stokes NPZ files.

This is intentionally a post-processing-only repair: it never invokes
Mitsuba, changes a Stokes value, or generates the retired per-component
diagnostics.  It adds the one human-readable RGB companion required by the
``raw_stokes_aolp_v1`` dataset policy and updates an adjacent observation
manifest atomically when present.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from mitsuba_converter.multimodal import (  # noqa: E402
    _despeckle_dark_preview_pixels,
    _fill_invalid_preview_pixels,
    _rgb_preview_array,
    _save_preview_image,
)


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        Path(tmp_name).unlink(missing_ok=True)


def _preview_from_npz(npz_path: Path, destination: Path) -> dict[str, float]:
    with np.load(npz_path) as source:
        rgb = np.asarray(source["rgb"], dtype=np.float32)
        s0 = np.asarray(source["s0"], dtype=np.float32) if "s0" in source else rgb
    if rgb.ndim != 3 or rgb.shape[-1] != 3:
        raise ValueError(f"{npz_path}: expected RGB array [H,W,3], got {rgb.shape}")
    preview, summary = _rgb_preview_array(rgb, percentile=0.992)
    finite_rgb_mask = np.all(np.isfinite(rgb), axis=2)
    # Match save_polarization_products' neutral S0 context for non-finite RGB.
    s0_l = np.tensordot(np.where(np.isfinite(s0), s0, 0.0), np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axes=([2], [0]))
    positive = s0_l[np.isfinite(s0_l) & (s0_l > 0)]
    scale = max(float(np.quantile(positive, 0.995)) if positive.size else 1.0, 1e-6)
    context = np.clip(np.sqrt(np.clip(s0_l, 0.0, None) / scale), 0.0, 1.0)
    fallback = np.repeat((0.12 + 0.88 * context)[:, :, None], 3, axis=2).astype(np.float32)
    fallback[~np.isfinite(s0_l)] = 0.18
    preview = _fill_invalid_preview_pixels(preview, valid_mask=finite_rgb_mask, fallback_rgb=fallback, max_iterations=8)
    preview = _despeckle_dark_preview_pixels(preview, iterations=3)
    _save_preview_image(preview, destination, blur_radius=0.45)
    return summary


def _patch_manifest(camera_dir: Path, preview_path: Path, *, dry_run: bool) -> bool:
    observation_dir = camera_dir.parent.parent
    manifest_path = observation_dir / "manifest.json"
    if not manifest_path.is_file():
        return False
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = False
    for artifact in document.get("artifacts", []):
        if artifact.get("camera_id") != camera_dir.name or artifact.get("modality") != "polar_rgb_preview":
            continue
        paths = artifact.setdefault("artifact_paths", {})
        if paths.get("png") != str(preview_path):
            paths["png"] = str(preview_path)
            changed = True
        extras = artifact.setdefault("extras", {})
        if extras.get("polar_visualization_policy") == "raw_stokes_aolp_v1":
            derived = extras.get("derived_on_demand")
            if isinstance(derived, list) and "rgb_preview" in derived:
                extras["derived_on_demand"] = [item for item in derived if item != "rgb_preview"]
                changed = True
    if changed and not dry_run:
        _atomic_json_write(manifest_path, document)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="A render version directory, observations directory, or camera directory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate an existing preview")
    args = parser.parse_args()

    root = args.root.resolve()
    candidates = [root] if root.name == "polar_cam" else sorted(root.rglob("polar_cam"))
    written = skipped = manifests = errors = 0
    for camera_dir in candidates:
        npz_path = camera_dir / "stokes_data.npz"
        if not npz_path.is_file():
            continue
        preview_path = camera_dir / "polar_rgb_preview.png"
        try:
            if preview_path.exists() and not args.overwrite:
                skipped += 1
            else:
                if not args.dry_run:
                    _preview_from_npz(npz_path, preview_path)
                written += 1
            manifests += int(_patch_manifest(camera_dir, preview_path, dry_run=args.dry_run))
        except Exception as exc:
            errors += 1
            print(f"ERROR {camera_dir}: {exc}", file=sys.stderr)
    print(json.dumps({"root": str(root), "written": written, "skipped": skipped, "manifest_updates": manifests, "errors": errors}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
