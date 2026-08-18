#!/usr/bin/env python3
"""Compare a completed reduced-SPP IR cohort against published 4000-SPP frames."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import cv2
import imageio.v3 as iio
import numpy as np
from PIL import Image


LUMA = np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32)


def _read(path: Path) -> np.ndarray:
    values = np.asarray(iio.imread(path), dtype=np.float32)
    return values[..., :3] if values.ndim == 3 and values.shape[-1] > 3 else values


def _metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    if reference.shape != candidate.shape:
        raise RuntimeError(f"shape mismatch: {reference.shape} vs {candidate.shape}")
    error = candidate - reference
    rmse = float(np.sqrt(np.mean(error * error)))
    peak = float(np.quantile(np.abs(reference), 0.999))
    return {
        "mae": float(np.mean(np.abs(error))), "rmse": rmse,
        "psnr_p999_db": float(20.0 * np.log10(peak / rmse)) if peak > 0 and rmse > 0 else float("inf"),
    }


def _stats(values: np.ndarray) -> dict[str, float]:
    y = values @ LUMA if values.ndim == 3 else values
    return {name: float(value) for name, value in {
        "mean": y.mean(), "p95": np.percentile(y, 95), "max": y.max(),
    }.items()}


def _preview_rgb(path: Path, values: np.ndarray, *, exposure: float = 3.0) -> None:
    x = values if values.ndim == 3 else np.repeat(values[..., None], 3, axis=-1)
    mapped = np.clip((x * exposure) / (1 + x * exposure), 0, 1)
    mapped = np.where(mapped <= 0.0031308, mapped * 12.92, 1.055 * np.power(mapped, 1 / 2.4) - 0.055)
    Image.fromarray(np.round(mapped * 255).astype(np.uint8), "RGB").save(path)


def _preview_error(path: Path, reference: np.ndarray, candidate: np.ndarray) -> None:
    error = np.mean(np.abs(reference - candidate), axis=-1) if reference.ndim == 3 else np.abs(reference - candidate)
    image = cv2.applyColorMap(np.round(np.clip(error / 0.02, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), "RGB").save(path)


def _aggregate(rows: list[dict], modality: str, key: str) -> dict[str, float] | None:
    values = np.asarray([
        row["metrics"][modality][key]
        for row in rows if row["metrics"].get(modality) is not None
    ], dtype=np.float64)
    if not len(values):
        return None
    return {"mean": float(values.mean()), "median": float(np.median(values)), "p95": float(np.percentile(values, 95))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True, help="IR root containing chunks/chunk_*/.render_batch_000")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--expected-frames", type=int, required=True)
    args = parser.parse_args()

    candidate_frames = sorted(args.candidate_dir.glob("vp_*/frame.json"))
    if len(candidate_frames) != args.expected_frames:
        raise RuntimeError(f"candidate cohort incomplete: expected {args.expected_frames}, found {len(candidate_frames)}")
    args.assets.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for frame_json in candidate_frames:
        candidate_dir = frame_json.parent
        frame_id = candidate_dir.name
        references = list(args.reference_root.glob(f"chunks/chunk_*/.render_batch_000/{frame_id}"))
        if len(references) != 1:
            raise RuntimeError(f"reference resolution for {frame_id}: expected one, found {len(references)}")
        reference_dir = references[0]
        candidate_record = json.loads(frame_json.read_text(encoding="utf-8"))
        values = {}
        metric = {}
        for modality, filename in (("rgb", "rgb.exr"), ("nir_ambient", "nir_ambient.exr")):
            reference = _read(reference_dir / filename)
            candidate = _read(candidate_dir / filename)
            values[modality] = (reference, candidate)
            metric[modality] = _metrics(reference, candidate)
        # The production batch publishes RGB/ambient before its direct pass.
        # Do not turn that legitimate partial reference into a failed cohort:
        # keep candidate direct timing now and attach direct quality later.
        direct_name = "nir_flash_direct.exr"
        reference_direct = reference_dir / direct_name
        candidate_direct = candidate_dir / direct_name
        if reference_direct.is_file() and candidate_direct.is_file():
            reference = _read(reference_direct)
            candidate = _read(candidate_direct)
            values["nir_flash_direct"] = (reference, candidate)
            metric["nir_flash_direct"] = _metrics(reference, candidate)
        else:
            metric["nir_flash_direct"] = None
        prefix = frame_id
        _preview_rgb(args.assets / f"{prefix}__reference.png", values["rgb"][0])
        _preview_rgb(args.assets / f"{prefix}__candidate.png", values["rgb"][1])
        _preview_error(args.assets / f"{prefix}__error.png", values["rgb"][0], values["rgb"][1])
        rows.append({
            "frame_id": frame_id, "reference_dir": str(reference_dir), "candidate_dir": str(candidate_dir),
            "reference_rgb_luminance": _stats(values["rgb"][0]), "candidate_rgb_luminance": _stats(values["rgb"][1]),
            "metrics": metric, "timings_s": candidate_record["render_timings_s"],
        })
    summary = {
        "frames": len(rows),
        "rgb": {key: _aggregate(rows, "rgb", key) for key in ("mae", "rmse", "psnr_p999_db")},
        "nir_ambient": {key: _aggregate(rows, "nir_ambient", key) for key in ("mae", "rmse", "psnr_p999_db")},
        "nir_flash_direct": {key: _aggregate(rows, "nir_flash_direct", key) for key in ("mae", "rmse", "psnr_p999_db")},
        "timings_s": {
            pass_name: {
                "mean_mi_render_s": float(np.mean([row["timings_s"][pass_name]["mi_render_s"] for row in rows])),
                "p95_mi_render_s": float(np.percentile([row["timings_s"][pass_name]["mi_render_s"] for row in rows], 95)),
            }
            for pass_name in ("rgb", "nir_ambient", "nir_flash_direct")
        },
    }
    payload = {"schema": "ir_sampling_cohort_comparison_v1", "candidate_dir": str(args.candidate_dir), "summary": summary, "frames": rows}
    (args.candidate_dir / "cohort_analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    asset_prefix = args.assets.relative_to(args.report.parent).as_posix()
    def img(name: str, caption: str) -> str:
        return f'<figure><img src="{asset_prefix}/{name}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>'
    html_rows = []
    image_sections = []
    for row in rows:
        timing = row["timings_s"]
        html_rows.append(
            "<tr><td><code>{}</code></td><td>{:.4f}</td><td>{:.4f}</td><td>{:.2f}</td><td>{:.2f}/{:.2f}/{:.2f}</td></tr>".format(
                row["frame_id"], row["metrics"]["rgb"]["mae"], row["metrics"]["rgb"]["rmse"], row["metrics"]["rgb"]["psnr_p999_db"],
                timing["rgb"]["mi_render_s"], timing["nir_ambient"]["mi_render_s"], timing["nir_flash_direct"]["mi_render_s"],
            )
        )
        frame_id = row["frame_id"]
        image_sections.append("<section><h3>{}</h3><div class=grid>{}{}{}</div></section>".format(
            frame_id,
            img(f"{frame_id}__reference.png", "4000-SPP RGB reference"),
            img(f"{frame_id}__candidate.png", "reduced-pass-Spp RGB"),
            img(f"{frame_id}__error.png", "absolute RGB error (0.02 full scale)"),
        ))
    rgb = summary["rgb"]
    time_summary = summary["timings_s"]
    report = f"""<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>IR bright 10-view sampling cohort</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:1450px;margin:auto;padding:28px;background:#f5f6f8;color:#18202a}} h2{{margin-top:36px}} h3{{margin-top:28px}} .summary{{background:#fff;border-left:4px solid #287e55;padding:15px 18px;border-radius:6px;line-height:1.6}} table{{border-collapse:collapse;width:100%;background:#fff}}th,td{{border:1px solid #dce3eb;padding:8px;text-align:left}}th{{background:#edf2f7}}code{{background:#e9eef4;padding:2px 5px;border-radius:3px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}figure{{margin:0;background:#fff;border:1px solid #dce3eb;border-radius:7px;overflow:hidden}}img{{width:100%;display:block;background:#111}}figcaption{{font-size:12px;padding:7px;color:#536273}}.note{{color:#596878}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}</style></head><body>
