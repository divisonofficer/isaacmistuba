"""Bounded, read-only Stokes preview materialization for the control backend.

The gallery lives in the 8765 control-plane process, not the 8766 GPU render
queue.  ``core_preview_v1`` deliberately persists only ``stokes_data.npz``
and one RGB preview; this service turns a requested diagnostic into PNG bytes
without ever writing into the immutable observation bundle.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
from typing import Final

from .multimodal import materialize_stokes_visualizations


_OUTPUT_KEYS: Final[dict[str, str]] = {
    "polar_rgb_preview": "rgb_preview",
    "stokes_s0_rgb": "s0_rgb_preview",
    "stokes_s1_rgb": "s1_rgb_preview",
    "stokes_s2_rgb": "s2_rgb_preview",
    "stokes_s3_rgb": "s3_rgb_preview",
}


class GalleryPreviewService:
    """Generate and byte-cache immutable Stokes diagnostics with bounded CPU work.

    A browser can issue several lazy image requests at once.  Limiting this to
    a small executor protects the control plane and, importantly, means a
    gallery page cannot contend with the 8766 renderer's GPU worker manager.
    The source bundle is immutable, therefore its resolved path plus stat
    fingerprint is a sufficient cache identity without hashing a multi-MB NPZ
    on every image request.
    """

    def __init__(self, *, max_cache_bytes: int | None = None, max_workers: int | None = None) -> None:
        cache_mb = float(os.environ.get("ROBOMITUBA_STOKES_PREVIEW_CACHE_MB", "128") or "128")
        worker_count = int(os.environ.get("ROBOMITUBA_GALLERY_PREVIEW_WORKERS", "2") or "2")
        self._max_cache_bytes = max(
            8 * 1024 * 1024,
            int(max_cache_bytes if max_cache_bytes is not None else cache_mb * 1024 * 1024),
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers if max_workers is not None else worker_count)),
            thread_name_prefix="robomituba-gallery-preview",
        )
        self._cache: OrderedDict[tuple[str, int, int, str], bytes] = OrderedDict()
        self._cache_bytes = 0
        self._inflight: dict[tuple[str, int, int, str], Future[bytes | None]] = {}
        self._lock = threading.Lock()

    @property
    def cache_bytes(self) -> int:
        with self._lock:
            return self._cache_bytes

    def png_bytes(self, *, npz_path: Path, modality: str) -> bytes | None:
        """Return one derived PNG, coalescing duplicate concurrent requests."""
        try:
            stat = npz_path.stat()
        except OSError:
            return None
        key = (str(npz_path.resolve()), int(stat.st_mtime_ns), int(stat.st_size), str(modality))
        with self._lock:
            cached = self._cache.pop(key, None)
            if cached is not None:
                self._cache[key] = cached
                return cached
            future = self._inflight.get(key)
            if future is None:
                future = self._executor.submit(self._materialize_one, npz_path, modality)
                self._inflight[key] = future
        try:
            rendered = future.result(timeout=60.0)
        except Exception:
            rendered = None
        with self._lock:
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)
            if rendered is not None:
                # Several HTTP threads can await the same single-flight
                # future.  Only the first completion owns the byte budget;
                # later waiters merely refresh the LRU position.
                existing = self._cache.pop(key, None)
                self._cache[key] = existing if existing is not None else rendered
                if existing is None:
                    self._cache_bytes += len(rendered)
                while self._cache and self._cache_bytes > self._max_cache_bytes:
                    _old_key, old = self._cache.popitem(last=False)
                    self._cache_bytes -= len(old)
        return rendered

    @staticmethod
    def _materialize_one(npz_path: Path, modality: str) -> bytes | None:
        output_key = _OUTPUT_KEYS.get(modality, modality)
        try:
            with tempfile.TemporaryDirectory(prefix="robomituba-gallery-preview-") as temporary_dir:
                outputs = materialize_stokes_visualizations(npz_path, temporary_dir, {modality})
                output = Path(outputs[output_key])
                return output.read_bytes() if output.is_file() else None
        except (OSError, KeyError, ValueError, TypeError):
            return None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
