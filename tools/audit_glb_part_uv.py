#!/usr/bin/env python3
"""Audit the UV quality of materialized GLB mesh parts.

UV bounds alone are not a health check: a layout can sit neatly inside [0,1]
while half its triangles collapse to zero area and the rest stack on top of each
other.  Both defects make a bound texture sample a handful of texels, which
looks like "the texture is in the wrong place" in a render.  This reports the
three signals that actually separate a usable atlas from a broken one:

  zero_area_ratio  fraction of triangles whose UV triangle has no area; those
                   triangles sample a single texel no matter the atlas
  overlap_factor   summed UV triangle area divided by the area of the bounding
                   box they occupy; >> 1 means triangles stack on each other
  unique_ratio     distinct UV coordinates over UV entries

Usage:
  python tools/audit_glb_part_uv.py <run_dir> [--json out.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

ZERO_AREA_EPS = 1e-12
# A part is called broken when it cannot address its atlas meaningfully: most
# triangles degenerate, or the layout folds over itself many times.
ZERO_AREA_LIMIT = 0.10
OVERLAP_LIMIT = 3.0


def read_obj_uv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    coords: list[tuple[float, float]] = []
    faces: list[list[int]] = []
    with path.open("r", errors="ignore") as handle:
        for line in handle:
            if line.startswith("vt "):
                parts = line.split()
                coords.append((float(parts[1]), float(parts[2])))
            elif line.startswith("f "):
                indices = []
                for token in line.split()[1:]:
                    fields = token.split("/")
                    indices.append(int(fields[1]) - 1 if len(fields) > 1 and fields[1] else -1)
                if len(indices) >= 3 and all(i >= 0 for i in indices[:3]):
                    faces.append(indices[:3])
    return np.asarray(coords, np.float64), np.asarray(faces, np.int64)


def audit_part(path: Path) -> dict[str, Any]:
    uv, faces = read_obj_uv(path)
    result: dict[str, Any] = {"part": path.name, "uv_count": int(uv.shape[0]),
                              "triangle_count": int(faces.shape[0])}
    if uv.size == 0 or faces.size == 0:
        return {**result, "status": "no_uv"}
    a, b, c = uv[faces[:, 0]], uv[faces[:, 1]], uv[faces[:, 2]]
    area = 0.5 * np.abs(
        (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    )
    span_u = float(uv[:, 0].max() - uv[:, 0].min())
    span_v = float(uv[:, 1].max() - uv[:, 1].min())
    box = span_u * span_v
    zero_ratio = float((area < ZERO_AREA_EPS).mean())
    overlap = float(area.sum() / box) if box > 1e-9 else float("inf")
    unique_ratio = float(len(np.unique(uv, axis=0)) / uv.shape[0])
    if box <= 1e-9:
        status = "degenerate_collapsed"
    elif zero_ratio > ZERO_AREA_LIMIT or overlap > OVERLAP_LIMIT:
        status = "broken"
    else:
        status = "ok"
    return {
        **result, "status": status,
        "u_range": [float(uv[:, 0].min()), float(uv[:, 0].max())],
        "v_range": [float(uv[:, 1].min()), float(uv[:, 1].max())],
        "zero_area_ratio": round(zero_ratio, 4),
        "overlap_factor": round(overlap, 3) if np.isfinite(overlap) else None,
        "unique_ratio": round(unique_ratio, 4),
        "uv_area": round(float(area.sum()), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path, help="A/B run directory containing glb_geometry/")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    root = args.run_dir / "glb_geometry"
    if not root.is_dir():
        raise SystemExit(f"no glb_geometry under {args.run_dir}")

    report: dict[str, Any] = {"run_dir": str(args.run_dir), "assets": {}}
    for asset_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        parts_dirs = sorted(asset_dir.glob("*_parts"))
        if not parts_dirs:
            continue
        rows = [audit_part(obj) for obj in sorted(parts_dirs[0].glob("*.obj"))]
        bad = [r for r in rows if r["status"] not in {"ok"}]
        bad_tris = sum(r["triangle_count"] for r in bad)
        total_tris = sum(r["triangle_count"] for r in rows) or 1
        report["assets"][asset_dir.name] = {
            "part_count": len(rows),
            "broken_part_count": len(bad),
            "broken_triangle_fraction": round(bad_tris / total_tris, 4),
            "parts": rows,
        }
        flag = "BROKEN" if bad else "ok"
        print(f"{asset_dir.name[:44]:46s} parts={len(rows):>2d} bad={len(bad):>2d} "
              f"bad_tri={bad_tris / total_tris:6.1%}  {flag}")
        for row in bad:
            print(f"    {row['part']:24s} status={row['status']:20s} "
                  f"zero_area={row.get('zero_area_ratio')} overlap={row.get('overlap_factor')} "
                  f"tris={row['triangle_count']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
