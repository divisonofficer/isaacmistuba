#!/usr/bin/env python3
"""A/B(/C) render comparison for the BSDF-injection work (ROBOMITUBA_BSDF_MODE).

Regenerates a scene's ``render_scene.xml`` under each BSDF mode and renders the
same viewpoint(s) with RGB + polarization (DoLP/AoLP), then assembles a montage
+ numeric summary so ``legacy`` (hardcoded int_ior=1.5 / material="Al") can be
compared against ``injected`` (per-material IOR / real metal eta-k) and, if
requested, ``measured`` (measured_polarized reference).

RUN IN THE MITSUBA ENV (needs mitsuba + robomituba modules):
    ROBOMITUBA_MITSUBA_PYTHONPATH=build/mitsuba3-optix7/python \
    LD_LIBRARY_PATH=/usr/lib/wsl/lib \
    <mitsuba_optix7 python> apps/compare_bsdf_modes.py \
        --scene infinigen_kr_20000221 \
        --request out/bridge_jobs/<job>/requests/<frame>.json \
        --modes legacy injected --spp 64 --res 512

Fast Phase-1 check (regenerate XMLs + diff BSDFs, NO render -- still needs the
in-env import but returns in seconds):
    ... apps/compare_bsdf_modes.py --scene infinigen_kr_20000221 --xml-only
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = "opticalnav-v0.2"
POLAR_VARIANT = "cuda_ad_spectral_polarized"


def _scene_dir(project_id: str, scene_id: str) -> Path:
    return REPO / "out" / "opticalnav" / project_id / "scenes" / scene_id


def _read_json(p: Path):
    import json
    return json.loads(p.read_text(encoding="utf-8"))


# --- regenerate render_scene.xml for a given BSDF mode ----------------------

def regenerate_xml(project_id: str, scene_id: str, mode: str, out_path: Path) -> int:
    """Write render_scene.xml for `scene_id` under ROBOMITUBA_BSDF_MODE=mode.
    Returns the shape count. Runs in-process (imports the daemon module)."""
    os.environ["ROBOMITUBA_BSDF_MODE"] = mode
    # Import lazily so --help works without the mitsuba env.
    from mitsuba_converter.render_daemon import (
        RenderDaemon, _generate_opticalnav_render_scene_xml,
    )
    scene_dir = _scene_dir(project_id, scene_id)
    saved = _read_json(scene_dir / "authoring_map.json")
    editor_geometry = None
    eg = scene_dir / "editor_geometry.json"
    if eg.exists():
        try:
            editor_geometry = _read_json(eg)
        except Exception:
            pass
    daemon = RenderDaemon(repo_root=REPO)  # no .start() -> no servers/threads
    project_dir = REPO / "out" / "opticalnav" / project_id
    mesh_resolver = daemon._make_mesh_resolver(project_dir, scene_id)
    return _generate_opticalnav_render_scene_xml(
        saved, saved, out_path,
        editor_geometry=editor_geometry, repo_root=REPO,
        mesh_resolver=mesh_resolver, mesh_stats={},
        materialization_records=[], material_policy_records=[],
    )


def _bsdf_material_histogram(xml_path: Path) -> dict:
    """Cheap XML summary: conductor `material` + dielectric/pplastic int_ior counts."""
    txt = xml_path.read_text(encoding="utf-8")
    mats = Counter(re.findall(r'name="material"\s+value="([^"]+)"', txt))
    iors = Counter(re.findall(r'name="int_ior"\s+value="([^"]+)"', txt))
    blends = txt.count('type="blendbsdf"')
    alpha_tex = len(re.findall(r'<texture name="alpha"', txt))
    return {"materials": dict(mats), "int_ior": dict(iors),
            "blendbsdf": blends, "alpha_textures": alpha_tex}


# --- render one viewpoint's rgb/dop/aolp for a staged xml -------------------

def render_viewpoint(xml_path: Path, cam_to_world, fov_deg: float, out_dir: Path,
                     *, spp: int, res: int, ambient: float) -> dict:
    import numpy as np
    from mitsuba_converter.multimodal import RenderConfig, render_modalities
    cfg = RenderConfig(width=res, height=res, path_spp=spp, polar_spp=spp,
                       aov_spp=max(4, spp // 4), ambient_radiance=ambient)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = render_modalities(
        xml_path, np.asarray(cam_to_world, dtype=float), float(fov_deg),
        ["rgb", "dop", "aolp", "s1_over_s0", "s2_over_s0"],
        out_dir=out_dir, config=cfg, variant=POLAR_VARIANT,
    )
    return {k: result.results[k] for k in result.results}


def _load_camera_from_request(request_path: Path):
    """Return (camera_to_world 4x4, fov_deg). Mirrors what the multibranch tool reads."""
    req = _read_json(request_path)
    # RenderRequest carries camera_spec / cameras; support a few shapes defensively.
    for key in ("cameras", "camera_specs"):
        cams = req.get(key)
        if isinstance(cams, list) and cams:
            c = cams[0]
            c2w = c.get("camera_to_world") or c.get("transform")
            fov = c.get("fov_deg") or c.get("fov_h_deg") or 60.0
            if c2w:
                return c2w, float(fov)
    c2w = req.get("camera_to_world")
    if c2w:
        return c2w, float(req.get("fov_deg", 60.0))
    raise SystemExit(f"[compare] could not find camera_to_world in {request_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--request", default=None,
                    help="saved RenderRequest json (out/bridge_jobs/.../requests/*.json) for the camera")
    ap.add_argument("--modes", nargs="+", default=["legacy", "injected"],
                    choices=["legacy", "injected", "measured"])
    ap.add_argument("--xml-only", action="store_true",
                    help="regenerate render_scene.xml per mode + print BSDF diff; no render")
    ap.add_argument("--spp", type=int, default=64)
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--ambient", type=float, default=1.0, help="ambient fill radiance (raise to brighten a dark viewpoint)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    scene_dir = _scene_dir(a.project, a.scene)
    if not scene_dir.exists():
        raise SystemExit(f"[compare] scene not found: {scene_dir}")
    out_root = Path(a.out) if a.out else (REPO / "out" / "bsdf_compare" / a.scene)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1) regenerate per-mode XMLs
    xmls: dict[str, Path] = {}
    for mode in a.modes:
        xml_path = out_root / f"render_scene_{mode}.xml"
        n = regenerate_xml(a.project, a.scene, mode, xml_path)
        xmls[mode] = xml_path
        hist = _bsdf_material_histogram(xml_path)
        print(f"[{mode}] shapes={n} materials={hist['materials']} "
              f"int_ior={hist['int_ior']} blendbsdf={hist['blendbsdf']} "
              f"alpha_tex={hist['alpha_textures']}")

    if a.xml_only:
        print("\n[compare] --xml-only: BSDF diff printed above. legacy should show "
              "material={'Al': N}/int_ior={'1.5': M}; injected should show real metals "
              "(Au/Cr/Ag/Al) + per-class int_ior.")
        return 0

    # 2) render viewpoint per mode
    if not a.request:
        raise SystemExit("[compare] --request is required for rendering (omit with --xml-only)")
    cam, fov = _load_camera_from_request(Path(a.request))
    montage_inputs: dict[str, dict] = {}
    for mode, xml_path in xmls.items():
        mdir = out_root / mode
        print(f"[{mode}] rendering {a.res}x{a.res} spp={a.spp} -> {mdir}")
        montage_inputs[mode] = render_viewpoint(xml_path, cam, fov, mdir, spp=a.spp, res=a.res, ambient=a.ambient)

    # 3) montage + stats (compose the pipeline's already-colormapped PNGs)
    mode_dirs = {m: out_root / m for m in a.modes}
    _assemble_montage(mode_dirs, out_root / "montage.png")
    print(f"[compare] montage -> {out_root / 'montage.png'}")
    return 0


# modality column -> saved PNG filename (the multimodal pipeline writes these with
# proper colormaps: DoLP red->black, AoLP rainbow/HSV, S1/S2 diverging bwr).
_COL_PNG = {
    "RGB": "rgb.png",
    "DoLP": "dop_red_black_colorbar.png",
    "AoLP": "aolp_rainbow_colorbar.png",
    "S1/S0": "s1_over_s0_bwr_colorbar.png",
}


def _assemble_montage(mode_dirs: dict, out_png: Path) -> None:
    """Rows = mode (+ a diff row), cols = [RGB, DoLP, AoLP, S1/S0], using the
    pipeline's colormapped PNGs. Adds a signed DoLP-diff heatmap and prints stats."""
    import numpy as np
    try:
        from PIL import Image, ImageDraw
    except Exception:
        print("[compare] PIL missing; skipping montage (colormapped PNGs are in the mode dirs)")
        return

    def _find(d: Path, name: str):
        hits = list(Path(d).rglob(name))
        return hits[0] if hits else None

    cols = list(_COL_PNG)
    rows = list(mode_dirs)
    tiles: list[list] = []
    for mode in rows:
        row = []
        for c in cols:
            p = _find(mode_dirs[mode], _COL_PNG[c])
            row.append(Image.open(p).convert("RGB") if p else Image.new("RGB", (256, 256), "gray"))
        tiles.append(row)

    # signed diff row (injected - legacy) for DoLP + AoLP, diverging colormap.
    diff_row = None
    if len(rows) >= 2:
        try:
            import matplotlib.cm as cm
            a = np.load(_find(mode_dirs[rows[0]], "stokes_data.npz"))
            b = np.load(_find(mode_dirs[rows[1]], "stokes_data.npz"))
            def heat(key, scale, cmap):
                d = (np.asarray(b[key], float) - np.asarray(a[key], float)) / scale
                d = np.clip(d * 0.5 + 0.5, 0, 1)
                rgb = (cm.get_cmap(cmap)(d)[..., :3] * 255).astype(np.uint8)
                return Image.fromarray(rgb)
            blank = Image.new("RGB", tiles[0][0].size, "white")
            diff_row = [blank,
                        heat("dop", 0.5, "bwr"),            # +-0.5 DoLP
                        heat("aolp", np.pi, "twilight"),    # +-pi AoLP
                        blank]
            dd = np.abs(np.asarray(b["dop"], float) - np.asarray(a["dop"], float))
            print(f"[diff] DoLP |Δ| mean={dd.mean():.4f} max={dd.max():.4f} ; "
                  f">0.05 on {100*(dd>0.05).mean():.1f}% of pixels")
        except Exception as e:
            print(f"[compare] diff row skipped ({e})")

    all_rows = tiles + ([diff_row] if diff_row else [])
    labels = list(rows) + (["diff (injected - legacy)"] if diff_row else [])
    w = max(im.width for r in all_rows for im in r)
    h = max(im.height for r in all_rows for im in r)
    pad = 24
    header = 20
    canvas = Image.new("RGB", (len(cols) * w, header + len(all_rows) * (h + pad)), "white")
    d = ImageDraw.Draw(canvas)
    for ci, c in enumerate(cols):
        d.text((ci * w + 4, 4), c, fill="black")
    for ri, row in enumerate(all_rows):
        y0 = header + ri * (h + pad)
        d.text((4, y0 + 4), labels[ri], fill="black")
        for ci, im in enumerate(row):
            canvas.paste(im.resize((w, h)), (ci * w, y0 + pad))
    canvas.save(out_png)


if __name__ == "__main__":
    raise SystemExit(main())
