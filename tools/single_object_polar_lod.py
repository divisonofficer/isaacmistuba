#!/usr/bin/env python3
"""Single-object polarization LOD test harness.

Renders one Infinigen prop in isolation under active polarized lighting, across
mesh LOD levels (trimesh quadric decimation), on the discrete-band
``cuda_ad_rgb_polarized`` Stokes carrier, and measures how the polarization
signal (DoLP / AoLP / S1,S2) degrades vs the original high-poly mesh — judged
against the Monte-Carlo noise floor (original rendered at two seeds).

Design ref: dev_report/report_2026-07-28_mesh_opt_plan.html and the 07-06
optical-class polarization report (polarized-trio materials, area-emitter +
`polarizer` BSDF active light).

GPU-free parts (mesh LOD, scene dict, metric fns) run under --dry-run so the
harness can be prepared and validated before the GPU is available.

Env: LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib
     PYTHONPATH=build/mitsuba3-optix7/python  python=~/miniconda3/envs/openusd_pip/bin/python
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

REPO = Path(__file__).resolve().parents[1]
IMPORT_DIR = REPO / "out/infinigen_imports/kr_20260625"

# NIR (854 nm) class-prior diffuse-reflectance synthesis (per material slot).
# Assigns a physically-reasoned NIR reflectance from the shader/optical_class,
# instead of the old NIR=f(RGB) uniform placeholder. Optional import.
for _p in (REPO / "modules/mitsuba_converter/src", REPO / "modules/robomituba_bridge/src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:
    from mitsuba_converter.nir_reflectance import nir_scalar_reflectance
except Exception:  # pragma: no cover - report harness still runs (falls back to 0.45)
    nir_scalar_reflectance = None
OUT_DIR = REPO / "dev_report/images/polar_lod_2026-07-28"
TMP = Path(os.environ.get("POLAR_LOD_TMP", "/tmp/claude-1000/polar_lod"))
# Source OBJs live on a slow CIFS mount; a local copy (basename match) is used
# when present. Populate with: cp out/infinigen_imports/.../meshes/<obj> $LOCAL_MESH
LOCAL_MESH = Path(os.environ.get("POLAR_LOD_MESH_CACHE", "/tmp/claude-1000/polar_lod/meshes"))


def resolve_mesh(rel: str) -> Path:
    local = LOCAL_MESH / Path(rel).name
    return local if local.is_file() else (IMPORT_DIR / rel)
VARIANT = "cuda_ad_rgb_polarized"

# --- 6 representative assets (mesh_obj relative to IMPORT_DIR) -------------- #
ASSETS = {
    "trinket_4M": dict(cls="diffuse", mesh="meshes/NatureShelfTrinketsFactory_6251345_.spawn_asset_4288383.obj"),  # 4.08M
    "trinket_0p5M_a": dict(cls="diffuse", mesh="meshes/NatureShelfTrinketsFactory_6486623_.spawn_asset_9785791.obj"),  # 0.53M
    "trinket_0p5M_b": dict(cls="diffuse", mesh="meshes/NatureShelfTrinketsFactory_7695705_.spawn_asset_742423.obj"),  # 0.53M
    # multi-material: unit optical_class is the CONTAINER; most geometry is diffuse
    # foliage. Rendered per material_slot (see MANIFEST / load_shapes) so the
    # cactus/mushrooms render diffuse and only the pot/vessel is metal/glass.
    "plant_metal": dict(cls="metal_aluminum", multi=True, unit_id="PlantContainerFactory_9090854_.spawn_asset_3503537", mesh="meshes/PlantContainerFactory_9090854_.spawn_asset_3503537.obj"),  # 1.31M
    "plant_glass": dict(cls="glass", multi=True, unit_id="PlantContainerFactory_8288363_.spawn_asset_1688329", mesh="meshes/PlantContainerFactory_8288363_.spawn_asset_1688329.obj"),  # 1.53M
    "cabinet_ctrl": dict(cls="diffuse", mesh="meshes/SingleCabinetFactory_2136931_.spawn_asset_7995440.obj"),  # 0.09M ctrl
}
# Percentage-of-original LOD sweep (fair across assets of different sizes).
# label = "<pct>pct"; orig is "100pct". Floored at MIN_FACES to avoid degeneracy.
LOD_FRACTIONS = [0.30, 0.10, 0.03, 0.01]
MIN_FACES = 150
# active-light conditions: (label, azimuth_deg incidence orbit, polarizer_theta_deg)
LIGHTS = [("az35_p0", 35.0, 0.0), ("az65_p0", 65.0, 0.0), ("az65_p90", 65.0, 90.0)]
PANEL_LIGHT = "az65_p0"  # lighting condition whose modality images go in the report
BANDS = ["visible", "nir_854"]
_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)
MANIFEST = IMPORT_DIR / "scene_manifest.json"

# Illustrative diffuse albedo per material-slot semantic (keyword match on the
# Infinigen shader name). These make the S0/RGB panel legible and prove the
# per-slot BSDF assignment by eye; they are placeholders (the polarization
# signal of a pplastic slot comes from its dielectric coat, not the albedo hue).
SLOT_ALBEDO = {
    "cactus": [0.13, 0.42, 0.11], "spikes": [0.55, 0.52, 0.30],
    "dirt": [0.24, 0.15, 0.08], "mushroom": [0.62, 0.34, 0.27],
    "sand": [0.78, 0.70, 0.52], "speckle": [0.42, 0.42, 0.42],
    "leaf": [0.16, 0.40, 0.14], "wood": [0.35, 0.22, 0.11],
}


def slot_albedo(matname: str | None) -> list | None:
    if not matname:
        return None
    n = matname.lower()
    for k, c in SLOT_ALBEDO.items():
        if k in n:
            return c
    return None


def slot_optical_classes(unit_id: str) -> dict:
    """{usemtl_name -> optical_class} from the scene manifest material_slots."""
    man = json.loads(MANIFEST.read_text())
    for u in man.get("units", []):
        if u.get("id") == unit_id:
            return {s["name"]: s.get("optical_class", "diffuse")
                    for s in u.get("material_slots", [])}
    return {}


def load_obj_groups(path: Path) -> tuple[np.ndarray, list]:
    """Parse an OBJ into shared vertices + per-usemtl triangle groups.
    Returns (V[N,3] float64, [(matname, faces[M,3] int64), ...]).
    Faces reference the first (vertex) index of each f token; polygons are
    fan-triangulated. Handles positive indices (Infinigen exports use them)."""
    verts: list = []
    groups: list = []
    cur: list | None = None
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                verts.append(line.split()[1:4])
            elif line.startswith("usemtl"):
                name = line.split(None, 1)[1].strip()
                cur = []
                groups.append((name, cur))
            elif line.startswith("f ") and cur is not None:
                idx = [int(t.split("/", 1)[0]) - 1 for t in line.split()[1:]]
                for k in range(1, len(idx) - 1):
                    cur.append((idx[0], idx[k], idx[k + 1]))
    V = np.asarray(verts, dtype=np.float64)
    return V, [(n, np.asarray(fs, dtype=np.int64)) for n, fs in groups if fs]


# --------------------------------------------------------------------------- #
# Mesh LOD
# --------------------------------------------------------------------------- #
def load_normalized(mesh_path: Path) -> trimesh.Trimesh:
    m = trimesh.load(mesh_path, process=False, force="mesh")
    m = trimesh.Trimesh(vertices=np.asarray(m.vertices), faces=np.asarray(m.faces), process=False)
    # center at origin, scale longest extent to 0.3 m (typical prop framing)
    m.apply_translation(-m.bounding_box.centroid)
    scale = 0.30 / max(m.extents.max(), 1e-6)
    m.apply_scale(scale)
    return m


def make_lods(m: trimesh.Trimesh) -> list[dict]:
    """Return [{label, mesh, faces}] : original + decimations to LOD_BUDGETS."""
    orig_n = len(m.faces)
    lods = [{"label": "orig", "mesh": m, "faces": orig_n}]  # 100%
    for frac in LOD_FRACTIONS:
        b = max(int(orig_n * frac), MIN_FACES)
        if b >= orig_n:
            continue
        d = m.simplify_quadric_decimation(face_count=b)
        d = trimesh.Trimesh(vertices=np.asarray(d.vertices), faces=np.asarray(d.faces), process=False)
        # decimation can floor out (returns ~same count for several budgets) -> dedupe
        if abs(len(d.faces) - lods[-1]["faces"]) / max(lods[-1]["faces"], 1) < 0.05:
            continue
        lods.append({"label": f"{frac * 100:g}pct", "mesh": d, "faces": len(d.faces)})
    return lods


def _decimate(m: trimesh.Trimesh, face_count: int) -> trimesh.Trimesh:
    d = m.simplify_quadric_decimation(face_count=face_count)
    return trimesh.Trimesh(vertices=np.asarray(d.vertices), faces=np.asarray(d.faces), process=False)


def first_usemtl(path: Path) -> str | None:
    """First ``usemtl`` shader name in an OBJ (used as the NIR class-prior key
    for single-material assets)."""
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("usemtl"):
                    return line.split(None, 1)[1].strip()
    except Exception:
        pass
    return None


def load_shapes(mpath: Path, spec: dict) -> list[dict]:
    """Orig-resolution renderable shapes in a shared 0.3 m frame.
    Single-material -> one shape (whole mesh). Multi-material -> one shape per
    OBJ usemtl group, each carrying its own optical_class from the manifest
    material_slots (so foliage renders diffuse and only the container is metal/glass).
    Each shape: {matname, cls, albedo, mesh}."""
    if not spec.get("multi"):
        return [{"matname": first_usemtl(mpath), "cls": spec["cls"], "albedo": None,
                 "mesh": load_normalized(mpath)}]
    slots = slot_optical_classes(spec["unit_id"])
    V, groups = load_obj_groups(mpath)
    # normalize in the shared frame (match load_normalized: AABB center + longest extent -> 0.3 m)
    centroid = (V.max(0) + V.min(0)) / 2.0
    V = V - centroid
    V = V * (0.30 / max((V.max(0) - V.min(0)).max(), 1e-6))
    shapes = []
    for name, faces in groups:
        cls = slots.get(name, "diffuse")
        shapes.append({"matname": name, "cls": cls, "albedo": slot_albedo(name),
                       "mesh": trimesh.Trimesh(vertices=V, faces=faces, process=False)})
    return shapes


def make_lods_shapes(shapes: list[dict]) -> list[dict]:
    """[{label, faces(total), shapes:[{matname,cls,albedo,mesh,faces}]}].
    Each submesh is decimated to the same fraction of ITS own face count, so the
    multi-material structure is preserved across LODs."""
    orig = [{**s, "faces": len(s["mesh"].faces)} for s in shapes]
    orig_n = sum(s["faces"] for s in orig)
    lods = [{"label": "orig", "faces": orig_n, "shapes": orig}]
    for frac in LOD_FRACTIONS:
        dec = []
        for s in orig:
            b = max(int(s["faces"] * frac), MIN_FACES)
            d = s["mesh"] if b >= s["faces"] else _decimate(s["mesh"], b)
            dec.append({**s, "mesh": d, "faces": len(d.faces)})
        tot = sum(s["faces"] for s in dec)
        if abs(tot - lods[-1]["faces"]) / max(lods[-1]["faces"], 1) < 0.05:
            continue
        lods.append({"label": f"{frac * 100:g}pct", "faces": tot, "shapes": dec})
    return lods


def export_ply(m: trimesh.Trimesh, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    m.export(path)  # smooth vertex normals recomputed by mitsuba if absent
    return path


# --------------------------------------------------------------------------- #
# Materials by optical class (band-aware). Only the polarized-capable trio.
# --------------------------------------------------------------------------- #
def nir_slot_rho(matname: str | None, cls: str) -> float:
    """Synthesized class-prior NIR (854 nm) scalar diffuse reflectance for a slot.
    Falls back to 0.45 (unknown dielectric) if the synthesis module is unavailable
    or returns None (metal/glass are handled by the Fresnel path, not here)."""
    rho = None
    if nir_scalar_reflectance is not None:
        try:
            rho = nir_scalar_reflectance(matname, cls, 854)
        except Exception:
            rho = None
    return 0.45 if rho is None else float(rho)


def material_dict(cls: str, band: str, albedo: list | None = None,
                  matname: str | None = None) -> dict:
    if cls == "glass":
        return {"type": "dielectric", "int_ior": 1.5, "ext_ior": 1.0}
    if cls in ("metal_aluminum", "metal", "mirror"):
        if band == "visible":
            return {"type": "roughconductor", "material": "Al", "alpha": 0.06}
        return {"type": "roughconductor", "alpha": 0.06,
                "eta": {"type": "srgb", "color": [2.58, 2.58, 2.58], "unbounded": True},
                "k": {"type": "srgb", "color": [8.21, 8.21, 8.21], "unbounded": True}}
    # diffuse / textured / flat -> pplastic (coating gives weak Fresnel polarization)
    if band == "visible":
        refl = albedo if albedo is not None else [0.5, 0.5, 0.5]
    else:
        # NIR: synthesized class-prior SCALAR reflectance (uniform gray per slot,
        # so the NIR render is genuinely single-channel). NOT derived from RGB.
        rho = nir_slot_rho(matname, cls)
        refl = [rho, rho, rho]
    return {"type": "pplastic", "diffuse_reflectance": {"type": "rgb", "value": refl}, "int_ior": 1.5}


# --------------------------------------------------------------------------- #
# Scene construction (mi.load_dict)
# --------------------------------------------------------------------------- #
def _rect_facing(mi, P, O, half, up=(0, 1, 0)):
    T = mi.ScalarTransform4f().look_at(origin=P, target=O, up=up)
    return T @ mi.ScalarTransform4f().scale([half, half, 1.0])


def build_scene(mi, shape_plys, band: str, az_deg: float,
                theta_deg: float, spp: int, res: int = 512):
    """shape_plys: list of {ply, cls, albedo} (one entry per material slot)."""
    O = [0.0, 0.0, 0.0]
    cam_d = 0.55
    cam = [0.0, 0.06, cam_d]
    # active polarized light: area emitter + polarizer, orbiting in azimuth at ~30deg elevation
    az = math.radians(az_deg)
    el = math.radians(30.0)
    r = 0.5
    P = [r * math.cos(el) * math.sin(az), r * math.sin(el), r * math.cos(el) * math.cos(az)]
    d = np.array(O) - np.array(P)
    d = d / (np.linalg.norm(d) + 1e-9)
    Ppol = (np.array(P) + 0.03 * d).tolist()
    scene = {
        "type": "scene",
        "integrator": {"type": "stokes", "nested": {"type": "path", "max_depth": 8}},
        "sensor": {
            "type": "perspective", "fov": 40.0,
            "to_world": mi.ScalarTransform4f().look_at(origin=cam, target=O, up=[0, 1, 0]),
            "sampler": {"type": "independent", "sample_count": spp},
            "film": {"type": "hdrfilm", "width": res, "height": res, "pixel_format": "rgb"},
        },
        # dim ambient so the object is not fully black where the flash doesn't reach
        "ambient": {"type": "constant", "radiance": {"type": "rgb", "value": [0.02, 0.02, 0.02]}},
        "flash": {
            "type": "rectangle", "to_world": _rect_facing(mi, P, O, 0.12),
            "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [60.0, 60.0, 60.0]}},
            "bsdf": {"type": "null"},
        },
        "polarizer": {
            "type": "rectangle", "to_world": _rect_facing(mi, Ppol, O, 0.14),
            "bsdf": {"type": "polarizer", "theta": float(theta_deg)},
        },
    }
    for i, sh in enumerate(shape_plys):
        scene[f"obj{i}"] = {"type": "ply", "filename": str(sh["ply"]),
                            "bsdf": material_dict(sh["cls"], band, sh.get("albedo"),
                                                  sh.get("matname"))}
    return scene


def stokes_modalities(img_np: np.ndarray) -> dict:
    assert img_np.shape[2] >= 15, img_np.shape
    # metal specular can produce NaN/Inf fireflies -> make everything finite first
    img_np = np.nan_to_num(img_np, nan=0.0, posinf=1e4, neginf=0.0)
    s0 = np.clip(img_np[:, :, 3:6].astype(np.float32), 0, 1e4)
    S0 = np.clip((s0 * _LUM).sum(2), 1e-8, None)
    S1 = (img_np[:, :, 6:9] * _LUM).sum(2)
    S2 = (img_np[:, :, 9:12] * _LUM).sum(2)
    dolp = np.nan_to_num(np.clip(np.sqrt(S1 * S1 + S2 * S2) / S0, 0, 1), nan=0.0)
    aolp = np.nan_to_num(0.5 * np.degrees(np.arctan2(S2, S1)), nan=0.0)
    return {"s0_rgb": s0, "S0": S0.astype(np.float32), "dolp": dolp.astype(np.float32),
            "aolp": aolp.astype(np.float32),
            "s1_over_s0": np.clip(S1 / S0, -1, 1).astype(np.float32),
            "s2_over_s0": np.clip(S2 / S0, -1, 1).astype(np.float32)}


# --------------------------------------------------------------------------- #
# Metrics (vs original), noise-floor aware
# --------------------------------------------------------------------------- #
def polar_diff(ref: dict, test: dict) -> dict:
    """Weighted polarization difference test-vs-ref. Mask = object (S0 bright).
    AoLP evaluated only where both are polarized, weighted by S0*DoLP."""
    S0 = ref["S0"]
    mask = S0 > (0.05 * S0.max() + 1e-6)
    w = (ref["S0"] * ref["dolp"])[mask]
    w = w / (w.sum() + 1e-9)
    ddolp = float(np.abs(test["dolp"][mask] - ref["dolp"][mask]).mean())
    # circular AoLP diff (pi-periodic), weighted
    da = np.radians(2 * (test["aolp"][mask] - ref["aolp"][mask]))
    aolp_circ = float(np.degrees(0.5 * np.abs(np.arctan2((w * np.sin(da)).sum(), (w * np.cos(da)).sum()))))
    ds1 = float(np.abs(test["s1_over_s0"][mask] - ref["s1_over_s0"][mask]).mean())
    ds2 = float(np.abs(test["s2_over_s0"][mask] - ref["s2_over_s0"][mask]).mean())
    ds0 = float(np.abs(test["S0"][mask] - ref["S0"][mask]).mean() / (ref["S0"][mask].mean() + 1e-9))
    # silhouette IoU (object masks)
    mt = test["S0"] > (0.05 * test["S0"].max() + 1e-6)
    iou = float((mask & mt).sum() / max((mask | mt).sum(), 1))
    return {"dDoLP": ddolp, "dAoLP_deg": aolp_circ, "dS1S0": ds1, "dS2S0": ds2,
            "rel_dS0": ds0, "silhouette_iou": iou}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run(asset_keys: list[str], spp: int, dry: bool) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    mi = None
    if not dry:
        import mitsuba as _mi
        mi = _mi
        mi.set_variant(VARIANT)

    results = {"spp": spp, "assets": {}}
    # merge with any prior results so a partial re-run doesn't drop completed assets
    prev = OUT_DIR / ("metrics_dry.json" if dry else "metrics.json")
    if prev.is_file():
        try:
            results = json.loads(prev.read_text())
            results["spp"] = spp
        except Exception:
            pass
    for key in asset_keys:
        spec = ASSETS[key]
        mpath = resolve_mesh(spec["mesh"])
        if not mpath.is_file():
            print(f"[skip] {key}: mesh not found {mpath}")
            continue
        t = time.time()
        lods = make_lods_shapes(load_shapes(mpath, spec))
        print(f"[{key}] cls={spec['cls']} multi={bool(spec.get('multi'))} "
              f"orig={lods[0]['faces']:,} tris -> LODs {[l['faces'] for l in lods]}  "
              f"(mesh {time.time()-t:.1f}s)")
        entry = {"cls": spec["cls"], "orig_tris": lods[0]["faces"],
                 "asset_id": Path(spec["mesh"]).stem, "mesh": spec["mesh"], "lods": []}
        if spec.get("multi"):
            entry["multi"] = True
            entry["slots"] = [{"matname": sh["matname"], "cls": sh["cls"],
                               "faces": len(sh["mesh"].faces),
                               "nir854": (nir_slot_rho(sh["matname"], sh["cls"])
                                          if sh["cls"] not in ("glass", "metal_aluminum", "metal", "mirror")
                                          else None)}
                              for sh in lods[0]["shapes"]]
        else:
            _sh = lods[0]["shapes"][0]
            entry["shader"] = _sh["matname"]
            entry["nir854"] = nir_slot_rho(_sh["matname"], _sh["cls"])

        # export a PLY per (LOD, material slot); carry cls/albedo for the scene
        for l in lods:
            l["plys"] = []
            for i, sh in enumerate(l["shapes"]):
                p = export_ply(sh["mesh"], TMP / f"{key}_{l['label']}_{i}.ply")
                l["plys"].append({"ply": p, "cls": sh["cls"], "albedo": sh["albedo"],
                                  "matname": sh["matname"]})

        if dry:
            entry["lods"] = [{"label": l["label"], "faces": l["faces"],
                              "ply_kb": round(sum(p["ply"].stat().st_size for p in l["plys"]) / 1024, 1)}
                             for l in lods]
            results["assets"][key] = entry
            continue

        # render: original twice (noise floor) + each LOD, per light x band
        panel_store = {}  # band -> {lod_label: mods}  for the panel lighting condition
        try:
            for band in BANDS:
                for (llab, az, th) in LIGHTS:
                    mods = {}
                    for l in lods:
                        sc = mi.load_dict(build_scene(mi, l["plys"], band, az, th, spp))
                        img = np.array(mi.render(sc, spp=spp, seed=7))
                        mods[l["label"]] = stokes_modalities(img)
                    # noise floor: original at second seed
                    sc = mi.load_dict(build_scene(mi, lods[0]["plys"], band, az, th, spp))
                    ref2 = stokes_modalities(np.array(mi.render(sc, spp=spp, seed=99)))
                    ref = mods["orig"]
                    noise = polar_diff(ref, ref2)
                    for l in lods:
                        d = polar_diff(ref, mods[l["label"]])
                        entry["lods"].append({"band": band, "light": llab, "lod": l["label"],
                                              "faces": l["faces"], **d,
                                              "within_noise": d["dDoLP"] <= noise["dDoLP"] * 1.5})
                    entry.setdefault("noise_floor", {})[f"{band}_{llab}"] = noise
                    if llab == PANEL_LIGHT:
                        panel_store[band] = mods
            entry["panel_lods"] = _save_full_panels(key, panel_store, lods)
            results["assets"][key] = entry
            print(f"[{key}] done ({len(entry['lods'])} measurements)", flush=True)
        except Exception as exc:
            import traceback; traceback.print_exc()
            print(f"[{key}] FAILED: {exc}", flush=True)
            results.setdefault("failed", {})[key] = str(exc)
        # persist after each asset so a later failure never loses earlier results
        (OUT_DIR / "metrics.json").write_text(json.dumps(results, indent=2, default=str))

    (OUT_DIR / ("metrics_dry.json" if dry else "metrics.json")).write_text(json.dumps(results, indent=2, default=str))
    print(f"\nwrote {OUT_DIR}/{'metrics_dry.json' if dry else 'metrics.json'}")


# --- colormaps (matplotlib-free) ------------------------------------------- #
_VIRIDIS = np.array([
    [0.267, 0.005, 0.329], [0.283, 0.141, 0.458], [0.254, 0.265, 0.530],
    [0.207, 0.372, 0.553], [0.164, 0.471, 0.558], [0.128, 0.567, 0.551],
    [0.135, 0.659, 0.518], [0.267, 0.749, 0.441], [0.478, 0.821, 0.318],
    [0.741, 0.873, 0.150], [0.993, 0.906, 0.144]], np.float32)


def _lut(v01, lut):
    idx = np.nan_to_num(np.clip(v01, 0, 1), nan=0.0) * (len(lut) - 1)
    lo = np.floor(idx).astype(int); hi = np.minimum(lo + 1, len(lut) - 1)
    f = (idx - lo)[..., None]
    return ((lut[lo] * (1 - f) + lut[hi] * f) * 255).astype(np.uint8)


def _tm(rgb):
    x = np.clip(rgb, 0, None); x = x / (1 + x)
    return (np.clip(x ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)


def _viridis(v, vmax): return _lut(v / max(vmax, 1e-6), _VIRIDIS)


# red-black DoLP colorbar: black (unpolarized) -> red -> bright red (high DoLP)
_REDBLACK = np.array([
    [0.0, 0.0, 0.0], [0.30, 0.0, 0.0], [0.60, 0.02, 0.0],
    [0.85, 0.10, 0.05], [1.0, 0.30, 0.22]], np.float32)


def _redblack(v, vmax): return _lut(v / max(vmax, 1e-6), _REDBLACK)


def _diverging(v):
    t = (np.clip(v, -1, 1) + 1) / 2
    lut = np.array([[0.23, 0.30, 0.75], [1, 1, 1], [0.75, 0.15, 0.15]], np.float32)
    return _lut(t, lut)


def _hsv_to_rgb(h, s, v):
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p = v * (1 - s); q = v * (1 - f * s); t = v * (1 - (1 - f) * s)
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [v, q, p, p, t, v])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [t, v, v, q, p, p])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def _aolp_img(aolp_deg, dolp):
    h = (((aolp_deg + 90.0) / 180.0) % 1.0)
    val = np.clip(dolp / max(dolp.max(), 1e-6), 0, 1)  # unpolarized -> dark
    return (_hsv_to_rgb(h, np.ones_like(h), val) * 255).astype(np.uint8)


def _save_full_panels(key, panel_store, lods):
    """Save RGB · DoLP · AoLP · S1/S0 · S2/S0 for orig + mid + coarsest LOD.
    visible S0 = real 3-channel RGB; NIR S0 = single-channel (grayscale) NIR
    reflectance map (each material slot a distinct gray). Returns LOD labels imaged."""
    try:
        from PIL import Image
    except Exception:
        return []
    labels = [l["label"] for l in lods]
    pick = sorted(set([labels[0], labels[len(labels) // 2], labels[-1]]),
                  key=labels.index)
    # shared DoLP scale across bands/LODs of this asset
    vmax = 1e-3
    for band, md in panel_store.items():
        for lab in pick:
            vmax = max(vmax, float(np.percentile(md[lab]["dolp"], 99)))
    for band, md in panel_store.items():
        bs = "vis" if band == "visible" else "nir"
        for lab in pick:
            m = md[lab]
            if bs == "nir":
                # genuine single-channel NIR S0 (per-slot class-prior reflectance)
                gray = (_tm(m["s0_rgb"]).astype(np.float32) @ _LUM).astype(np.uint8)
                Image.fromarray(gray, mode="L").save(OUT_DIR / f"{key}_{bs}_{lab}_rgb.png")
            else:
                Image.fromarray(_tm(m["s0_rgb"])).save(OUT_DIR / f"{key}_{bs}_{lab}_rgb.png")
            Image.fromarray(_redblack(m["dolp"], vmax)).save(OUT_DIR / f"{key}_{bs}_{lab}_dolp.png")
            Image.fromarray(_aolp_img(m["aolp"], m["dolp"])).save(OUT_DIR / f"{key}_{bs}_{lab}_aolp.png")
            Image.fromarray(_diverging(m["s1_over_s0"])).save(OUT_DIR / f"{key}_{bs}_{lab}_s1s0.png")
            Image.fromarray(_diverging(m["s2_over_s0"])).save(OUT_DIR / f"{key}_{bs}_{lab}_s2s0.png")
    return {"lods_imaged": pick, "dolp_vmax": vmax}


class _T:  # minimal ScalarTransform4f stub for dry-run scene-dict build
    def look_at(self, **k): return self
    def scale(self, *a, **k): return self
    def __matmul__(self, o): return self


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", nargs="*", default=list(ASSETS.keys()))
    ap.add_argument("--spp", type=int, default=1024)
    ap.add_argument("--dry-run", action="store_true", help="GPU-free: mesh LOD + ply export only")
    a = ap.parse_args()
    run(a.assets, a.spp, a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
