#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COMPONENTS = [
    ("path_total.png", "RGB / Path Total"),
    ("direct_light_map.png", "Direct Light"),
    ("indirect_light_map.png", "Indirect Light"),
    ("albedo.png", "Albedo"),
    ("diffuse_map.png", "Diffuse Map"),
    ("specular_map.png", "Specular Map"),
    ("depth_jet_colorbar.png", "Depth"),
    ("dop_red_black_colorbar.png", "DoP"),
    ("aolp_rainbow_colorbar.png", "AoLP"),
    ("s1_bwr_colorbar.png", "S1"),
    ("s2_bwr_colorbar.png", "S2"),
    ("polar_rgb_preview.png", "Polar RGB Preview"),
]


def log(message: str) -> None:
    print(message, flush=True)


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        font_path = Path(path)
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def fit_image(path: Path, *, width: int, height: int) -> Image.Image:
    image = Image.open(path).convert("RGB")
    canvas = Image.new("RGB", (width, height), (18, 20, 24))
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    offset = ((width - image.width) // 2, (height - image.height) // 2)
    canvas.paste(image, offset)
    return canvas


def draw_tile(
    sheet: Image.Image,
    draw: ImageDraw.ImageDraw,
    image_path: Path,
    label: str,
    *,
    x: int,
    y: int,
    tile_w: int,
    tile_h: int,
    label_h: int,
    title_font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle(
        (x, y, x + tile_w, y + tile_h),
        radius=18,
        fill=(27, 31, 38),
        outline=(70, 77, 90),
        width=2,
    )
    content_pad = 14
    image_w = tile_w - 2 * content_pad
    image_h = tile_h - label_h - 2 * content_pad
    fitted = fit_image(image_path, width=image_w, height=image_h)
    sheet.paste(fitted, (x + content_pad, y + content_pad))
    label_bbox = draw.textbbox((0, 0), label, font=title_font)
    label_w = label_bbox[2] - label_bbox[0]
    label_x = x + max(content_pad, (tile_w - label_w) // 2)
    label_y = y + tile_h - label_h + max(0, (label_h - (label_bbox[3] - label_bbox[1])) // 2) - 2
    draw.text((label_x, label_y), label, font=title_font, fill=(236, 238, 242))


def make_camera_sheet(camera_dir: Path, output_path: Path) -> Path:
    summary_path = camera_dir / "camera_multimodal_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    camera_name = summary["camera"]["name"]
    camera_label = summary["camera"].get("label", camera_name)
    room = summary["camera"].get("room", "")
    total_time = summary.get("total_pipeline_s", 0.0)

    cols = 4
    rows = 3
    tile_w = 440
    tile_h = 330
    gap = 22
    margin = 28
    header_h = 112
    label_h = 42
    width = margin * 2 + cols * tile_w + (cols - 1) * gap
    height = header_h + margin + rows * tile_h + (rows - 1) * gap + margin

    sheet = Image.new("RGB", (width, height), (240, 236, 228))
    draw = ImageDraw.Draw(sheet)
    header_font = load_font(34)
    sub_font = load_font(21)
    tile_font = load_font(22)

    title = f"{camera_label} ({camera_name})"
    subtitle = f"room={room} | total pipeline={total_time:.2f}s | 12-panel multimodal summary"
    draw.rounded_rectangle(
        (margin, margin, width - margin, margin + header_h - 18),
        radius=22,
        fill=(250, 248, 244),
        outline=(170, 164, 154),
        width=2,
    )
    draw.text((margin + 22, margin + 16), title, font=header_font, fill=(36, 36, 36))
    draw.text((margin + 22, margin + 62), subtitle, font=sub_font, fill=(88, 88, 88))

    grid_top = header_h + margin
    for idx, (filename, label) in enumerate(COMPONENTS):
        image_path = camera_dir / filename
        if not image_path.exists():
            raise FileNotFoundError(f"Missing component image: {image_path}")
        col = idx % cols
        row = idx // cols
        x = margin + col * (tile_w + gap)
        y = grid_top + row * (tile_h + gap)
        draw_tile(
            sheet,
            draw,
            image_path,
            label,
            x=x,
            y=y,
            tile_w=tile_w,
            tile_h=tile_h,
            label_h=label_h,
            title_font=tile_font,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=95)
    return output_path


def make_overview_sheet(sheet_paths: list[Path], output_path: Path) -> Path:
    cols = 2
    rows = (len(sheet_paths) + cols - 1) // cols
    margin = 24
    gap = 24
    thumb_w = 960
    thumb_h = 734
    header_h = 90
    width = margin * 2 + cols * thumb_w + (cols - 1) * gap
    height = header_h + margin + rows * thumb_h + (rows - 1) * gap + margin

    overview = Image.new("RGB", (width, height), (235, 231, 223))
    draw = ImageDraw.Draw(overview)
    header_font = load_font(34)
    draw.text((margin, margin), "Selected Camera Multimodal Sheets", font=header_font, fill=(40, 40, 40))

    for idx, sheet_path in enumerate(sheet_paths):
        image = Image.open(sheet_path).convert("RGB")
        image.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        col = idx % cols
        row = idx // cols
        x = margin + col * (thumb_w + gap)
        y = header_h + margin + row * (thumb_h + gap)
        draw.rounded_rectangle(
            (x, y, x + thumb_w, y + thumb_h),
            radius=20,
            fill=(248, 246, 242),
            outline=(174, 168, 156),
            width=2,
        )
        px = x + (thumb_w - image.width) // 2
        py = y + (thumb_h - image.height) // 2
        overview.paste(image, (px, py))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    overview.save(output_path, quality=95)
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create per-camera multimodal contact sheets.")
    parser.add_argument(
        "--root",
        default="/jarvis/project/robomituba/out/moorelane_green_arrow_candidates_multimodal_full",
        help="Root directory containing per-camera multimodal outputs.",
    )
    parser.add_argument("--name", default=None, help="Optional single camera directory name.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root)
    camera_dirs = sorted(
        p for p in root.iterdir()
        if p.is_dir() and (args.name is None or p.name == args.name)
    )
    if not camera_dirs:
        raise SystemExit("No camera directories found")

    sheet_paths: list[Path] = []
    for camera_dir in camera_dirs:
        output_path = camera_dir / "multimodal_sheet.png"
        log(f"[sheet] start {camera_dir.name}")
        make_camera_sheet(camera_dir, output_path)
        log(f"[sheet] done  {camera_dir.name} -> {output_path}")
        sheet_paths.append(output_path)

    if len(sheet_paths) > 1:
        overview_path = root / "multimodal_sheet_overview.png"
        log(f"[sheet] start overview -> {overview_path}")
        make_overview_sheet(sheet_paths, overview_path)
        log(f"[sheet] done  overview -> {overview_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
