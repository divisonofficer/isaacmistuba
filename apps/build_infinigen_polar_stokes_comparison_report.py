#!/usr/bin/env python3
"""Compare old and refreshed perturbed Stokes renders for featured Infinigen views."""
from __future__ import annotations

import argparse
import html
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


DEFAULT_SCENE = "infinigen_apartment_20260811"
DEFAULT_OLD_VERSION = "rv_20260816T021646_34fdc514f99d_273e3e"
DEFAULT_ARCHIVE = Path("out/opticalnav/opticalnav-v0.2/exports/export-infinigen_apartment_20260811-20260821T065949931891/infinigen_apartment_20260811_20260821T070015Z_polar_stokes.zip")


def _rgb(image: np.ndarray) -> np.ndarray:
    image = np.nan_to_num(image, nan=0.0, posinf=0.0, neginf=0.0)
    scale = max(float(np.quantile(image[image > 0], .992)) if np.any(image > 0) else 1.0, 1e-6)
    return (np.clip(image / scale, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


def _dop(data: dict[str, np.ndarray]) -> np.ndarray:
    weights = np.array([.2126, .7152, .0722], dtype=np.float32)
    s0 = np.tensordot(data["s0"], weights, axes=([2], [0]))
    s1 = np.tensordot(data["s1"], weights, axes=([2], [0]))
    s2 = np.tensordot(data["s2"], weights, axes=([2], [0]))
    return np.clip(np.sqrt(np.maximum(0, s1 * s1 + s2 * s2)) / np.maximum(s0, 1e-8), 0, 1)


def _aolp(data: dict[str, np.ndarray]) -> np.ndarray:
    weights = np.array([.2126, .7152, .0722], dtype=np.float32)
    s1 = np.tensordot(data["s1"], weights, axes=([2], [0])); s2 = np.tensordot(data["s2"], weights, axes=([2], [0]))
    return np.mod(.5 * np.arctan2(s2, s1), np.pi)


def _red_black(value: np.ndarray) -> np.ndarray:
    out = np.zeros(value.shape + (3,), dtype=np.uint8); out[..., 0] = (np.sqrt(np.clip(value, 0, 1)) * 255).astype(np.uint8); return out


def _aolp_hue(angle: np.ndarray) -> np.ndarray:
    """AoLP hue with no DoLP-opacity masking; invalid values become black."""
    finite = np.isfinite(angle); hsv = np.zeros(angle.shape + (3,), dtype=np.uint8)
    hsv[..., 0] = (np.mod(np.nan_to_num(angle), np.pi) / np.pi * 255).astype(np.uint8)
    hsv[..., 1][finite] = 255; hsv[..., 2][finite] = 255
    return np.asarray(Image.fromarray(hsv, mode="HSV").convert("RGB"))


def _luminance(image: np.ndarray) -> np.ndarray:
    return np.tensordot(image, np.array([.2126, .7152, .0722], dtype=np.float32), axes=([2], [0]))


def _diverging(value: np.ndarray, scale: float) -> np.ndarray:
    norm = np.clip(np.nan_to_num(value / max(scale, 1e-8)), -1, 1); out = np.full(value.shape + (3,), 255, dtype=np.uint8)
    pos, neg = np.clip(norm, 0, 1), np.clip(-norm, 0, 1)
    out[..., 1] = (255 * (1 - np.maximum(pos, neg))).astype(np.uint8); out[..., 0] = (255 * (1 - neg)).astype(np.uint8); out[..., 2] = (255 * (1 - pos)).astype(np.uint8); return out


def _save(array: np.ndarray, path: Path) -> None:
    if path.is_file(): return
    path.parent.mkdir(parents=True, exist_ok=True); Image.fromarray(array).save(path)


def _load_old(root: Path, scene: str, version: str, vp: str, heading: str) -> dict[str, np.ndarray]:
    path = root / "scenes" / scene / "observations" / "versions" / version / "perturbed" / vp / heading / "cameras" / "polar_cam" / "stokes_data.npz"
    with np.load(path, allow_pickle=False) as data: return {key: data[key] for key in ("rgb", "s0", "s1", "s2", "s3", "mask")}


def _load_new(archive: Path, scene: str, vp: str, heading: str) -> dict[str, np.ndarray]:
    member = f"scenes/{scene}/observations_perturbed/{vp}/{heading}/sensors/polar_cam/stokes_core_v1.npz"
    with zipfile.ZipFile(archive) as source, source.open(member) as handle, np.load(handle, allow_pickle=False) as data:
        return {key: data[key] for key in ("rgb", "s0", "s1", "s2", "s3", "mask")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=Path("dev_report/report_2026-08-18_infinigen_dataset_thumbnails.selection.json"))
    parser.add_argument("--project", type=Path, default=Path("out/opticalnav/opticalnav-v0.2")); parser.add_argument("--scene", default=DEFAULT_SCENE)
    parser.add_argument("--old-version", default=DEFAULT_OLD_VERSION); parser.add_argument("--new-archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, required=True); parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--view", action="append", default=[], metavar="VP:HEADING", help="Additional reviewed pair to visualize; repeatable")
    args = parser.parse_args(); payload = json.loads(args.selection.read_text())
    scene_row = next(row for row in payload["scenes"] if row["scene_id"] == args.scene); cards = []; summaries = []
    rows = list(scene_row["selected"]); by_key = {(row["vp_id"], row["heading_id"]): row for row in [*rows, *scene_row.get("gallery", [])]}
    for value in args.view:
        vp, separator, heading = value.partition(":")
        if not separator or not vp or not heading or (vp, heading) not in by_key:
            raise SystemExit(f"Unknown --view {value!r}; expected a reviewed VP:HEADING pair")
        if (vp, heading) not in {(row["vp_id"], row["heading_id"]) for row in rows}: rows.append(by_key[(vp, heading)])
    for row in rows:
        vp, heading = row["vp_id"], row["heading_id"]; old, new = _load_old(args.project, args.scene, args.old_version, vp, heading), _load_new(args.new_archive, args.scene, vp, heading)
        old_dop, new_dop, old_aolp, new_aolp = _dop(old), _dop(new), _aolp(old), _aolp(new)
        old_s0, new_s0, old_s1, new_s1, old_s2, new_s2, old_s3, new_s3 = (_luminance(item[key]) for item, key in ((old,"s0"),(new,"s0"),(old,"s1"),(new,"s1"),(old,"s2"),(new,"s2"),(old,"s3"),(new,"s3")))
        valid = old["mask"] & new["mask"] & np.isfinite(old_dop) & np.isfinite(new_dop); valid = valid if np.any(valid) else np.ones(old_dop.shape, bool)
        metrics = {"mean_abs_dolp": float(np.mean(np.abs(new_dop[valid] - old_dop[valid]))), "mean_abs_s0_delta": float(np.mean(np.abs(new_s0[valid] - old_s0[valid])))}; summaries.append(metrics)
        stem = f"{vp}_{heading}"; files = {key: f"{stem}_{key}.png" for key in ("old_rgb","new_rgb","old_dop","new_dop","dop_delta","old_aolp","new_aolp","old_s1","new_s1","old_s2","new_s2","old_s3","new_s3")}
        _save(_rgb(old["rgb"]), args.assets / files["old_rgb"]); _save(_rgb(new["rgb"]), args.assets / files["new_rgb"]); _save(_red_black(old_dop), args.assets / files["old_dop"]); _save(_red_black(new_dop), args.assets / files["new_dop"])
        _save(_diverging(new_dop - old_dop, .25), args.assets / files["dop_delta"]); _save(_aolp_hue(old_aolp), args.assets / files["old_aolp"]); _save(_aolp_hue(new_aolp), args.assets / files["new_aolp"])
        scale_s1 = max(float(np.quantile(np.abs(np.concatenate((old_s1[valid], new_s1[valid]))), .99)), 1e-6); scale_s2 = max(float(np.quantile(np.abs(np.concatenate((old_s2[valid], new_s2[valid]))), .99)), 1e-6)
        _save(_diverging(old_s1, scale_s1), args.assets / files["old_s1"]); _save(_diverging(new_s1, scale_s1), args.assets / files["new_s1"]); _save(_diverging(old_s2, scale_s2), args.assets / files["old_s2"]); _save(_diverging(new_s2, scale_s2), args.assets / files["new_s2"])
        # S3 is often much smaller than S0.  Do not percentile-stretch it: show the
        # physical normalized circular component on its fixed [-1, 1] scale.
        old_s3_normalized = np.clip(old_s3 / np.maximum(old_s0, 1e-8), -1, 1)
        new_s3_normalized = np.clip(new_s3 / np.maximum(new_s0, 1e-8), -1, 1)
        _save(_diverging(old_s3_normalized, 1.0), args.assets / files["old_s3"]); _save(_diverging(new_s3_normalized, 1.0), args.assets / files["new_s3"])
        cards.append((vp, heading, row.get("evidence", {}), files, metrics))
    overall = {key: float(np.mean([item[key] for item in summaries])) for key in summaries[0]}
    sections = []
    for vp, heading, evidence, files, metrics in cards:
        figures = "".join(f'<figure><img src="{html.escape((args.assets / name).relative_to(args.output.parent).as_posix())}"><figcaption>{label}</figcaption></figure>' for key, label in (("old_rgb","old RGB"),("new_rgb","21 Aug RGB"),("old_dop","old DoLP"),("new_dop","21 Aug DoLP"),("dop_delta","ΔDoLP: new−old"),("old_aolp","old AoLP, unmasked"),("new_aolp","21 Aug AoLP, unmasked"),("old_s1","old S1, raw"),("new_s1","21 Aug S1, raw"),("old_s2","old S2, raw"),("new_s2","21 Aug S2, raw"),("old_s3","old S3/S0, fixed scale"),("new_s3","21 Aug S3/S0, fixed scale")) for name in (files[key],))
        sections.append(f'<article><h2>{vp} / {heading}</h2><p>{html.escape(str(evidence.get("likely_overlay_type", "")))} · {html.escape(str(evidence.get("likely_overlay_id", "")))} · mean |ΔDoLP| {metrics["mean_abs_dolp"]:.4f}, mean |ΔS0| {metrics["mean_abs_s0_delta"]:.4g}. S1/S2 use a shared old/new symmetric scale; AoLP hue is intentionally not DoLP-masked.</p><div>{figures}</div></article>')
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(f'''<!doctype html><meta charset="utf-8"><title>Infinigen perturbed Stokes comparison</title><style>body{{background:#0d1117;color:#e8edf4;font:15px system-ui;margin:auto;max-width:1500px;padding:32px}}article{{border-top:1px solid #334155;padding:20px 0}}article>div{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}figure{{margin:0;background:#161d27}}img{{width:100%;height:170px;object-fit:contain}}figcaption,p{{padding:6px;color:#a5b0bf}}code{{background:#202a38;padding:2px 5px}}@media(max-width:900px){{article>div{{grid-template-columns:repeat(2,1fr)}}}}</style><h1>Infinigen apartment: perturbed Stokes refresh comparison</h1><p>Old: <code>{args.old_version}</code> · New: <code>{args.new_archive}</code>. Same perturbed viewpoint/heading pairs. AoLP panels have no DoLP masking; raw S1/S2 use a shared old/new symmetric scale. This is a rerender comparison, not a physical-quality claim.</p><p>Featured-pair mean: |ΔDoLP| {overall["mean_abs_dolp"]:.4f}; mean |ΔS0| {overall["mean_abs_s0_delta"]:.4g}.</p>{''.join(sections)}''')


if __name__ == "__main__": main()
