#!/usr/bin/env python3
"""Single-object 'material closeup' viewpoints for the RGB-vs-polarization report.

Thesis of the report: *"this material looks like <X> in RGB but like <Y> in
polarization."* A whole-room viewpoint drowns each material's polarization
signature in surrounding geometry, so this tool instead **frames one optically
interesting object at a time**, tightly, with the surroundings minimized.

Selection: objects whose injected BSDF is a metal / mirror / glass (roughconductor
/ conductor / dielectric) -- the classes with a strong, material-specific DoLP/AoLP
signature -- ranked by isolation (nearest-neighbour distance) and apparent size.

Framing: the object's world bbox is read from its baked mesh (mesh_cache OBJ +
XML translate). The camera is placed in the *open* direction (toward the scene
centroid) at a distance that makes the object fill ~`--fill` of the frame, looking
at the bbox centre with a slight downward tilt -> the object dominates, the wall /
floor behind is what little background remains.

Renders the injected mode (physical per-material IOR / eta-k) in the polarized
variant and writes a per-object montage [RGB | DoLP | AoLP | S1/S0] labelled with
the material. `--also-legacy` adds the legacy (int_ior=1.5 / Al) render for A/B.

RUN (standard build env):
    PYTHONPATH=modules/robomituba_bridge/src:modules/mitsuba_converter/src:\
modules/navigation_dataset/src:/home/jinnyeong/robomituba-build/mitsuba3/python \
    LD_LIBRARY_PATH=/usr/lib/wsl/lib \
    /usr/bin/python3.10 apps/render_material_closeups.py \
        --scene infinigen_kr_20260625 --k 6 --spp 1024 --res 640
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PROJECT = "opticalnav-v0.2"
STRAT_CLASS = {"roughconductor": "metal", "conductor": "mirror", "dielectric": "glass"}
CLASS_ORDER = {"mirror": 0, "glass": 1, "metal": 2}
_COL_PNG = [
    ("RGB", "rgb.png"),
    ("DoLP", "dop_red_black_colorbar.png"),
    ("AoLP", "aolp_rainbow_colorbar.png"),
    ("S1/S0", "s1_over_s0_bwr_colorbar.png"),
]


def _scene_dir(scene: str) -> Path:
    return REPO / "out" / "opticalnav" / PROJECT / "scenes" / scene


def _obj_bbox(obj_path: Path) -> tuple[list[float], list[float]] | None:
    """Local axis-aligned bbox (min, max) from an OBJ's vertex 'v' lines."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    try:
        with obj_path.open() as fh:
            for line in fh:
                if line[:2] == "v " or line.startswith("v "):
                    parts = line.split()
                    if len(parts) >= 4:
                        for i in range(3):
                            val = float(parts[i + 1])
                            lo[i] = min(lo[i], val)
                            hi[i] = max(hi[i], val)
    except Exception:
        return None
    if not all(map(math.isfinite, lo + hi)):
        return None
    return lo, hi


def _parse_shape_geometry(xml_path: Path) -> dict[str, dict]:
    """object_id -> {obj: Path, translate: [x,y,z]} from the generated scene XML.
    Only translate-only shapes are returned (scale/rotate shapes are skipped so the
    OBJ-bbox framing stays exact)."""
    txt = xml_path.read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for m in re.finditer(r'<shape\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</shape>', txt, re.S):
        oid, body = m.group(1), m.group(2)
        if "<rotate" in body or "<scale" in body:
            continue
        fn = re.search(r'filename"\s+value="([^"]+\.obj)"', body)
        tr = re.search(r'<translate\s+x="([-\d.eE]+)"\s+y="([-\d.eE]+)"\s+z="([-\d.eE]+)"', body)
        if fn and tr:
            out[oid] = {"obj": Path(fn.group(1)), "translate": [float(tr.group(i)) for i in (1, 2, 3)]}
    return out


