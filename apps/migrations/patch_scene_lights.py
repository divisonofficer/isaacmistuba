#!/usr/bin/env python3
"""Patch the baked area-light emitters in a compiled render_scene.xml to cut noise.

Infinigen-imported indoor scenes (e.g. indoor_seed2) light a room with a few
small, very intense ceiling fixtures (e.g. a 0.34 m panel at radiance 300). The
render variance of an area light scales inversely with the solid angle it
subtends, so those tiny-but-bright fixtures produce heavy rice-grain / firefly
noise in the indirectly-lit parts of the room even at 4096 spp — and the OptiX
denoiser barely touches this HDR noise.

This patch, applied directly to the already-compiled ``render_scene.xml`` (no
re-import, no recompile — the daemon loads this file as-is):

  * widens every area-emitter cube in x/z by ``--area-factor`` (keeping it thin
    in y) and divides its radiance by the area increase, so luminous power is
    CONSERVED: same brightness, lower variance;
  * optionally adds one weak ``constant`` ambient emitter (zero variance) to lift
    the dark zones that the envmap/fixtures leave noisy (``--ambient``).

It rewrites only ``<shape type="cube">`` blocks that contain an
``<emitter type="area">``; the ``opticalnav-obj`` authoring comments and all
other geometry are left untouched. A timestamped ``.bak`` is written first.

    # preview the changes without writing
    python apps/migrations/patch_scene_lights.py <render_scene.xml> --dry-run
    # apply to a copy for a test render
    python apps/migrations/patch_scene_lights.py <render_scene.xml> --out /tmp/test_scene.xml
    # apply in place (backs up first)
    python apps/migrations/patch_scene_lights.py <render_scene.xml> --area-factor 2.0 --ambient 0.4
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

# One <shape type="cube"> ... </shape> block that carries an area emitter.
_CUBE_BLOCK = re.compile(
    r'(<shape type="cube"[^>]*>.*?</shape>)',
    re.DOTALL,
)
_SCALE = re.compile(r'(<scale\b[^>]*\bx=")([\d.eE+-]+)("[^>]*\by=")([\d.eE+-]+)("[^>]*\bz=")([\d.eE+-]+)(")')
_RADIANCE = re.compile(r'(<rgb name="radiance" value=")([^"]+)(")')


def _patch_block(block: str, area_factor: float) -> tuple[str, dict | None]:
    if 'emitter type="area"' not in block:
        return block, None
    info: dict = {}

    def scale_sub(m: re.Match) -> str:
        sx, sy, sz = float(m.group(2)), float(m.group(4)), float(m.group(6))
        nx, nz = sx * area_factor, sz * area_factor  # widen x/z, keep y thin
        info["scale"] = (sx, sz, nx, nz)
        return f"{m.group(1)}{nx:.6f}{m.group(3)}{sy:.6f}{m.group(5)}{nz:.6f}{m.group(7)}"

    block = _SCALE.sub(scale_sub, block, count=1)

    def rad_sub(m: re.Match) -> str:
        vals = [float(v) for v in m.group(2).split()]
        new = [v / (area_factor * area_factor) for v in vals]  # conserve power
        info["radiance"] = (vals, new)
        return f"{m.group(1)}{' '.join(f'{v:.6g}' for v in new)}{m.group(3)}"

    block = _RADIANCE.sub(rad_sub, block, count=1)
    return block, info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene_xml", type=Path)
    ap.add_argument("--area-factor", type=float, default=2.0, help="x/z widen factor for area emitters (radiance ÷ factor² to conserve power).")
    ap.add_argument("--ambient", type=float, default=0.0, help="If >0, add one constant ambient emitter at this grey radiance (zero-variance fill).")
    ap.add_argument("--out", type=Path, default=None, help="Write patched XML here instead of in-place (no .bak).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = args.scene_xml.read_text()
    n = [0]
    samples: list[dict] = []

    def repl(m: re.Match) -> str:
        block, info = _patch_block(m.group(1), args.area_factor)
        if info is not None:
            n[0] += 1
            if len(samples) < 3:
                samples.append(info)
        return block

    patched = _CUBE_BLOCK.sub(repl, text)

    if args.ambient > 0.0:
        amb = f'  <emitter type="constant">\n    <rgb name="radiance" value="{args.ambient:.4g} {args.ambient:.4g} {args.ambient:.4g}" />\n  </emitter>\n'
        # insert before the closing </scene>
        patched = re.sub(r'(\s*</scene>\s*)$', "\n" + amb + r"\1", patched, count=1)

    print(f"[patch] area emitters patched: {n[0]} (area_factor={args.area_factor}, radiance ÷{args.area_factor**2:.2f})")
    for s in samples:
        if "radiance" in s:
            old, new = s["radiance"]
            print(f"  e.g. radiance {old} -> {[round(v,2) for v in new]}; scale x/z {s.get('scale')}")
    if args.ambient > 0.0:
        print(f"[patch] added constant ambient emitter radiance={args.ambient}")

    if args.dry_run:
        print("[patch] dry-run: nothing written")
        return 0
    if n[0] == 0:
        print("[patch] no area emitters found — aborting")
        return 1

    if args.out is not None:
        args.out.write_text(patched)
        print(f"[patch] wrote {args.out}")
    else:
        import time as _t  # local import; only needed for in-place backup name
        bak = args.scene_xml.with_suffix(f".xml.bak")
        if not bak.exists():
            shutil.copy2(args.scene_xml, bak)
            print(f"[patch] backup -> {bak}")
        args.scene_xml.write_text(patched)
        print(f"[patch] patched in place: {args.scene_xml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
