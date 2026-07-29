#!/usr/bin/env python3
"""Per-object LOD budget analysis — Infinigen high-poly optimization while
preserving polarization quality.

Problem: given a (non-textured) high-poly prop whose appearance lives in its
geometry, find the maximum compression (minimum face fraction) that still
preserves the polarization signal. The answer is per-object: solid blobs
(shells) tolerate ~99% reduction; thin/branchy structures (coral, foliage)
collapse after a few percent.

This is TIER 1: a GPU-free predictor. For each compression ratio it decimates
the mesh (fast-simplification) and computes geometry-only quality proxies that
track the render-based polarization fidelity:

  polar_dolp_rel  relative change of the area-weighted Fresnel-DoLP proxy
                  (drives DoLP; a scrambled normal field changes it)
  aolp_coh_drop   drop in AoLP orientation coherence (drives AoLP)
  chamfer_rel     surface deviation (sampled) / object diagonal  (silhouette/shape)
  area_rel        surface-area preservation (thin structure loss shows here)

The safe budget is the smallest face-fraction whose proxies all stay within
tolerance. Thresholds are calibrated against the Tier-2 render experiment
(dev_report/images/polar_lod_2026-07-28/metrics.json) in `calibrate`.

Runs on the 6 representatives, or on every no-normal prop of a scene manifest.

Env: python=~/miniconda3/envs/openusd_pip/bin/python (trimesh + fast-simplification)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import trimesh

REPO = Path(__file__).resolve().parents[1]
IMPORT_DIR = REPO / "out/infinigen_imports/kr_20260625"
LOCAL_MESH = Path("/tmp/claude-1000/polar_lod/meshes")
OUT_DIR = REPO / "dev_report/images/polar_lod_2026-07-28"

RATIOS = [0.5, 0.3, 0.2, 0.1, 0.05, 0.03, 0.02, 0.01, 0.005]
MIN_FACES = 100
# geometry-quality tolerances (calibrated vs render fidelity: IoU>=0.9, dDoLP<=~2x noise)
TOL = {"polar_dolp_rel": 0.10, "aolp_coh_drop": 0.15, "chamfer_rel": 0.010, "area_rel": 0.15}

_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)
VIEWS = np.array([[0, 0, 1], [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, 1]], float)
VIEWS /= np.linalg.norm(VIEWS, axis=1, keepdims=True)


def resolve_mesh(rel: str) -> Path:
    local = LOCAL_MESH / Path(rel).name
    return local if local.is_file() else (IMPORT_DIR / rel)


def load_norm(path: Path) -> trimesh.Trimesh:
    m = trimesh.load(path, process=False, force="mesh")
    m = trimesh.Trimesh(vertices=np.asarray(m.vertices), faces=np.asarray(m.faces), process=False)
    m.apply_translation(-m.bounding_box.centroid)
    m.apply_scale(0.30 / max(m.extents.max(), 1e-6))
    return m


def _fresnel_dolp(cos_i, n=1.52):
    cos_i = np.clip(np.abs(cos_i), 1e-4, 1.0)
    sin_t2 = (1 / n**2) * (1 - cos_i**2)
    cos_t = np.sqrt(np.clip(1 - sin_t2, 0, 1))
    rs = ((cos_i - n * cos_t) / (cos_i + n * cos_t)) ** 2
    rp = ((n * cos_i - cos_t) / (n * cos_i + cos_t)) ** 2
    return np.abs(rs - rp) / np.clip(rs + rp, 1e-8, None)


def polar_signature(mesh):
    """Area-weighted Fresnel-DoLP proxy + AoLP orientation coherence, view-averaged."""
    N = mesh.face_normals
    A = mesh.area_faces
    dolp, coh = [], []
    for V in VIEWS:
        c = N @ V
        vis = c > 0.01
        if vis.sum() < 4:
            continue
        w = A[vis] * c[vis]
        w = w / w.sum()
        dolp.append(float((_fresnel_dolp(c[vis]) * w).sum()))
        az = np.arctan2(N[vis, 1], N[vis, 0])
        C = (w * np.cos(2 * az)).sum()
        S = (w * np.sin(2 * az)).sum()
        coh.append(float(np.hypot(C, S)))
    return (float(np.mean(dolp)) if dolp else 0.0, float(np.mean(coh)) if coh else 0.0)


def chamfer_rel(a: trimesh.Trimesh, b: trimesh.Trimesh, n=20000) -> float:
    from scipy.spatial import cKDTree
    pa = a.sample(n)
    pb = b.sample(n)
    diag = float(np.linalg.norm(a.extents))
    da = cKDTree(pb).query(pa)[0]
    db = cKDTree(pa).query(pb)[0]
    return float((da.mean() + db.mean()) / 2 / max(diag, 1e-6))


def analyze_object(key: str, path: Path) -> dict:
    m = load_norm(path)
    orig_n = len(m.faces)
    d0, a0 = polar_signature(m)
    area0 = float(m.area)
    curve = []
    for frac in RATIOS:
        b = max(int(orig_n * frac), MIN_FACES)
        if b >= orig_n:
            continue
        d = m.simplify_quadric_decimation(face_count=b)
        d = trimesh.Trimesh(vertices=np.asarray(d.vertices), faces=np.asarray(d.faces), process=False)
        if len(d.faces) < 4:
            continue
        dd, ad = polar_signature(d)
        rec = {
            "frac": frac, "faces": len(d.faces),
            "polar_dolp_rel": abs(dd - d0) / max(d0, 1e-6),
            "aolp_coh_drop": max(0.0, a0 - ad),
            "chamfer_rel": chamfer_rel(m, d),
            "area_rel": abs(float(d.area) - area0) / max(area0, 1e-6),
        }
        rec["within_tol"] = all(rec[k] <= TOL[k] for k in TOL)
        curve.append(rec)
    # safe budget = smallest frac (most compression) that is still within tol,
    # AND all coarser levels above it are also within tol (monotone safe region)
    safe = None
    for rec in curve:  # coarsening order
        if rec["within_tol"]:
            safe = rec
        else:
            break
    return {"key": key, "orig_tris": orig_n, "polar_dolp0": d0, "aolp_coh0": a0,
            "curve": curve,
            "safe_frac": safe["frac"] if safe else 1.0,
            "safe_faces": safe["faces"] if safe else orig_n,
            "verdict": _verdict(safe)}


def _verdict(safe) -> str:
    if safe is None:
        return "no-compress (thin/fragile)"
    if safe["frac"] <= 0.02:
        return "aggressive-ok (solid blob)"
    if safe["frac"] <= 0.10:
        return "moderate"
    return "conservative (fragile)"


def calibrate() -> None:
    """Cross-check Tier-1 geometry safe budget vs Tier-2 render polarization fidelity."""
    mp = OUT_DIR / "metrics.json"
    if not mp.is_file():
        print("no render metrics yet; skipping calibration")
        return
    render = json.loads(mp.read_text())["assets"]
    print(f"\n{'asset':16} {'Tier1 safe':>12} {'Tier2 IoU@10%':>14} {'Tier2 dDoLP@10%':>16}")
    for key, ge in _RESULTS.items():
        e = render.get(key)
        iou = ddolp = None
        if e:
            recs = [r for r in e["lods"] if r["band"] == "visible" and r["light"] == "az65_p0" and r["lod"] == "10pct"]
            if recs:
                iou, ddolp = recs[0]["silhouette_iou"], recs[0]["dDoLP"]
        print(f"{key:16} {ge['safe_frac']*100:>9.1f}%  {('%.2f'%iou) if iou is not None else '-':>14} "
              f"{('%.3f'%ddolp) if ddolp is not None else '-':>16}   [{ge['verdict']}]")


_RESULTS = {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", nargs="*")
    ap.add_argument("--manifest", action="store_true", help="analyze all no-normal props in the scene manifest")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "lod_budget.json")
    a = ap.parse_args()

    targets = {}
    if a.manifest:
        man = json.loads((IMPORT_DIR / "scene_manifest.json").read_text())
        STRUCT = {"wall", "glass_wall", "glass_door", "floor", "ceiling", "door", "window", "frame", "building", "landmark"}
        for u in man["units"]:
            if u.get("semantic_type") in STRUCT or u.get("baked_normal"):
                continue
            if (u.get("polys") or 0) < 50000:
                continue  # only high-poly
            targets[u["id"]] = IMPORT_DIR / u["mesh_obj"]
    else:
        from single_object_polar_lod import ASSETS  # reuse the representative set
        keys = a.assets or list(ASSETS.keys())
        for k in keys:
            targets[k] = resolve_mesh(ASSETS[k]["mesh"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, path in targets.items():
        if not Path(path).is_file():
            print(f"[skip] {key}: {path} missing"); continue
        try:
            r = analyze_object(key, Path(path))
        except Exception as exc:
            import traceback; traceback.print_exc(); print(f"[{key}] FAIL {exc}"); continue
        _RESULTS[key] = r
        print(f"[{key:28}] orig {r['orig_tris']:>9,}  safe={r['safe_frac']*100:>5.1f}% "
              f"({r['safe_faces']:>8,} tri)  {r['verdict']}", flush=True)
    a.out.write_text(json.dumps({"tol": TOL, "ratios": RATIOS, "results": _RESULTS}, indent=2))
    print(f"\nwrote {a.out}")
    calibrate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
