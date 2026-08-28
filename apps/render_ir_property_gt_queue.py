#!/usr/bin/env python3
"""Resumably add deterministic Mitsuba property GT to a completed IR observation run.

Rolling observation workers deliberately keep only the transport passes in GPU
memory.  This companion queue runs the independent primary-ray readout after
observations are complete, then patches the existing chunk/root indexes without
rewriting RGB/NIR artifacts.  It owns depth, NIR albedo, geometric normals,
stable IDs, and first-hit glass/mirror masks; Blender owns ARMN PBR GT.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))
sys.path.insert(0, str(REPO_ROOT / "apps"))

from mitsuba_converter.material_pipeline import uses_specular_semantic_masks, validate_ir_effective_scene  # noqa: E402
import render_ir_dataset as renderer  # noqa: E402
from render_ir_dataset_queue import (  # noqa: E402
    _atomic_json,
    _atomic_text,
    _parse_gpu_indices,
    _resolve_mitsuba_runtime,
    _runtime_worker_env,
    _validate_mitsuba_runtime,
)


RENDER_APP = REPO_ROOT / "apps" / "render_ir_dataset.py"
STATE_NAME = "property_gt_queue_state.json"
PROPERTY_GT = {
    "rgb_albedo", "nir_albedo", "roughness_perceptual", "metallic", "depth", "range",
    "normal_geometry_world", "normal_shading_world", "normal_tangent",
}
PROPERTY_MASKS = {"material_id", "object_id", "valid_mask", "replacement_mask"}
SPECULAR_MASKS = {"window_glass", "object_glass", "glass", "mirror"}


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    _atomic_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def _frame_spec(row: dict[str, Any]) -> str:
    return f"{row['viewpoint_id']}@{float(row['heading_deg']):g}"


def _required_masks(surface_domain: str) -> set[str]:
    return PROPERTY_MASKS | (SPECULAR_MASKS if uses_specular_semantic_masks(surface_domain) else set())


def _property_complete(row: dict[str, Any], *, surface_domain: str) -> bool:
    gt = dict(row.get("gt_paths") or {})
    masks = dict(row.get("mask_paths") or {})
    if not PROPERTY_GT <= set(gt) or not _required_masks(surface_domain) <= set(masks):
        return False
    paths = [Path(str(gt[name])) for name in PROPERTY_GT]
    paths += [Path(str(masks[name])) for name in _required_masks(surface_domain)]
    return all(path.is_file() for path in paths)


def _state_contract(*, effective_digest: str, width: int, height: int, fov: float, subpixel: int, band: int) -> dict[str, Any]:
    return {
        "effective_scene_digest": effective_digest,
        "width": int(width), "height": int(height), "fov": float(fov),
        "subpixel": int(subpixel), "band": int(band), "storage": "png16",
    }


def _load_state(dataset: Path, rows: list[dict[str, Any]], *, contract: dict[str, Any], surface_domain: str) -> dict[str, Any]:
    path = dataset / STATE_NAME
    by_id = {str(row["frame_id"]): row for row in rows}
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema") != "robomituba.ir_property_gt_queue.v1" or state.get("contract") != contract:
            raise RuntimeError("existing property GT queue is stale or incompatible; use a new output directory")
        if set(state.get("frames") or {}) != set(by_id):
            raise RuntimeError("property GT state frame set does not match root index")
    else:
        state = {
            "schema": "robomituba.ir_property_gt_queue.v1", "created_at": _utc_now(),
            "contract": contract, "frames": {frame_id: {"status": "pending", "attempts": 0}
                                                  for frame_id in by_id},
        }
    for frame_id, row in by_id.items():
        entry = state["frames"][frame_id]
        if _property_complete(row, surface_domain=surface_domain):
            entry.update({"status": "complete", "completed_at": entry.get("completed_at") or _utc_now()})
        elif entry.get("status") != "failed":
            entry["status"] = "pending"
    state["updated_at"] = _utc_now()
    _atomic_json(path, state)
    return state


def _persist_state(dataset: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _atomic_json(dataset / STATE_NAME, state)


def _run_batch(
    *, dataset: Path, effective_scene: Path, stage: Path, rows: list[dict[str, Any]],
    gpu: int, runtime: dict[str, str | None], args: argparse.Namespace,
) -> tuple[int, Path, list[dict[str, Any]], float]:
    """Run one bounded property-readout subprocess; parent alone publishes it."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    local_nir = dataset / "shared" / "property_gt_nir" / f"gpu_{gpu}"
    command = [
        str(runtime["python"]), "-u", str(RENDER_APP),
        "--scene-dir", str(effective_scene), "--surface-domain", str(args.surface_domain),
        "--out", str(stage), "--viewpoints", ",".join(_frame_spec(row) for row in rows),
        "--width", str(args.width), "--height", str(args.height), "--fov", str(args.fov),
        "--subpixel", str(args.subpixel), "--band", str(args.band),
        "--nir-cache-dir", str(local_nir), "--gt-only", "--gt-storage", "png16",
        "--gt-png-compression", str(args.png_compression),
        "--texture-max-resolution", str(args.texture_max_resolution),
        "--texture-cache-dir", str(args.texture_cache_dir),
        "--gpu-cleanup-interval", str(args.gpu_cleanup_interval),
    ]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=REPO_ROOT, env=_runtime_worker_env(gpu, runtime))
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"property GT subprocess failed gpu={gpu} returncode={result.returncode}")
    produced = _rows(stage / "index.jsonl")
    expected = {str(row["frame_id"]) for row in rows}
    if {str(row.get("frame_id")) for row in produced} != expected:
        raise RuntimeError(f"property GT batch returned an unexpected frame set on gpu={gpu}")
    return gpu, stage, produced, elapsed


