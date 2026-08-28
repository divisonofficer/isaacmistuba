#!/usr/bin/env python3
"""Render canonical direct-vs-path polarization transport fixtures.

The fixtures deliberately use closed, finite-thickness geometry: no
``thindielectric`` is used because it is not a polarized BSDF.  They are a
small regression suite for transmission/reflection paths before scene-scale
OpticalNav renders are accepted.

Example (from a host with the Mitsuba polarized build configured)::

    python apps/render_polar_transport_fixtures.py --out out/polar_transport_fixtures_v1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from mitsuba_converter.multimodal import (
    RenderConfig, camera_to_world_from_lookat, render_modalities,
)


FIXTURES: dict[str, str] = {
    "glass_window": """<shape type='cube'><transform name='to_world'><scale x='2.6' y='1.8' z='0.06'/><translate z='0.4'/></transform><bsdf type='dielectric'><float name='int_ior' value='1.5'/></bsdf></shape>
<shape type='rectangle'><transform name='to_world'><translate z='1.8'/><scale x='3' y='2'/></transform><bsdf type='diffuse'><rgb name='reflectance' value='0.1 0.35 0.8'/></bsdf></shape>""",
    "glass_bottle": """<shape type='sphere'><transform name='to_world'><scale x='0.9' y='1.35' z='0.9'/></transform><bsdf type='dielectric'><float name='int_ior' value='1.5'/></bsdf></shape>
<shape type='rectangle'><transform name='to_world'><translate z='1.8'/><scale x='3' y='2'/></transform><bsdf type='diffuse'><rgb name='reflectance' value='0.8 0.18 0.08'/></bsdf></shape>""",
    "back_silvered_mirror": """<shape type='cube'><transform name='to_world'><scale x='2.4' y='1.7' z='0.06'/><translate z='0.3'/></transform><bsdf type='dielectric'><float name='int_ior' value='1.5'/></bsdf></shape>
<shape type='cube'><transform name='to_world'><scale x='2.4' y='1.7' z='0.025'/><translate z='0.42'/></transform><bsdf type='conductor'><string name='material' value='Ag'/></bsdf></shape>
<shape type='rectangle'><transform name='to_world'><rotate y='180'/><translate z='-2.0'/><scale x='3' y='2'/></transform><bsdf type='diffuse'><rgb name='reflectance' value='0.15 0.65 0.24'/></bsdf></shape>""",
}


def _scene_xml(body: str) -> str:
    return """<scene version='3.0.0'>
  <integrator type='path'><integer name='max_depth' value='10'/></integrator>
  <emitter type='constant'><rgb name='radiance' value='0.35 0.35 0.35'/></emitter>
%s
</scene>""" % body


def _stokes_stats(path: Path) -> dict[str, float | int]:
    arrays = np.load(path / "stokes_data.npz")
    s0 = np.asarray(arrays["s0_l"], dtype=np.float64)
    dop = np.asarray(arrays["dop"], dtype=np.float64)
    finite = np.isfinite(s0) & np.isfinite(dop)
    return {
        "finite_ratio": float(finite.mean()),
        "invalid_pixel_count": int(finite.size - finite.sum()),
        "s0_mean": float(np.nanmean(s0)),
        "dolp_mean": float(np.nanmean(dop)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spp", type=int, default=256)
    parser.add_argument("--res", type=int, default=320)
    parser.add_argument("--variant", default="cuda_ad_spectral_polarized")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    camera = camera_to_world_from_lookat([0, 0, -5], [0, 0, 0], [0, 1, 0])
    report: dict[str, object] = {"schema": "robomituba.polar-transport-fixtures.v1", "fixtures": {}}
    for name, body in FIXTURES.items():
        fixture_dir = args.out / name
        fixture_dir.mkdir(exist_ok=True)
        scene = fixture_dir / "scene.xml"
        scene.write_text(_scene_xml(body), encoding="utf-8")
        entry: dict[str, object] = {}
        for transport in ("preview", "physical"):
            render_dir = fixture_dir / transport
            cfg = RenderConfig(width=args.res, height=args.res, polar_spp=args.spp,
                               path_spp=args.spp, polar_transport=transport)
            render_modalities(scene, camera, 55.0, ["rgb", "dop"], out_dir=render_dir,
                              config=cfg, variant=args.variant)
            entry[transport] = _stokes_stats(render_dir)
        report["fixtures"][name] = entry
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
