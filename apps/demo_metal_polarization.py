#!/usr/bin/env python3
"""Controlled 'metal palette' polarization demo: a row of spheres, each a different
BSDF (dielectric pplastic + real metals Al/Au/Cr/Ag/Cu), rendered in the polarized
variant via the same render_modalities path used by the production pipeline. Each
material shows a DISTINCT DoLP/AoLP signature -- the physical reason per-material
IOR / eta-k injection matters (vs the legacy "everything = Al / int_ior=1.5").

RUN (standard build env):
    PYTHONPATH=modules/robomituba_bridge/src:modules/mitsuba_converter/src:\
modules/navigation_dataset/src:/home/jinnyeong/robomituba-build/mitsuba3/python \
    LD_LIBRARY_PATH=/usr/lib/wsl/lib \
    /usr/bin/python3.10 apps/demo_metal_polarization.py --out out/bsdf_compare/metal_palette
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

_CHECKER = ('<texture type="checkerboard" name="alpha"><float name="color0" value="0.04"/>'
            '<float name="color1" value="0.35"/><transform name="to_uv"><scale value="5"/>'
            '</transform></texture>')

PRESETS = {
    # metal palette: each real metal has a distinct color + DoLP signature
    "metal": [
        ("plastic", '<bsdf type="pplastic"><rgb name="diffuse_reflectance" value="0.55 0.15 0.15"/>'
                    '<float name="alpha" value="0.1"/></bsdf>'),
        ("Al", '<bsdf type="roughconductor"><string name="material" value="Al"/><float name="alpha" value="0.05"/></bsdf>'),
        ("Au", '<bsdf type="roughconductor"><string name="material" value="Au"/><float name="alpha" value="0.05"/></bsdf>'),
        ("Cr", '<bsdf type="roughconductor"><string name="material" value="Cr"/><float name="alpha" value="0.05"/></bsdf>'),
        ("Ag", '<bsdf type="roughconductor"><string name="material" value="Ag"/><float name="alpha" value="0.05"/></bsdf>'),
        ("Cu", '<bsdf type="roughconductor"><string name="material" value="Cu"/><float name="alpha" value="0.05"/></bsdf>'),
    ],
    # per-texel roughness (patched pplastic): scalar alpha -> uniform gloss;
    # a checkerboard alpha texture -> spatially-varying gloss/DoLP (the new capability).
    "roughness": [
        ("pplastic scalar 0.04", '<bsdf type="pplastic"><rgb name="diffuse_reflectance" value="0.5 0.16 0.16"/>'
                                 '<float name="alpha" value="0.04"/></bsdf>'),
        ("pplastic scalar 0.35", '<bsdf type="pplastic"><rgb name="diffuse_reflectance" value="0.5 0.16 0.16"/>'
                                 '<float name="alpha" value="0.35"/></bsdf>'),
        ("pplastic TEXTURE alpha", f'<bsdf type="pplastic"><rgb name="diffuse_reflectance" value="0.5 0.16 0.16"/>'
                                   f'{_CHECKER}</bsdf>'),
    ],
}
MATERIALS = PRESETS["metal"]  # default; overridden by --preset in main()


def write_scene_xml(path: Path) -> None:
    n = len(MATERIALS)
    shapes = []
    for i, (_, bsdf) in enumerate(MATERIALS):
        x = (i - (n - 1) / 2.0) * 2.4
        shapes.append(
            f'<shape type="sphere"><point name="center" x="{x:.3f}" y="0" z="0"/>'
            f'<float name="radius" value="1"/>{bsdf}</shape>')
    xml = (
        '<scene version="3.0.0">\n'
        '  <integrator type="path"><integer name="max_depth" value="8"/></integrator>\n'
        '  <emitter type="constant"><rgb name="radiance" value="0.9"/></emitter>\n'
        '  <emitter type="point"><point name="position" x="6" y="8" z="8"/>'
        '<rgb name="intensity" value="220"/></emitter>\n'
        '  ' + "\n  ".join(shapes) + "\n</scene>\n")
    path.write_text(xml, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", choices=list(PRESETS), default="metal")
    ap.add_argument("--out", default=None)
    ap.add_argument("--spp", type=int, default=256)
    ap.add_argument("--res", type=int, default=1200)
    a = ap.parse_args()
    global MATERIALS
    MATERIALS = PRESETS[a.preset]
    if a.out is None:
        a.out = f"out/bsdf_compare/{a.preset}_palette"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    xml = out / "metal_palette_scene.xml"
    write_scene_xml(xml)

    from mitsuba_converter.multimodal import (
        RenderConfig, render_modalities, camera_to_world_from_lookat)
    # Use the pipeline's own look-at convention (camera looks down -Z) so the
    # sphere row is framed correctly (mi.look_at uses +Z -> spheres end up behind).
    cam = camera_to_world_from_lookat([0, 1.4, 16.0], [0, 0, 0], [0, 1, 0])
    cfg = RenderConfig(width=a.res, height=a.res // 3, path_spp=a.spp,
                       polar_spp=a.spp, aov_spp=max(4, a.spp // 4), ambient_radiance=1.0)
    render_modalities(xml, cam, 40.0, ["rgb", "dop", "aolp", "s1_over_s0"],
                      out_dir=out, config=cfg, variant="cuda_ad_spectral_polarized")

    # labeled montage: RGB / DoLP / AoLP stacked (materials left->right)
    try:
        from PIL import Image, ImageDraw
        def L(name):
            hits = list(out.rglob(name))
            return Image.open(hits[0]).convert("RGB") if hits else None
        panels = [(t, im) for t, im in (
            ("RGB", L("rgb.png")), ("DoLP", L("dop_red_black_colorbar.png")),
            ("AoLP", L("aolp_rainbow_colorbar.png"))) if im is not None]
        w = max(im.width for _, im in panels); h = max(im.height for _, im in panels)
        pad = 22
        canvas = Image.new("RGB", (w, len(panels) * (h + pad)), "white")
        d = ImageDraw.Draw(canvas)
        row = "   ".join(name for name, _ in MATERIALS)
        for i, (t, im) in enumerate(panels):
            d.text((4, i * (h + pad) + 4), f"{t}     [ {row} ]", fill="black")
            canvas.paste(im.resize((w, h)), (0, i * (h + pad) + pad))
        canvas.save(out / "metal_palette_montage.png")
        print("[metal_palette] montage ->", out / "metal_palette_montage.png")
    except Exception as e:
        print("[metal_palette] montage skipped:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