def _relocate_batch_path(source: Path, *, stage: Path, dataset: Path, moved: dict[Path, Path]) -> Path:
    source = source.resolve()
    if source in moved:
        return moved[source]
    try:
        relative = source.relative_to(stage.resolve())
    except ValueError as exc:
        raise ValueError(f"property GT artifact escaped staging directory: {source}") from exc
    if not source.is_file():
        raise FileNotFoundError(f"property GT staged artifact missing: {source}")
    target = (dataset / relative).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    moved[source] = target
    return target


def _publish_batch(
    *, dataset: Path, stage: Path, produced: list[dict[str, Any]], rows_by_id: dict[str, dict[str, Any]],
    state: dict[str, Any], surface_domain: str, gpu: int, elapsed_s: float,
) -> list[str]:
    """Move staged rasters and make their metadata visible only after all files exist."""
    completed: list[str] = []
    moved: dict[Path, Path] = {}
    required_masks = _required_masks(surface_domain)
    for generated in produced:
        frame_id = str(generated["frame_id"])
        row = rows_by_id[frame_id]
        gt = dict(generated.get("gt_paths") or {})
        masks = dict(generated.get("mask_paths") or {})
        if not PROPERTY_GT <= set(gt) or not required_masks <= set(masks):
            raise RuntimeError(f"{frame_id}: property worker did not produce required GT/masks")
        final_gt = {
            name: str(_relocate_batch_path(Path(gt[name]), stage=stage, dataset=dataset, moved=moved))
            for name in gt
        }
        final_masks = {
            name: str(_relocate_batch_path(Path(masks[name]), stage=stage, dataset=dataset, moved=moved))
            for name in masks
        }
        legend = generated.get("id_legends_ref")
        final_legend = (
            str(_relocate_batch_path(Path(str(legend)), stage=stage, dataset=dataset, moved=moved))
            if legend else None
        )
        row.setdefault("gt_paths", {}).update(final_gt)
        row.setdefault("mask_paths", {}).update(final_masks)
        if final_legend:
            row["id_legends_ref"] = final_legend
        row["coverage"] = dict(generated.get("coverage") or {})
        row["property_gt_provider"] = "mitsuba_primary_ray_readout"
        row["property_gt_effective_scene_digest"] = state["contract"]["effective_scene_digest"]
        state["frames"][frame_id].update({
            "status": "complete", "gpu_index": int(gpu), "completed_at": _utc_now(),
            "wall_s": round(float(elapsed_s) / max(len(produced), 1), 6),
        })
        frame_json = (
            Path(str(row["frame_metadata_path"])).resolve()
            if row.get("frame_metadata_path")
            else Path(str(row["observation_paths"]["rgb"])).resolve().parent / "frame.json"
        )
        _atomic_json(frame_json, row)
        completed.append(frame_id)
    shutil.rmtree(stage, ignore_errors=True)
    return completed


