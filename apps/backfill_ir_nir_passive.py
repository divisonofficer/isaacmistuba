#!/usr/bin/env python3
"""Incrementally add passive NIR and active-minus-passive to a completed dataset.

This is an explicit migration tool rather than a normal render queue stage:
RGB/GT artifacts remain untouched, frames are processed in index order, and a
durable state file makes a stopped invocation resume one frame at a time.  It
uses the same persistent Blender worker as the production queue, with a
flash-off NIR-only task for each existing frame.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.render_ir_principled_dataset_queue import (  # noqa: E402
    BlenderWorker,
    _atomic_json,
    _derive_nir_difference,
    _refresh_index,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path,
                        help="completed work or published dataset directory")
    parser.add_argument("--next", action="store_true",
                        help="select the first completed work dataset missing passive sidecars")
    parser.add_argument("--dataset-root", type=Path, default=Path("/bean/ir_dataset_work"))
    parser.add_argument("--prepared-scene-dir", type=Path,
                        help="Stage 2 directory containing derived_ir_principled_v1.blend")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--device", choices=("OPTIX", "CUDA"), default="OPTIX")
    parser.add_argument("--limit", type=int,
                        help="process at most N pending frames; useful for a smoke migration")
    parser.add_argument("--force", action="store_true", help="re-render passive even when sidecars exist")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _discover_next(root: Path) -> tuple[Path, Path]:
    """Resolve one dataset and its prepared blend from controller snapshots."""
    root = root.resolve()
    jobs_root = root / ".control" / "jobs"
    prepared_by_dataset: dict[str, Path] = {}
    active_backfill_datasets: set[str] = set()
    for snapshot in jobs_root.glob("*.json"):
        try:
            job = _read(snapshot)
            request = job.get("request") or {}
            if (
                request.get("source_mode") == "nir_passive_backfill"
                and job.get("status") in {"queued", "running"}
            ):
                target = request.get("backfill_dataset") or (request.get("paths") or {}).get("dataset")
                if target:
                    active_backfill_datasets.add(str(Path(str(target)).resolve()))
            paths = request.get("paths") or {}
            dataset_raw = str(paths.get("dataset") or "")
            prepared_raw = str(paths.get("prepared") or "")
            if not dataset_raw or not prepared_raw:
                continue
            dataset = str(Path(dataset_raw).resolve())
            prepared = Path(prepared_raw).resolve()
            if prepared.joinpath("derived_ir_principled_v1.blend").is_file():
                prepared_by_dataset[dataset] = prepared
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    candidates = []
    for dataset in sorted(root.iterdir()):
        if not dataset.is_dir() or dataset.name.startswith("."):
            continue
        index = dataset / "index.jsonl"
        if not index.is_file():
            continue
        # Only migrate an immutable, completed capture.  A dataset can have a
        # prepared Stage 2 and a partially populated index while its rolling
        # render is still running; selecting it here would make the passive
        # sidecars race the primary renderer and could leave a misleadingly
        # complete passive contract.  The queue state is the authoritative
        # completion marker for work datasets.
        queue_state_path = dataset / "rolling_queue_state.json"
        try:
            queue_state = _read(queue_state_path)
            completed = queue_state.get("completed") or []
            pending_frames = queue_state.get("pending") or []
            failed_frames = queue_state.get("failed") or {}
            frame_count = int(queue_state.get("frame_count") or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if (
            not queue_state_path.is_file()
            or not frame_count
            or len(completed) != frame_count
            or pending_frames
            or failed_frames
        ):
            continue
        pending = False
        for line in index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            paths = row.get("paths") or {}
            if not (dataset / str(paths.get("nir_passive") or "")).is_file() or not (dataset / str(paths.get("nir_active_minus_passive") or "")).is_file():
                pending = True
                break
        prepared = prepared_by_dataset.get(str(dataset.resolve()))
        if pending and prepared is not None:
            if str(dataset.resolve()) in active_backfill_datasets:
                continue
            # ``--next --dry-run`` is also used while another dataset is
            # being migrated.  A lock file by itself is not enough to reject
            # a candidate because an interrupted process can leave it
            # behind; probe the advisory lock non-destructively and skip only
            # a dataset currently owned by another backfill process.
            lock_path = dataset / ".nir_passive_backfill" / "lock"
            if lock_path.exists():
                try:
                    with lock_path.open("a+", encoding="utf-8") as lock_handle:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                except BlockingIOError:
                    continue
            candidates.append((dataset, prepared))
    if not candidates:
        raise FileNotFoundError("no completed work dataset with a resolvable prepared Stage 2 is missing passive NIR")
    return candidates[0]


def _task(row: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    camera = row.get("camera") or {}
    if not camera.get("camera_to_world_blender"):
        raise ValueError(f"frame {row.get('frame_id')} lacks camera_to_world_blender")
    return {
        "frame_id": str(row["frame_id"]),
        "viewpoint_id": str(row["viewpoint_id"]),
        "heading_deg": float(row.get("heading_deg", 0.0)),
        "camera_to_world_blender": camera["camera_to_world_blender"],
        "camera": camera,
        "dataset_fingerprint": fingerprint,
        "pbr_gt_contract_digest": row.get("pbr_gt_contract_digest"),
        "external_lighting_available": bool(row.get("external_lighting_available", False)),
        "width": int(row.get("width") or 0),
        "height": int(row.get("height") or 0),
        "fov_deg": float(row.get("fov_deg") or 60.0),
        "lighting": dict(row.get("lighting") or {}),
        "capture_kind": row.get("capture_kind", "single"),
        "pair_id": row.get("pair_id"),
        "pair_member_index": row.get("pair_member_index"),
        "render_mode": "nir_passive_only",
        "nir_passive": True,
        "preserve_existing_row": True,
    }


def _write_contract(dataset: Path, config: dict[str, Any]) -> None:
    config["nir_passive_enabled"] = True
    config["nir_passive_contract"] = {
        "version": "nir-passive-v1",
        "active_minus_passive": "linear_exr_subtraction",
        "flash_state": "camera_relative_flash_disabled",
        "backfill_started_at": config.get("nir_passive_contract", {}).get("backfill_started_at", _now()),
    }
    _atomic_json(dataset / "dataset_config.json", config)
    contract_path = dataset / "artifact_contract.json"
    if contract_path.is_file():
        contract = _read(contract_path)
        contract["nir_passive"] = {
            "requested": True,
            "ready": True,
            "contract_version": "nir-passive-v1",
        }
        contract.setdefault("exposure_ev", {}).update({
            "nir_passive": 0.0, "nir_active_minus_passive": 0.0,
        })
        observations = contract.setdefault("observations", {})
        observations["nir_passive"] = {
            "path": "nir_passive/{frame_id}.exr",
            "encoding": "synthetic_nir_linear_float32_rgb_replicated",
            "flash": "disabled",
            "formula": config.get("nir_formula", "primary"),
        }
        observations["nir_active_minus_passive"] = {
            "path": "nir_active_minus_passive/{frame_id}.exr",
            "encoding": "scene_linear_float32_rgb_difference",
            "definition": "nir_active - nir_passive",
        }
        contract["nir_passive_backfill"] = {"version": "nir-passive-v1", "updated_at": _now()}
        _atomic_json(contract_path, contract)


def main() -> int:
    args = _args()
    if bool(args.dataset) == bool(args.next):
        raise ValueError("choose exactly one of --dataset or --next")
    if args.next:
        dataset, prepared = _discover_next(args.dataset_root)
    else:
        if args.prepared_scene_dir is None:
            raise ValueError("--prepared-scene-dir is required with --dataset")
        dataset = args.dataset.resolve()
        prepared = args.prepared_scene_dir.resolve()
    if not dataset.is_dir():
        raise FileNotFoundError(dataset)
    if dataset.name.startswith(".") or ".staging" in dataset.parts:
        raise ValueError("staging/cache directories cannot be backfilled")
    config_path = dataset / "dataset_config.json"
    index_path = dataset / "index.jsonl"
    blend = prepared / "derived_ir_principled_v1.blend"
    if not config_path.is_file() or not index_path.is_file() or not blend.is_file():
        raise FileNotFoundError("dataset, index.jsonl, dataset_config.json, or prepared blend is missing")
    config = _read(config_path)
    if config.get("schema") != "robomituba.ir_principled_dataset.v2":
        raise ValueError("only Principled dataset v2 can be backfilled")
    fingerprint = str(config.get("dataset_fingerprint") or "")
    if not fingerprint:
        raise ValueError("dataset config lacks dataset_fingerprint")
    rows: list[dict[str, Any]] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("index row is not an object")
            rows.append(row)
    pending = []
    for row in rows:
        paths = row.get("paths") or {}
        passive = dataset / str(paths.get("nir_passive") or "")
        difference = dataset / str(paths.get("nir_active_minus_passive") or "")
        if not args.force and passive.is_file() and difference.is_file():
            continue
        pending.append(row)
    total_pending = len(pending)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        pending = pending[:args.limit]

    # A dry run is an inspection operation.  Do not create the backfill
    # directory, lock, or state snapshot: leaving ``status=dry_run`` in the
    # dataset makes the viewer look as if a migration had started and can
    # interfere with the controller's recovery audit.
    if args.dry_run:
        print(json.dumps({"dataset": str(dataset), "pending": len(pending),
                          "frames": [row["frame_id"] for row in pending]},
                         ensure_ascii=False, indent=2))
        return 0

    state_dir = dataset / ".nir_passive_backfill"
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another passive NIR backfill already owns this dataset") from exc
        # A bounded run is an intentional smoke/incremental checkpoint.  It
        # must not advertise the dataset-wide passive contract until every
        # indexed frame has a passive and difference sidecar.
        partial_run = args.limit is not None and args.limit < total_pending
        state = {
            "schema": "robomituba.ir_nir_passive_backfill.v1",
            "dataset": str(dataset), "dataset_fingerprint": fingerprint,
            "prepared_blend": str(blend),
            "prepared_blend_sha256": _sha256(blend) if not args.dry_run else None,
            "started_at": _now(), "updated_at": _now(),
            "requested": len(pending), "completed": [], "failed": {},
            "status": "running",
            "partial_run": bool(partial_run),
        }
        _atomic_json(state_dir / "state.json", state)

        first = rows[0] if rows else None
        if first is None:
            raise ValueError("dataset index is empty")
        worker_args = argparse.Namespace(
            out=dataset, width=int(first.get("width") or config.get("width") or 684),
            height=int(first.get("height") or config.get("height") or 512),
            fov=float(first.get("fov_deg") or config.get("fov") or 60.0),
            rgb_spp=1, nir_spp=max(1, int(config.get("nir_spp") or 64)),
            max_bounces=max(1, int(config.get("max_bounces") or 8)),
            render_seed=int(config.get("render_seed") or 20260812), device=args.device,
            nir_formula=str(config.get("nir_formula") or "primary"),
            flash_energy_scale=float(config.get("flash_energy_scale") or 1.0),
            ambient_fill_energy_scale=float(config.get("ambient_fill_energy_scale") or 1.0),
            qc_components=False, nir_passive=True, verbose_blender=False,
            # Passive-only backfill preserves every existing RGB/GT artifact.
            # Older prepared blends legitimately predate MetallicContractV2's
            # three auxiliary label AOVs, which are irrelevant to this render.
            allow_legacy_passive_backfill_aovs=True,
        )
        worker = BlenderWorker(args.gpu_index, worker_args, blend, fingerprint)
        worker.start()
        try:
            for row in pending:
                frame_id = str(row["frame_id"])
                try:
                    event = worker.render(_task(row, fingerprint))
                    updated = _derive_nir_difference(dataset, event["row"])
                    state["completed"].append(frame_id)
                    state["updated_at"] = _now()
                    _refresh_index(dataset, fingerprint=fingerprint)
                    _atomic_json(state_dir / "state.json", state)
                    print(f"[nir-passive-backfill] {len(state['completed'])}/{len(pending)} {frame_id}", flush=True)
                except Exception as exc:
                    state["failed"][frame_id] = f"{type(exc).__name__}: {exc}"
                    state["updated_at"] = _now()
                    _atomic_json(state_dir / "state.json", state)
                    raise
        finally:
            worker.stop()
        if partial_run:
            state["status"] = "partial"
            state["remaining"] = max(0, total_pending - len(state["completed"]))
        else:
            _write_contract(dataset, config)
            state["status"] = "succeeded"
            state["remaining"] = 0
        state["finished_at"] = _now()
        state["updated_at"] = state["finished_at"]
        _atomic_json(state_dir / "state.json", state)
        _atomic_json(dataset / "nir_passive_backfill.json", state)
        _refresh_index(dataset, fingerprint=fingerprint)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
