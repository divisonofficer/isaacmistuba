from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from robomituba_bridge import read_job_manifest, repo_root_from, resolve_repo_path

from .pipeline import build_scene_dict_from_job


def _try_bootstrap_mitsuba_from_dir(mitsuba_dir: str) -> None:
    """Add Mitsuba's Python bindings to sys.path if present.

    Expected layout (build tree):
      <mitsuba_dir>/python/mitsuba/...
    """
    import sys

    py_dir = os.path.join(mitsuba_dir, "python")
    if os.path.isdir(py_dir) and py_dir not in sys.path:
        sys.path.insert(0, py_dir)


def _materialize_transforms(payload: Any) -> Any:
    """Convert placeholder transform dicts into Mitsuba transform objects."""
    import mitsuba as mi
    import numpy as np

    transform_ctor = getattr(mi, "ScalarTransform4f", getattr(mi, "Transform4f"))

    if isinstance(payload, dict):
        if payload.get("type") == "lookat":
            return transform_ctor.look_at(payload["origin"], payload["target"], payload["up"])
        if payload.get("type") == "matrix":
            matrix = np.asarray(payload["value"], dtype=float).reshape(4, 4)
            return transform_ctor(matrix)
        return {key: _materialize_transforms(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_materialize_transforms(item) for item in payload]
    return payload


def render_scene_dict(
    scene: Dict[str, Any],
    *,
    out_exr: str,
    variant: str = "scalar_rgb",
) -> None:
    """Render a Mitsuba scene dict to an EXR."""
    import mitsuba as mi

    mi.set_variant(variant)
    scene = _materialize_transforms(scene)
    s = mi.load_dict(scene)
    img = mi.render(s)

    out_exr_p = Path(out_exr)
    out_exr_p.parent.mkdir(parents=True, exist_ok=True)
    mi.util.write_bitmap(str(out_exr_p), img)


def exr_to_png(exr_path: str, png_path: str) -> None:
    """Simple EXR->PNG tonemap (clamp + gamma)."""
    import OpenEXR, Imath
    import numpy as np
    from PIL import Image

    exr = OpenEXR.InputFile(exr_path)
    dw = exr.header()["dataWindow"]
    w = dw.max.x - dw.min.x + 1
    h = dw.max.y - dw.min.y + 1

    pt = Imath.PixelType(Imath.PixelType.FLOAT)
    R, G, B = exr.channels(["R", "G", "B"], pt)
    R = np.frombuffer(R, dtype=np.float32).reshape(h, w)
    G = np.frombuffer(G, dtype=np.float32).reshape(h, w)
    B = np.frombuffer(B, dtype=np.float32).reshape(h, w)

    img = np.stack([R, G, B], axis=-1)
    img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)
    img = np.clip(img, 0.0, 1.0)
    img = img ** (1 / 2.2)
    img8 = (img * 255.0 + 0.5).astype(np.uint8)

    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img8, mode="RGB").save(png_path)


def render_json(
    scene_json_path: str,
    *,
    out_dir: str,
    mitsuba_dir: str | None = None,
    variant: str = "scalar_rgb",
    write_png: bool = True,
) -> None:
    """Load scene dict from JSON, render EXR (+PNG)."""

    if mitsuba_dir:
        _try_bootstrap_mitsuba_from_dir(mitsuba_dir)

    scene = json.loads(Path(scene_json_path).read_text(encoding="utf-8"))

    out_dir_p = Path(out_dir)
    out_exr = str(out_dir_p / "render.exr")
    out_png = str(out_dir_p / "render.png")

    render_scene_dict(scene, out_exr=out_exr, variant=variant)

    if write_png:
        exr_to_png(out_exr, out_png)


def render_job(
    manifest_path: str,
    *,
    repo_root: str | Path | None = None,
    out_dir: str | None = None,
    variant: str = "scalar_rgb",
    write_png: bool = True,
    render_mode: str = "rgb",
    width: int = 768,
    height: int = 768,
    spp: int = 64,
    mitsuba_dir: str | None = None,
) -> None:
    if mitsuba_dir:
        _try_bootstrap_mitsuba_from_dir(mitsuba_dir)

    root = Path(repo_root) if repo_root else repo_root_from(manifest_path)
    manifest = read_job_manifest(manifest_path, repo_root=root)
    target_out_dir = Path(out_dir) if out_dir else resolve_repo_path(root, manifest.paths.renders_dir) / render_mode
    scene = build_scene_dict_from_job(
        manifest_path,
        repo_root=root,
        width=width,
        height=height,
        spp=spp,
        render_mode=render_mode,
    )
    render_scene_dict(scene, out_exr=str(target_out_dir / "render.exr"), variant=variant)
    if write_png:
        exr_to_png(str(target_out_dir / "render.exr"), str(target_out_dir / "render.png"))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--scene-json", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--variant", default="scalar_rgb")
    p.add_argument("--mitsuba-dir", default=os.environ.get("MITSUBA_DIR"))
    p.add_argument("--no-png", action="store_true")
    args = p.parse_args()

    render_json(
        args.scene_json,
        out_dir=args.out_dir,
        mitsuba_dir=args.mitsuba_dir,
        variant=args.variant,
        write_png=not args.no_png,
    )
