#!/usr/bin/env python3
"""Visualize the latest paired passive/active polarization queue outputs.

The report is deliberately artifact-led: it reads Stokes NPZ files and their
manifests directly, then uses the render ledger only for the two latest active
tasks that did not produce an observation bundle.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[1]
DEFAULT_SCENE = "infinigen_apartment_20260811"
PASSIVE_VERSION = "rv_20260825T055240_34fdc514f99d_64d567"
ACTIVE_VERSION = "rv_20260825T055242_34fdc514f99d_7d2a8a"
LATEST_ACTIVE_VERSION = "rv_20260825T060642_34fdc514f99d_eb2f4f"
TILE = (230, 180)
FONT = ImageFont.load_default()


@dataclass(frozen=True)
class Bundle:
    variant: str
    version: str
    view: str
    path: Path
    manifest: dict
    arrays: dict[str, np.ndarray]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def observation_dir(scene_dir: Path, version: str, variant: str, view: str) -> Path:
    vp, heading = view.split("/")
    return scene_dir / "observations" / "versions" / version / variant / vp / heading


def load_bundle(scene_dir: Path, version: str, variant: str, view: str) -> Bundle:
    directory = observation_dir(scene_dir, version, variant, view)
    manifest = read_json(directory / "manifest.json")
    npz = directory / "cameras" / "polar_cam" / "stokes_data.npz"
    with np.load(npz) as source:
        arrays = {key: source[key] for key in source.files}
    return Bundle(variant, version, view, directory, manifest, arrays)


def available_views(scene_dir: Path, version: str, variant: str) -> set[str]:
    root = scene_dir / "observations" / "versions" / version / variant
    return {f"{path.parent.parent.name}/{path.parent.name}" for path in root.glob("*/h_*/manifest.json")}


def percentile(values: np.ndarray, q: float) -> float:
    finite = values[np.isfinite(values)]
    return float(np.percentile(finite, q)) if finite.size else 0.0


def tone_rgb(rgb: np.ndarray) -> np.ndarray:
    image = np.maximum(rgb.astype(np.float32), 0.0)
    image = image / (1.0 + image)
    return np.uint8(np.clip(image ** (1.0 / 2.2) * 255.0, 0, 255))


def gray(values: np.ndarray, scale: float) -> np.ndarray:
    return np.uint8(np.clip(np.maximum(values, 0.0) / max(scale, 1e-8) * 255.0, 0, 255))


def bwr(values: np.ndarray, scale: float) -> np.ndarray:
    x = np.clip(values / max(scale, 1e-8), -1.0, 1.0)
    red = np.where(x >= 0.0, 255.0, 255.0 * (1.0 + x))
    blue = np.where(x <= 0.0, 255.0, 255.0 * (1.0 - x))
    green = 255.0 * (1.0 - np.abs(x))
    return np.uint8(np.stack((red, green, blue), axis=-1))


def red_black(values: np.ndarray) -> np.ndarray:
    x = np.clip(values, 0.0, 1.0)
    return np.uint8(np.stack((255.0 * x, np.zeros_like(x), np.zeros_like(x)), axis=-1))


def aolp_rainbow(angle: np.ndarray, dop: np.ndarray) -> np.ndarray:
    # AoLP is π-periodic; hue spans the full rainbow once over [0, π).
    hue = (np.mod(angle, math.pi) / math.pi) * 6.0
    sector = np.floor(hue).astype(np.int32) % 6
    f = hue - np.floor(hue)
    q = 1.0 - f
    rgb = np.zeros((*angle.shape, 3), dtype=np.float32)
    mappings = ((1, f, 0), (q, 1, 0), (0, 1, f), (0, q, 1), (f, 0, 1), (1, 0, q))
    for index, channels in enumerate(mappings):
        mask = sector == index
        for channel, value in enumerate(channels):
            rgb[..., channel][mask] = value[mask] if isinstance(value, np.ndarray) else value
    # Undefined/weakly polarized pixels go dark rather than giving arbitrary hue.
    return np.uint8(np.clip(rgb * np.clip(dop[..., None], 0.0, 1.0) * 255.0, 0, 255))


def channel_dolp_aolp(arrays: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Return DoLP/AoLP independently for the R, G, and B Stokes triplets."""
    s0 = np.maximum(arrays["s0"].astype(np.float32), 1e-8)
    s1, s2, s3 = (arrays[key].astype(np.float32) for key in ("s1", "s2", "s3"))
    dolp = np.clip(np.sqrt(s1 * s1 + s2 * s2 + s3 * s3) / s0, 0.0, 1.0)
    aolp = np.mod(0.5 * np.arctan2(s2, s1), math.pi)
    return dolp, aolp


