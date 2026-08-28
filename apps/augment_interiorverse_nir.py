#!/usr/bin/env python3
"""Augment InteriorVerse G-buffers with deterministic pseudo-NIR relighting."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
import traceback
from typing import Any, Iterable

import numpy as np
from PIL import Image
from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.interiorverse_nir import (  # noqa: E402
    DATASET_SCHEMA,
    DATASET_SCHEMA_V1,
    DATASET_SCHEMA_V2,
    FRAME_SCHEMA,
    FRAME_SCHEMA_V1,
    FRAME_SCHEMA_V2,
    FORMULA_ID,
    FORMULA_ID_V1,
    FORMULA_ID_V2,
    FramePaths,
    atomic_write_json,
    discover_frames,
    frame_is_complete,
    load_frame,
    output_paths,
    render_frame,
    TRANSPORT_MODEL_RGB_REUSED_V1,
    TRANSPORT_MODEL_SS1_V1,
    TRANSPORT_MODELS,
    source_inventory,
    verify_source_inventory,
    write_frame,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("/bean/datasets/interiorverse_85_raw"))
    parser.add_argument("--output-root", type=Path, default=Path("/bean/datasets/interiorverse_85_nir_v2"))
    parser.add_argument("--devices", default="0,1,2,3,4,5,6,7", help="CUDA indices, or 'cpu'")
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--scene", action="append", help="process only this scene; repeatable")
    parser.add_argument("--limit-frames", "--frame-limit", type=int)
    parser.add_argument("--shadow-map-size", type=int, default=512)
    parser.add_argument("--transport-model", choices=sorted(TRANSPORT_MODELS), default=TRANSPORT_MODEL_SS1_V1)
    parser.add_argument("--legacy-v1-output-contract", action="store_true",
                        help="required acknowledgement before writing rgb_reused_v1 output")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cpu-fallback", action="store_true", help="fall back if CUDA/PyTorch is unavailable")
    parser.add_argument("--qc-count", type=int, default=32, help="rows in qc_montage.png; 0 disables")
    parser.add_argument("--log-every", type=float, default=30.0, help="non-TTY progress log interval in seconds")
    args = parser.parse_args(argv)
    if args.resume and args.overwrite:
        parser.error("--resume and --overwrite are mutually exclusive")
    if args.limit_frames is not None and args.limit_frames < 1:
        parser.error("--limit-frames must be positive")
    if args.shadow_map_size < 16:
        parser.error("--shadow-map-size must be at least 16")
    if args.transport_model == TRANSPORT_MODEL_RGB_REUSED_V1 and not args.legacy_v1_output_contract:
        parser.error("rgb_reused_v1 requires --legacy-v1-output-contract and a distinct v1 output root")
    if (args.transport_model == TRANSPORT_MODEL_RGB_REUSED_V1
            and "v1" not in str(args.output_root).lower()):
        parser.error("rgb_reused_v1 must use a distinct output root whose name contains 'v1'")
    return args


def _resolve_devices(spec: str, cpu_fallback: bool) -> list[str]:
    values = [part.strip() for part in spec.split(",") if part.strip()]
    if not values:
        raise ValueError("--devices is empty")
    if values == ["cpu"]:
        return values
    if "cpu" in values:
        raise ValueError("'cpu' cannot be mixed with CUDA device indices")
    try:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("torch.cuda.is_available() is false")
        count = torch.cuda.device_count()
        indices = [int(value) for value in values]
        invalid = [index for index in indices if index < 0 or index >= count]
        if invalid:
            raise RuntimeError(f"invalid CUDA indices {invalid}; visible device count={count}")
        return [f"cuda:{index}" for index in indices]
    except (ImportError, RuntimeError, ValueError) as exc:
        if cpu_fallback:
            print(f"CUDA unavailable ({exc}); using CPU fallback", file=sys.stderr, flush=True)
            return ["cpu"]
        raise RuntimeError(f"cannot use --devices={spec!r}: {exc}; pass --cpu-fallback to continue") from exc


def _scene_shards(frames: list[FramePaths], devices: list[str]) -> list[list[FramePaths]]:
    by_scene: dict[str, list[FramePaths]] = {}
    for frame in frames:
        by_scene.setdefault(frame.scene, []).append(frame)
    shards = [[] for _ in devices]
    loads = [0 for _ in devices]
    for _, scene_frames in sorted(by_scene.items(), key=lambda item: (-len(item[1]), item[0])):
        target = min(range(len(devices)), key=lambda index: (loads[index], index))
        shards[target].extend(scene_frames)
        loads[target] += len(scene_frames)
    return shards


def _worker(
    frames: list[FramePaths],
    device: str,
    source_root: Path,
    output_root: Path,
    seed: int,
    resume: bool,
    overwrite: bool,
    shadow_map_size: int,
    transport_model: str,
    events: Any,
) -> None:
    try:
        if device.startswith("cuda"):
            import torch

            torch.cuda.set_device(int(device.split(":", 1)[1]))
        for frame in frames:
            started = time.monotonic()
            try:
                complete = frame_is_complete(output_root, frame.scene, frame.frame)
                if complete and resume:
                    events.put({"kind": "frame", "status": "skipped", "scene": frame.scene, "frame": frame.frame, "seconds": 0.0})
                    continue
                if complete and not overwrite:
                    raise FileExistsError(
                        f"complete output exists for {frame.scene}/{frame.frame}; use --resume or --overwrite"
                    )
                had_artifact = any(path.exists() for path in output_paths(
                    output_root, frame.scene, frame.frame, transport_model=transport_model,
                ).values())
                data = load_frame(frame)
                outputs, metadata = render_frame(
                    data,
                    seed=seed,
                    scene=frame.scene,
                    frame=frame.frame,
                    shadow_device=device,
                    shadow_map_size=shadow_map_size,
                    transport_model=transport_model,
                )
                write_frame(frame, output_root, outputs, metadata, source_root)
                events.put({
                    "kind": "frame", "status": "regenerated" if had_artifact else "written",
                    "scene": frame.scene, "frame": frame.frame, "seconds": time.monotonic() - started,
                })
            except Exception:
                events.put({
                    "kind": "frame", "status": "failed", "scene": frame.scene, "frame": frame.frame,
                    "seconds": time.monotonic() - started, "error": traceback.format_exc(),
                })
    except BaseException:
        events.put({"kind": "worker_failed", "device": device, "error": traceback.format_exc()})
    finally:
        events.put({"kind": "worker_done", "device": device})


def _run_workers(frames: list[FramePaths], devices: list[str], args: argparse.Namespace) -> Counter:
    context = mp.get_context("spawn")
    events = context.Queue()
    processes = []
    for device, shard in zip(devices, _scene_shards(frames, devices)):
        if not shard:
            continue
        process = context.Process(
            target=_worker,
            args=(
                shard, device, args.source_root, args.output_root, args.seed, args.resume,
                args.overwrite, args.shadow_map_size, args.transport_model, events,
            ),
            name=f"interiorverse-nir-{device.replace(':', '-')}",
        )
        process.start()
        processes.append(process)
    counts: Counter = Counter()
    failures: list[str] = []
    done = 0
    last_log = time.monotonic()
    interactive = sys.stderr.isatty()
    with tqdm(total=len(frames), unit="frame", desc="InteriorVerse NIR", dynamic_ncols=True) as progress:
        while done < len(processes):
            try:
                event = events.get(timeout=1.0)
            except queue.Empty:
                if not interactive and time.monotonic() - last_log >= args.log_every:
                    print(
                        f"progress {progress.n}/{len(frames)} "
                        f"written={counts['written']} skipped={counts['skipped']} "
                        f"regenerated={counts['regenerated']} failed={counts['failed']}",
                        file=sys.stderr, flush=True,
                    )
                    last_log = time.monotonic()
                continue
            if event["kind"] == "worker_done":
                done += 1
                continue
            if event["kind"] == "worker_failed":
                failures.append(f"worker {event['device']}:\n{event['error']}")
                continue
            status = event["status"]
            counts[status] += 1
            progress.update(1)
            progress.set_postfix(
                ok=counts["written"], skip=counts["skipped"], redo=counts["regenerated"], fail=counts["failed"],
                scene=event["scene"][:12],
                refresh=False,
            )
            if status == "failed":
                failures.append(f"{event['scene']}/{event['frame']}:\n{event['error']}")
    for process in processes:
        process.join()
        if process.exitcode:
            failures.append(f"{process.name} exited with code {process.exitcode}")
    if failures:
        preview = "\n\n".join(failures[:10])
        raise RuntimeError(f"{len(failures)} processing failure(s):\n{preview}")
    return counts


def _load_completed_metadata(frames: Iterable[FramePaths], output_root: Path) -> list[dict[str, Any]]:
    rows = []
    for frame in frames:
        path = output_paths(output_root, frame.scene, frame.frame)["metadata"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_schema = FRAME_SCHEMA_V2 if payload.get("transport_model") == TRANSPORT_MODEL_SS1_V1 else FRAME_SCHEMA_V1
        if payload.get("schema") != expected_schema or payload.get("complete") is not True:
            raise RuntimeError(f"invalid completion metadata: {path}")
        rows.append(payload)
    return sorted(rows, key=lambda row: (row["scene"], row["frame"]))


def _atomic_write_index(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                compact = {
                    "scene": row["scene"], "frame": row["frame"], "shape": row["shape"],
                    "source": row["source"], "outputs": row["outputs"],
                    "metadata": f"{row['scene']}/{row['frame']}_nir_meta.json",
                    "valid_fraction": row["statistics"]["valid_fraction"],
                }
                handle.write(json.dumps(compact, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _tone_scalar(value: np.ndarray, exposure: float) -> np.ndarray:
    mapped = np.clip(np.maximum(value, 0.0) / max(exposure, 1e-8), 0.0, 1.0) ** (1.0 / 2.2)
    return np.repeat((mapped * 255.0 + 0.5).astype(np.uint8)[..., None], 3, axis=2)


def _write_qc_montage(rows: list[dict[str, Any]], source_root: Path, output_root: Path, count: int) -> None:
    if count <= 0 or not rows:
        return
    import cv2

    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    selected = rows[:count]
    strips = []
    for row in tqdm(selected, desc="QC montage", unit="frame", leave=False):
        image = cv2.imread(str(source_root / row["source"]["im"]), cv2.IMREAD_UNCHANGED)
        image = np.maximum(np.asarray(image[..., :3][..., ::-1], np.float32), 0.0)
        rgb_exposure = float(np.percentile(image[np.isfinite(image)], 99.0)) if np.isfinite(image).any() else 1.0
        rgb = np.clip(image / max(rgb_exposure, 1e-8), 0.0, 1.0) ** (1.0 / 2.2)
        rgb = (rgb * 255.0 + 0.5).astype(np.uint8)
        nir = [
            cv2.imread(str(output_root / row["outputs"][name]), cv2.IMREAD_UNCHANGED)
            for name in ("nir_passive", "nir_active_colocated", "nir_active_random")
        ]
        finite = np.concatenate([value[np.isfinite(value)] for value in nir])
        exposure = float(np.percentile(finite, 99.0)) if len(finite) else 1.0
        strips.append(np.concatenate([rgb] + [_tone_scalar(value, exposure) for value in nir], axis=1))
    montage = np.concatenate(strips, axis=0)
    Image.fromarray(montage, "RGB").save(output_root / "qc_montage.png")


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.source_root = args.source_root.resolve()
    args.output_root = args.output_root.resolve()
    if args.source_root == args.output_root:
        raise ValueError("source and output roots must differ")
    frames = discover_frames(args.source_root, args.scene)
    if args.limit_frames is not None:
        frames = frames[: args.limit_frames]
    if not frames:
        raise RuntimeError("no complete InteriorVerse frames found")
    inventory = source_inventory(frames, args.source_root)
    devices = _resolve_devices(args.devices, args.cpu_fallback)
    if args.transport_model == TRANSPORT_MODEL_SS1_V1 and devices == ["cpu"] and not args.cpu_fallback:
        raise RuntimeError("screen_space_one_bounce_v1 production output requires CUDA; use --cpu-fallback only for tests/limited frames")
    scenes = sorted({frame.scene for frame in frames})
    print(
        f"discovered {len(frames)} frames in {len(scenes)} scenes; devices={','.join(devices)}; "
        f"source={args.source_root}; output={args.output_root}", flush=True,
    )
    if args.dry_run:
        counts = Counter(
            complete=sum(frame_is_complete(args.output_root, frame.scene, frame.frame) for frame in frames)
        )
        print(f"dry-run complete_outputs={counts['complete']} pending={len(frames) - counts['complete']}")
        return 0
    args.output_root.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    counts = _run_workers(frames, devices, args)
    changed = verify_source_inventory(inventory, args.source_root)
    if changed:
        raise RuntimeError(f"raw source inventory changed during processing: {changed[:20]}")
    rows = _load_completed_metadata(frames, args.output_root)
    _atomic_write_index(args.output_root / "index.jsonl", rows)
    manifest = {
        "schema": DATASET_SCHEMA_V2 if args.transport_model == TRANSPORT_MODEL_SS1_V1 else DATASET_SCHEMA_V1,
        "formula_id": FORMULA_ID_V2 if args.transport_model == TRANSPORT_MODEL_SS1_V1 else FORMULA_ID_V1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started.isoformat(),
        "source_root": str(args.source_root),
        "output_root": str(args.output_root),
        "frame_count": len(frames),
        "scene_count": len(scenes),
        "scenes": scenes,
        "split_policy": "none; recovery split is not reused and no split is generated",
        "configuration": {
            "seed": args.seed, "devices": devices, "shadow_map_size": args.shadow_map_size,
            "transport_model": args.transport_model,
            "train_eligible": True, "default_training_weight": 1.0,
            "visible_only_limitation": (
                "off_screen_or_unresolved_rays_contribute_zero"
                if args.transport_model == TRANSPORT_MODEL_SS1_V1 else None
            ),
            "resume": args.resume, "overwrite": args.overwrite,
        },
        "counts": {name: counts[name] for name in ("written", "skipped", "regenerated", "failed")},
        "source_inventory": inventory,
        "source_inventory_verified": True,
        "git_sha": _git_sha(),
    }
    atomic_write_json(args.output_root / "dataset_manifest.json", manifest)
    _write_qc_montage(rows, args.source_root, args.output_root, args.qc_count)
    print(
        f"complete: frames={len(rows)} written={counts['written']} skipped={counts['skipped']} "
        f"regenerated={counts['regenerated']} output={args.output_root}", flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
