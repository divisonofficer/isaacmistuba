#!/usr/bin/env python3.10
"""Export an OpticalNav bridge-job dataset into a compact, trainable bundle.

The raw render output under ``out/bridge_jobs/`` stores three redundant rasters
per frame: ``rgb.exr`` (HDR linear float), ``rgb_raw.npz`` (the same buffer as
float32) and ``rgb.png`` (8-bit sRGB tonemapped).  EXR + NPZ account for ~92% of
the on-disk size and carry the same information.  For downstream optical-nav
training (place recognition / relative pose / feature matching) the 8-bit image
plus per-frame camera pose & intrinsics is enough.

This tool drops EXR/NPZ, re-encodes the PNG (JPEG q95 by default), and writes a
flat trainable layout with a consolidated ``index.jsonl`` of labels:

    <out>/
      images/<frame_id>__<camera_id>.jpg
      index.jsonl          # one record per (frame, camera) with pose + intrinsics
      dataset_meta.json    # scene, camera rig, counts, export options + nav refs
      graph/<scene>__viewpoint_graph.json   # nav graph: nodes + edges (vertex connectivity)
      grid/<scene>__traversable_grid.npy    # occupancy grid (+ .npy.json spec/legend)
      grid/<scene>__birdseye.png            # top-down grid + graph + episode paths
      episodes/<split>/<episode>.json       # vertex navigation paths (path_nodes)
      manifests/<frame_id>.json   # slimmed per-frame manifest (optional, --keep-manifests)

The navigation graph / grid / episodes are pulled from the OpticalNav dataset
root (``out/opticalnav/<version>/``, auto-detected) so the bundle is a usable
navigation-graph dataset, not just vertex positions + images.  Disable with
``--no-graph``; ``index.jsonl`` ``vp_id``/``heading_id`` are the join keys.

Measured on shared_office_floor_001 (2059 jobs, ~15 GB): JPEG q95 export lands
around ~0.3 GB (~48x smaller) while staying trainable.

Examples
--------
    python apps/export_optical_nav_dataset.py \
        --scene shared_office_floor_001 \
        --out out/exports/shared_office_floor_001_trainable \
        --image-format jpeg --jpeg-quality 95 --zip
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FrameRecord:
    frame_id: str
    camera_id: str
    image_rel: str
    record: dict
    src_png: Path
    manifest_slim: dict | None
    modality: str = "rgb"
    stokes_npz_src: Path | None = None


def _find_jobs(bridge_dir: Path, scene: str | None, include_probe: bool) -> list[Path]:
    jobs = []
    for job_dir in sorted(bridge_dir.glob("opticalnav-*")):
        if not job_dir.is_dir():
            continue
        if scene and scene not in job_dir.name:
            continue
        if not include_probe and "probe" in job_dir.name:
            continue
        jobs.append(job_dir)
    return jobs


def _load_manifest(job_dir: Path) -> tuple[Path, dict] | None:
    obs_root = job_dir / "observations"
    if not obs_root.is_dir():
        return None
    for obs_dir in sorted(obs_root.iterdir()):
        manifest = obs_dir / "manifest.json"
        if manifest.is_file():
            try:
                return obs_dir, json.loads(manifest.read_text())
            except json.JSONDecodeError:
                return None
    return None


def _camera_spec(manifest: dict, camera_id: str) -> dict:
    for spec in manifest.get("camera_specs", []) or []:
        if spec.get("camera_id") == camera_id:
            return spec
    return {}


def _build_records(job_dir: Path, keep_manifests: bool, exact_scene: str | None = None) -> list[FrameRecord]:
    loaded = _load_manifest(job_dir)
    if loaded is None:
        return []
    obs_dir, manifest = loaded
    frame_id = manifest.get("frame_id") or obs_dir.name
    scene_id = manifest.get("scene_id")
    # Exact scene matching: the --scene substring filter also catches sibling
    # scenes (e.g. "shared_office_floor_001" matches "..._chairtest").  When
    # --exact-scene is set, keep only frames whose manifest scene_id matches.
    if exact_scene is not None and scene_id != exact_scene:
        return []
    base_pose = (manifest.get("robot_state") or {}).get("base_pose")
    extras = manifest.get("extras") or {}

    records: list[FrameRecord] = []
    for artifact in manifest.get("artifacts", []) or []:
        camera_id = artifact.get("camera_id")
        png_rel = (artifact.get("artifact_paths") or {}).get("png")
        if not camera_id or not png_rel:
            continue
        src_png = (REPO_ROOT / png_rel).resolve()
        if not src_png.is_file():
            continue
        spec = _camera_spec(manifest, camera_id)
        modality = artifact.get("modality", "rgb")
        # Include the modality in the filename for non-rgb modalities so a camera
        # with multiple modalities (e.g. a polarization camera emitting s1_over_s0,
        # s2_over_s0, dop, aolp, polar_rgb_preview) doesn't overwrite itself.
        mod_suffix = "" if modality == "rgb" else f"__{modality}"
        image_rel = f"images/{frame_id}__{camera_id}{mod_suffix}.{{ext}}"
        stokes_rel = (artifact.get("artifact_paths") or {}).get("stokes_npz")
        stokes_src = (REPO_ROOT / stokes_rel).resolve() if stokes_rel else None
        record = {
            "frame_id": frame_id,
            "scene_id": scene_id,
            "camera_id": camera_id,
            "image": image_rel,  # ext filled in later
            "modality": modality,
            "camera_to_world": spec.get("camera_to_world"),
            "base_pose": base_pose,
            "fov_deg": spec.get("fov_deg"),
            "resolution": spec.get("resolution"),
            "vp_id": extras.get("opticalnav_vp_id") or extras.get("node_id"),
            "heading_id": extras.get("opticalnav_heading_id") or extras.get("heading_id"),
            "yaw_deg": extras.get("yaw_deg"),
            "render_mode": extras.get("render_mode"),
            "timestamp": manifest.get("timestamp"),
        }
        manifest_slim = None
        if keep_manifests:
            manifest_slim = _slim_manifest(manifest)
        records.append(
            FrameRecord(
                frame_id=frame_id,
                camera_id=camera_id,
                image_rel=image_rel,
                record=record,
                src_png=src_png,
                manifest_slim=manifest_slim,
                modality=modality,
                stokes_npz_src=stokes_src if (stokes_src and stokes_src.is_file()) else None,
            )
        )
    return records


def _slim_manifest(manifest: dict) -> dict:
    """Drop the bulky per-channel render-timing blocks but keep provenance."""
    slim = json.loads(json.dumps(manifest))  # deep copy
    for artifact in slim.get("artifacts", []) or []:
        artifact.pop("timing", None)
        # repoint artifact paths to the exported image only
        paths = artifact.get("artifact_paths") or {}
        for key in ("exr", "raw_npz"):
            paths.pop(key, None)
    return slim


# ---------------------------------------------------------------------------
# Navigation-graph artifacts (viewpoint graph + grid + episodes + bird's-eye)
#
# The compact image export above only knows about per-frame render manifests.
# The actual navigation graph (viewpoint nodes + edges), the traversable grid
# and the episode vertex paths live in the OpticalNav dataset root under
# ``out/opticalnav/<version>/``.  The index records carry ``vp_id`` / ``heading_id``
# which are the join keys back into the viewpoint graph, so we ship the graph,
# grid and episodes alongside the images to make the bundle a real nav dataset
# (not just scattered vertex positions + JPEGs).
# ---------------------------------------------------------------------------


def _autodetect_nav_root(scene_id: str, search_root: Path) -> Path | None:
    """Find the OpticalNav dataset root whose dataset.json lists this scene."""
    if not search_root.is_dir():
        return None
    for ds in sorted(search_root.glob("*/dataset.json")):
        try:
            data = json.loads(ds.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for art in data.get("scene_artifacts", []) or []:
            if art.get("scene_id") == scene_id:
                return ds.parent
    return None


def _find_scene_artifact(nav_root: Path, scene_id: str) -> dict | None:
    ds = nav_root / "dataset.json"
    try:
        data = json.loads(ds.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    for art in data.get("scene_artifacts", []) or []:
        if art.get("scene_id") == scene_id:
            return art
    return None


def _collect_episodes(nav_root: Path, scene_id: str) -> list[tuple[Path, dict]]:
    """Return (path, payload) for every episode whose scene_id matches."""
    eps: list[tuple[Path, dict]] = []
    ep_dir = nav_root / "episodes"
    if not ep_dir.is_dir():
        return eps
    for p in sorted(ep_dir.glob("*/*.json")):
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if d.get("scene_id") == scene_id:
            eps.append((p, d))
    return eps


def _node_cell_map(vgraph: dict, grid_spec: dict) -> dict[str, tuple[int, int]]:
    """Map node_id -> integer grid cell (col, row), deriving from world if absent."""
    origin = grid_spec.get("origin", [0.0, 0.0])
    res = grid_spec.get("resolution", 1.0) or 1.0
    out: dict[str, tuple[int, int]] = {}
    for n in vgraph.get("nodes", []) or []:
        nid = n.get("node_id")
        if not nid:
            continue
        cell = (n.get("extras") or {}).get("cell")
        if cell is None:
            pos = n.get("position") or n.get("world") or [0.0, 0.0]
            cell = [round((pos[0] - origin[0]) / res), round((pos[1] - origin[1]) / res)]
        out[nid] = (int(cell[0]), int(cell[1]))
    return out


def _render_birdseye(
    grid_npy: Path,
    grid_spec: dict,
    vgraph: dict,
    episodes: list[tuple[Path, dict]],
    dst_png: Path,
    scale: int,
) -> str | None:
    """Render a top-down grid map with the viewpoint graph + episode paths overlaid."""
    try:
        import numpy as np
        from PIL import ImageDraw
    except Exception as exc:  # noqa: BLE001
        print(f"[birdseye] skipped ({exc})", file=sys.stderr)
        return None
    try:
        grid = np.load(grid_npy)
    except Exception as exc:  # noqa: BLE001
        print(f"[birdseye] cannot load grid ({exc})", file=sys.stderr)
        return None

    h, w = grid.shape
    scale = max(1, scale)
    palette = {0: (45, 45, 48), 1: (232, 232, 235), 2: (196, 72, 72)}  # obstacle / traversable / hazard
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for val, col in palette.items():
        rgb[grid == val] = col
    img = Image.fromarray(rgb, "RGB").transpose(Image.FLIP_TOP_BOTTOM)  # +y world points up
    img = img.resize((w * scale, h * scale), Image.NEAREST).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    def px(cell: tuple[int, int]) -> tuple[int, int]:
        cx, cy = cell
        return (cx * scale + scale // 2, (h - 1 - cy) * scale + scale // 2)

    cellmap = _node_cell_map(vgraph, grid_spec)

    # Graph edges (the connectivity that "vertices only" was missing).
    ew = max(1, scale // 2)
    for e in vgraph.get("edges", []) or []:
        s = cellmap.get(e.get("source"))
        t = cellmap.get(e.get("target"))
        if s and t:
            draw.line([px(s), px(t)], fill=(90, 140, 220, 150), width=ew)

    # Graph nodes.
    r = max(1, scale)
    for cell in cellmap.values():
        x, y = px(cell)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(40, 90, 200, 230))

    # Episode vertex navigation paths.
    ep_colors = [(255, 160, 0), (0, 200, 120), (220, 60, 200), (0, 180, 220), (255, 90, 90)]
    for i, (_p, d) in enumerate(episodes):
        nodes = d.get("path_nodes") or []
        pts = [px(cellmap[n]) for n in nodes if n in cellmap]
        if len(pts) >= 2:
            draw.line(pts, fill=ep_colors[i % len(ep_colors)] + (255,), width=max(2, scale))
        if pts:
            sx, sy = pts[0]
            draw.ellipse([sx - 2 * r, sy - 2 * r, sx + 2 * r, sy + 2 * r], fill=(0, 220, 0, 255))
            gx, gy = pts[-1]
            draw.ellipse([gx - 2 * r, gy - 2 * r, gx + 2 * r, gy + 2 * r], fill=(230, 0, 0, 255))

    dst_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst_png, "PNG", optimize=True)
    return dst_png.name


def _export_nav_graph(
    out_dir: Path,
    scenes: list[str],
    nav_root_override: Path | None,
    include_dense: bool,
    birdseye: bool,
    birdseye_scale: int,
) -> dict:
    """Copy viewpoint graph / grid / episodes into the export and build metadata."""
    import shutil

    search_root = REPO_ROOT / "out" / "opticalnav"
    info: dict = {"root": None, "scenes": {}}
    graph_dir = out_dir / "graph"
    grid_dir = out_dir / "grid"
    ep_dir = out_dir / "episodes"

    for scene_id in scenes:
        root = nav_root_override or _autodetect_nav_root(scene_id, search_root)
        if root is None:
            print(f"[graph] no OpticalNav dataset found for scene {scene_id!r}", file=sys.stderr)
            continue
        art = _find_scene_artifact(root, scene_id)
        if not art:
            print(f"[graph] scene {scene_id!r} not in {root}/dataset.json", file=sys.stderr)
            continue
        info["root"] = str(root)
        scene_entry: dict = {"source": str(root)}

        # Viewpoint graph (nodes + edges).
        vgraph: dict = {}
        vg_ref = art.get("viewpoint_graph_ref")
        if vg_ref and (root / vg_ref).is_file():
            vgraph = json.loads((root / vg_ref).read_text())
            graph_dir.mkdir(parents=True, exist_ok=True)
            dst = graph_dir / f"{scene_id}__viewpoint_graph.json"
            dst.write_text(json.dumps(vgraph, ensure_ascii=False))
            scene_entry["viewpoint_graph"] = str(dst.relative_to(out_dir))
            scene_entry["node_count"] = len(vgraph.get("nodes", []) or [])
            scene_entry["edge_count"] = len(vgraph.get("edges", []) or [])
            scene_entry["node_heading_count"] = vgraph.get("node_heading_count")

        # Traversable grid (+ legend/spec sidecar).
        grid_spec: dict = {}
        grid_npy_dst: Path | None = None
        grid_ref = art.get("traversable_grid_ref")
        if grid_ref and (root / grid_ref).is_file():
            grid_dir.mkdir(parents=True, exist_ok=True)
            grid_npy_dst = grid_dir / f"{scene_id}__traversable_grid.npy"
            shutil.copy2(root / grid_ref, grid_npy_dst)
            scene_entry["grid"] = str(grid_npy_dst.relative_to(out_dir))
            sidecar = root / (grid_ref + ".json")
            if sidecar.is_file():
                meta = json.loads(sidecar.read_text())
                grid_spec = meta.get("grid", {})
                (grid_dir / f"{scene_id}__traversable_grid.npy.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2)
                )
                scene_entry["grid_spec"] = grid_spec
                scene_entry["grid_legend"] = meta.get("legend")
        if not grid_spec:
            grid_spec = vgraph.get("metadata", {}).get("grid", {}) if vgraph else {}

        # Dense cell-level nav graph (optional; large).
        if include_dense:
            ng_ref = art.get("nav_graph_ref")
            if ng_ref and (root / ng_ref).is_file():
                graph_dir.mkdir(parents=True, exist_ok=True)
                dst = graph_dir / f"{scene_id}__nav_graph.json"
                shutil.copy2(root / ng_ref, dst)
                scene_entry["nav_graph"] = str(dst.relative_to(out_dir))

        # Episodes (vertex navigation paths).
        episodes = _collect_episodes(root, scene_id)
        ep_rel: list[str] = []
        for src, payload in episodes:
            split = src.parent.name
            dst = ep_dir / split / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(payload, ensure_ascii=False))
            ep_rel.append(str(dst.relative_to(out_dir)))
        scene_entry["episodes"] = ep_rel
        scene_entry["episode_count"] = len(ep_rel)

        # Bird's-eye grid map PNG with graph + episode paths overlaid.
        if birdseye and grid_npy_dst is not None and vgraph:
            png = grid_dir / f"{scene_id}__birdseye.png"
            name = _render_birdseye(grid_npy_dst, grid_spec, vgraph, episodes, png, birdseye_scale)
            if name:
                scene_entry["birdseye_image"] = str(png.relative_to(out_dir))

        info["scenes"][scene_id] = scene_entry
        print(
            f"[graph] {scene_id}: {scene_entry.get('node_count', 0)} nodes, "
            f"{scene_entry.get('edge_count', 0)} edges, {len(ep_rel)} episodes"
            + (", birdseye" if scene_entry.get("birdseye_image") else "")
        )
    return info


def _encode_image(args: tuple[str, str, str, int]) -> tuple[str, int, str | None]:
    """Worker: read src png, write target image, return (dst, bytes, error)."""
    src, dst, fmt, quality = args
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            if fmt == "jpeg":
                im.save(dst, "JPEG", quality=quality, optimize=True)
            elif fmt == "webp":
                im.save(dst, "WEBP", quality=quality, method=6)
            elif fmt == "png":
                im.save(dst, "PNG", optimize=True)
            else:
                return dst, 0, f"unknown format {fmt}"
        return dst, Path(dst).stat().st_size, None
    except Exception as exc:  # noqa: BLE001
        return dst, 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default=None, help="Only export jobs whose name contains this string (e.g. shared_office_floor_001).")
    ap.add_argument("--exact-scene", action="store_true", help="Treat --scene as an exact scene_id (drops sibling scenes like '..._chairtest' that the substring filter would otherwise include).")
    ap.add_argument("--bridge-jobs-dir", default=str(REPO_ROOT / "out" / "bridge_jobs"))
    ap.add_argument("--out", required=True, help="Output dataset directory.")
    ap.add_argument("--image-format", choices=["jpeg", "webp", "png"], default="jpeg")
    ap.add_argument("--jpeg-quality", type=int, default=95, help="Quality for jpeg/webp (1-100).")
    ap.add_argument("--include-probe", action="store_true", help="Also export probe_* jobs (default: grid vp only).")
    ap.add_argument("--keep-manifests", action="store_true", help="Also write slimmed per-frame manifest.json for full provenance.")
    ap.add_argument("--no-polarization-raw", action="store_true", help="Skip copying polarization stokes_data.npz (raw Stokes) into polarization_raw/.")
    ap.add_argument("--nav-dataset-root", default=None, help="OpticalNav dataset root (dataset.json + scenes/ + episodes/). Auto-detected under out/opticalnav/* if omitted.")
    ap.add_argument("--no-graph", action="store_true", help="Skip exporting the viewpoint navigation graph / grid / episodes.")
    ap.add_argument("--no-birdseye", action="store_true", help="Skip the bird's-eye grid+graph PNG.")
    ap.add_argument("--include-dense-nav-graph", action="store_true", help="Also copy the large cell-level nav_graph.json (tens of MB).")
    ap.add_argument("--birdseye-scale", type=int, default=2, help="Upscale factor for the bird's-eye PNG (default 2).")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="Process only the first N jobs (debug).")
    ap.add_argument("--zip", action="store_true", help="Produce a single <out>.zip after export.")
    ap.add_argument("--dry-run", action="store_true", help="Scan and report sizes without writing images.")
    args = ap.parse_args()

    bridge_dir = Path(args.bridge_jobs_dir).resolve()
    out_dir = Path(args.out).resolve()
    ext = {"jpeg": "jpg", "webp": "webp", "png": "png"}[args.image_format]

    jobs = _find_jobs(bridge_dir, args.scene, args.include_probe)
    if args.limit:
        jobs = jobs[: args.limit]
    if not jobs:
        print(f"[error] no matching jobs under {bridge_dir} (scene={args.scene!r})", file=sys.stderr)
        return 1
    print(f"[scan] {len(jobs)} jobs matched (scene={args.scene!r}, include_probe={args.include_probe})")

    # Collect frame records.
    records: list[FrameRecord] = []
    skipped = 0
    exact_scene = args.scene if (args.exact_scene and args.scene) else None
    for job_dir in jobs:
        frame_records = _build_records(job_dir, args.keep_manifests, exact_scene)
        if not frame_records:
            skipped += 1
            continue
        records.extend(frame_records)
    print(f"[scan] {len(records)} frames to export ({skipped} jobs skipped: no manifest/png)")

    src_bytes = sum(r.src_png.stat().st_size for r in records)
    print(f"[scan] source PNG total: {src_bytes / 1048576:.1f} MB")

    if args.dry_run:
        print("[dry-run] no images written.")
        return 0

    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Encode images in parallel.
    tasks = []
    for r in records:
        mod_suffix = "" if r.modality == "rgb" else f"__{r.modality}"
        dst = images_dir / f"{r.frame_id}__{r.camera_id}{mod_suffix}.{ext}"
        r.record["image"] = f"images/{dst.name}"
        tasks.append((str(r.src_png), str(dst), args.image_format, args.jpeg_quality))

    # Polarization raw: copy each camera's stokes_data.npz once (shared across the
    # camera's Stokes-representation modality rows) so downstream code can recompute
    # any representation. PNG representations are already exported as image rows above.
    polar_raw_copied = 0
    if not args.no_polarization_raw:
        raw_dir = out_dir / "polarization_raw"
        seen_raw: set[str] = set()
        for r in records:
            if r.stokes_npz_src is None:
                continue
            dst_name = f"{r.frame_id}__{r.camera_id}__stokes.npz"
            if dst_name in seen_raw:
                continue
            seen_raw.add(dst_name)
            raw_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(r.stokes_npz_src, raw_dir / dst_name)
                polar_raw_copied += 1
            except OSError as exc:
                print(f"[warn] stokes copy failed {dst_name}: {exc}", file=sys.stderr)
        if polar_raw_copied:
            print(f"[encode] copied {polar_raw_copied} polarization stokes_data.npz → polarization_raw/")

    out_bytes = 0
    errors = 0
    done = 0
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = [ex.submit(_encode_image, t) for t in tasks]
        for fut in as_completed(futures):
            dst, nbytes, err = fut.result()
            done += 1
            if err:
                errors += 1
                print(f"[warn] encode failed {Path(dst).name}: {err}", file=sys.stderr)
            else:
                out_bytes += nbytes
            if done % 500 == 0:
                print(f"[encode] {done}/{len(tasks)} ...")
    print(f"[encode] done: {done - errors} ok, {errors} failed")

    # Write index.jsonl.
    index_path = out_dir / "index.jsonl"
    with index_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r.record, ensure_ascii=False) + "\n")
    print(f"[write] {index_path.relative_to(out_dir.parent)} ({len(records)} records)")

    # Optional per-frame slimmed manifests.
    if args.keep_manifests:
        man_dir = out_dir / "manifests"
        man_dir.mkdir(exist_ok=True)
        for r in records:
            if r.manifest_slim is not None:
                (man_dir / f"{r.frame_id}.json").write_text(
                    json.dumps(r.manifest_slim, ensure_ascii=False, indent=2)
                )
        print(f"[write] manifests/ ({len(records)} files)")

    # Navigation graph + grid + episodes (the metadata the image-only export dropped).
    scenes = sorted({r.record["scene_id"] for r in records if r.record["scene_id"]})
    nav_info: dict = {"root": None, "scenes": {}}
    if not args.no_graph:
        nav_root = Path(args.nav_dataset_root).resolve() if args.nav_dataset_root else None
        nav_info = _export_nav_graph(
            out_dir,
            scenes,
            nav_root,
            include_dense=args.include_dense_nav_graph,
            birdseye=not args.no_birdseye,
            birdseye_scale=args.birdseye_scale,
        )

    # Dataset-level metadata.
    cameras = sorted({r.camera_id for r in records})
    meta = {
        "source": str(bridge_dir),
        "scene_filter": args.scene,
        "scenes": scenes,
        "cameras": cameras,
        "frame_count": len(records),
        "image_format": args.image_format,
        "jpeg_quality": args.jpeg_quality if args.image_format != "png" else None,
        "dropped_modalities": ["exr", "raw_npz"],
        "index_schema": {
            "image": "relative path to encoded image",
            "camera_to_world": "row-major flattened 4x4 (Mitsuba/USD convention, column-translation last)",
            "base_pose": "robot base 4x4 flattened",
            "fov_deg": "horizontal field of view",
            "resolution": "[width, height]",
            "vp_id": "viewpoint graph node id — join key into navigation.scenes[*].viewpoint_graph nodes[].node_id",
            "heading_id": "discrete heading bucket — matches viewpoint_graph nodes[].headings[].heading_id",
            "yaw_deg": "heading yaw in degrees",
        },
        "navigation": nav_info,
        "navigation_schema": {
            "viewpoint_graph": "per-scene graph JSON: nodes[] (node_id, position, headings) + edges[] (source, target, distance_m, path_polyline) — the connectivity between vertices",
            "grid": "traversable occupancy grid .npy (uint8 HxW); sidecar .npy.json holds grid spec (origin, resolution, width, height) + legend {0:obstacle,1:traversable,2:hazard}",
            "episodes": "vertex navigation paths: each episode has path_nodes[] / path_headings[] (vp ids), start_node, goal_node, instruction",
            "birdseye_image": "top-down PNG of the grid with the viewpoint graph (nodes+edges) and episode paths overlaid",
            "join": "index.jsonl vp_id+heading_id -> viewpoint_graph node+heading -> episode path_nodes",
        },
        "size_bytes": {"source_png": src_bytes, "exported_images": out_bytes},
    }
    (out_dir / "dataset_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"[write] dataset_meta.json")

    print(
        f"[size] source PNG {src_bytes / 1048576:.1f} MB -> exported {out_bytes / 1048576:.1f} MB "
        f"({src_bytes / out_bytes:.1f}x vs png)" if out_bytes else "[size] no images written"
    )

    if args.zip:
        zip_path = out_dir.with_suffix(".zip")
        print(f"[zip] writing {zip_path} ...")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for p in sorted(out_dir.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(out_dir.parent))
        print(f"[zip] {zip_path} ({zip_path.stat().st_size / 1048576:.1f} MB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
