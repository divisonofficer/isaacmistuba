#!/usr/bin/env python3
"""Validate a 768-SPP physical-polar version against a 1024-SPP reference.

The tool consumes immutable render-version roots, never observation ``current``
pointers.  It is deliberately renderer-independent: both scientific metrics and
the browse-preview metric are recomputed/read from the emitted Stokes products.

Example::

  python tools/validate_polar_profile_cutover.py \
    --reference out/opticalnav/.../versions/rv_1024 \
    --candidate out/opticalnav/.../versions/rv_768 \
    --out out/opticalnav/.../polar_768_gate --require-count 10
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps


LUMA = np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32)
REQUIRED = ("rgb", "s0", "s1", "s2", "s3", "mask")


def _stokes_paths(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("stokes_data.npz"))
    }


def _load(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as source:
        missing = [key for key in REQUIRED if key not in source.files]
        if missing:
            raise ValueError(f"{path} lacks {', '.join(missing)}")
        return {key: np.asarray(source[key]) for key in REQUIRED}


def _derive(data: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    s0 = np.tensordot(data["s0"], LUMA, axes=([2], [0]))
    s1 = np.tensordot(data["s1"], LUMA, axes=([2], [0]))
    s2 = np.tensordot(data["s2"], LUMA, axes=([2], [0]))
    finite = np.isfinite(s0) & np.isfinite(s1) & np.isfinite(s2)
    valid = np.asarray(data["mask"], dtype=bool) & finite
    dop = np.clip(np.sqrt(np.maximum(0.0, s1 * s1 + s2 * s2)) / np.maximum(s0, 1e-8), 0.0, 1.0)
    aolp = np.mod(0.5 * np.arctan2(s2, s1), np.pi)
    return valid, finite, dop, aolp


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Global RGB SSIM, sufficient for a fixed-size preview acceptance gate."""
    x = np.asarray(a, dtype=np.float64) / 255.0
    y = np.asarray(b, dtype=np.float64) / 255.0
    mux, muy = float(x.mean()), float(y.mean())
    vx, vy = float(x.var()), float(y.var())
    cov = float(((x - mux) * (y - muy)).mean())
    c1, c2 = 0.01**2, 0.03**2
    return float(((2 * mux * muy + c1) * (2 * cov + c2)) / ((mux * mux + muy * muy + c1) * (vx + vy + c2)))


def _preview(path: Path) -> np.ndarray:
    preview = path.parent / "polar_rgb_preview.png"
    if not preview.is_file():
        raise FileNotFoundError(f"core preview missing beside {path}")
    with Image.open(preview) as image:
        return np.asarray(image.convert("RGB"))


def _find_timing(path: Path) -> dict[str, float]:
    """Read the nearest bundle timing log, if the version still contains it."""
    for parent in path.parents:
        candidate = parent / "logs" / "render_timing.json"
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if "render_s" in value and (value.get("task") == "polar" or "polar" in str(value.get("scene", "")).lower()):
                    records.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        if records:
            record = records[0]
            return {
                key: float(record[key])
                for key in ("render_s", "stokes_npz_write_s", "preview_write_s", "polar_postprocess_s", "total_s")
                if isinstance(record.get(key), (int, float))
            }
    return {}