def select_objects(scene: str, k: int, include_plastic: bool, min_aspect: float = 0.3) -> list[dict]:
    saved = json.loads((_scene_dir(scene) / "authoring_map.json").read_text())
    objs = saved["objects"]
    mats = {m["material_id"]: m for m in saved["materials"]}
    positions = []
    for o in objs:
        c = (o.get("geometry") or {}).get("center") or [0.0, 0.0]
        positions.append((float(c[0]), float(c[1])))
    centroid = [sum(p[0] for p in positions) / len(positions),
                sum(p[1] for p in positions) / len(positions)]

    cands: list[dict] = []
    for o, (x, y) in zip(objs, positions):
        mat = mats.get(o.get("material"))
        if not mat:
            continue
        strat = (mat.get("render_binding") or {}).get("bsdf_strategy")
        cls = STRAT_CLASS.get(strat)
        if cls is None and not (include_plastic and strat == "pplastic"):
            continue
        if cls is None:
            cls = "plastic"
        size = (o.get("geometry") or {}).get("size_m") or [0.3, 0.3, 0.3]
        ssz = sorted(float(v) for v in size)
        aspect = ssz[0] / max(ssz[2], 1e-3)     # smallest/largest extent
        if aspect < min_aspect:
            continue                             # flat/thin (wall mirrors, panels) -> sliver when framed
        halfw = 0.5 * max(float(size[0]), float(size[2]))
        nn = min((math.hypot(x - ox, y - oy) for (ox, oy) in positions if (ox, oy) != (x, y)), default=9.0)
        cands.append(dict(
            id=o["id"], label=o["label"], cls=cls, strategy=strat,
            material=o.get("material"), center=[x, y], halfw=halfw, nn=nn,
            base_height=(o.get("geometry") or {}).get("base_height_m") or 0.0,
        ))
    # rank: most isolated first (clean background), then class priority, then larger.
    cands.sort(key=lambda c: (-c["nn"], CLASS_ORDER.get(c["cls"], 9), -c["halfw"]))
    # keep class diversity (mirror / glass / metal): cap per class ~ k/3 so a single
    # class can't monopolise the report.
    per_class_cap = max(1, math.ceil(k / max(1, len(CLASS_ORDER))))
    picked: list[dict] = []
    seen_cls: dict[str, int] = {}
    for c in cands:
        if seen_cls.get(c["cls"], 0) >= per_class_cap:
            continue
        picked.append(c)
        seen_cls[c["cls"]] = seen_cls.get(c["cls"], 0) + 1
        if len(picked) >= k:
            break
    if len(picked) < k:
        for c in cands:
            if c not in picked:
                picked.append(c)
            if len(picked) >= k:
                break
    return picked, centroid


def frame_camera(geom: dict, centroid: list[float], fill: float, fov_deg: float):
    """Return (camera_to_world 4x4, target) framing the object's world bbox."""
    from mitsuba_converter.multimodal import camera_to_world_from_lookat
    lo, hi = geom["bbox"]
    tr = geom["translate"]
    wlo = [lo[i] + tr[i] for i in range(3)]
    whi = [hi[i] + tr[i] for i in range(3)]
    center = [(wlo[i] + whi[i]) / 2.0 for i in range(3)]
    diag = math.dist(wlo, whi)
    radius = max(0.5 * diag, 0.15)
    # distance so the object subtends ~`fill` of the frame height.
    half_ang = math.radians(fov_deg) * 0.5 * fill
    d = radius / max(math.tan(half_ang), 1e-3)
    # open direction: from object toward scene centroid (into the room, away from wall).
    ox, oz = center[0], center[2]
    dx, dz = centroid[0] - ox, centroid[1] - oz
    n = math.hypot(dx, dz) or 1.0
    dx, dz = dx / n, dz / n
    # Camera height in a comfortable viewing band [0.9, 1.6] m (NOT center_y+0.35r,
    # which skims the floor for floor-standing objects and hits the ceiling for
    # shelf objects). The vertical offset to `center` gives a natural look-down /
    # look-up; horizontal standoff is set so the 3D distance stays ~= d (framing).
    eye_y = min(2.0, max(0.9, center[1]))
    dy = eye_y - center[1]
    horiz = math.sqrt(max(d * d - dy * dy, (0.45 * d) ** 2))
    eye = [ox + dx * horiz, eye_y, oz + dz * horiz]
    c2w = camera_to_world_from_lookat(eye, center, [0.0, 1.0, 0.0])
    return c2w, center, radius, d, eye


def _inject_point_light(src_xml: Path, dst_xml: Path, position, intensity: float) -> None:
    """Write a copy of src_xml with a camera-side point emitter added. The scene's
    own lights are dim/uneven, so this fill light guarantees the framed object is
    consistently lit (product-shot / flash style) regardless of scene lighting."""
    txt = src_xml.read_text(encoding="utf-8")
    x, y, z = position
    i = float(intensity)
    emitter = (f'  <emitter type="point"><point name="position" '
               f'x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>'
               f'<rgb name="intensity" value="{i:.3f} {i:.3f} {i:.3f}"/></emitter>\n')
    dst_xml.write_text(txt.replace("</scene>", emitter + "</scene>"), encoding="utf-8")