def _write_indexes(dataset: Path, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    rows_by_id = {str(row["frame_id"]): row for row in rows}
    _write_rows(dataset / "index.jsonl", rows)
    if (manifest.get("configuration") or {}).get("storage_layout") == "modality_first_v1":
        return
    for chunk in manifest.get("chunks") or []:
        chunk_rows = []
        for spec in chunk.get("viewpoints") or []:
            node, _, heading = str(spec).partition("@")
            frame_id = f"{node}__h_{int(round(float(heading))) % 360:03d}"
            chunk_rows.append(rows_by_id[frame_id])
        _write_rows(dataset / str(chunk["relative_dir"]) / "index.jsonl", chunk_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="completed Stage-3 rolling observation root")
    parser.add_argument("--effective-scene", type=Path, help="defaults to <dataset>/ir_effective_scene")
    parser.add_argument("--gpu-indices", "--gpus", dest="gpu_indices", default="0,1,2,3,4,5,6,7")
    parser.add_argument("--parallel-workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--batch-retries", type=int, default=3)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fov", type=float, required=True)
    parser.add_argument("--subpixel", type=int, default=2)
    parser.add_argument("--band", type=int, default=854)
    parser.add_argument("--texture-max-resolution", type=int, default=256)
    parser.add_argument("--texture-cache-dir", type=Path, required=True)
    parser.add_argument("--png-compression", type=int, default=6)
    parser.add_argument("--gpu-cleanup-interval", type=int, default=4)
    parser.add_argument("--mitsuba-runtime", choices=("auto", "optix7", "optix8"), default="auto")
    args = parser.parse_args()
    if min(args.parallel_workers, args.batch_size, args.batch_retries, args.width, args.height, args.subpixel, args.band, args.gpu_cleanup_interval) < 1:
        parser.error("worker/batch/image/subpixel/band values must be positive")
    if not 0 <= args.png_compression <= 9 or args.texture_max_resolution < 0:
        parser.error("invalid PNG compression or texture maximum resolution")
    args.dataset = args.dataset.resolve()
    args.effective_scene = (args.effective_scene or args.dataset / "ir_effective_scene").resolve()
    args.texture_cache_dir = args.texture_cache_dir.expanduser().resolve()
    if str(args.texture_cache_dir).startswith("/jarvis/"):
        parser.error("--texture-cache-dir must be host-local, not /jarvis/NAS")
    manifest_path = args.dataset / "queue_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = validate_ir_effective_scene(args.effective_scene)
    if manifest.get("effective_scene_digest") != contract.get("effective_scene_digest"):
        raise RuntimeError("property GT effective-scene digest does not match completed observations")
    args.surface_domain = str(contract["surface_domain"])
    rows = _rows(args.dataset / "index.jsonl")
    if len(rows) != int(manifest.get("frame_count", -1)):
        raise RuntimeError("property GT requires a complete published Stage-3 root index")
    if len({str(row.get("frame_id")) for row in rows}) != len(rows):
        raise RuntimeError("root index contains duplicate or missing frame ids")
    runtime = _resolve_mitsuba_runtime(args.mitsuba_runtime)
    _validate_mitsuba_runtime(runtime)
    gpus = _parse_gpu_indices(args.gpu_indices)[:args.parallel_workers]
    if not gpus:
        raise RuntimeError("no GPU workers selected")
    contract_state = _state_contract(
        effective_digest=str(contract["effective_scene_digest"]), width=args.width, height=args.height,
        fov=args.fov, subpixel=args.subpixel, band=args.band,
    )
    state = _load_state(args.dataset, rows, contract=contract_state, surface_domain=args.surface_domain)
    renderer._write_gt_artifact_contract(args.dataset, storage="png16", band_nm=args.band)
    rows_by_id = {str(row["frame_id"]): row for row in rows}
    todo = [row for row in rows if state["frames"][str(row["frame_id"])].get("status") != "complete"]
    print(
        f"[property-gt] runtime={runtime['runtime']} frames={len(rows)} complete={len(rows)-len(todo)} "
        f"pending={len(todo)} workers={len(gpus)} gpus={','.join(map(str, gpus))}", flush=True,
    )
    if not todo:
        return 0
    batches = deque([todo[index:index + args.batch_size] for index in range(0, len(todo), args.batch_size)])
    staging_root = args.dataset / ".property_gt_batches"
    available = deque(gpus)
    active: dict[Any, tuple[int, Path, list[dict[str, Any]], int]] = {}
    terminal_failures: list[str] = []
    completed = len(rows) - len(todo)
    with ThreadPoolExecutor(max_workers=len(gpus)) as pool:
        while batches or active:
            while batches and available:
                gpu = available.popleft()
                batch = batches.popleft()
                first_id = str(batch[0]["frame_id"])
                attempt = max(int(state["frames"][str(row["frame_id"])].get("attempts", 0)) for row in batch) + 1
                for row in batch:
                    state["frames"][str(row["frame_id"])].update({"status": "running", "attempts": attempt, "gpu_index": gpu})
                stage = staging_root / f"gpu_{gpu}" / f"{first_id}_attempt_{attempt}"
                print(f"[property-gt] dispatch gpu={gpu} frames={len(batch)} attempt={attempt} first={first_id}", flush=True)
                future = pool.submit(
                    _run_batch, dataset=args.dataset, effective_scene=args.effective_scene, stage=stage,
                    rows=batch, gpu=gpu, runtime=runtime, args=args,
                )
                active[future] = (gpu, stage, batch, attempt)
                _persist_state(args.dataset, state)
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                gpu, stage, batch, attempt = active.pop(future)
                available.append(gpu)
                try:
                    result_gpu, result_stage, produced, elapsed_s = future.result()
                    frame_ids = _publish_batch(
                        dataset=args.dataset, stage=result_stage, produced=produced, rows_by_id=rows_by_id,
                        state=state, surface_domain=args.surface_domain, gpu=result_gpu, elapsed_s=elapsed_s,
                    )
                    completed += len(frame_ids)
                    _write_indexes(args.dataset, rows, manifest)
                    print(
                        f"[property-gt] complete {completed}/{len(rows)} gpu={gpu} frames={len(frame_ids)} "
                        f"batch_wall={elapsed_s:.2f}s", flush=True,
                    )
                except Exception as exc:  # retry the bounded batch in a fresh CUDA process
                    message = f"gpu={gpu} frames={len(batch)} attempt={attempt}: {type(exc).__name__}: {exc}"
                    print(f"[property-gt] failed {message}", flush=True)
                    shutil.rmtree(stage, ignore_errors=True)
                    if attempt < args.batch_retries:
                        for row in batch:
                            state["frames"][str(row["frame_id"])].update({"status": "pending", "last_error": message})
                        batches.appendleft(batch)
                    else:
                        for row in batch:
                            state["frames"][str(row["frame_id"])].update({"status": "failed", "terminal_error": message})
                            terminal_failures.append(str(row["frame_id"]))
                _persist_state(args.dataset, state)
    counts = Counter(str(entry.get("status")) for entry in state["frames"].values())
    print(f"[property-gt] finished status={dict(counts)}", flush=True)
    return 1 if terminal_failures or counts.get("complete", 0) != len(rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
