#!/usr/bin/env python3
"""Run reproducible, exclusive-GPU IR sampling benchmarks.

``render_ir_dataset.py`` already gives the meaningful per-pass timing: it
converts the returned Dr.Jit tensor to NumPy before stopping the clock, hence
each ``mi_render_s`` is synchronized GPU wall time.  This wrapper adds:

* several viewpoints in one worker, so both passive and direct scenes warm up
  only once per sampling profile;
* a strict *idle GPU* precondition by default, avoiding a misleading timing
  from a production sweep sharing the device;
* low-overhead device telemetry (SM utilisation, VRAM, power) integrated over
  time.  When the exclusive precondition holds, device SM-active seconds are
  attributable to this benchmark rather than merely to the whole GPU.

The underlying renderer writes no frame directory until a frame has a rendered
artifact, so an interrupted benchmark remains visibly incomplete.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MITSUBA_PYTHON = Path("/root/miniconda3/envs/mitsuba_optix7/bin/python")
DEFAULT_MITSUBA_PYTHONPATH = Path("/root/robomituba-build/mitsuba3-optix7/python")


@dataclass(frozen=True)
class Profile:
    name: str
    width: int
    height: int
    rgb_spp: int
    ambient_spp: int
    direct_spp: int
    max_depth: int


def _parse_profile(value: str) -> Profile:
    """Parse ``name:WxH:rgb:ambient:direct:max_depth``."""
    parts = value.split(":")
    if len(parts) != 6 or "x" not in parts[1].lower():
        raise argparse.ArgumentTypeError(
            "profile must be name:WIDTHxHEIGHT:rgb_spp:ambient_spp:direct_spp:max_depth"
        )
    width_text, height_text = parts[1].lower().split("x", 1)
    try:
        profile = Profile(
            name=parts[0], width=int(width_text), height=int(height_text),
            rgb_spp=int(parts[2]), ambient_spp=int(parts[3]),
            direct_spp=int(parts[4]), max_depth=int(parts[5]),
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid profile: {value!r}") from exc
    if not profile.name or min(profile.width, profile.height, profile.rgb_spp, profile.ambient_spp, profile.direct_spp) <= 0:
        raise argparse.ArgumentTypeError(f"profile values must be positive: {value!r}")
    if profile.max_depth == 0 or profile.max_depth < -1:
        raise argparse.ArgumentTypeError(f"max_depth must be -1 or positive: {value!r}")
    return profile


def _nvidia_smi_gpu(gpu_index: int) -> dict[str, float]:
    command = [
        "nvidia-smi", "--id", str(gpu_index),
        "--query-gpu=index,utilization.gpu,memory.used,memory.total,power.draw",
        "--format=csv,noheader,nounits",
    ]
    line = subprocess.check_output(command, text=True).strip().splitlines()[-1]
    values = [part.strip() for part in line.split(",")]
    if len(values) != 5:
        raise RuntimeError(f"unexpected nvidia-smi response: {line!r}")
    return {
        "gpu_index": float(values[0]), "sm_percent": float(values[1]),
        "memory_used_mib": float(values[2]), "memory_total_mib": float(values[3]),
        "power_w": float(values[4]),
    }


def _compute_pids(gpu_index: int) -> list[int]:
    command = [
        "nvidia-smi", "--id", str(gpu_index), "--query-compute-apps=pid",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "could not inspect GPU processes")
    result_pids = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and line not in {"No running compute processes found"}:
            result_pids.append(int(line))
    return result_pids


class DeviceTelemetry:
    """Device-level samples, valid as process telemetry only on an idle GPU."""

    def __init__(self, gpu_index: int, interval_s: float) -> None:
        self.gpu_index = gpu_index
        self.interval_s = interval_s
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self) -> None:
        try:
            payload = _nvidia_smi_gpu(self.gpu_index)
            payload["time_s"] = time.perf_counter()
            self.samples.append(payload)
        except Exception as exc:  # retain benchmark result even if a driver query glitches
            self.samples.append({"time_s": time.perf_counter(), "telemetry_error": str(exc)})

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._sample()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.interval_s * 3.0))
        self._sample()

    def summary(self, start_index: int = 0, end_index: int | None = None) -> dict[str, Any]:
        selected = self.samples[start_index:end_index]
        valid = [sample for sample in selected if "sm_percent" in sample]
        busy_s = energy_j = 0.0
        for left, right in zip(valid, valid[1:]):
            dt = max(0.0, right["time_s"] - left["time_s"])
            busy_s += dt * ((left["sm_percent"] + right["sm_percent"]) * 0.5) / 100.0
            energy_j += dt * ((left["power_w"] + right["power_w"]) * 0.5)
        return {
            "sample_interval_s": self.interval_s,
            "sample_count": len(valid),
            "device_sm_active_seconds_estimate": round(busy_s, 4),
            "device_energy_j_estimate": round(energy_j, 3),
            "peak_memory_mib": max((sample["memory_used_mib"] for sample in valid), default=None),
            "mean_sm_percent": round(statistics.fmean(sample["sm_percent"] for sample in valid), 3) if valid else None,
            "mean_power_w": round(statistics.fmean(sample["power_w"] for sample in valid), 3) if valid else None,
            "raw_samples": selected,
        }


def _timing_summary(profile_dir: Path, *, warmup_count: int) -> dict[str, Any]:
    records = []
    for frame_path in sorted(profile_dir.glob("vp_*/frame.json")):
        record = json.loads(frame_path.read_text(encoding="utf-8"))
        records.append(record)
    if not records:
        raise RuntimeError(f"no completed benchmark frames found in {profile_dir}")
    measured = records[warmup_count:]
    if not measured:
        raise RuntimeError("warmup-count removed every completed benchmark frame")
    pass_stats: dict[str, dict[str, float]] = {}
    for pass_name in ("rgb", "nir_ambient", "nir_flash_direct"):
        values = [float(record["render_timings_s"][pass_name]["mi_render_s"]) for record in measured]
        pass_stats[pass_name] = {
            "mean_s": round(statistics.fmean(values), 6), "median_s": round(statistics.median(values), 6),
            "p95_s": round(float(np.percentile(values, 95)), 6), "sum_s": round(sum(values), 6),
        }
    totals = [float(record["render_timings_s"]["observation_render_total_s"]) for record in measured]
    return {
        "completed_frames": len(records), "warmup_excluded_frames": warmup_count,
        "measured_frames": len(measured),
        "measured_frame_ids": [record["frame_id"] for record in measured],
        "per_pass_gpu_synchronized_wall_time": pass_stats,
        "per_frame_total_s": {
            "mean_s": round(statistics.fmean(totals), 6), "median_s": round(statistics.median(totals), 6),
            "p95_s": round(float(np.percentile(totals, 95)), 6), "sum_s": round(sum(totals), 6),
        },
    }


def _run_profile(args: argparse.Namespace, profile: Profile, telemetry: DeviceTelemetry) -> dict[str, Any]:
    profile_dir = args.out / profile.name
    if profile_dir.exists():
        raise FileExistsError(f"refusing to mix benchmark runs in existing {profile_dir}")
    command = [
        str(args.mitsuba_python), "-u", str(REPO_ROOT / "apps/render_ir_dataset.py"),
        "--scene-dir", str(args.scene_dir), "--surface-domain", args.surface_domain,
        "--out", str(profile_dir), "--viewpoints", ",".join(args.viewpoints),
        "--width", str(profile.width), "--height", str(profile.height), "--fov", str(args.fov),
        "--spp", str(profile.rgb_spp), "--rgb-spp", str(profile.rgb_spp),
        "--nir-ambient-spp", str(profile.ambient_spp), "--nir-direct-spp", str(profile.direct_spp),
        "--max-depth", str(profile.max_depth), "--subpixel", "1", "--band", str(args.band),
        "--observations-only", "--gpu-cleanup-interval", str(args.gpu_cleanup_interval), "--async-io",
        "--texture-max-resolution", str(args.texture_max_resolution),
        "--texture-cache-dir", str(args.texture_cache_dir), "--observation-variant", args.observation_variant,
    ]
    environment = os.environ.copy()
    environment.update({
        "CUDA_VISIBLE_DEVICES": str(args.gpu_index),
        "PYTHONPATH": str(args.mitsuba_pythonpath),
        "ROBOMITUBA_MITSUBA_RUNTIME": "optix7",
    })
    started = time.perf_counter()
    telemetry_start = len(telemetry.samples)
    log_path = args.out / f"{profile.name}.log"
    with log_path.open("x", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=REPO_ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    telemetry_end = len(telemetry.samples)
    if result.returncode:
        raise RuntimeError(f"profile {profile.name} failed ({result.returncode}); see {log_path}")
    timing = _timing_summary(profile_dir, warmup_count=args.warmup_count)
    timing.update({
        "profile": profile.__dict__, "process_elapsed_s": round(elapsed, 6),
        "command": command, "log": str(log_path),
        "device_telemetry": telemetry.summary(telemetry_start, telemetry_end),
    })
    return timing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True, help="published IR effective scene directory")
    parser.add_argument("--out", type=Path, required=True, help="new benchmark root; must not already exist")
    parser.add_argument("--viewpoints", required=True, help="comma-separated vp_id@heading list (at least two)")
    parser.add_argument("--profile", type=_parse_profile, action="append", default=[], help="name:WIDTHxHEIGHT:rgb:ambient:direct:max_depth")
    parser.add_argument("--gpu-index", type=int, required=True)
    parser.add_argument("--allow-shared-gpu", action="store_true", help="record telemetry as device-level only; do not use for normalized conclusions")
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--warmup-count", type=int, default=1, help="completed initial views excluded from normalized aggregates")
    parser.add_argument("--surface-domain", default="structural_specular_pbr")
    parser.add_argument("--fov", type=float, default=60.0)
    parser.add_argument("--band", type=int, default=854)
    parser.add_argument("--texture-max-resolution", type=int, default=256)
    parser.add_argument("--texture-cache-dir", type=Path, default=Path.home() / "robomituba-cache/ir_texture_downsampled")
    parser.add_argument("--gpu-cleanup-interval", type=int, default=100)
    parser.add_argument("--observation-variant", default="cuda_ad_rgb")
    parser.add_argument("--mitsuba-python", type=Path, default=DEFAULT_MITSUBA_PYTHON)
    parser.add_argument("--mitsuba-pythonpath", type=Path, default=DEFAULT_MITSUBA_PYTHONPATH)
    args = parser.parse_args()
    args.viewpoints = [value.strip() for value in args.viewpoints.split(",") if value.strip()]
    if len(args.viewpoints) < 2:
        parser.error("at least two viewpoints are required for normalized timing")
    if args.out.exists():
        parser.error(f"benchmark root exists: {args.out}; select a new output root")
    if not args.profile:
        parser.error("provide at least one --profile")
    if args.warmup_count < 0 or args.warmup_count >= len(args.viewpoints):
        parser.error("warmup-count must be non-negative and smaller than the viewpoint count")
    if args.sample_interval <= 0:
        parser.error("sample-interval must be positive")
    for path, label in ((args.scene_dir, "scene-dir"), (args.mitsuba_python, "mitsuba-python"), (args.mitsuba_pythonpath, "mitsuba-pythonpath")):
        if not path.exists():
            parser.error(f"{label} does not exist: {path}")

    existing_pids = _compute_pids(args.gpu_index)
    if existing_pids and not args.allow_shared_gpu:
        parser.error(
            f"GPU {args.gpu_index} is occupied by compute PIDs {existing_pids}; "
            "an exclusive GPU is required for attributable SM-active time. "
            "Wait for it or pass --allow-shared-gpu for a clearly non-normalized smoke run."
        )
    args.out.mkdir(parents=True)
    telemetry = DeviceTelemetry(args.gpu_index, args.sample_interval)
    telemetry.start()
    started = time.perf_counter()
    try:
        profiles = [_run_profile(args, profile, telemetry) for profile in args.profile]
    finally:
        telemetry.stop()
    payload = {
        "schema": "ir_sampling_benchmark_v1",
        "created_at_epoch_s": time.time(), "gpu_index": args.gpu_index,
        "exclusive_gpu_precondition": not args.allow_shared_gpu,
        "initial_compute_pids": existing_pids, "viewpoints": args.viewpoints,
        "warmup_count": args.warmup_count, "process_elapsed_s": round(time.perf_counter() - started, 6),
        "telemetry": telemetry.summary(), "profiles": profiles,
        "telemetry_interpretation": (
            "device SM-active seconds and energy are attributable to this benchmark because the GPU was idle at launch"
            if not args.allow_shared_gpu else
            "shared-GPU mode: device telemetry is not attributable to this benchmark; use per-pass synchronized timings only"
        ),
    }
    (args.out / "benchmark_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("gpu_index", "process_elapsed_s", "telemetry_interpretation", "profiles")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
