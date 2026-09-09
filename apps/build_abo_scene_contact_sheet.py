#!/usr/bin/env python3
"""One representative frame per ABO scene, as a channel strip, for review.

A scene is 76 frames and a corpus is a hundred-odd scenes, so nobody reviews
the corpus by opening it. This picks one pose per scene -- the highest-scoring
important pose under baseline lighting, which is the frame the scene was
composed to produce -- and renders a strip of the channels that a PBR consumer
actually needs to trust: RGB, active NIR, base colour, roughness, metallic and
world normal.

The point is per-scene confirmation, so the strip is deliberately small and the
scenes are deliberately all present. A sheet that shows six scenes beautifully
is not a review of a hundred.

Tone mapping is stated rather than tuned: HDR channels get a fixed exposure and
sRGB transfer, so two scenes that differ on the sheet differ in the data. An
auto-exposure per frame would make every scene look correctly lit, which is the
opposite of what a review is for.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

#: (channel, label, treatment). "hdr" is exposed and gamma-encoded; "unit" is
#: already 0-1 display-referred; "signed" is a world normal mapped to 0-1.
STRIP = (
    ("rgb", "RGB", "hdr"),
    ("nir_active", "NIR active", "hdr"),
    ("albedo_rgb", "base colour", "unit"),
    ("roughness", "roughness", "unit"),
    ("metallic", "metallic", "unit"),
    ("normal", "normal", "signed"),
)
BASELINE = "B0_warm_all"
EXPOSURE = 1.0
#: The closed-box curriculum, in the order the renderer walks it. Shown as RGB
#: for the same pose so a scene's lighting spread can be judged against itself
#: rather than against a neighbour's.
VARIANTS = ("B0_warm_all", "B1_warm_partial", "B2_neutral_all",
            "B3_cool_all", "B4_dim_warm", "B5_bright_mixed")


def _read(frame_dir: Path, channel: str) -> np.ndarray | None:
    for suffix in (".exr", ".png"):
        matches = list(frame_dir.glob(f"*_{channel}0001{suffix}"))
        if matches:
            image = cv2.imread(str(matches[0]), cv2.IMREAD_UNCHANGED)
            if image is None:
                return None
            image = image.astype(np.float32)
            if matches[0].suffix == ".png":
                image /= 65535.0 if image.max() > 255.0 else 255.0
            return image
    return None


def _encode(image: np.ndarray, treatment: str, width: int) -> str:
    if image.ndim == 2:
        image = image[..., None]
    if image.shape[2] == 1:
        image = np.repeat(image, 3, axis=2)
    image = image[..., :3]
    if treatment == "hdr":
        image = np.clip(image * EXPOSURE, 0.0, None)
        image = np.where(image <= 0.0031308, image * 12.92,
                         1.055 * np.power(image, 1 / 2.4) - 0.055)
    elif treatment == "signed":
        image = image * 0.5 + 0.5
    image = np.clip(image, 0.0, 1.0)
    height = max(1, round(image.shape[0] * width / image.shape[1]))
    small = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", (small * 255).astype(np.uint8),
                              [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode()


def spread_views(record, count):
    """`count` baseline poses chosen to show the scene, not one object.

    Reviewing a scene from a single frame reviews the frame. The first sheet
    showed each scene's highest-scoring important pose, and because that score
    rewards specular observability -- which peaks on glancing views of glossy
    surfaces, often from inside the furniture -- the pick was systematically the
    scene's most awkward framing rather than a typical one.

    So this rotates over distinct target objects and takes each target's
    best-covered pose. The targets sit in different places, so choosing one
    apiece spreads the viewpoints without needing to reason about camera
    geometry. Only when the targets are exhausted does it take a second pose
    from each.
    """
    baseline = [f for f in record.get("frames", [])
                if f.get("lighting_variant") == BASELINE]
    by_target = {}
    for frame in baseline:
        by_target.setdefault(frame.get("target_source_id") or "?", []).append(frame)
    for frames in by_target.values():
        frames.sort(key=lambda f: (f.get("coverage") or {}).get("object_fraction", 0.0),
                    reverse=True)
    chosen = []
    depth = 0
    while len(chosen) < count:
        added = False
        for target in sorted(by_target):
            if depth < len(by_target[target]):
                chosen.append(by_target[target][depth])
                added = True
                if len(chosen) == count:
                    break
        if not added:
            break
        depth += 1
    return chosen


def variant_frames(scene: Path, pose_index: int) -> list[dict[str, Any]]:
    """Every lighting variant of one pose, in curriculum order.

    Only important poses carry the full sweep, so this returns what exists
    rather than asserting six: a scene whose chosen pose is not important shows
    its baseline alone, which is the truth about that pose.
    """
    found: dict[str, Path] = {}
    for shard in sorted((scene / "render").glob("shard_*")):
        for frame_dir in shard.iterdir():
            if not frame_dir.is_dir():
                continue
            for variant in VARIANTS:
                if frame_dir.name.endswith(f"_p{pose_index:03d}_{variant}"):
                    found[variant] = frame_dir
    return [{"variant": v, "dir": found[v]} for v in VARIANTS if v in found]


def pick_frame(scene: Path) -> tuple[Path, dict[str, Any]] | None:
    """The scene's best important pose under baseline lighting.

    Read from the render manifest rather than by sorting directory names: the
    important poses are the ones the scene was composed to produce, and pose
    index 0 is not reliably one of them.
    """
    manifest = scene / "render" / "manifest.json"
    if not manifest.is_file():
        return None
    record = json.loads(manifest.read_text(encoding="utf-8"))
    frames = [f for f in record.get("frames", []) if f.get("lighting_variant") == BASELINE]
    if not frames:
        return None
    important = {f["pose_index"] for f in record["frames"]
                 if f.get("lighting_variant") != BASELINE}
    ranked = sorted(frames, key=lambda f: (f["pose_index"] in important,
                                           f.get("specular_score", 0.0)), reverse=True)
    for frame in ranked:
        for shard in sorted((scene / "render").glob("shard_*")):
            candidate = shard / frame["frame"]
            if candidate.is_dir():
                return candidate, {**frame, "_manifest": record}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=210)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--views", type=int, default=0,
                        help="RGB renders from this many viewpoints per scene, one per target "
                             "object where possible, so a review judges the scene rather than "
                             "one frame's framing")
    parser.add_argument("--variants", action=argparse.BooleanOptionalAction, default=True,
                        help="include the lighting sweep row")
    parser.add_argument("--seeds", default=None,
                        help="restrict to a seed range, e.g. 100-149, matched against the "
                             "four-digit suffix of the scene directory")
    args = parser.parse_args()

    scenes = sorted(p for p in args.root.glob("abo_cornell_*") if p.is_dir())
    if args.seeds:
        low, high = (int(v) for v in args.seeds.split("-", 1))
        scenes = [p for p in scenes if low <= int(p.name.rsplit("_", 1)[1]) <= high]
    if args.limit:
        scenes = scenes[:args.limit]
    rows, skipped = [], []
    for scene in scenes:
        picked = pick_frame(scene)
        if picked is None:
            skipped.append((scene.name, "no baseline frame in manifest"))
            continue
        frame_dir, frame = picked
        strip, missing = [], []
        for channel, label, treatment in STRIP:
            image = _read(frame_dir, channel)
            if image is None:
                missing.append(channel)
                strip.append({"label": label, "uri": None})
                continue
            strip.append({"label": label, "uri": _encode(image, treatment, args.width)})
        views = []
        for chosen in spread_views(frame["_manifest"], args.views):
            shard_dir = next((shard / chosen["frame"]
                              for shard in sorted((scene / "render").glob("shard_*"))
                              if (shard / chosen["frame"]).is_dir()), None)
            image = _read(shard_dir, "rgb") if shard_dir else None
            views.append({
                "label": "p%03d %s" % (chosen["pose_index"],
                                       (chosen.get("target_source_id") or "?")[-4:]),
                "uri": None if image is None else _encode(image, "hdr", args.width),
            })

        lighting = []
        for entry in (variant_frames(scene, frame["pose_index"]) if args.variants else []):
            image = _read(entry["dir"], "rgb")
            lighting.append({"label": entry["variant"].split("_", 1)[1].replace("_", " "),
                             "uri": None if image is None
                             else _encode(image, "hdr", args.width)})
        record = frame["_manifest"]
        scene_manifest = json.loads((scene / "scene_manifest.json").read_text(encoding="utf-8"))
        rows.append({
            "scene": scene.name,
            "frame": frame["frame"],
            "poses": record.get("pose_count"),
            "instances": len(scene_manifest.get("instances", [])),
            "room": scene_manifest.get("room", {}),
            "finish": scene_manifest.get("structural_finish", {}),
            "target": frame.get("target_source_id"),
            "distance_m": frame.get("target_distance_m"),
            "missing": missing,
            "strip": strip,
            "lighting": lighting,
            "views": views,
            "pose_index": frame["pose_index"],
        })
        print(f"[sheet] {scene.name} {frame['frame']}"
              + (f" MISSING {missing}" if missing else ""), flush=True)
    args.out.write_text(json.dumps({"rows": rows, "skipped": skipped}), encoding="utf-8")
    print(f"[sheet] {len(rows)} scenes, {len(skipped)} skipped -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