<h1>IR sampling: bright 10-view cohort</h1><p class=note>Reference: published 684×512 4000-SPP sweep. Candidate: same geometry, pose and resolution; RGB 1000 / NIR ambient 750 / NIR direct 384; max depth 8.</p>
<div class=summary><b>Aggregate RGB:</b> MAE mean/median/p95 <code>{rgb['mae']['mean']:.6f}</code> / <code>{rgb['mae']['median']:.6f}</code> / <code>{rgb['mae']['p95']:.6f}</code>; PSNR(p99.9 reference) mean/median/p95 <code>{rgb['psnr_p999_db']['mean']:.2f}</code> / <code>{rgb['psnr_p999_db']['median']:.2f}</code> / <code>{rgb['psnr_p999_db']['p95']:.2f} dB</code>.</div>
<p class=note>These candidate wall times were collected while a production sweep shared the GPU; they are frame-comparable but not GPU-attributable throughput figures. Use the exclusive benchmark runner for that decision.</p>
<h2>Per-frame quality and synchronized render time</h2><table><thead><tr><th>frame</th><th>RGB MAE</th><th>RGB RMSE</th><th>RGB PSNR</th><th>RGB / ambient / direct mi.render s</th></tr></thead><tbody>{''.join(html_rows)}</tbody></table>
<h2>Pass timing distribution</h2><table><thead><tr><th>pass</th><th>mean mi.render s</th><th>p95 mi.render s</th></tr></thead><tbody>{''.join(f'<tr><td>{name}</td><td>{values["mean_mi_render_s"]:.3f}</td><td>{values["p95_mi_render_s"]:.3f}</td></tr>' for name, values in time_summary.items())}</tbody></table>
<h2>Visual comparisons</h2>{''.join(image_sections)}
</body></html>"""
    args.report.write_text(report, encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