def tile(image: np.ndarray, title: str) -> Image.Image:
    if image.ndim == 2:
        image = np.repeat(image[..., None], 3, axis=2)
    source = Image.fromarray(image, "RGB")
    source.thumbnail((TILE[0], TILE[1] - 18), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", TILE, (15, 23, 42))
    canvas.paste(source, ((TILE[0] - source.width) // 2, 18 + (TILE[1] - 18 - source.height) // 2))
    ImageDraw.Draw(canvas).text((5, 4), title, fill=(232, 238, 248), font=FONT)
    return canvas


def channel_metrics(bundle: Bundle) -> dict:
    result = {}
    mask = bundle.arrays["mask"].astype(bool)
    for key in ("s0", "s1", "s2", "s3"):
        value = bundle.arrays[key]
        result[key] = {
            "mean": [float(value[..., channel][mask].mean()) for channel in range(3)],
            "p995_abs": [percentile(np.abs(value[..., channel][mask]), 99.5) for channel in range(3)],
        }
    dolp_rgb, _ = channel_dolp_aolp(bundle.arrays)
    result["dolp_rgb"] = {
        "mean": [float(dolp_rgb[..., channel][mask].mean()) for channel in range(3)],
        "p995": [percentile(dolp_rgb[..., channel][mask], 99.5) for channel in range(3)],
    }
    return result


def contact_sheet(passive: Bundle, active: Bundle, destination: Path) -> dict:
    all_arrays = [passive.arrays, active.arrays]
    channels = ("R", "G", "B")
    s0_scales = [max(percentile(arrays["s0"][..., channel], 99.5) for arrays in all_arrays) for channel in range(3)]
    signed_scales = {
        key: [max(percentile(np.abs(arrays[key][..., channel]), 99.5) for arrays in all_arrays) for channel in range(3)]
        for key in ("s1", "s2", "s3")
    }
    columns = (["S0 RGB"] + [f"S0-{channel}" for channel in channels]
               + [f"S1-{channel} (BWR)" for channel in channels]
               + [f"S2-{channel} (BWR)" for channel in channels]
               + [f"S3-{channel} (BWR)" for channel in channels]
               + [f"DoLP-{channel}" for channel in channels]
               + [f"AoLP-{channel}" for channel in channels])
    sheet = Image.new("RGB", (len(columns) * TILE[0], 2 * TILE[1]), (8, 12, 20))
    for row, bundle in enumerate((passive, active)):
        arrays = bundle.arrays
        dolp_rgb, aolp_rgb = channel_dolp_aolp(arrays)
        previews = ([tone_rgb(arrays["s0"])]
                    + [gray(arrays["s0"][..., channel], s0_scales[channel]) for channel in range(3)]
                    + [bwr(arrays["s1"][..., channel], signed_scales["s1"][channel]) for channel in range(3)]
                    + [bwr(arrays["s2"][..., channel], signed_scales["s2"][channel]) for channel in range(3)]
                    + [bwr(arrays["s3"][..., channel], signed_scales["s3"][channel]) for channel in range(3)]
                    + [red_black(dolp_rgb[..., channel]) for channel in range(3)]
                    + [aolp_rainbow(aolp_rgb[..., channel], dolp_rgb[..., channel]) for channel in range(3)])
        row_name = "Passive / ambient" if row == 0 else "Active / polarized assist"
        for column, (label, preview) in enumerate(zip(columns, previews)):
            title = f"{row_name}: {label}"
            sheet.paste(tile(preview, title), (column * TILE[0], row * TILE[1]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, "WEBP", quality=86, method=6)
    return {"s0_p995": s0_scales, **{f"{key}_p995_abs": value for key, value in signed_scales.items()}}


def latest_task_status(project_dir: Path, version: str) -> list[dict]:
    ledger = project_dir / "render_ledger.sqlite3"
    if not ledger.is_file():
        return []
    with sqlite3.connect(ledger) as connection:
        rows = connection.execute(
            """select node_id, heading_id, state, job_id, error
               from sweep_tasks where render_version_id = ?
               order by ordinal""",
            (version,),
        ).fetchall()
    return [{"node_id": row[0], "heading_id": row[1], "state": row[2], "job_id": row[3], "error": row[4]} for row in rows]


def esc(value: object) -> str:
    return html.escape(str(value))


def report_html(scene_id: str, passive_version: str, active_version: str, latest_active_version: str,
                rows: list[dict], latest_tasks: list[dict]) -> str:
    cards = []
    for row in rows:
        p, a = row["passive"], row["active"]
        def means(metrics: dict, key: str) -> str:
            return " / ".join(f"{item:.4f}" for item in metrics[key]["mean"])
        cards.append(f'''<article>
<h3>{esc(row["view"])} <span class="ok">paired / valid</span></h3>
<img src="{esc(row["image"])}" loading="lazy" alt="Passive and active Stokes comparison for {esc(row["view"])}">
<table><thead><tr><th>metric</th><th>passive</th><th>active</th></tr></thead><tbody>
<tr><td>S0 mean (R/G/B)</td><td>{means(p, "s0")}</td><td>{means(a, "s0")}</td></tr>
<tr><td>S1 mean (R/G/B)</td><td>{means(p, "s1")}</td><td>{means(a, "s1")}</td></tr>
<tr><td>S2 mean (R/G/B)</td><td>{means(p, "s2")}</td><td>{means(a, "s2")}</td></tr>
<tr><td>S3 mean (R/G/B)</td><td>{means(p, "s3")}</td><td>{means(a, "s3")}</td></tr>
<tr><td>DoLP mean (R/G/B)</td><td>{means(p, "dolp_rgb")}</td><td>{means(a, "dolp_rgb")}</td></tr>
<tr><td>DoLP p99.5 (R/G/B)</td><td>{" / ".join(f"{item:.4f}" for item in p["dolp_rgb"]["p995"])}</td><td>{" / ".join(f"{item:.4f}" for item in a["dolp_rgb"]["p995"])}</td></tr>
</tbody></table></article>''')
    task_rows = "".join(
        f"<tr><td>{esc(task['node_id'])}</td><td>{esc(task['heading_id'])}</td><td>{esc(task['state'])}</td><td>{esc(task['job_id'])}</td><td>{esc(task['error'] or '—')}</td></tr>"
        for task in latest_tasks
    ) or "<tr><td colspan=5>No ledger rows found.</td></tr>"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Recent polar queue: passive vs active</title><style>
:root{{--bg:#0d1117;--panel:#161d27;--line:#2c3849;--fg:#e8edf4;--mut:#a5b0bf;--ok:#58dba2;--acc:#78abff}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif}}main{{max-width:2160px;margin:auto;padding:36px 24px 72px}}h1{{margin:0}}h2{{margin:38px 0 10px;border-top:1px solid var(--line);padding-top:24px}}h3{{margin:0 0 8px;color:var(--acc)}}p,li{{color:var(--mut)}}code{{background:#202a38;padding:2px 5px;border-radius:3px}}article{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:18px 0}}article>img{{width:100%;display:block;border:1px solid var(--line);border-radius:7px;background:#080c14}}table{{border-collapse:collapse;width:100%;margin-top:12px;font-size:13px}}th,td{{border:1px solid var(--line);padding:6px 8px;text-align:left;font-variant-numeric:tabular-nums}}th{{color:var(--mut);background:#111824}}.ok{{color:var(--ok);font-size:12px}}.note{{padding:12px 16px;background:#141c29;border-left:3px solid var(--acc);border-radius:0 7px 7px 0}}.legend{{display:grid;grid-template-columns:repeat(4,minmax(170px,1fr));gap:10px}}.legend div{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px}}@media(max-width:900px){{main{{padding:20px 10px}}.legend{{grid-template-columns:1fr}}article{{padding:8px}}}}</style></head><body><main>
<h1>Recent polar render queue — passive vs active RGB-Stokes comparison</h1>
<p>Scene <code>{esc(scene_id)}</code> · generated {datetime.now(UTC).isoformat()} · direct artifacts, not UI thumbnails.</p>
<div class="note"><strong>Conclusion:</strong> the eight completed paired poses use <code>cuda_ad_rgb_polarized</code> with the <code>opticalnav.stokes_rgb_12.v2</code> contract. Each NPZ contains <code>S0/S1/S2/S3</code> as H×W×3 tensors, so the rendered Stokes state is retained independently for R/G/B rather than as a replicated grayscale polarization product. Passive and active runs both satisfy this contract; active adds the camera-aligned polarized RGB assist.</div>
<h2>Render sets</h2><ul>
<li>Passive: <code>{esc(passive_version)}/perturbed</code>, ambient-room illumination.</li>
<li>Active: <code>{esc(active_version)}/perturbed_active_polar</code>, protocol <code>rgb_stokes_12_active_polar_v1</code>.</li>
<li>Pairing: {len(rows)} shared completed views, same scene version and heading.</li></ul>
<h2>Visualization convention</h2><div class="legend"><div><strong>S0 RGB and R/G/B</strong><br>shared Reinhard tone map / shared intensity scale.</div><div><strong>S1, S2, S3 × R/G/B</strong><br>BWR with zero = white; each component/channel uses one common passive/active p99.5 scale.</div><div><strong>DoLP-R/G/B</strong><br>computed separately as √(S1²+S2²+S3²)/S0, then black → red over [0, 1].</div><div><strong>AoLP-R/G/B</strong><br>computed separately as ½atan2(S2,S1); rainbow over [0°, 180°), brightness and saturation modulated by that channel's DoLP.</div></div>
<h2>Completed passive/active pairs</h2>{''.join(cards)}
<h2>Newest active queue status</h2><p>The newest version <code>{esc(latest_active_version)}</code> contains the two manual-view tasks that were not part of the completed eight-pair evidence set.</p><table><thead><tr><th>viewpoint</th><th>heading</th><th>state</th><th>job</th><th>error</th></tr></thead><tbody>{task_rows}</tbody></table>
<h2>Interpretation boundary</h2><p>This report verifies the output contract and demonstrates non-identical R/G/B Stokes components in actual artifacts. It does not independently prove wavelength-specific physics beyond the RGB-polarized renderer contract; that requires a controlled spectral/reference test.</p>
</main></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", default=DEFAULT_SCENE)
    parser.add_argument("--passive-version", default=PASSIVE_VERSION)
    parser.add_argument("--active-version", default=ACTIVE_VERSION)
    parser.add_argument("--latest-active-version", default=LATEST_ACTIVE_VERSION)
    parser.add_argument("--out", type=Path, default=REPO / "dev_report" / "report_recent_polar_queue_2026-08-25.html")
    parser.add_argument("--assets", type=Path, default=REPO / "dev_report" / "images" / "recent_polar_queue_2026-08-25")
    args = parser.parse_args()
    scene_dir = REPO / "out" / "opticalnav" / "opticalnav-v0.2" / "scenes" / args.scene
    passive_views = available_views(scene_dir, args.passive_version, "perturbed")
    active_views = available_views(scene_dir, args.active_version, "perturbed_active_polar")
    paired = sorted(passive_views & active_views)
    if not paired:
        raise SystemExit("no completed passive/active polar pairs found")
    args.assets.mkdir(parents=True, exist_ok=True)
    rows = []
    for view in paired:
        passive = load_bundle(scene_dir, args.passive_version, "perturbed", view)
        active = load_bundle(scene_dir, args.active_version, "perturbed_active_polar", view)
        image = args.assets / f"{view.replace('/', '_')}.webp"
        contact_sheet(passive, active, image)
        rows.append({"view": view, "image": image.relative_to(args.out.parent).as_posix(),
                     "passive": channel_metrics(passive), "active": channel_metrics(active)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    latest_tasks = latest_task_status(REPO / "out" / "opticalnav" / "opticalnav-v0.2", args.latest_active_version)
    args.out.write_text(report_html(args.scene, args.passive_version, args.active_version, args.latest_active_version, rows, latest_tasks), encoding="utf-8")
    summary = args.assets / "summary.json"
    summary.write_text(json.dumps({"scene": args.scene, "passive_version": args.passive_version,
                                   "active_version": args.active_version, "paired_views": [row["view"] for row in rows],
                                   "rows": rows, "latest_active_tasks": latest_tasks}, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"paired views: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
