#!/usr/bin/env python3
"""Create a compact visual/timing report for IR sampling-policy experiments.

The report deliberately keeps the float EXR inputs untouched.  Its PNGs are
only fixed-exposure inspection previews, so comparisons are reproducible and
do not become an accidental dataset transform.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import cv2
import imageio.v3 as iio
import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT = REPO_ROOT / "out/ir_dataset/kitchen_structural_specular_lod"
REPORT = REPO_ROOT / "dev_report/report_2026-08-11_ir_sampling_benchmark.html"
ASSETS = REPO_ROOT / "dev_report/images/ir_sampling_benchmark_2026-08-11"
LUMA = np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32)


def read_exr(path: Path) -> np.ndarray:
    values = np.asarray(iio.imread(path), dtype=np.float32)
    if values.ndim == 3 and values.shape[-1] > 3:
        return values[..., :3]
    return values


def luminance(values: np.ndarray) -> np.ndarray:
    return values @ LUMA if values.ndim == 3 else values


def stats(values: np.ndarray) -> dict[str, float]:
    y = luminance(values)
    return {
        "mean": float(y.mean()),
        "p50": float(np.percentile(y, 50)),
        "p95": float(np.percentile(y, 95)),
        "p99": float(np.percentile(y, 99)),
        "max": float(y.max()),
    }


def resize(values: np.ndarray, target_hw: tuple[int, int]) -> np.ndarray:
    h, w = target_hw
    return cv2.resize(values, (w, h), interpolation=cv2.INTER_LANCZOS4)


def compare(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    if reference.shape != candidate.shape:
        candidate = resize(candidate, reference.shape[:2])
    error = candidate - reference
    rmse = float(np.sqrt(np.mean(error * error)))
    peak = float(np.quantile(np.abs(reference), 0.999))
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": rmse,
        "p999_reference": peak,
        "psnr_p999_db": float(20 * np.log10(peak / rmse)) if rmse > 0 and peak > 0 else float("inf"),
    }


def save_rgb_preview(path: Path, values: np.ndarray, *, exposure: float) -> None:
    rgb = values if values.ndim == 3 else np.repeat(values[..., None], 3, axis=-1)
    mapped = np.clip((rgb * exposure) / (1.0 + rgb * exposure), 0.0, 1.0)
    srgb = np.where(mapped <= 0.0031308, mapped * 12.92, 1.055 * np.power(mapped, 1 / 2.4) - 0.055)
    Image.fromarray(np.round(srgb * 255).astype(np.uint8), "RGB").save(path)


def save_scalar_preview(path: Path, values: np.ndarray, *, scale: float, log: bool = False) -> None:
    x = np.maximum(values, 0.0)
    if log:
        mapped = np.log1p(x) / np.log1p(scale)
    else:
        mapped = x / (x + scale)
    Image.fromarray(np.round(np.clip(mapped, 0, 1) * 255).astype(np.uint8), "L").save(path)


def save_error_preview(path: Path, reference: np.ndarray, candidate: np.ndarray) -> None:
    if reference.shape != candidate.shape:
        candidate = resize(candidate, reference.shape[:2])
    delta = np.mean(np.abs(candidate - reference), axis=-1) if reference.ndim == 3 else np.abs(candidate - reference)
    # 0.01 is deliberately fixed, rather than per-image normalisation.
    heat = cv2.applyColorMap(np.round(np.clip(delta / 0.01, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    Image.fromarray(cv2.cvtColor(heat, cv2.COLOR_BGR2RGB), "RGB").save(path)


def load_timing(frame_dir: Path) -> dict:
    path = frame_dir / "frame.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("render_timings_s", {})


def f(value: float) -> str:
    return f"{value:.6g}"


def image(tag: str, label: str) -> str:
    return (
        '<figure><img src="images/ir_sampling_benchmark_2026-08-11/' + html.escape(tag) +
        '.png" alt="' + html.escape(label) + '"><figcaption>' + html.escape(label) + "</figcaption></figure>"
    )


def candidate_row(name: str, frame_dir: Path, resolution: str, spp: str, depth: str) -> tuple[str, dict] | None:
    required = (frame_dir / "rgb.exr", frame_dir / "nir_ambient.exr", frame_dir / "nir_flash_direct.exr")
    if not all(path.exists() for path in required):
        return None
    timing = load_timing(frame_dir)
    total = timing.get("observation_render_total_s")
    pass_times = []
    for pass_name in ("rgb", "nir_ambient", "nir_flash_direct"):
        value = timing.get(pass_name, {}).get("mi_render_s")
        if value is not None:
            pass_times.append(f"{pass_name} {value:.2f}s")
    timing_label = (
        f"{total:.2f} s<br><small>{' · '.join(pass_times)}</small>"
        if total is not None else "not recorded"
    )
    line = (
        "<tr><td>" + html.escape(name) + "</td><td>" + resolution + "</td><td>" + spp +
        "</td><td>" + depth + "</td><td>" + timing_label + "</td></tr>"
    )
    return line, {"dir": frame_dir, "timing": timing, "total": total}


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    dark_reference_dir = ROOT / "chunks/chunk_006/.render_batch_000/vp_000066__h_240"
    bright_reference_dir = ROOT / "chunks/chunk_003/.render_batch_000/vp_000051__h_165"
    highlight_trap_dir = ROOT / "chunks/chunk_003/.render_batch_000/vp_000025__h_345"
    reference = {name: read_exr(dark_reference_dir / name) for name in ("rgb.exr", "nir_ambient.exr")}
    bright = {name: read_exr(bright_reference_dir / name) for name in ("rgb.exr", "nir_ambient.exr")}
    candidates = {
        "Full resolution / reduced pass SPP": candidate_row(
            "Full resolution / reduced pass SPP",
            ROOT / "benchmarks/fullres_r1000_a750_d384_depth8/vp_000066__h_240",
            "684×512", "RGB 1000 · ambient 750 · direct 384", "8",
        ),
        "Fast resolution / reduced SPP & depth": candidate_row(
            "Fast resolution / reduced SPP & depth",
            ROOT / "benchmarks/fast_512x384_r768_a512_d256_depth6/vp_000066__h_240",
            "512×384", "RGB 768 · ambient 512 · direct 256", "6",
        ),
        "Bright-view full-resolution check": candidate_row(
            "Bright-view full-resolution check",
            ROOT / "benchmarks/fullres_bright_r1000_a750_d384_depth8_local/vp_000051__h_165",
            "684×512", "RGB 1000 · ambient 750 · direct 384", "8",
        ),
    }

    save_rgb_preview(ASSETS / "dark_reference_rgb.png", reference["rgb.exr"], exposure=60.0)
    save_scalar_preview(ASSETS / "dark_reference_nir_ambient.png", reference["nir_ambient.exr"], scale=0.01)
    save_rgb_preview(ASSETS / "bright_reference_rgb.png", bright["rgb.exr"], exposure=3.0)
    save_scalar_preview(ASSETS / "bright_reference_nir_ambient.png", bright["nir_ambient.exr"], scale=0.05)

    candidate_html = []
    rows = []
    for name, result in candidates.items():
        if result is None:
            continue
        row, entry = result
        rows.append(row)
        directory: Path = entry["dir"]
        rgb = read_exr(directory / "rgb.exr")
        ambient = read_exr(directory / "nir_ambient.exr")
        direct = read_exr(directory / "nir_flash_direct.exr")
        prefix = "candidate_" + ("fullres" if "Full resolution" in name else "fast" if "Fast" in name else "bright")
        save_rgb_preview(ASSETS / f"{prefix}_rgb.png", rgb, exposure=60.0 if "bright" not in prefix else 3.0)
        save_scalar_preview(ASSETS / f"{prefix}_ambient.png", ambient, scale=0.01 if "bright" not in prefix else 0.05)
        save_scalar_preview(ASSETS / f"{prefix}_direct.png", direct, scale=80.0, log=True)
        target_ref = bright if "bright" in prefix else reference
        rgb_metrics = compare(target_ref["rgb.exr"], rgb)
        ambient_metrics = compare(target_ref["nir_ambient.exr"], ambient)
        if "bright" not in prefix:
            save_error_preview(ASSETS / f"{prefix}_rgb_error.png", target_ref["rgb.exr"], rgb)
            save_error_preview(ASSETS / f"{prefix}_ambient_error.png", target_ref["nir_ambient.exr"], ambient)
        grid = [
            image(f"{prefix}_rgb", "RGB passive — fixed exposure"),
            image(f"{prefix}_ambient", "NIR ambient — fixed scale"),
            image(f"{prefix}_direct", "NIR flash-direct — log preview"),
        ]
        if "bright" not in prefix:
            grid.extend((
                image(f"{prefix}_rgb_error", "|RGB candidate − 4000 spp reference| — 0.01 full scale"),
                image(f"{prefix}_ambient_error", "|NIR ambient candidate − reference| — 0.01 full scale"),
            ))
        candidate_html.append(
            "<section><h2>" + html.escape(name) + "</h2><div class=grid>" + "".join(grid) +
            "</div><p class=metrics>RGB: MAE <code>" + f(rgb_metrics["mae"]) + "</code>, RMSE <code>" +
            f(rgb_metrics["rmse"]) + "</code>, PSNR(p99.9 reference) <code>" + f(rgb_metrics["psnr_p999_db"]) +
            " dB</code>. NIR ambient: MAE <code>" + f(ambient_metrics["mae"]) + "</code>, RMSE <code>" +
            f(ambient_metrics["rmse"]) + "</code>, PSNR <code>" + f(ambient_metrics["psnr_p999_db"]) +
            " dB</code>.</p></section>"
        )

    dark_rgb = stats(reference["rgb.exr"])
    dark_nir = stats(reference["nir_ambient.exr"])
    bright_rgb = stats(bright["rgb.exr"])
    bright_nir = stats(bright["nir_ambient.exr"])
    highlight_trap_rgb = stats(read_exr(highlight_trap_dir / "rgb.exr"))
    html_text = f"""<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">