def _montage(rows: list[tuple[str, Path, Path]], out: Path) -> None:
    tiles: list[Image.Image] = []
    width, height = 224, 128
    for _key, reference, candidate in rows:
        with Image.open(reference.parent / "polar_rgb_preview.png") as left, Image.open(candidate.parent / "polar_rgb_preview.png") as right:
            left_tile = ImageOps.fit(left.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
            right_tile = ImageOps.fit(right.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
            delta = np.abs(np.asarray(left_tile, dtype=np.int16) - np.asarray(right_tile, dtype=np.int16))
            delta_tile = Image.fromarray(np.clip(delta * 3, 0, 255).astype(np.uint8), "RGB")
            row = Image.new("RGB", (width * 3, height), (0, 0, 0))
            row.paste(left_tile, (0, 0)); row.paste(right_tile, (width, 0)); row.paste(delta_tile, (width * 2, 0))
            tiles.append(row)
    if not tiles:
        return
    canvas = Image.new("RGB", (width * 3, height * len(tiles)), (0, 0, 0))
    for index, tile in enumerate(tiles):
        canvas.paste(tile, (0, height * index))
    canvas.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="1024-SPP immutable render-version root")
    parser.add_argument("--candidate", type=Path, required=True, help="768-SPP immutable render-version root")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-views", type=int, default=10)
    parser.add_argument("--require-count", type=int, default=10)
    args = parser.parse_args()

    reference = _stokes_paths(args.reference.resolve())
    candidate = _stokes_paths(args.candidate.resolve())
    shared = sorted(set(reference) & set(candidate))[: max(0, args.max_views)]
    if len(shared) < args.require_count:
        raise SystemExit(f"need at least {args.require_count} matched Stokes frames; found {len(shared)}")

    rows: list[dict[str, Any]] = []
    all_dop: list[np.ndarray] = []
    all_aolp: list[np.ndarray] = []
    valid_mismatch = 0
    finite_mismatch = 0
    preview_scores: list[float] = []
    montage_rows: list[tuple[str, Path, Path]] = []
    reference_timing: list[dict[str, float]] = []
    candidate_timing: list[dict[str, float]] = []

    for key in shared:
        ref_data, candidate_data = _load(reference[key]), _load(candidate[key])
        if any(ref_data[name].shape != candidate_data[name].shape for name in REQUIRED):
            raise SystemExit(f"shape mismatch: {key}")
        ref_valid, ref_finite, ref_dop, ref_aolp = _derive(ref_data)
        new_valid, new_finite, new_dop, new_aolp = _derive(candidate_data)
        valid_mismatch += int(np.count_nonzero(ref_valid != new_valid))
        finite_mismatch += int(np.count_nonzero(ref_finite != new_finite))
        common = ref_valid & new_valid
        if not np.any(common):
            raise SystemExit(f"no common valid pixels: {key}")
        dop_error = np.abs(ref_dop[common] - new_dop[common])
        angle_mask = common & (ref_dop >= 0.1) & (new_dop >= 0.1)
        angle_error = np.abs(((ref_aolp[angle_mask] - new_aolp[angle_mask] + np.pi / 2) % np.pi) - np.pi / 2)
        angle_error = np.degrees(angle_error)
        ref_preview, new_preview = _preview(reference[key]), _preview(candidate[key])
        if ref_preview.shape != new_preview.shape:
            raise SystemExit(f"preview shape mismatch: {key}")
        score = _ssim(ref_preview, new_preview)
        preview_scores.append(score)
        all_dop.append(dop_error); all_aolp.append(angle_error)
        reference_timing.append(_find_timing(reference[key])); candidate_timing.append(_find_timing(candidate[key]))
        rows.append({
            "frame": key,
            "preview_ssim": score,
            "dolp_mae": float(dop_error.mean()),
            "dolp_p95": float(np.quantile(dop_error, 0.95)),
            "aolp_circular_mae_deg": float(angle_error.mean()) if angle_error.size else 0.0,
            "aolp_circular_p95_deg": float(np.quantile(angle_error, 0.95)) if angle_error.size else 0.0,
            "valid_pixels": int(common.sum()),
        })
        montage_rows.append((key, reference[key], candidate[key]))

    dop = np.concatenate(all_dop)
    aolp = np.concatenate([item for item in all_aolp if item.size]) if any(item.size for item in all_aolp) else np.empty(0)
    metrics = {
        "matched_frames": len(shared),
        "valid_mask_mismatch_pixels": valid_mismatch,
        "finite_mask_mismatch_pixels": finite_mismatch,
        "preview_ssim_min": min(preview_scores),
        "preview_ssim_mean": float(np.mean(preview_scores)),
        "dolp_mae": float(dop.mean()),
        "dolp_p95": float(np.quantile(dop, 0.95)),
        "aolp_circular_mae_deg": float(aolp.mean()) if aolp.size else 0.0,
        "aolp_circular_p95_deg": float(np.quantile(aolp, 0.95)) if aolp.size else 0.0,
    }
    gate = {
        "finite_valid_masks": valid_mismatch == 0 and finite_mismatch == 0,
        "preview_ssim": metrics["preview_ssim_min"] >= 0.97,
        "dolp": metrics["dolp_mae"] <= 0.03 and metrics["dolp_p95"] <= 0.12,
        "aolp": metrics["aolp_circular_mae_deg"] <= 6.0 and metrics["aolp_circular_p95_deg"] <= 20.0,
    }
    payload = {
        "schema": "opticalnav.polar_profile_cutover_gate.v1",
        "reference_root": str(args.reference.resolve()),
        "candidate_root": str(args.candidate.resolve()),
        "thresholds": {"preview_ssim_min": 0.97, "dolp_mae": 0.03, "dolp_p95": 0.12, "aolp_mae_deg": 6.0, "aolp_p95_deg": 20.0},
        "metrics": metrics,
        "gate": {**gate, "passed": all(gate.values())},
        "rows": rows,
        "timing": {"reference": reference_timing, "candidate": candidate_timing},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "polar_profile_cutover.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _montage(montage_rows, args.out / "preview_montage.png")
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row[key]))}</td>" for key in ("frame", "preview_ssim", "dolp_mae", "dolp_p95", "aolp_circular_mae_deg", "aolp_circular_p95_deg")) + "</tr>"
        for row in rows
    )
    (args.out / "polar_profile_cutover.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Polar profile cutover gate</title>"
        "<style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px}img{max-width:100%}</style>"
        f"<h1>1024 → 768 physical-polar gate: {'PASS' if payload['gate']['passed'] else 'FAIL'}</h1>"
        f"<pre>{html.escape(json.dumps(metrics, ensure_ascii=False, indent=2))}</pre>"
        "<p>Montage columns: 1024 reference · 768 candidate · 3× absolute preview delta.</p><img src='preview_montage.png'>"
        "<table><tr><th>frame</th><th>SSIM</th><th>DoLP MAE</th><th>DoLP p95</th><th>AoLP MAE°</th><th>AoLP p95°</th></tr>"
        f"{html_rows}</table>",
        encoding="utf-8",
    )
    print(json.dumps(payload["gate"], ensure_ascii=False))
    return 0 if payload["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
