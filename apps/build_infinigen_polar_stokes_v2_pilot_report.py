#!/usr/bin/env python3
"""Build a static three-condition RGB-Stokes v2 pilot report.

The report intentionally treats a missing member as a failed triad rather than
silently comparing a pair.  It reads lossless ``stokes_data.npz`` artifacts and
uses existing RGB/DoLP/AoLP previews when present.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

import numpy as np


VARIANT_ROOTS = {
    "base": "observations",
    "perturbed": "observations_perturbed",
    "perturbed_active_polar": "observations_perturbed_active_polar",
}


def _bundle(scene_dir: Path, variant: str, node_id: str, heading_id: str) -> Path | None:
    stable = scene_dir / VARIANT_ROOTS[variant] / node_id / heading_id
    pointer = stable / "current.json"
    if pointer.is_file():
        try:
            reference = json.loads(pointer.read_text(encoding="utf-8")).get("bundle_ref")
            candidate = (scene_dir.parent.parent / str(reference)).resolve()
            if candidate.is_dir():
                return candidate
        except (OSError, ValueError, TypeError):
            pass
    return stable if stable.is_dir() else None


def _sensor_dir(bundle: Path | None) -> Path | None:
    if bundle is None:
        return None
    if (bundle / "stokes_data.npz").is_file():
        return bundle
    candidates = sorted(bundle.glob("sensors/*/stokes_data.npz")) + sorted(bundle.glob("cameras/*/stokes_data.npz"))
    return candidates[0].parent if candidates else None


def _metrics(sensor_dir: Path | None) -> dict[str, float] | None:
    if sensor_dir is None or not (sensor_dir / "stokes_data.npz").is_file():
        return None
    with np.load(sensor_dir / "stokes_data.npz") as data:
        result = {}
        for channel in ("s0", "s1", "s2", "s3"):
            field = np.asarray(data[channel], dtype=np.float32)
            result[f"{channel}_mean"] = float(np.nanmean(field))
            result[f"{channel}_p95"] = float(np.nanpercentile(field, 95))
            result[f"{channel}_nan_ratio"] = float(np.mean(~np.isfinite(field)))
        s0 = np.asarray(data["s0"], dtype=np.float32)
        s1 = np.asarray(data["s1"], dtype=np.float32)
        s2 = np.asarray(data["s2"], dtype=np.float32)
        dolp = np.sqrt(np.maximum(0.0, s1 * s1 + s2 * s2)) / np.maximum(s0, 1e-8)
        result["dolp_mean"] = float(np.nanmean(np.clip(dolp, 0.0, 1.0)))
        return result


def _preview(sensor_dir: Path | None, names: tuple[str, ...], scene_dir: Path, report_dir: Path) -> str:
    if sensor_dir is None:
        return "—"
    for name in names:
        candidate = sensor_dir / name
        if candidate.is_file():
            return html.escape(os.path.relpath(candidate, report_dir))
    return "—"


def _render_metric_row(metrics: dict[str, float] | None, base: dict[str, float] | None) -> str:
    if metrics is None:
        return "<td class='missing'>missing Stokes GT</td>"
    delta = "—" if base is None else f"{metrics['s0_mean'] - base['s0_mean']:+.5f}"
    return f"<td>S0 {metrics['s0_mean']:.5f} / Δ {delta}<br>DoLP {metrics['dolp_mean']:.4f}<br>NaN {max(metrics[f'{ch}_nan_ratio'] for ch in ('s0','s1','s2','s3')):.3%}</td>"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-contract", type=Path, required=True)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.pilot_contract.read_text(encoding="utf-8"))
    if contract.get("polar_color_mode") != "rgb_stokes_12":
        raise SystemExit("pilot contract is not rgb_stokes_12")
    rows: list[str] = []
    complete = 0
    for view in contract.get("views", []):
        node_id, heading_id = str(view["node_id"]), str(view["heading_id"])
        data = {variant: _sensor_dir(_bundle(args.scene_dir, variant, node_id, heading_id)) for variant in VARIANT_ROOTS}
        metrics = {variant: _metrics(path) for variant, path in data.items()}
        complete += int(all(value is not None for value in metrics.values()))
        cells = []
        for variant in VARIANT_ROOTS:
            rgb = _preview(data[variant], ("polar_rgb_preview.png", "rgb.png"), args.scene_dir, args.out.parent)
            dolp = _preview(data[variant], ("dop_red_black_colorbar.png",), args.scene_dir, args.out.parent)
            aolp = _preview(data[variant], ("aolp_rainbow_colorbar.png",), args.scene_dir, args.out.parent)
            cells.append(f"<td><b>{variant}</b><br>RGB: {rgb}<br>DoLP: {dolp}<br>AoLP: {aolp}</td>")
        metrics_html = "".join(_render_metric_row(metrics[variant], metrics["base"]) for variant in VARIANT_ROOTS)
        rows.append(f"<tr><th>{html.escape(node_id)} / {html.escape(heading_id)}</th>{''.join(cells)}</tr><tr class='metrics'><th>Stokes summary</th>{metrics_html}</tr>")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(rows)
    args.out.write_text(f"""<!doctype html><meta charset='utf-8'>
<title>Infinigen OpticalNav RGB Stokes v2 pilot</title>
<style>body{{font:14px system-ui;margin:24px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #b9c1cb;padding:9px;text-align:left;vertical-align:top}}th{{background:#edf2f7}}.metrics td{{font-family:ui-monospace,monospace}}.missing{{color:#b42318}}code{{background:#f3f4f6;padding:2px 4px}}</style>
<h1>RGB Stokes v2 + active polar pilot</h1>
<p>Contract: <code>{html.escape(str(args.pilot_contract))}</code>. Complete triads: <b>{complete}/{len(contract.get('views', []))}</b>. A pilot is acceptable only at 10/10; this report does not mask missing variants.</p>
<p>GT contract: <code>S0_RGB, S1_RGB, S2_RGB, S3_RGB</code>, float32, camera-image x/y Stokes basis, <code>cuda_ad_rgb_polarized</code>. Active condition: camera-aligned white area light, polarizer 0°.</p>
<table><thead><tr><th>view</th><th>base</th><th>perturbed</th><th>perturbed_active_polar</th></tr></thead><tbody>{body}</tbody></table>
""", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "complete_triads": complete, "views": len(contract.get("views", []))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
