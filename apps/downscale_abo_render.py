#!/usr/bin/env python3
"""Downscale an ABO hover render tree from 720x540 to 512x384 (user 2026-10-13).

Training squares and resizes every view to 272 px, so 512x384 still downsamples
(env_v3 was rendered at it natively). Per channel:

- radiance and smooth maps (rgb, nir_*, active_minus_passive, diffuse_*,
  albedo_*, roughness*, metallic*, mr_confidence): INTER_AREA, the box average
  a 1.40625x downscale needs;
- geometry and labels (depth, normal, material_id, layer_count, every *_mask):
  INTER_NEAREST. Averaging depth across an edge invents a surface that is not
  there, a mask must stay 0/1, an id must stay an id, and a normal must stay
  unit length.

Formats are kept: EXR keeps its pixel type and compression, PNG keeps its bit
depth. The manifest's camera block is rescaled (width/height, fx/fy/cx/cy by
512/720), which IR_PIPELINE's loader reads for intrinsics.

    python3 apps/downscale_abo_render.py SRC_RENDER_DIR DST_RENDER_DIR
    python3 apps/downscale_abo_render.py --self-check
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

SRC_WH, DST_WH = (720, 540), (512, 384)
NEAREST = re.compile(r"(depth|normal|material_id|layer_count|mask)\d*\.(exr|png)$")
_COMP = {0: cv2.IMWRITE_EXR_COMPRESSION_NO, 1: cv2.IMWRITE_EXR_COMPRESSION_RLE,
         2: cv2.IMWRITE_EXR_COMPRESSION_ZIPS, 3: cv2.IMWRITE_EXR_COMPRESSION_ZIP,
         4: cv2.IMWRITE_EXR_COMPRESSION_PIZ}


def _exr_header(path: Path) -> tuple[int, bool]:
    """(compression code, any float32 channel) from the EXR header."""
    blob = path.read_bytes()[:4096]
    i, comp, f32 = 8, 3, False
    while blob[i] != 0:
        n = blob.index(0, i); t = blob.index(0, n + 1)
        name = blob[i:n]; size = struct.unpack("<i", blob[t + 1:t + 5])[0]
        value = blob[t + 5:t + 5 + size]; i = t + 5 + size
        if name == b"compression":
            comp = value[0]
        elif name == b"channels":
            j = 0
            while value[j] != 0:
                k = value.index(0, j)
                f32 |= struct.unpack("<i", value[k + 1:k + 5])[0] == 2
                j = k + 17
    return comp, f32


def downscale_file(src: Path, dst: Path) -> None:
    interp = cv2.INTER_NEAREST if NEAREST.search(src.name) else cv2.INTER_AREA
    img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"unreadable: {src}")
    if img.shape[1] != SRC_WH[0] or img.shape[0] != SRC_WH[1]:
        raise RuntimeError(f"{src}: {img.shape[1]}x{img.shape[0]}, expected {SRC_WH}")
    out = cv2.resize(img, DST_WH, interpolation=interp)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".exr":
        comp, f32 = _exr_header(src)
        flags = [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT if f32 else cv2.IMWRITE_EXR_TYPE_HALF,
                 cv2.IMWRITE_EXR_COMPRESSION, _COMP.get(comp, cv2.IMWRITE_EXR_COMPRESSION_ZIP)]
    else:
        flags = [cv2.IMWRITE_PNG_COMPRESSION, 6]
    if not cv2.imwrite(str(dst), out, flags):
        raise RuntimeError(f"write failed: {dst}")


def rescale_camera(block: dict) -> None:
    sx, sy = DST_WH[0] / SRC_WH[0], DST_WH[1] / SRC_WH[1]
    if block.get("width") == SRC_WH[0]:
        block["width"], block["height"] = DST_WH
    for key, s in (("fx_px", sx), ("cx_px", sx), ("fy_px", sy), ("cy_px", sy)):
        if key in block:
            block[key] = block[key] * s


def downscale_tree(src: Path, dst: Path) -> int:
    count = 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src); out = dst / rel
        if path.is_dir():
            continue
        if path.suffix in (".exr", ".png"):
            downscale_file(path, out); count += 1
        elif path.name == "manifest.json":
            data = json.loads(path.read_text(encoding="utf-8"))
            rescale_camera(data.get("camera", {}))
            for frame in data.get("frames", []):
                rescale_camera(frame.get("camera", {}))
            data["downscaled_from"] = {"width": SRC_WH[0], "height": SRC_WH[1],
                                       "tool": "apps/downscale_abo_render.py"}
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(data, indent=1), encoding="utf-8")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
    return count


def downscale_in_place(render: Path) -> tuple[int, int]:
    """Rewrite a live render tree file by file: (downscaled, already 512).

    The dataloader reads these trees while training, so every file goes to a
    hidden temp beside it and is renamed over the original: a reader sees the
    old file or the new one, never half of either. Files already at 512 are
    skipped, so an interrupted run resumes. Manifests go last; IR_PIPELINE
    scales intrinsics by camera.width, so a frame read mid-scene is consistent
    whichever pair it gets.
    """
    done = skipped = 0
    for path in sorted(render.rglob("*")):
        if path.suffix not in (".exr", ".png") or path.name.startswith("."):
            continue
        img_hw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img_hw is not None and img_hw.shape[1] == DST_WH[0]:
            skipped += 1
            continue
        tmp = path.with_name(f".{path.stem}.dstmp{path.suffix}")
        downscale_file(path, tmp)
        os.replace(tmp, path)
        done += 1
    for manifest in sorted(render.rglob("manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if "downscaled_from" in data:
            continue
        rescale_camera(data.get("camera", {}))
        for frame in data.get("frames", []):
            rescale_camera(frame.get("camera", {}))
        data["downscaled_from"] = {"width": SRC_WH[0], "height": SRC_WH[1],
                                   "tool": "apps/downscale_abo_render.py"}
        tmp = manifest.with_name(".manifest.dstmp.json")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, manifest)
    return done, skipped


def _self_check() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp, "src"), Path(tmp, "dst")
        (src / "f").mkdir(parents=True)
        mask = np.zeros((540, 720), np.uint8); mask[100:300, 200:500] = 255
        cv2.imwrite(str(src / "f/x_glass_mask0001.png"), mask)
        rgb = np.random.default_rng(0).random((540, 720, 3)).astype(np.float32)
        cv2.imwrite(str(src / "f/x_rgb0001.exr"), rgb, [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF])
        (src / "manifest.json").write_text(json.dumps({"camera": {"width": 720, "height": 540,
            "fx_px": 869.5461, "cx_px": 360.0, "cy_px": 270.0, "fy_px": 869.5461}, "frames": []}))
        assert downscale_tree(src, dst) == 2
        m = cv2.imread(str(dst / "f/x_glass_mask0001.png"), cv2.IMREAD_UNCHANGED)
        assert m.shape == (384, 512) and set(np.unique(m)) <= {0, 255}, "mask must stay binary"
        r = cv2.imread(str(dst / "f/x_rgb0001.exr"), cv2.IMREAD_UNCHANGED)
        assert r.shape == (384, 512, 3) and abs(float(r.mean()) - float(rgb.mean())) < 1e-3, "area keeps mean"
        cam = json.loads((dst / "manifest.json").read_text())["camera"]
        assert (cam["width"], cam["height"]) == (512, 384)
        assert abs(cam["fx_px"] - 618.3439) < 1e-3 and cam["cx_px"] == 256.0 and cam["cy_px"] == 192.0
        # in place: rewrites once, then is a no-op; no temp files left behind
        assert downscale_in_place(src) == (2, 0)
        assert downscale_in_place(src) == (0, 2)
        assert not list(src.rglob(".*dstmp*"))
        cam = json.loads((src / "manifest.json").read_text())["camera"]
        assert abs(cam["fx_px"] - 618.3439) < 1e-3, "manifest rescaled exactly once"
    print("self-check ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-check"]:
        _self_check()
    elif sys.argv[1:2] == ["--in-place"]:
        for d in sys.argv[2:]:
            n, s = downscale_in_place(Path(d))
            print(f"{d}: downscaled {n}, already 512 {s}", flush=True)
    else:
        n = downscale_tree(Path(sys.argv[1]), Path(sys.argv[2]))
        print(f"downscaled {n} images")