def _shadow_lift_rgb(mode_dir: Path):
    """Re-tonemap the linear HDR RGB (stokes_data.npz['rgb']) with a shadow-lifting
    exposure + Reinhard highlight compression + sRGB gamma, so dark diffuse surfaces
    are visible. The saved rgb.png auto-exposes on a specular percentile, which crushes
    shadows in these dim indoor closeups. Returns a PIL image, or None if no npz."""
    import numpy as np
    from PIL import Image
    hits = list(mode_dir.rglob("stokes_data.npz"))
    if not hits:
        return None
    lin = np.clip(np.nan_to_num(np.asarray(np.load(hits[0])["rgb"], float)), 0.0, None)
    lum = lin.mean(-1)
    pos = lum[lum > 0]
    p90 = float(np.percentile(pos, 90)) if pos.size else 0.1
    e = 2.33 / max(p90, 1e-4)                       # map bright level p90 -> Reinhard 0.7
    tm = (e * lin) / (1.0 + e * lin)                # per-channel Reinhard (soft-clip speculars)
    srgb = np.where(tm <= 0.0031308, 12.92 * tm, 1.055 * np.power(tm, 1 / 2.4) - 0.055)
    return Image.fromarray((np.clip(srgb, 0, 1) * 255).astype("uint8"))


