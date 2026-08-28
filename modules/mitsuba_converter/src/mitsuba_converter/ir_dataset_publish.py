"""Immutable, resumable publication of Principled IR datasets."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from .ir_dataset_contract import (
    ARTIFACT_SCHEMA,
    DATASET_SCHEMA,
    SUPPORTED_ARTIFACT_SCHEMAS,
    SUPPORTED_DATASET_SCHEMAS,
    CLASS_MODALITIES,
    DISTANCE_MODALITIES,
    HDR_MODALITIES,
    ID_MODALITIES,
    LINEAR_RGB_MODALITIES,
    MASK_MODALITIES,
    NORMAL_MODALITIES,
    SCALAR_MODALITIES,
    _read_json,
    _safe_artifact_path,
)

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
INVENTORY_NAME = "publish_inventory.jsonl"
MANIFEST_NAME = "publish_manifest.json"
TRANSIENT_NAMES = {".staging", ".viewer_cache", INVENTORY_NAME, MANIFEST_NAME}


class PublishCancelled(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise PublishCancelled("publish cancelled")


def _read_index(source: Path) -> list[dict[str, Any]]:
    rows = []
    with (source / "index.jsonl").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"index line {line_number} is not an object")
            rows.append(row)
    return rows


def _validate_image_bytes(data: bytes, modality: str, expected_shape: tuple[int, int]) -> None:
    import cv2

    value = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"cannot decode {modality}")
    if value.shape[:2] != expected_shape:
        raise ValueError(f"{modality} shape {value.shape[:2]} != {expected_shape}")
    if np.issubdtype(value.dtype, np.floating) and not np.isfinite(value).all():
        raise ValueError(f"{modality} contains non-finite values")
    if modality in HDR_MODALITIES and value.dtype != np.float32:
        raise ValueError(f"{modality} must be float32 EXR, got {value.dtype}")
    if modality in LINEAR_RGB_MODALITIES | SCALAR_MODALITIES | NORMAL_MODALITIES | DISTANCE_MODALITIES | ID_MODALITIES:
        if value.dtype != np.uint16:
            raise ValueError(f"{modality} must be uint16 PNG, got {value.dtype}")
    if modality in CLASS_MODALITIES:
        if value.dtype != np.uint8:
            raise ValueError(f"{modality} must be uint8 PNG, got {value.dtype}")
    if modality in MASK_MODALITIES or modality.endswith("_mask"):
        if value.dtype != np.uint8:
            raise ValueError(f"{modality} must be uint8 PNG, got {value.dtype}")
        unique = np.unique(value)
        if not set(int(item) for item in unique).issubset({0, 1, 255}):
            raise ValueError(f"{modality} is not binary")


def validate_publish_source(source: Path) -> dict[str, Any]:
    """Validate the immutable dataset-level contract before hashing files."""
    source = Path(source).resolve()
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"dataset directory not found or symlinked: {source}")
    config = _read_json(source / "dataset_config.json")
    contract = _read_json(source / "artifact_contract.json")
    queue_state = _read_json(source / "rolling_queue_state.json")
    qc = _read_json(source / "qc_summary.json")
    if config.get("schema") not in SUPPORTED_DATASET_SCHEMAS:
        raise ValueError(f"unsupported dataset schema: {config.get('schema')!r}")
    if contract.get("schema") not in SUPPORTED_ARTIFACT_SCHEMAS:
        raise ValueError(f"unsupported artifact schema: {contract.get('schema')!r}")
    if ((config.get("schema") == DATASET_SCHEMA) != (contract.get("schema") == ARTIFACT_SCHEMA)):
        raise ValueError("dataset/artifact contract major versions differ")
    if queue_state.get("schema") != "robomituba.ir_principled_rolling_queue.v1":
        raise ValueError(f"unsupported rolling queue schema: {queue_state.get('schema')!r}")
    if qc.get("schema") != "robomituba.ir_principled_qc_summary.v1":
        raise ValueError(f"unsupported QC schema: {qc.get('schema')!r}")
    fingerprint = str(config.get("dataset_fingerprint") or "")
    if not fingerprint or fingerprint != str(contract.get("dataset_fingerprint") or ""):
        raise ValueError("dataset/artifact fingerprint mismatch")
    if queue_state.get("dataset_fingerprint") != fingerprint:
        raise ValueError("rolling queue fingerprint mismatch")
    rows = _read_index(source)
    frame_ids: list[str] = []
    indexed: dict[str, tuple[str, tuple[int, int]]] = {}
    for row in rows:
        frame_id = str(row.get("frame_id") or "")
        if not frame_id or frame_id in frame_ids:
            raise ValueError(f"empty or duplicate frame_id: {frame_id!r}")
        if row.get("dataset_fingerprint") != fingerprint:
            raise ValueError(f"frame fingerprint mismatch: {frame_id}")
        frame_ids.append(frame_id)
        shape = (int(row.get("height") or config.get("height") or 0), int(row.get("width") or config.get("width") or 0))
        if min(shape) <= 0:
            raise ValueError(f"invalid frame dimensions: {frame_id} {shape}")
        paths = row.get("paths") or {}
        if not paths:
            raise ValueError(f"frame has no artifacts: {frame_id}")
        for modality, relative in paths.items():
            path = _safe_artifact_path(source, str(relative))
            rel = path.relative_to(source).as_posix()
            previous = indexed.get(rel)
            if previous is not None and previous[0] != modality:
                raise ValueError(f"artifact used by multiple modalities: {rel}")
            indexed[rel] = (str(modality), shape)
    completed = [str(item) for item in (queue_state.get("completed") or [])]
    if set(completed) != set(frame_ids) or len(completed) != len(frame_ids):
        raise ValueError("rolling queue completed set does not match index")
    if queue_state.get("pending"):
        raise ValueError("rolling queue still has pending frames")
    if queue_state.get("failed"):
        raise ValueError("rolling queue has failed frames")
    if int(queue_state.get("frame_count") or -1) != len(frame_ids):
        raise ValueError("rolling queue frame_count does not match index")
    if not bool(qc.get("fallback_threshold_passed")):
        raise ValueError("QC fallback threshold did not pass")
    if int(qc.get("frame_count") or -1) != len(frame_ids):
        raise ValueError("QC frame_count does not match index")
    overview_contract = contract.get("overview")
    if overview_contract is not None:
        if not isinstance(overview_contract, dict) or overview_contract.get("schema") != "robomituba.ir_scene_overview.v1":
            raise ValueError("invalid scene overview contract")
        overview_path = _safe_artifact_path(source, str(overview_contract.get("path") or ""))
        overview = _read_json(overview_path)
        if overview.get("schema") != "robomituba.ir_scene_overview.v1" or overview.get("dataset_fingerprint") != fingerprint:
            raise ValueError("scene overview schema or fingerprint mismatch")
        if overview.get("graph_available") and overview.get("graph_digest") != config.get("graph_sha256"):
            raise ValueError("scene overview graph binding mismatch")
        proxy = overview.get("proxy_mesh") or {}
        declared_proxy = overview_contract.get("proxy_mesh_path")
        if declared_proxy or proxy:
            proxy_path_text = str(proxy.get("path") or declared_proxy or "")
            if not proxy_path_text or (declared_proxy and proxy_path_text != declared_proxy):
                raise ValueError("scene overview proxy path mismatch")
            proxy_path = _safe_artifact_path(source, proxy_path_text)
            digest = str(proxy.get("sha256") or "")
            actual = _sha256_file(proxy_path)
            if not digest or digest != actual or overview_contract.get("proxy_mesh_sha256") != actual:
                raise ValueError("scene overview proxy digest mismatch")
            if int(proxy.get("triangles") or 0) < 1 or int(proxy.get("triangles") or 0) > 50_000:
                raise ValueError("scene overview proxy triangle contract is invalid")
            if proxy.get("coordinate_system") != "mitsuba_y_up":
                raise ValueError("scene overview proxy coordinate system is invalid")
            header = proxy_path.read_bytes()[:12]
            if len(header) != 12 or header[:4] != b"glTF" or struct.unpack("<I", header[4:8])[0] != 2:
                raise ValueError("scene overview proxy is not a GLB v2 file")
            bounds = proxy.get("bounds") or {}
            try:
                low = [float(value) for value in bounds["min"]]
                high = [float(value) for value in bounds["max"]]
            except (KeyError, TypeError, ValueError):
                raise ValueError("scene overview proxy bounds are invalid") from None
            if len(low) != 3 or len(high) != 3 or not np.isfinite(low + high).all() or any(a > b for a, b in zip(low, high)):
                raise ValueError("scene overview proxy bounds are invalid")
        traversability = overview.get("traversability") or {}
        declared_path = overview_contract.get("traversability_path")
        if declared_path or traversability:
            path_text = str(traversability.get("path") or declared_path or "")
            if not path_text or (declared_path and path_text != declared_path):
                raise ValueError("scene overview traversability path mismatch")
            grid_path = _safe_artifact_path(source, path_text)
            import cv2
            grid = cv2.imread(str(grid_path), cv2.IMREAD_UNCHANGED)
            shape = traversability.get("shape") or []
            if grid is None or len(shape) != 2 or tuple(grid.shape[:2]) != (int(shape[0]), int(shape[1])):
                raise ValueError("scene overview traversability shape mismatch")
            if float(traversability.get("resolution_m") or 0.0) <= 0.0:
                raise ValueError("scene overview traversability resolution is invalid")
    return {
        "source": source,
        "fingerprint": fingerprint,
        "config": config,
        "contract": contract,
        "rows": rows,
        "indexed": indexed,
    }


def _source_files(source: Path) -> list[Path]:
    files = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in TRANSIENT_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"symlinks are not publishable: {relative}")
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(source).as_posix())


Progress = Callable[[str, int, int, int, int], None]


def build_inventory(source_info: dict[str, Any], *, progress: Progress | None = None,
                    cancel: threading.Event | None = None) -> tuple[list[dict[str, Any]], str]:
    source: Path = source_info["source"]
    indexed: dict[str, tuple[str, tuple[int, int]]] = source_info["indexed"]
    files = _source_files(source)
    total_bytes = sum(path.stat().st_size for path in files)
    done_bytes = 0
    inventory: list[dict[str, Any]] = []
    for index, path in enumerate(files, 1):
        _check_cancel(cancel)
        data = path.read_bytes()
        relative = path.relative_to(source).as_posix()
        spec = indexed.get(relative)
        if spec is not None:
            try:
                _validate_image_bytes(data, spec[0], spec[1])
            except ValueError as exc:
                raise ValueError(f"{relative}: {exc}") from exc
        stat = path.stat()
        inventory.append({
            "path": relative,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "mtime_ns": stat.st_mtime_ns,
        })
        done_bytes += len(data)
        if progress:
            progress("scanning", index, len(files), done_bytes, total_bytes)
    digest_rows = [{key: row[key] for key in ("path", "size", "sha256")} for row in inventory]
    return inventory, _json_digest(digest_rows)


def _hash_file(path: Path, *, cancel: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            _check_cancel(cancel)
            chunk = stream.read(8 * 1024**2)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_inventory(path: Path, inventory: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in inventory:
            stream.write(json.dumps({key: row[key] for key in ("path", "size", "sha256")}, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _destination_fingerprint(path: Path) -> str | None:
    try:
        return str(_read_json(path / "dataset_config.json").get("dataset_fingerprint") or "") or None
    except Exception:
        return None


def publish_dataset(source: Path, destination_root: Path, *, name: str | None = None,
                    progress: Progress | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """Publish one complete dataset without ever exposing a partial final directory."""
    started = time.monotonic()
    source_info = validate_publish_source(source)
    source = source_info["source"]
    publish_name = name or source.name
    if not NAME_RE.fullmatch(publish_name):
        raise ValueError("publish name must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    destination_root = Path(destination_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    staging_root = destination_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    fingerprint = source_info["fingerprint"]
    final = destination_root / publish_name
    staging = staging_root / f"{publish_name}.{fingerprint}"
    inventory, inventory_digest = build_inventory(source_info, progress=progress, cancel=cancel)
    total_bytes = sum(int(row["size"]) for row in inventory)

    if final.exists():
        existing = _destination_fingerprint(final)
        if existing != fingerprint:
            raise FileExistsError(f"destination exists with a different fingerprint: {final}")
        target = final
        mode = "adopted_existing"
    else:
        staging.mkdir(parents=True, exist_ok=True)
        target = staging
        mode = "published"

    copied_bytes = 0
    for index, row in enumerate(inventory, 1):
        _check_cancel(cancel)
        src = source / row["path"]
        dst = target / row["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and dst.stat().st_size == row["size"] and _hash_file(dst, cancel=cancel) == row["sha256"]:
            copied_bytes += int(row["size"])
            if progress:
                progress("copying", index, len(inventory), copied_bytes, total_bytes)
            continue
        temporary = dst.with_name(dst.name + ".partial")
        digest = hashlib.sha256()
        with src.open("rb") as input_stream, temporary.open("wb") as output_stream:
            while True:
                _check_cancel(cancel)
                chunk = input_stream.read(8 * 1024**2)
                if not chunk:
                    break
                output_stream.write(chunk)
                digest.update(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if digest.hexdigest() != row["sha256"]:
            raise RuntimeError(f"source changed during copy: {row['path']}")
        shutil.copystat(src, temporary, follow_symlinks=False)
        os.replace(temporary, dst)
        copied_bytes += int(row["size"])
        if progress:
            progress("copying", index, len(inventory), copied_bytes, total_bytes)

    verified_bytes = 0
    for index, row in enumerate(inventory, 1):
        _check_cancel(cancel)
        dst = target / row["path"]
        if not dst.is_file() or dst.stat().st_size != row["size"] or _hash_file(dst, cancel=cancel) != row["sha256"]:
            raise RuntimeError(f"destination verification failed: {row['path']}")
        verified_bytes += int(row["size"])
        if progress:
            progress("verifying", index, len(inventory), verified_bytes, total_bytes)

    # Recheck source metadata after the long copy/verify window.
    for row in inventory:
        src = source / row["path"]
        stat = src.stat()
        if stat.st_size != row["size"] or stat.st_mtime_ns != row["mtime_ns"]:
            raise RuntimeError(f"source changed during publication: {row['path']}")

    _write_inventory(target / INVENTORY_NAME, inventory)
    manifest = {
        "schema": "robomituba.ir_principled_publish.v1",
        "published_at": _utc_now(),
        "source": str(source),
        "destination": str(final),
        "dataset_fingerprint": fingerprint,
        "inventory_sha256": inventory_digest,
        "file_count": len(inventory),
        "byte_count": total_bytes,
        "verification": "sha256_all_files",
    }
    manifest_tmp = target / f"{MANIFEST_NAME}.tmp"
    manifest_tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(manifest_tmp, target / MANIFEST_NAME)
    if target == staging:
        _check_cancel(cancel)
        if final.exists():
            raise FileExistsError(f"destination appeared during publish: {final}")
        os.replace(staging, final)
    if progress:
        progress("committing", len(inventory), len(inventory), total_bytes, total_bytes)
    return {**manifest, "status": "succeeded", "mode": mode, "elapsed_s": time.monotonic() - started}


@dataclass
class PublishJob:
    job_id: str
    source: str
    destination_root: str
    name: str
    status: str = "queued"
    stage: str = "queued"
    files_done: int = 0
    files_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    error: str | None = None
    result: dict[str, Any] | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    started_monotonic: float | None = field(default=None, repr=False)

    def payload(self) -> dict[str, Any]:
        elapsed = (time.monotonic() - self.started_monotonic) if self.started_monotonic else 0.0
        speed = self.bytes_done / elapsed if elapsed > 0 else 0.0
        eta = (self.bytes_total - self.bytes_done) / speed if speed > 0 and self.bytes_total > self.bytes_done else None
        return {
            "job_id": self.job_id, "source": self.source, "destination_root": self.destination_root,
            "name": self.name, "status": self.status, "stage": self.stage,
            "files_done": self.files_done, "files_total": self.files_total,
            "bytes_done": self.bytes_done, "bytes_total": self.bytes_total,
            "speed_bytes_s": speed, "eta_s": eta, "created_at": self.created_at,
            "updated_at": self.updated_at, "error": self.error, "result": self.result,
        }


class PublishManager:
    """One-worker publication queue to avoid saturating both NFS mounts."""

    def __init__(self):
        self._jobs: dict[str, PublishJob] = {}
        self._queue: queue.Queue[PublishJob] = queue.Queue()
        self._lock = threading.RLock()
        self._worker = threading.Thread(target=self._run, name="ir-dataset-publisher", daemon=True)
        self._worker.start()

    def submit(self, source: Path, destination_root: Path, name: str | None = None) -> dict[str, Any]:
        publish_name = name or Path(source).name
        if not NAME_RE.fullmatch(publish_name):
            raise ValueError("invalid publish name")
        job = PublishJob(uuid.uuid4().hex, str(Path(source).resolve()), str(Path(destination_root).resolve()), publish_name)
        with self._lock:
            self._jobs[job.job_id] = job
        self._queue.put(job)
        return job.payload()

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return job.payload()

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in {"queued", "running"}:
                job.cancel_event.set()
                if job.status == "queued":
                    job.status = "cancelled"
                    job.stage = "cancelled"
                    job.updated_at = _utc_now()
            return job.payload()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job.cancel_event.is_set():
                self._queue.task_done()
                continue
            with self._lock:
                job.status = "running"
                job.started_monotonic = time.monotonic()
                job.updated_at = _utc_now()

            def update(stage: str, files_done: int, files_total: int, bytes_done: int, bytes_total: int) -> None:
                with self._lock:
                    job.stage = stage
                    job.files_done = files_done
                    job.files_total = files_total
                    job.bytes_done = bytes_done
                    job.bytes_total = bytes_total
                    job.updated_at = _utc_now()

            try:
                result = publish_dataset(Path(job.source), Path(job.destination_root), name=job.name,
                                         progress=update, cancel=job.cancel_event)
                with self._lock:
                    job.result = result
                    job.status = "succeeded"
                    job.stage = "succeeded"
            except PublishCancelled as exc:
                with self._lock:
                    job.status = "cancelled"
                    job.stage = "cancelled"
                    job.error = str(exc)
            except Exception as exc:
                with self._lock:
                    job.status = "failed"
                    job.stage = "failed"
                    job.error = str(exc)
            finally:
                with self._lock:
                    job.updated_at = _utc_now()
                self._queue.task_done()
