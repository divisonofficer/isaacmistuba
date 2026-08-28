#!/usr/bin/env python3
"""Generate material-aware RGB diffuse shading and 12 W CCS active NIR data.

This publishes a new dataset root; it never mutates legacy InteriorVerse NIR
outputs.  The active source is a three-bar LDL-42X15IR2-850 assembly using a
provisional forward beam profile until manufacturer angular data is digitized.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import time
import traceback
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
for package in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / package / "src"))

from mitsuba_converter.interiorverse_nir import (  # noqa: E402
    ACTIVE_DATASET_SCHEMA_V1, ACTIVE_FRAME_SCHEMA_V1, FramePaths, atomic_write_exr,
    atomic_write_json, discover_frames, load_frame, render_ccs_active_nir_frame,
    source_inventory, verify_source_inventory,
)

OUTPUT_NAMES = (
    "rgb_diffuse_shading", "rgb_diffuse_reconstruction", "nir_passive_diffuse",
    "nir_passive_confidence", "nir_active_direct_ccs_3bar", "nir_active_ccs_3bar",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", type=Path, default=Path("/bean/datasets/interiorverse_85_raw"))
    p.add_argument("--output-root", type=Path, default=Path("/bean/datasets/interiorverse_85_active_nir_ccs12w_v1"))
    p.add_argument("--devices", default="0,1,2,3,4,5,6,7", help="CUDA indices or cpu")
    p.add_argument("--cpu-fallback", action="store_true")
    p.add_argument("--scene", action="append")
    p.add_argument("--limit-frames", type=int)
    p.add_argument("--shadow-map-size", type=int, default=512)
    p.add_argument("--samples-per-bar", type=int, default=3)
    p.add_argument("--relative-flux-per-bar", type=float, default=12.0 / 6.9)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.resume and args.overwrite:
        p.error("--resume and --overwrite are mutually exclusive")
    if args.limit_frames is not None and args.limit_frames < 1:
        p.error("--limit-frames must be positive")
    if args.shadow_map_size < 16 or args.samples_per_bar < 1 or args.relative_flux_per_bar <= 0:
        p.error("invalid rendering parameter")
    return args


def _devices(spec: str, cpu_fallback: bool) -> list[str]:
    parts = [value.strip() for value in spec.split(",") if value.strip()]
    if parts == ["cpu"]:
        return ["cpu"]
    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable")
        result = [f"cuda:{int(value)}" for value in parts]
        if any(int(item.split(":")[1]) >= torch.cuda.device_count() for item in result):
            raise RuntimeError("requested CUDA index is unavailable")
        return result
    except Exception as exc:
        if cpu_fallback:
            print(f"CUDA fallback: {exc}", file=sys.stderr)
            return ["cpu"]
        raise RuntimeError(f"cannot resolve --devices={spec!r}: {exc}") from exc


def _paths(root: Path, frame: FramePaths) -> dict[str, Path]:
    base = root / frame.scene
    return {name: base / f"{frame.frame}_{name}.exr" for name in OUTPUT_NAMES} | {
        "metadata": base / f"{frame.frame}_active_nir_meta.json",
    }


def _complete(root: Path, frame: FramePaths) -> bool:
    try:
        paths = _paths(root, frame)
        meta = json.loads(paths["metadata"].read_text())
        return meta.get("schema") == ACTIVE_FRAME_SCHEMA_V1 and meta.get("complete") is True and all(
            paths[name].is_file() for name in OUTPUT_NAMES
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _write(root: Path, frame: FramePaths, outputs: dict[str, Any], metadata: dict[str, Any], source_root: Path) -> dict[str, Any]:
    paths = _paths(root, frame)
    for name in OUTPUT_NAMES:
        atomic_write_exr(paths[name], outputs[name])
    payload = {
        "schema": ACTIVE_FRAME_SCHEMA_V1, "complete": True, "scene": frame.scene, "frame": frame.frame,
        "shape": list(outputs["nir_active_ccs_3bar"].shape),
        "source": {name: str(path.relative_to(source_root)) for name, path in frame.source.items()},
        "outputs": {name: str(paths[name].relative_to(root)) for name in OUTPUT_NAMES}, **metadata,
    }
    atomic_write_json(paths["metadata"], payload)
    return payload


def _worker(frames: list[FramePaths], device: str, args: argparse.Namespace, events: Any) -> None:
    try:
        if device.startswith("cuda"):
            import torch
            torch.cuda.set_device(int(device.split(":")[1]))
        for frame in frames:
            started = time.monotonic()
            try:
                complete = _complete(args.output_root, frame)
                if complete and args.resume:
                    events.put(("skipped", frame.scene, frame.frame, None)); continue
                if complete and not args.overwrite:
                    raise FileExistsError("complete output exists; use --resume or --overwrite")
                data = load_frame(frame)
                outputs, metadata = render_ccs_active_nir_frame(
                    data, relative_flux_per_bar=args.relative_flux_per_bar,
                    samples_per_bar=args.samples_per_bar, shadow_map_size=args.shadow_map_size,
                    shadow_device=device,
                )
                _write(args.output_root, frame, outputs, metadata, args.source_root)
                events.put(("written", frame.scene, frame.frame, time.monotonic() - started))
            except Exception:
                events.put(("failed", frame.scene, frame.frame, traceback.format_exc()))
    finally:
        events.put(("done", device, "", None))


def _shards(frames: list[FramePaths], count: int) -> list[list[FramePaths]]:
    result = [[] for _ in range(count)]
    for index, frame in enumerate(frames):
        result[index % count].append(frame)
    return result


def _run(frames: list[FramePaths], devices: list[str], args: argparse.Namespace) -> Counter:
    context = mp.get_context("spawn"); events = context.Queue()
    workers = [context.Process(target=_worker, args=(shard, device, args, events))
               for device, shard in zip(devices, _shards(frames, len(devices))) if shard]
    for worker in workers: worker.start()
    counts: Counter = Counter(); failures: list[str] = []; done = 0
    while done < len(workers):
        try: status, scene, frame, detail = events.get(timeout=1.0)
        except queue.Empty: continue
        if status == "done": done += 1; continue
        counts[status] += 1
        if status == "failed": failures.append(f"{scene}/{frame}:\n{detail}")
    for worker in workers: worker.join()
    if failures or any(worker.exitcode for worker in workers):
        raise RuntimeError("active NIR generation failed:\n" + "\n".join(failures[:10]))
    return counts


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.source_root = args.source_root.resolve(); args.output_root = args.output_root.resolve()
    if args.source_root == args.output_root: raise ValueError("source and output roots must differ")
    frames = discover_frames(args.source_root, args.scene)
    if args.limit_frames: frames = frames[:args.limit_frames]
    devices = _devices(args.devices, args.cpu_fallback)
    print(f"frames={len(frames)} devices={devices} output={args.output_root}", flush=True)
    if args.dry_run:
        print(f"complete={sum(_complete(args.output_root, frame) for frame in frames)} pending={len(frames)}")
        return 0
    args.output_root.mkdir(parents=True, exist_ok=True)
    inventory = source_inventory(frames, args.source_root)
    counts = _run(frames, devices, args)
    changed = verify_source_inventory(inventory, args.source_root)
    if changed: raise RuntimeError(f"source changed during generation: {changed[:20]}")
    rows = []
    for frame in frames:
        meta = json.loads(_paths(args.output_root, frame)["metadata"].read_text())
        rows.append({"scene": frame.scene, "frame": frame.frame, "outputs": meta["outputs"], "metadata": f"{frame.scene}/{frame.frame}_active_nir_meta.json"})
    atomic_write_json(args.output_root / "dataset_manifest.json", {
        "schema": ACTIVE_DATASET_SCHEMA_V1, "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(args.source_root), "frame_count": len(rows), "devices": devices,
        "configuration": {"electrical_input_w": 12.0, "relative_flux_per_bar": args.relative_flux_per_bar,
                          "angular_profile": "provisional spot core=45 cutoff=52", "samples_per_bar": args.samples_per_bar,
                          "shadow_map_size": args.shadow_map_size},
        "counts": dict(counts), "source_inventory": inventory, "source_inventory_verified": True,
    })
    with (args.output_root / "index.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows: handle.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"complete: {dict(counts)} output={args.output_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