def _montage(mode_dir: Path, label: str, out_png: Path, *, shadow_lift: bool = True) -> None:
    from PIL import Image, ImageDraw
    tiles = []
    for col, name in _COL_PNG:
        if col == "RGB" and shadow_lift:
            lifted = _shadow_lift_rgb(mode_dir)
            if lifted is not None:
                tiles.append(lifted)
                continue
        hits = list(mode_dir.rglob(name))
        tiles.append(Image.open(hits[0]).convert("RGB") if hits else Image.new("RGB", (256, 256), "gray"))
    w = max(t.width for t in tiles)
    h = max(t.height for t in tiles)
    header = 22
    canvas = Image.new("RGB", (len(tiles) * w, h + header), "white")
    d = ImageDraw.Draw(canvas)
    # column titles centred per tile (object label lives in the report figcaption).
    for i, (title, _) in enumerate(_COL_PNG):
        d.text((i * w + w // 2 - 4 * len(title), 6), title, fill="black")
    for i, t in enumerate(tiles):
        canvas.paste(t.resize((w, h)), (i * w, header))
    canvas.save(out_png)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scene", default="infinigen_kr_20260625")
    ap.add_argument("--k", type=int, default=6, help="number of objects to frame")
    ap.add_argument("--spp", type=int, default=1024)
    ap.add_argument("--res", type=int, default=640)
    ap.add_argument("--fov", type=float, default=45.0)
    ap.add_argument("--fill", type=float, default=0.72, help="fraction of frame the object should fill")
    ap.add_argument("--min-aspect", type=float, default=0.3,
                    help="reject objects flatter than this (min/max extent) -- wall mirrors/panels render as slivers")
    ap.add_argument("--ambient", type=float, default=3.0, help="ambient fill radiance (NOTE: ignored when the scene already has emitters)")
    ap.add_argument("--headlight", type=float, default=6.0,
                    help="camera-side fill point light: irradiance base (intensity = headlight * dist^2); 0 disables")
    ap.add_argument("--backlight", type=float, default=0.0,
                    help="point light BEHIND the object (transmission/rim for glass); irradiance base; 0 disables")
    ap.add_argument("--only-class", choices=["metal", "glass", "mirror"], default=None,
                    help="render only objects of this optical class")
    ap.add_argument("--also-legacy", action="store_true", help="also render legacy mode for A/B")
    ap.add_argument("--regen-injected", action="store_true",
                    help="rebuild the injected XML instead of reusing the scene's render_scene.xml (~7 min)")
    ap.add_argument("--injected-xml", default=None,
                    help="use this pre-built injected XML (e.g. the GLB-routed one) instead of the scene's render_scene.xml")
    ap.add_argument("--only-select", action="store_true", help="print the chosen objects + cameras, no render")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    import apps.compare_bsdf_modes as C

    out_root = Path(a.out) if a.out else (REPO / "out" / "bsdf_compare" / f"closeups_{a.scene}")
    out_root.mkdir(parents=True, exist_ok=True)

    picked, centroid = select_objects(a.scene, a.k, include_plastic=False, min_aspect=a.min_aspect)
    if a.only_class:
        picked = [c for c in picked if c["cls"] == a.only_class][:a.k]

    # Geometry (obj path + translate) is BSDF-mode-independent, so read it from the
    # scene's existing render_scene.xml -- avoids the slow per-mode XML rebuild when
    # we only need framing (e.g. --only-select).
    geom_map = _parse_shape_geometry(_scene_dir(a.scene) / "render_scene.xml")

    modes = ["injected"] + (["legacy"] if a.also_legacy else [])
    xmls: dict[str, Path] = {}
    if not a.only_select:
        for mode in modes:
            # The scene's production render_scene.xml is already the injected build
            # (per-class IOR + real metal eta-k), so reuse it and skip the ~7 min
            # rebuild unless --regen-injected is given. legacy always regenerates.
            if mode == "injected" and not a.regen_injected:
                # Copy (not reference) the production injected XML into the clean out
                # dir so scene staging (.staged_mitsuba/) happens fresh -- the scene
                # dir carries a stale staged cache from daemon runs. Paths are absolute.
                # --injected-xml lets a caller supply a pre-built injected XML (e.g. the
                # GLB-routed one) to skip the ~7 min rebuild.
                import shutil
                src_xml = Path(a.injected_xml) if a.injected_xml else (_scene_dir(a.scene) / "render_scene.xml")
                xp = out_root / "render_scene_injected.xml"
                shutil.copyfile(src_xml, xp)
                xmls["injected"] = xp
                continue
            xp = out_root / f"render_scene_{mode}.xml"
            C.regenerate_xml(PROJECT, a.scene, mode, xp)
            xmls[mode] = xp

    manifest = []
    for rank, c in enumerate(picked, 1):
        g = geom_map.get(c["id"])
        if not g:
            print(f"  [skip] {c['id']} not translate-only / not in XML", flush=True)
            continue
        bbox = _obj_bbox(g["obj"])
        if bbox is None:
            print(f"  [skip] {c['id']} bbox read failed", flush=True)
            continue
        g["bbox"] = bbox
        c2w, center, radius, dist, eye = frame_camera(g, centroid, a.fill, a.fov)
        slug = re.sub(r"[^0-9A-Za-z]+", "_", c["label"])[:40].strip("_")
        tag = f"{rank:02d}_{c['cls']}_{slug}"
        print(f"[{rank}] {c['cls']:6s} {c['strategy']:14s} {c['label'][:44]:44s} "
              f"r={radius:.2f} d={dist:.2f} eye_y={eye[1]:.2f} nn={c['nn']:.2f}", flush=True)
        rec = dict(rank=rank, tag=tag, center=center, radius=radius, dist=dist, eye=eye, **{k: c[k] for k in ("id", "label", "cls", "strategy", "material", "nn")})
        manifest.append(rec)
        if a.only_select:
            continue
        vp_out = out_root / tag
        vp_out.mkdir(parents=True, exist_ok=True)
        # camera-side fill light: raised slightly above the eye; intensity ~ d^2 so
        # irradiance on the object stays consistent regardless of standoff distance.
        headlight_pos = [eye[0], eye[1] + 0.35, eye[2]]
        headlight_i = a.headlight * dist * dist
        # optional backlight BEHIND the object (far side from camera), raised: for
        # dielectrics it lights the object's back so transmission/refraction reads.
        bdir = [center[i] - eye[i] for i in range(3)]
        bn = math.sqrt(sum(v * v for v in bdir)) or 1.0
        bd = radius + 0.5
        backlight_pos = [center[0] + bdir[0] / bn * bd, center[1] + bdir[1] / bn * bd + 0.25, center[2] + bdir[2] / bn * bd]
        backlight_i = a.backlight * bd * bd
        for mode in modes:
            src = xmls[mode]
            if a.headlight > 0:
                lit = vp_out / f"render_{mode}_lit.xml"
                _inject_point_light(src, lit, headlight_pos, headlight_i)
                src = lit
            if a.backlight > 0:
                lit2 = vp_out / f"render_{mode}_lit2.xml"
                _inject_point_light(src, lit2, backlight_pos, backlight_i)
                src = lit2
            C.render_viewpoint(src, c2w, a.fov, vp_out / mode,
                               spp=a.spp, res=a.res, ambient=a.ambient)
            _montage(vp_out / mode, f"{c['cls']} · {c['label'][:40]} [{mode}]", vp_out / f"montage_{mode}.png")
        (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"  [ok] {tag} -> {vp_out}", flush=True)

    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n[closeups] {len(manifest)} objects -> {out_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
