"""Render worker subprocess (Phase R, 2026-04-30).

Spawned by ``WorkerManager`` from ``render_daemon``. Reads JSON-RPC job
requests from stdin (one JSON object per line), executes them on the GPU,
and writes JSON-RPC events to stdout (one JSON object per line).

The worker owns the Mitsuba/drjit imports and the GPU CUDA context. The
daemon process never imports mitsuba — that's the whole point: GPU work
holding the Python GIL no longer blocks daemon HTTP handlers.

Run as::

    python -m mitsuba_converter.preview_worker --gpu-index 0

``CUDA_VISIBLE_DEVICES`` is expected to be set by the manager before
spawn so each worker is pinned to a single GPU.

Stdout protocol (one JSON object per line, ``\\n`` separated):

  request (daemon → worker)::

      {"job_id": "...", "kind": "<kind>", "spec": {...}}

  events (worker → daemon)::

      {"job_id": "...", "type": "started", "ts": <epoch>}
      {"job_id": "...", "type": "progress", "stage": "...", "current": N, "total": M}
      {"job_id": "...", "type": "log", "level": "info", "line": "..."}
      {"job_id": "...", "type": "completed", "out_path": "...", "elapsed_ms": N}
      {"job_id": "...", "type": "failed", "reason": "...", "message": "..."}
      {"type": "heartbeat", "ts": <epoch>}

``preview_bench:`` lines from ``sphere_preview._render_to_png`` are
written to ``stderr`` (inherited from the daemon's stderr fd) so they
keep showing up in the daemon log unchanged. Stderr is *not* the
JSON-RPC channel.

Job kinds:

* ``curated_preview`` — render a curated material onto a preview object
* ``measured_preview`` — render a measured (.pbsdf / .pbrdf) preview
* ``channel_split_preview`` — render a 4-wavelength composite (hpBRDF)
* ``render_job`` — execute a full observation-bundle render

Runtime policy:
  * CUDA variants are preferred, but Docker hosts with an older NVIDIA
    driver can set ``ROBOMITUBA_DISABLE_CUDA=1`` or rely on late OptiX
    failure fallback to use LLVM/scalar variants instead.
  * No thread parallelism inside the worker. The reader loop is
    single-threaded; jobs are processed strictly in order.
  * ``flush_malloc_cache`` runs after every render (anti-leak).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any


_HEARTBEAT_INTERVAL_S = 5.0
_stdout_lock = threading.Lock()
ENV_FULL_RENDER_DISABLE_CUDA = "ROBOMITUBA_FULL_RENDER_DISABLE_CUDA"


def _emit(event: dict[str, Any]) -> None:
    """Write one JSON line to stdout. Thread-safe; never raises."""
    try:
        line = json.dumps(event, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        line = json.dumps({
            "type": "error",
            "reason": "json_encode_failed",
            "message": f"{type(exc).__name__}: {exc}",
        })
    with _stdout_lock:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def _emit_failed(job_id: str, reason: str, message: str, *, elapsed_ms: int | None = None) -> None:
    payload: dict[str, Any] = {"job_id": job_id, "type": "failed", "reason": reason, "message": message}
    if elapsed_ms is not None:
        payload["elapsed_ms"] = int(elapsed_ms)
    _emit(payload)


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _heartbeat_loop(stop_event: threading.Event) -> None:
    """Emit a ``heartbeat`` event every ``_HEARTBEAT_INTERVAL_S`` seconds."""
    while not stop_event.wait(_HEARTBEAT_INTERVAL_S):
        _emit({"type": "heartbeat", "ts": time.time()})


# ── Verbose logging toggle (mitsuba + drjit) ──────────────────────────


_LOG_LEVEL_NAMES = ("off", "error", "warn", "info", "debug", "trace")


def _set_render_log_level(level_name: str) -> str:
    """Set mitsuba + drjit log level (writes to stderr).

    Env: ``ROBOMITUBA_RENDER_LOG_LEVEL`` ∈ {off|error|warn|info|debug|trace}
    Default ``info`` — shows OptiX kernel-compile begin/end, scene load
    progress, allocator stats. ``debug`` adds per-kernel JIT trace (very
    noisy on hot paths). ``trace`` is impractical for production but
    useful for one-shot dives.

    Returns the level that was actually applied (after normalization).
    """
    name = (level_name or "info").strip().lower()
    if name not in _LOG_LEVEL_NAMES:
        name = "info"
    if name == "off":
        return name
    try:
        import mitsuba as mi  # type: ignore
        mi_levels = {
            "error": getattr(mi.LogLevel, "Error", None),
            "warn": getattr(mi.LogLevel, "Warn", None),
            "info": getattr(mi.LogLevel, "Info", None),
            "debug": getattr(mi.LogLevel, "Debug", None),
            "trace": getattr(mi.LogLevel, "Trace", None),
        }
        lvl = mi_levels.get(name)
        if lvl is not None:
            mi.set_log_level(lvl)
    except Exception as exc:
        # Mitsuba 3.4.x raises if imported before mi.set_variant(). The
        # worker sets variants lazily per job, so suppress that expected
        # startup warning and let Dr.Jit log-level capping below do the
        # important stdout-noise control.
        if "must specify the desired variant" not in str(exc):
            print(f"[worker] mitsuba log-level setup failed: {exc}", file=sys.stderr, flush=True)
    try:
        import drjit as dr  # type: ignore
        # drjit prints its log to stdout, which IS our JSONL channel — info
        # and above floods the reader with "malformed JSON" warnings (no
        # functional impact, just noise). Cap drjit at warn even when
        # mitsuba is verbose; the ABI-detection line ("loaded OptiX via
        # 7.4 ABI") and any real error still come through.
        dr_levels = {"error": 1, "warn": 2, "info": 2, "debug": 4, "trace": 5}
        dr_int = dr_levels.get(name, 2)
        # drjit's set_log_level signature has shifted across versions — try
        # both the int form and (if present) the LogLevel enum form.
        set_fn = getattr(dr, "set_log_level", None)
        if callable(set_fn):
            try:
                set_fn(dr_int)
            except (TypeError, ValueError):
                ll_enum = getattr(dr, "LogLevel", None)
                if ll_enum is not None:
                    enum_name = {1: "Error", 2: "Warn", 3: "Info", 4: "Debug", 5: "Trace"}.get(dr_int)
                    if enum_name and hasattr(ll_enum, enum_name):
                        try:
                            set_fn(getattr(ll_enum, enum_name))
                        except Exception:
                            pass
    except Exception as exc:
        print(f"[worker] drjit log-level setup failed: {exc}", file=sys.stderr, flush=True)
    return name


# ── Dispatch stage heartbeat ──────────────────────────────────────────


_DISPATCH_HEARTBEAT_INTERVAL_S = float(
    os.environ.get("ROBOMITUBA_RENDER_HEARTBEAT_INTERVAL_S", "5.0")
)


class _DispatchHeartbeat:
    """Per-job watchdog thread that emits ``progress`` events with the
    elapsed wall-clock so the daemon UI can show "still running… Xs" even
    when the underlying mitsuba/OptiX call is a 5-minute black box with
    no native progress callback.

    Use as a context manager around the full dispatch body. The dispatch
    function calls ``hb.update(stage, message)`` whenever it transitions
    so the next heartbeat tick carries the most-recent label::

        with _DispatchHeartbeat(job_id) as hb:
            hb.update("scene_build", "씬 dict 빌드 중")
            scene_dict = _build_scene_dict(...)
            hb.update("rendering", "OptiX compile + path tracing")
            _render_to_png(...)
    """

    def __init__(self, job_id: str, *, interval_s: float | None = None) -> None:
        self.job_id = job_id
        self.interval_s = float(interval_s if interval_s is not None else _DISPATCH_HEARTBEAT_INTERVAL_S)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0
        self._stage = "dispatching"
        self._message = ""
        self._lock = threading.Lock()

    def update(self, stage: str, message: str = "") -> None:
        with self._lock:
            self._stage = str(stage)
            self._message = str(message)

    def __enter__(self) -> "_DispatchHeartbeat":
        self._t0 = time.perf_counter()
        self._thread = threading.Thread(
            target=self._loop, name=f"render-worker-stage-hb-{self.job_id}", daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        # First tick is `interval_s` after entry; very short jobs never emit
        # a stage heartbeat (good — would just spam).
        while not self._stop.wait(self.interval_s):
            elapsed = time.perf_counter() - self._t0
            with self._lock:
                stage = self._stage
                base = self._message or stage
            _emit({
                "job_id": self.job_id,
                "type": "progress",
                "stage": stage,
                "message": f"{base} · 경과 {elapsed:.0f}s",
                "elapsed_s": round(elapsed, 1),
            })


# ── Job dispatch ──────────────────────────────────────────────────────


def _dispatch_curated(job_id: str, spec: dict[str, Any]) -> None:
    from .curated_library import get_curated_material
    from .sphere_preview import (
        _build_scene_dict,
        _ensure_mitsuba_variant,
        _mitsuba_render_lock,
        _pick_variant_for,
        _render_to_png,
        _supersample_default,
        resolve_preview_object,
    )

    material_id = str(spec["material_id"])
    object_id = resolve_preview_object(spec.get("object_id") or "sphere")
    out_path = Path(str(spec["out_path"]))
    spp = int(spec["spp"])
    target_size = int(spec.get("target_size", 192))
    bench_label = str(spec.get("bench_label") or f"curated/{material_id}/{object_id}")

    mat = get_curated_material(material_id)
    if mat is None:
        _emit_failed(job_id, "unknown_material", f"curated material not found: {material_id}")
        return

    variant = _pick_variant_for("rgb")
    if variant is None:
        _emit_failed(
            job_id, "plugin_unavailable",
            "no GPU RGB variant available — Mitsuba CUDA build missing or unloadable",
        )
        return

    ss = _supersample_default()
    render_size = target_size * ss

    def _on_progress(current: int, total: int) -> None:
        _emit({
            "job_id": job_id, "type": "progress",
            "stage": "rendering",
            "current": int(current), "total": int(total),
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    with _DispatchHeartbeat(job_id) as hb, _mitsuba_render_lock:
        hb.update("variant", f"Mitsuba 변종 진입 ({variant})")
        _ensure_mitsuba_variant(variant)
        hb.update(
            "scene_build",
            f"씬 dict 빌드 중 (spp={spp}, render={render_size}px, object={object_id})",
        )
        _emit({
            "job_id": job_id, "type": "progress",
            "stage": "scene_build", "current": 0, "total": 1,
            "message": f"씬 dict 빌드 중 (spp={spp}, render={render_size}px, object={object_id})",
        })
        scene_dict = _build_scene_dict(
            mat.bsdf_spec, size=render_size, spp=spp, object_id=object_id,
        )
        hb.update(
            "rendering",
            f"Mitsuba 렌더 중 ({material_id}/{object_id}) · spp={spp} · OptiX compile+trace",
        )
        _emit({
            "job_id": job_id, "type": "progress",
            "stage": "rendering", "current": 0, "total": 0,
            "message": f"Mitsuba 렌더 중 ({material_id}/{object_id}) · spp={spp}",
        })
        _render_to_png(
            scene_dict, out_path, variant=variant, spp=spp,
            progress_cb=_on_progress,
            supersample=ss, target_size=target_size,
            bench_label=bench_label,
        )
    elapsed_ms = int((time.perf_counter() - t_start) * 1000.0)
    _emit({
        "job_id": job_id, "type": "completed",
        "out_path": str(out_path), "elapsed_ms": elapsed_ms,
    })


def _dispatch_measured(job_id: str, spec: dict[str, Any]) -> None:
    from .sphere_preview import (
        _mitsuba_render_lock,
        get_channel_split_preview,
        get_measured_preview,
        resolve_preview_object,
        RGBNIR_DEFAULT,
    )

    dataset_id = str(spec["dataset_id"])
    material_id = str(spec["material_id"])
    measured_file_path = spec.get("measured_file_path") or None
    object_id = resolve_preview_object(spec.get("object_id") or "sphere")
    repo_root = Path(str(spec["repo_root"]))
    cache_dir = Path(str(spec["cache_dir"]))
    spp = int(spec["spp"])
    use_channel_split = bool(spec.get("use_channel_split"))
    channels_dir_str = spec.get("channels_dir")

    if not use_channel_split and not measured_file_path:
        _emit_failed(job_id, "missing_path", "measured_file_path missing")
        return

    t_start = time.perf_counter()
    with _DispatchHeartbeat(job_id) as hb:
        if use_channel_split:
            if not channels_dir_str:
                _emit_failed(job_id, "missing_path", "channels_dir missing for channel-split render")
                return
            channels_dir = Path(str(channels_dir_str))
            n_channels = len(RGBNIR_DEFAULT)
            hb.update(
                "rendering",
                f"채널-split 렌더 ({material_id}) 0/{n_channels} RGB+NIR · spp={spp}",
            )
            _emit({
                "job_id": job_id, "type": "progress",
                "stage": "rendering", "current": 0, "total": n_channels,
                "message": f"Mitsuba 채널-split 렌더 중 ({material_id}) 0/{n_channels} RGB+NIR · spp={spp}",
            })

            def _on_channel(done: int, total: int) -> None:
                hb.update(
                    "rendering",
                    f"채널-split 렌더 ({material_id}) {done}/{total} RGB+NIR · spp={spp}",
                )
                _emit({
                    "job_id": job_id, "type": "progress",
                    "stage": "rendering",
                    "current": int(done), "total": int(total),
                    "message": f"Mitsuba 채널-split 렌더 중 ({material_id}) {done}/{total} RGB+NIR · spp={spp}",
                })

            result = get_channel_split_preview(
                material_id, channels_dir, cache_dir,
                mode="rgbnir", spp=spp,
                progress_cb=_on_channel,
                object_id=object_id,
            )
        else:
            with _mitsuba_render_lock:
                hb.update(
                    "rendering",
                    f"measured 렌더 ({material_id}/{object_id}) · spp={spp} · OptiX compile+trace",
                )
                _emit({
                    "job_id": job_id, "type": "progress",
                    "stage": "rendering", "current": 0, "total": 0,
                    "message": f"Mitsuba 렌더 중 ({material_id}/{object_id}) · spp={spp}",
                })
                result = get_measured_preview(
                    dataset_id, material_id, measured_file_path, repo_root, cache_dir,
                    spp=spp, object_id=object_id,
                )

    elapsed_ms = int((time.perf_counter() - t_start) * 1000.0)
    if result.path is None:
        # Map sphere_preview's status enum onto the JSON-RPC failed reason.
        status = getattr(result, "status", "unknown")
        msg_map = {
            "plugin_unavailable": (
                "GPU(CUDA) 변종이 빌드되지 않았거나, 이 재질이 패치된 "
                "Mitsuba 빌드를 요구합니다 (hpBRDF 등)"
            ),
            "mitsuba_unavailable": "Mitsuba 임포트 실패",
            "load_error": "파일 파싱 실패 (포맷 불일치)",
            "optix_unavailable": (
                "OptiX 초기화 실패 — 호스트 NVIDIA 드라이버가 OptiX 8 요구사항(R535+)보다 낮습니다. "
                "ROBOMITUBA_DISABLE_CUDA=1 로 CPU variant를 사용하세요."
            ),
            "gpu_oom": (
                "GPU/host-pinned 메모리 부족 — hpBRDF는 파일당 13 GB라 "
                "다른 큰 작업 종료 후 재시도하세요"
            ),
            "not_downloaded": "원본 파일 없음 — 먼저 다운로드 필요",
            "placeholder": "원본 파일 없음 — placeholder 사용",
        }
        message = msg_map.get(status, f"render unavailable: {status}")
        _emit_failed(job_id, status, message, elapsed_ms=elapsed_ms)
        return

    _emit({
        "job_id": job_id, "type": "completed",
        "out_path": str(result.path), "elapsed_ms": elapsed_ms,
    })


def _dispatch_render_job(job_id: str, spec: dict[str, Any]) -> None:
    """Execute a full observation-bundle render via observation_bridge."""
    from .observation_bridge import render_timestep_bundle_split_lighting
    from robomituba_bridge import render_request_from_payload

    request_payload = spec.get("request_payload")
    if not isinstance(request_payload, dict):
        _emit_failed(job_id, "bad_request", "render_job spec.request_payload missing or not a dict")
        return

    repo_root_str = spec.get("repo_root")
    if not repo_root_str:
        _emit_failed(job_id, "bad_request", "render_job spec.repo_root missing")
        return
    repo_root = Path(str(repo_root_str))
    variant = str(spec.get("variant") or "")
    if not variant:
        _emit_failed(job_id, "bad_request", "render_job spec.variant missing")
        return
    disable_cuda_for_full_render = bool(spec.get("disable_cuda")) or _env_flag(ENV_FULL_RENDER_DISABLE_CUDA)

    try:
        render_request = render_request_from_payload(request_payload)
    except Exception as exc:
        _emit_failed(
            job_id, "bad_request",
            f"failed to deserialize RenderRequest: {type(exc).__name__}: {exc}",
        )
        return

    t_start = time.perf_counter()
    with _DispatchHeartbeat(job_id) as hb:
        hb.update(
            "running",
            f"full /render variant={variant}"
            + (" cuda=disabled" if disable_cuda_for_full_render else ""),
        )

        def _progress(stage: str, payload: Any = None) -> None:
            event: dict[str, Any] = {
                "job_id": job_id, "type": "progress",
                "stage": str(stage),
            }
            # Update the heartbeat label so the next tick reflects the
            # current sub-stage (e.g. "rgb 1/2 spp=4096") instead of the
            # generic "running" placeholder.
            label = str(stage)
            if isinstance(payload, dict):
                event["payload"] = payload
                if "pass_index" in payload and "total_passes" in payload:
                    event["current"] = int(payload.get("pass_index") or 0)
                    event["total"] = int(payload.get("total_passes") or 0)
                bits = []
                if payload.get("pass"):
                    bits.append(str(payload["pass"]))
                if payload.get("pass_index") and payload.get("total_passes"):
                    bits.append(f"{payload['pass_index']}/{payload['total_passes']}")
                if payload.get("spp"):
                    bits.append(f"spp={payload['spp']}")
                if payload.get("variant"):
                    bits.append(f"variant={payload['variant']}")
                if bits:
                    label = f"{stage} · " + " · ".join(bits)
            hb.update(stage, label)
            _emit(event)

        previous_disable_cuda = os.environ.get("ROBOMITUBA_DISABLE_CUDA")
        if disable_cuda_for_full_render:
            os.environ["ROBOMITUBA_DISABLE_CUDA"] = "1"
        try:
            try:
                bundle = render_timestep_bundle_split_lighting(
                    render_request,
                    repo_root=repo_root,
                    variant=variant,
                    progress_callback=_progress,
                )
            finally:
                if disable_cuda_for_full_render:
                    if previous_disable_cuda is None:
                        os.environ.pop("ROBOMITUBA_DISABLE_CUDA", None)
                    else:
                        os.environ["ROBOMITUBA_DISABLE_CUDA"] = previous_disable_cuda
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t_start) * 1000.0)
            tb_tail = "\n".join(traceback.format_exc().splitlines()[-12:])
            _emit_failed(
                job_id, "render_exception",
                f"{type(exc).__name__}: {exc}\n{tb_tail}",
                elapsed_ms=elapsed_ms,
            )
            return

    elapsed_ms = int((time.perf_counter() - t_start) * 1000.0)
    manifest_path = f"{bundle.bundle_root}/manifest.json"
    _emit({
        "job_id": job_id, "type": "completed",
        "manifest_path": manifest_path,
        "elapsed_ms": elapsed_ms,
    })


_DISPATCH_TABLE: dict[str, Any] = {
    "curated_preview": _dispatch_curated,
    "measured_preview": _dispatch_measured,
    "channel_split_preview": _dispatch_measured,  # shares dispatcher; spec.use_channel_split=True
    "render_job": _dispatch_render_job,
}


def _dispatch(request: dict[str, Any]) -> None:
    job_id = str(request.get("job_id") or "")
    kind = str(request.get("kind") or "")
    spec = request.get("spec") or {}
    if not isinstance(spec, dict):
        _emit_failed(job_id, "bad_request", "spec must be an object")
        return

    handler = _DISPATCH_TABLE.get(kind)
    if handler is None:
        _emit_failed(job_id, "unknown_kind", f"unknown job kind: {kind!r}")
        return

    _emit({"job_id": job_id, "type": "started", "ts": time.time()})
    try:
        handler(job_id, spec)
    except SystemExit:
        raise
    except Exception as exc:
        tb_tail = "\n".join(traceback.format_exc().splitlines()[-12:])
        _emit_failed(
            job_id, "exception",
            f"{type(exc).__name__}: {exc}\n{tb_tail}",
        )


# ── Worker entry point ────────────────────────────────────────────────


def _warm_variant_cache() -> None:
    """Run ``_pick_variant_for`` once at startup so the first job doesn't
    pay the variant-detection cost. Failures are tolerated — if no variant
    is available the dispatcher will fail with ``plugin_unavailable``
    when a render is actually attempted.
    """
    try:
        from .sphere_preview import _pick_variant_for  # noqa: F401
        _pick_variant_for("rgb")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mitsuba_converter.preview_worker")
    parser.add_argument("--gpu-index", type=int, default=0,
                        help="GPU index this worker is pinned to (informational)")
    args = parser.parse_args(argv)

    # Echoed for the daemon log so we can correlate worker <-> GPU.
    print(
        f"[worker] start pid={os.getpid()} gpu_index={args.gpu_index} "
        f"CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', '<unset>')}",
        file=sys.stderr, flush=True,
    )

    log_level = _set_render_log_level(
        os.environ.get("ROBOMITUBA_RENDER_LOG_LEVEL", "info"),
    )
    print(
        f"[worker] log_level={log_level} heartbeat_interval={_DISPATCH_HEARTBEAT_INTERVAL_S:.1f}s",
        file=sys.stderr, flush=True,
    )

    _warm_variant_cache()

    stop_event = threading.Event()
    hb_thread = threading.Thread(target=_heartbeat_loop, args=(stop_event,), daemon=True)
    hb_thread.start()

    # Initial readiness signal so the manager can mark the worker live
    # without waiting for the first heartbeat tick.
    _emit({"type": "ready", "pid": os.getpid(), "gpu_index": int(args.gpu_index), "ts": time.time()})

    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                _emit({
                    "type": "error", "reason": "bad_json",
                    "message": f"{type(exc).__name__}: {exc}",
                })
                continue
            if not isinstance(request, dict):
                _emit({"type": "error", "reason": "bad_request", "message": "request must be an object"})
                continue
            _dispatch(request)
    finally:
        stop_event.set()

    return 0


if __name__ == "__main__":
    sys.exit(main())
