from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .pipeline import convert_usd_to_mitsuba_dict
from .render import render_job, render_json


def _json_ready(payload: Any) -> Any:
    if hasattr(payload, "tolist"):
        return payload.tolist()
    if isinstance(payload, dict):
        return {key: _json_ready(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_json_ready(item) for item in payload]
    return payload


def cmd_convert(args) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene_dict = convert_usd_to_mitsuba_dict(args.usd, width=args.width, height=args.height, spp=args.spp)
    out_path = out_dir / "scene.mitsuba.json"
    out_path.write_text(json.dumps(_json_ready(scene_dict), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}")


def cmd_render(args) -> None:
    render_json(
        args.scene_json,
        out_dir=args.out,
        mitsuba_dir=args.mitsuba_dir,
        variant=args.variant,
        write_png=not args.no_png,
    )
    print(f"Rendered to: {args.out}")


def cmd_render_job(args) -> None:
    render_job(
        args.manifest,
        out_dir=args.out,
        repo_root=args.repo_root,
        variant=args.variant,
        write_png=not args.no_png,
        render_mode=args.mode,
        width=args.width,
        height=args.height,
        spp=args.spp,
        mitsuba_dir=args.mitsuba_dir,
    )
    print(f"Rendered job to: {args.out or args.manifest}")


def main() -> None:
    p = argparse.ArgumentParser(prog="mitsuba_converter")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_conv = sub.add_parser("convert", help="USD -> Mitsuba scene dict JSON")
    p_conv.add_argument("--usd", required=True)
    p_conv.add_argument("--out", required=True)
    p_conv.add_argument("--width", type=int, default=768)
    p_conv.add_argument("--height", type=int, default=768)
    p_conv.add_argument("--spp", type=int, default=64)
    p_conv.set_defaults(fn=cmd_convert)

    p_r = sub.add_parser("render", help="Render a Mitsuba scene dict JSON")
    p_r.add_argument("--scene-json", required=True)
    p_r.add_argument("--out", required=True, help="Output directory")
    p_r.add_argument("--variant", default="scalar_rgb")
    p_r.add_argument("--mitsuba-dir", default=None, help="Mitsuba build/install dir (contains python/)")
    p_r.add_argument("--no-png", action="store_true")
    p_r.set_defaults(fn=cmd_render)

    p_job = sub.add_parser("render-job", help="Render a bridge job manifest")
    p_job.add_argument("--manifest", required=True)
    p_job.add_argument("--out", default=None, help="Optional output directory override")
    p_job.add_argument("--repo-root", default=None, help="Optional repo root override for path resolution")
    p_job.add_argument("--mode", default="rgb", choices=["rgb", "polarization", "nir"])
    p_job.add_argument("--variant", default="scalar_rgb")
    p_job.add_argument("--width", type=int, default=768)
    p_job.add_argument("--height", type=int, default=768)
    p_job.add_argument("--spp", type=int, default=64)
    p_job.add_argument("--mitsuba-dir", default=None, help="Mitsuba build/install dir (contains python/)")
    p_job.add_argument("--no-png", action="store_true")
    p_job.set_defaults(fn=cmd_render_job)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