<title>IR sampling benchmark · 2026-08-11</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:1480px;margin:auto;padding:28px;background:#f5f6f8;color:#18202a;line-height:1.55}}
h1{{margin-bottom:4px}} h2{{margin-top:38px;border-bottom:2px solid #dbe2ea;padding-bottom:7px}} .lead,.note{{color:#596878}} .summary{{background:#fff;border-left:4px solid #287e55;padding:15px 18px;border-radius:6px}} .warn{{border-color:#c58724}} table{{width:100%;border-collapse:collapse;background:white}} th,td{{border:1px solid #dce3eb;padding:9px;text-align:left;vertical-align:top}} th{{background:#edf2f7}} .grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}} figure{{margin:0;background:#fff;border:1px solid #dce3eb;border-radius:7px;overflow:hidden}} img{{width:100%;display:block;background:#111}} figcaption{{font-size:12px;padding:8px;color:#536273}} code{{background:#e9eef4;padding:2px 5px;border-radius:3px}} pre{{white-space:pre-wrap;background:#111923;color:#d8e6f5;padding:14px;border-radius:6px;overflow:auto}} .metrics{{background:#fff;padding:10px 12px;border-radius:5px}} @media(max-width:1000px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body>
<h1>Kitchen IR sampling-policy probes</h1>
<p class=lead>2026-08-11 · structural_specular_pbr · shared effective scene digest · OptiX 7 / RTX 3090 · texture cap 256 · raw EXR is unchanged</p>
<div class=summary><b>Result:</b> texture capping has eliminated the prior 24&nbsp;GiB OOM (the live workers hold about 8.3&nbsp;GiB each); they are now compute-bound at nearly 100% SM use. The two low-cost probes deliberately target the same <code>vp_000066__h_240</code> dark view, so they demonstrate an important separate issue: it is intrinsically unlit, not a view that becomes useful merely by increasing SPP.</div>
<p><a href=\"report_2026-08-11_ir_sampling_bright_cohort10.html\">Bright 10-view cohort comparison →</a> same-resolution reduced-pass result against published 4000-SPP RGB/NIR-ambient references.</p>
<h2>Configurations and observed timings</h2>
<table><thead><tr><th>Configuration</th><th>Resolution</th><th>Pass SPP</th><th>max depth</th><th>observation render time</th></tr></thead><tbody>
<tr><td>Live baseline</td><td>684×512</td><td>RGB 4000 · ambient 4000 · direct 4000</td><td>8</td><td>per-pass timing was added after this live batch started</td></tr>
{''.join(rows)}
</tbody></table>
<p class=note>All probes ran while GPU 0/2 also rendered a live 4000-SPP batch, so these wall times are contention-affected and are not advertised as standalone throughput. Work requested falls from 4.20 billion sample-pixels/frame in the baseline to 0.75B (17.8%) for the full-resolution candidate and 0.30B (7.2%) for the fast candidate. Subsequent isolated probes should use the now-recorded <code>render_timings_s</code> per pass.</p>
<h2>Why illumination must be gated separately</h2>
<div class=grid>{image('dark_reference_rgb','Dark reference RGB — 4000 spp, fixed exposure')}{image('dark_reference_nir_ambient','Dark reference NIR ambient — 4000 spp')}{image('bright_reference_rgb','Bright reference RGB — 4000 spp, fixed exposure')}{image('bright_reference_nir_ambient','Bright reference NIR ambient — 4000 spp')}</div>
<table><thead><tr><th>Live 4000-SPP reference</th><th>RGB mean / p95</th><th>NIR ambient mean / p95</th><th>Interpretation</th></tr></thead><tbody>
<tr><td><code>vp_000066__h_240</code></td><td>{f(dark_rgb['mean'])} / {f(dark_rgb['p95'])}</td><td>{f(dark_nir['mean'])} / {f(dark_nir['p95'])}</td><td>unlit/dim: noise is visible even at 4000 spp</td></tr>
<tr><td><code>vp_000051__h_165</code></td><td>{f(bright_rgb['mean'])} / {f(bright_rgb['p95'])}</td><td>{f(bright_nir['mean'])} / {f(bright_nir['p95'])}</td><td>well-lit control view</td></tr>
</tbody></table>
<p class=note><b><code>rgb_max</code> alone must not select the benchmark cohort.</b> <code>vp_000025__h_345</code> has a deceptively high RGB max of <code>{f(highlight_trap_rgb['max'])}</code>, yet its mean/p95 are only <code>{f(highlight_trap_rgb['mean'])}</code> / <code>{f(highlight_trap_rgb['p95'])}</code>; it is a mostly dark frame with a small highlight. The normalized cohort should require robust luminance mean and p95, not max.</p>
<div class=\"summary warn\"><b>Candidate policy to decide after visual review:</b> run a 32-SPP RGB-passive preflight on every frame, then exclude a frame from the expensive IR sweep when both <code>luminance p95 &lt; 0.02</code> and <code>mean &lt; 0.01</code>. This changes neither scene lighting nor SPP; it only stops investing in views that are already demonstrably non-informative. Thresholds remain a proposal here, not an enabled default.</div>
{''.join(candidate_html)}
<h2>Next: normalized multi-view GPU benchmark</h2>
<p>Added <code>apps/benchmark_ir_sampling.py</code>. It refuses to start while a production worker occupies the selected GPU, then records each profile's synchronized <code>mi_render_s</code> mean/median/p95 plus device SM-active seconds, peak VRAM and energy estimate. The first view warms the scene/JIT and is excluded from aggregation.</p>
<pre>python3 apps/benchmark_ir_sampling.py \\
  --scene-dir out/ir_dataset/kitchen_structural_specular_lod/ir_effective_scene \\
  --out out/ir_dataset/kitchen_structural_specular_lod/benchmarks/normalized_bright_cohort \\
  --gpu-index &lt;idle GPU&gt; --warmup-count 1 \\
  --viewpoints vp_000051@165,vp_000044@135,vp_000046@165,vp_000054@075,vp_000011@090,vp_000047@300 \\
  --profile baseline:684x512:4000:4000:4000:8 \\
  --profile fullres_reduced:684x512:1000:750:384:8 \\
  --profile fast:512x384:768:512:256:6</pre>
<p class=note>Do not add <code>--allow-shared-gpu</code> for a decision-quality result: that mode deliberately labels device telemetry as non-attributable. The resulting <code>benchmark_summary.json</code> is the source for a cohort-normalized report.</p>
<h2>Interpretation</h2><ul><li><b>Full-resolution pass-specific SPP</b> is the cleanest first candidate: it preserves camera sampling, texture cap, resolution and depth while cutting requested sample work by about 82%.</li><li><b>Fast resolution/depth</b> is an upper speed-bound rather than a default; its error images reveal the combined effect of lower SPP and lower spatial resolution.</li><li>The dark-view comparisons have intentionally poor PSNR against the 4000-SPP reference. That is evidence for the illumination gate, not evidence that 4000 SPP should be retained for dark views.</li><li>RGB/NIR ambient cannot currently be fused in one render because the band carrier is a whole-scene BSDF-weight swap. Flash-direct is additionally a different integrator/emitter pass. Therefore this report only evaluates safe sampling/depth/resolution controls.</li></ul>
<p class=note>Generated from <code>tools/generate_ir_sampling_benchmark_report.py</code>. Preview exposure is fixed per dark/bright group; EXR values used for training are never tone-mapped or overwritten.</p>
</body></html>"""
    REPORT.write_text(html_text, encoding="utf-8")
    print(REPORT)


if __name__ == "__main__":
    main()
