from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
from PIL import Image, ImageDraw  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
for rel in ("modules/mitsuba_converter/src", "modules/robomituba_bridge/src"):
    path = str(REPO_ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)

from mitsuba_converter.usd_editor_geometry import extract_prim_mesh_for_editor  # noqa: E402


THUMB_COLORS: dict[str, tuple[int, int, int]] = {
    "glass": (103, 232, 249),
    "mirror": (100, 116, 139),
    "furniture": (154, 90, 36),
    "shell": (80, 80, 80),
    "floor": (134, 239, 172),
    "plant": (22, 101, 52),
    "electronics": (100, 116, 139),
    "object": (148, 163, 184),
}


def render_mesh_to_png(vertices_flat: list[Any], indices_flat: list[Any], color: tuple[int, int, int], size: int) -> bytes | None:
    verts = np.asarray(vertices_flat, dtype=np.float32).reshape(-1, 3)
    tris = np.asarray(indices_flat, dtype=np.int32).reshape(-1, 3)
    if len(verts) == 0 or len(tris) == 0:
        return None

    mn = verts.min(axis=0)
    mx = verts.max(axis=0)
    scale = max(float((mx - mn).max()), 1e-6)
    verts = (verts - (mn + mx) * 0.5) / scale

    pitch = math.radians(28)
    yaw = math.radians(40)
    rx = np.asarray([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    ry = np.asarray([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rot = verts @ (rx @ ry).T

    xy_min = rot[:, :2].min(axis=0)
    xy_max = rot[:, :2].max(axis=0)
    xy_size = np.maximum(xy_max - xy_min, 1e-6)
    pad = size * 0.12
    image_scale = min((size - 2 * pad) / float(xy_size[0]), (size - 2 * pad) / float(xy_size[1]))
    x2d = (rot[:, 0] - (xy_min[0] + xy_max[0]) * 0.5) * image_scale + size * 0.5
    y2d = -(rot[:, 1] - (xy_min[1] + xy_max[1]) * 0.5) * image_scale + size * 0.5
    z2d = rot[:, 2]

    tri_pts = rot[tris]
    normals = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
    normal_len = np.linalg.norm(normals, axis=1, keepdims=True)
    valid = normal_len.squeeze() > 1e-10
    normals[valid] /= normal_len[valid]
    light = np.asarray([-0.4, 0.7, 0.6], dtype=np.float32)
    light /= np.linalg.norm(light)
    diffuse = np.clip(normals @ light, 0, 1)
    depth = (z2d[tris[:, 0]] + z2d[tris[:, 1]] + z2d[tris[:, 2]]) / 3.0

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    r0, g0, b0 = color
    for face_index in np.argsort(depth):
        if not valid[face_index]:
            continue
        shade = 0.35 + 0.65 * float(diffuse[face_index])
        fill = (int(min(255, r0 * shade)), int(min(255, g0 * shade)), int(min(255, b0 * shade)), 240)
        i0, i1, i2 = [int(v) for v in tris[face_index]]
        draw.polygon(
            [(float(x2d[i0]), float(y2d[i0])), (float(x2d[i1]), float(y2d[i1])), (float(x2d[i2]), float(y2d[i2]))],
            fill=fill,
        )

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def resolve_repo_path(ref: str) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else REPO_ROOT / path


def thumb_key(asset: dict[str, Any], version: str) -> dict[str, Any]:
    return {
        "version": version,
        "asset_id": asset["asset_id"],
        "source_ref": str(asset.get("source_ref") or ""),
        "bounds": asset.get("bounds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", default="opticalnav-v0.2")
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--version", default="mesh_thumb_v2")
    args = parser.parse_args()

    catalogs_dir = REPO_ROOT / "out" / "opticalnav" / "asset_library" / "catalogs"
    thumbs_dir = REPO_ROOT / "out" / "opticalnav" / args.project_id / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    baked = 0
    skipped = 0
    for catalog_path in sorted(catalogs_dir.glob("*.json")):
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for asset in catalog.get("assets", []) or []:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get("asset_id") or "")
            usd_ref = str(asset.get("usd_ref") or "")
            source_path = str(asset.get("source_path") or "")
            if not asset_id or not usd_ref or not source_path:
                skipped += 1
                continue
            try:
                mesh = extract_prim_mesh_for_editor(resolve_repo_path(usd_ref), source_path, max_triangles=3500, max_mesh_prims=96)
                if not mesh:
                    skipped += 1
                    continue
                color = THUMB_COLORS.get(str(asset.get("category") or "object"), THUMB_COLORS["object"])
                png = render_mesh_to_png(mesh["vertices"], mesh["indices"], color, args.size)
                if png is None:
                    skipped += 1
                    continue
                key = thumb_key(asset, args.version)
                etag = hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
                (thumbs_dir / f"{asset_id}.png").write_bytes(png)
                (thumbs_dir / f"{asset_id}.json").write_text(
                    json.dumps({"thumb_key": key, "etag": etag, "render_mode": "mesh"}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                baked += 1
            except Exception as exc:
                print(f"skip {asset_id}: {exc}", file=sys.stderr)
                skipped += 1
    print(json.dumps({"baked": baked, "skipped": skipped, "thumbs_dir": str(thumbs_dir)}, indent=2))
    return 0 if baked else 1


if __name__ == "__main__":
    raise SystemExit(main())
