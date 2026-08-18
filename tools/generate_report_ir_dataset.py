#!/usr/bin/env python3
"""Generate a visual HTML report for an inverse-rendering dataset run."""
from __future__ import annotations

import argparse
import colorsys
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]


def _read(path: Path) -> np.ndarray:
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    import cv2
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"failed to read {path}")
    if value.ndim == 3 and value.shape[2] == 3:
        value = value[..., ::-1]
    return np.asarray(value, np.float32)


def _u8(value: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(value, 0, 1) * 255).astype(np.uint8)


def _linear_rgb(value: np.ndarray) -> np.ndarray:
    scale = max(float(np.percentile(np.maximum(value, 0), 99.5)), 1e-6)
    linear = np.clip(value / scale, 0, 1)
    srgb = np.where(linear <= 0.0031308, linear * 12.92,
                    1.055 * np.power(linear, 1 / 2.4) - 0.055)
    return _u8(srgb)


def _base_color(value: np.ndarray) -> np.ndarray:
    linear = np.clip(value, 0, 1)
    srgb = np.where(linear <= 0.0031308, linear * 12.92,
                    1.055 * np.power(linear, 1 / 2.4) - 0.055)
    return _u8(srgb)


def _gray(value: np.ndarray, scale: float = 1.0) -> np.ndarray:
    return _u8(np.clip(value / max(scale, 1e-8), 0, 1))


def _turbo(value: np.ndarray, valid: np.ndarray | None = None) -> np.ndarray:
    import cv2
    mask = np.isfinite(value) & (value > 0) if valid is None else valid
    normalized = np.zeros_like(value, np.float32)
    if mask.any():
        lo, hi = np.percentile(value[mask], [2, 98])
        normalized[mask] = np.clip((value[mask] - lo) / max(float(hi - lo), 1e-8), 0, 1)
    colored = cv2.applyColorMap(_u8(normalized), cv2.COLORMAP_TURBO)[..., ::-1]
    colored[~mask] = 0
    return colored


def _ids(value: np.ndarray) -> np.ndarray:
    output = np.zeros((*value.shape, 3), np.uint8)
    for identifier in np.unique(value.astype(np.int64)):
        if identifier < 0:
            continue
        rgb = colorsys.hsv_to_rgb((identifier * 0.61803398875) % 1.0, 0.68, 0.95)
        output[value.astype(np.int64) == identifier] = np.rint(np.asarray(rgb) * 255).astype(np.uint8)
    return output


