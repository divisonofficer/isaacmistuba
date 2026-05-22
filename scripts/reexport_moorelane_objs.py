"""Re-export the MooreLane scene to per-material OBJ+MTL files.

Runs under ``openusd_pip`` conda env (has ``pxr`` + ``numpy``)::

    PYTHONPATH=/jarvis/project/robomituba/modules/mitsuba_converter/src \\
    /home/jinnyeong/miniconda3/envs/openusd_pip/bin/python \\
        /jarvis/project/robomituba/scripts/reexport_moorelane_objs.py

Reproduces the original ``out/moorelane_full_export/objs/materials_<safe>_mtl.obj``
layout. The new export gets the Phase B normal-sanitization patch in
``usd_export_obj_mtl._sanitize_normals`` so mitsuba's OBJ loader no
longer rejects files with zero/NaN normals.

Writes to ``OUT_DIR`` (defaults to a sibling ``.fixed`` directory so the
old export stays available for diffing — rename to swap in).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


USD_PATH = (
    "/jarvis/project/robomituba/assets/moorelane/"
    "Intel_mooreLane_v1_2_0/Intel_mooreLane/USD/"
    "MooreLane_ASWF_0621_fullComposition.usda"
)
DEFAULT_OUT_DIR = Path("/jarvis/project/robomituba/out/moorelane_full_export/objs.fixed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usd", default=USD_PATH)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit", type=int, default=0, help="export only first N materials (0=all)")
    parser.add_argument("--max-meshes-per-material", type=int, default=10000)
    args = parser.parse_args()

    from pxr import Usd, UsdGeom, UsdShade
    from mitsuba_converter.usd_export_obj_mtl import (
        _safe_name, export_roots_to_obj_mtl,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[reexport] USD: {args.usd}", flush=True)
    print(f"[reexport] OUT: {out_dir}", flush=True)

    t_open = time.perf_counter()
    stage = Usd.Stage.Open(args.usd)
    if stage is None:
        print(f"[reexport] FATAL: cannot open USD: {args.usd}", file=sys.stderr)
        return 2
    print(f"[reexport] stage opened in {time.perf_counter() - t_open:.1f}s", flush=True)

    # Build material -> [mesh prim paths] map.
    t_walk = time.perf_counter()
    mat_to_meshes: dict[str, list[str]] = {}
    total_meshes = 0
    unbound = 0
    for prim in Usd.PrimRange(stage.GetPseudoRoot()):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        total_meshes += 1
        bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        mat = bound[0] if bound else None
        if not mat:
            unbound += 1
            continue
        mat_path = mat.GetPath().pathString
        mat_to_meshes.setdefault(mat_path, []).append(prim.GetPath().pathString)
    print(
        f"[reexport] walked {total_meshes} meshes, {len(mat_to_meshes)} materials, "
        f"{unbound} unbound — {time.perf_counter() - t_walk:.1f}s",
        flush=True,
    )

    items = list(mat_to_meshes.items())
    if args.limit > 0:
        items = items[: args.limit]
        print(f"[reexport] --limit {args.limit}: exporting only first {len(items)} materials", flush=True)

    summary = {
        "usd": args.usd,
        "out_dir": str(out_dir),
        "materials_total": len(items),
        "exported": 0,
        "failed": [],
        "elapsed_s": 0.0,
    }
    t_loop = time.perf_counter()
    for i, (mat_path, mesh_paths) in enumerate(items, 1):
        safe = _safe_name(mat_path)
        out_obj = out_dir / f"{safe}.obj"
        out_mtl = out_dir / f"{safe}.mtl"
        t0 = time.perf_counter()
        try:
            stats, _ = export_roots_to_obj_mtl(
                usd_path=args.usd,
                root_prims=mesh_paths,
                out_obj=str(out_obj),
                out_mtl=str(out_mtl),
                max_meshes=args.max_meshes_per_material,
                smooth_normals=True,
                stage=stage,  # reuse the opened stage — avoids 3.8 GB reload per call
            )
            summary["exported"] += 1
            elapsed = time.perf_counter() - t0
            print(
                f"[reexport] [{i}/{len(items)}] {mat_path} -> {safe}.obj "
                f"({len(mesh_paths)} meshes, {elapsed:.2f}s)",
                flush=True,
            )
        except Exception as exc:
            summary["failed"].append({"material": mat_path, "error": f"{type(exc).__name__}: {exc}"})
            print(
                f"[reexport] [{i}/{len(items)}] FAIL {mat_path}: {type(exc).__name__}: {exc}",
                file=sys.stderr, flush=True,
            )

    summary["elapsed_s"] = round(time.perf_counter() - t_loop, 2)
    summary_path = out_dir / "_reexport_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"[reexport] done — exported {summary['exported']}/{len(items)} materials in "
        f"{summary['elapsed_s']}s. summary at {summary_path}",
        flush=True,
    )
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