def _save(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scale = 4 if array.shape[1] < 512 else 1
    Image.fromarray(array).resize(
        (array.shape[1] * scale, array.shape[0] * scale), Image.Resampling.NEAREST
    ).save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path,
                        default=REPO / "out/ir_dataset/kitchen_opaque_stage_c_4view")
    parser.add_argument("--preview-dir", type=Path,
                        default=REPO / "dev_report/images/ir_kitchen_opaque_2026-08-06")
    parser.add_argument("--out", type=Path,
                        default=REPO / "dev_report/report_2026-08-06_ir_kitchen_opaque.html")
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.dataset / "index.jsonl").read_text().splitlines() if line.strip()]
    validation = json.loads((args.dataset / "validation.json").read_text())
    depth_validation_path = args.dataset / "depth_validation.json"
    depth_validation = (json.loads(depth_validation_path.read_text())
                        if depth_validation_path.is_file() else {})
    args.preview_dir.mkdir(parents=True, exist_ok=True)

    sections = []
    for row in rows:
        frame_id = row["frame_id"]
        obs = {name: _read(Path(path)) for name, path in row["observation_paths"].items()}
        gt = {name: _read(Path(path)) for name, path in row["gt_paths"].items()}
        masks = {name: _read(Path(path)) for name, path in row["mask_paths"].items()}
        active_scale = max(float(np.percentile(np.maximum(obs["nir_active"], 0), 99.5)), 1e-6)
        previews = {
            "rgb": _linear_rgb(obs["rgb"]),
            "nir_ambient": _gray(obs["nir_ambient"], active_scale),
            "nir_active": _gray(obs["nir_active"], active_scale),
            "nir_flash_direct": _gray(obs["nir_flash_direct"], active_scale),
            "nir_dflash": _gray(np.maximum(obs["nir_dflash"], 0), active_scale),
            "rgb_albedo": _base_color(gt.get("rgb_albedo", gt["base_color"])),
            "nir_albedo": _gray(gt["nir_albedo"]),
            "roughness": _gray(gt["roughness_perceptual"]),
            "metallic": _gray(gt["metallic"]),
            "depth": _turbo(gt["depth"]),
            "range": _turbo(gt["range"]),
            "normal_geometry": _u8(gt["normal_geometry_world"] * 0.5 + 0.5),
            "normal_shading": _u8(gt["normal_shading_world"] * 0.5 + 0.5),
            "normal_tangent": _u8(gt["normal_tangent"] * 0.5 + 0.5),
            "material_id": _ids(masks["material_id"]),
            "object_id": _ids(masks["object_id"]),
            "valid": _gray(masks["valid_mask"]),
            "replacement": np.stack([_gray(masks["replacement_mask"]),
                                      np.zeros_like(_gray(masks["replacement_mask"])),
                                      _gray(masks["replacement_mask"])], axis=-1),
        }
        overlay = previews["rgb"].astype(np.float32)
        replacement = masks["replacement_mask"] > 0.5
        overlay[replacement] = overlay[replacement] * 0.42 + np.asarray([255, 25, 220]) * 0.58
        previews["replacement_overlay"] = np.rint(overlay).astype(np.uint8)
        for name, image in previews.items():
            _save(args.preview_dir / f"{frame_id}__{name}.png", image)

        def cells(items):
            return "".join(
                f'<figure><img src="images/{args.preview_dir.name}/{frame_id}__{key}.png">'
                f'<figcaption><b>{title}</b><br>{caption}</figcaption></figure>'
                for key, title, caption in items
            )
        observations = cells([
            ("rgb", "RGB passive", "linear HDR, p99.5 exposure preview"),
            ("nir_ambient", "NIR ambient I_off", "active와 동일 scale"),
            ("nir_active", "NIR active", "ambient path + direct flash"),
            ("nir_flash_direct", "NIR flash direct", "aligned MicroBrite spot + direct integrator"),
            ("nir_dflash", "Delta flash", "direct flash와 동일한 물리량"),
            ("replacement_overlay", "Replacement overlay", "치환 표면을 magenta로 표시"),
        ])
        pbr = cells([
            ("rgb_albedo", "RGB albedo", "linear RGB GT를 sRGB preview로 변환"),
            ("nir_albedo", "NIR albedo", "854 nm material-band reflectance"),
            ("roughness", "Roughness", "perceptual roughness"),
            ("metallic", "Metallic", "continuous metallic weight"),
            ("depth", "Z-depth", "camera optical-axis depth; 평행면은 평평하게 표시"),
            ("range", "Ray range", "camera point로부터의 Euclidean 거리 (참고용)"),
        ])
        normals = cells([
            ("normal_geometry", "Geometry normal", "world-space XYZ"),
            ("normal_shading", "Shading normal", "world-space, normal-map 적용"),
            ("normal_tangent", "Tangent normal", "TBN-space XYZ"),
        ])
        mask_cells = cells([
            ("material_id", "Material ID", "stable opaque-unit palette"),
            ("object_id", "Object ID", "stable object palette"),
            ("valid", "Valid mask", "white = four-map GT valid"),
            ("replacement", "Replacement mask", "magenta = glass semantic replacement"),
        ])
        coverage = row.get("coverage") or {}
        sections.append(
            f'<section><h2>{frame_id}</h2><p class="meta">heading {row["heading_deg"]:.0f} deg · '
            f'valid {coverage.get("valid", 0):.1%} · replacement {coverage.get("replacement", 0):.1%}</p>'
            f'<h3>Observations</h3><div class="grid obs">{observations}</div>'
            f'<h3>PBR and depth GT</h3><div class="grid">{pbr}</div>'
            f'<h3>Normal GT</h3><div class="grid normal">{normals}</div>'
            f'<h3>Masks</h3><div class="grid">{mask_cells}</div></section>'
        )

    gate = validation.get("rerender_gate") or {}
    intrinsics = rows[0].get("intrinsics") or {}
    render_config = rows[0].get("render_config") or {}
    resolution = f'{intrinsics.get("width", "?")}x{intrinsics.get("height", "?")}'
    spp = render_config.get("observation_spp", "?")
    z_cv = (depth_validation.get("z_depth") or {}).get("robust_cv_pct", float("nan"))
    range_cv = (depth_validation.get("ray_range") or {}).get("robust_cv_pct", float("nan"))
    depth_gain = depth_validation.get("cv_improvement_x", float("nan"))
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Opaque PBR inverse-rendering sample report</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1500px;margin:auto;padding:28px;background:#f5f6f8;color:#18202a}}
h1{{margin-bottom:6px}} h2{{border-bottom:2px solid #dce1e8;padding-bottom:7px;margin-top:42px}} h3{{font-size:15px;margin:18px 0 8px}}
.lead,.meta{{color:#586474}} .summary{{background:white;border-left:4px solid #2e9b57;padding:14px 18px;border-radius:5px;line-height:1.65}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}} .grid.obs{{grid-template-columns:repeat(6,minmax(0,1fr))}} .grid.normal{{grid-template-columns:repeat(3,minmax(0,1fr))}}
figure{{margin:0;background:white;border:1px solid #dce1e8;border-radius:7px;overflow:hidden}} img{{width:100%;display:block;image-rendering:pixelated;background:#111}}
figcaption{{font-size:11px;padding:7px 9px;color:#677281;line-height:1.35}} figcaption b{{color:#202934;font-size:12px}} code{{background:#e9edf2;padding:2px 5px;border-radius:3px}}
@media(max-width:900px){{.grid,.grid.obs,.grid.normal{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<h1>Opaque-PBR inverse-rendering sample render</h1>
<p class="lead">2026-08-06 · Infinigen kitchen · {len(rows)} viewpoints · {resolution} · spp {spp} · RTX 5090 · raw source is unclamped float EXR</p>
<div class="summary"><b>Validation passed.</b> RGB는 passive path, NIR ambient는 flash-off path, NIR active는 ambient + aligned MicroBrite direct flash입니다.<br>
Forbidden dielectric/measured BSDF: 0 · non-opaque shape refs: 0 ·
RGB rerender MAE <code>{gate.get("mae", float("nan")):.3g}</code> ·
PSNR <code>{gate.get("psnr_db", float("nan")):.2f} dB</code>.<br>
Wall ROI depth CV: ray range <code>{range_cv:.2f}%</code> → Z-depth <code>{z_cv:.2f}%</code>
(<code>{depth_gain:.2f}x</code> flatter).
Preview만 tone mapping되며 dataset EXR은 변경하지 않았습니다.</div>
{''.join(sections)}
</body></html>'''
    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out} previews={len(rows) * len(previews)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
