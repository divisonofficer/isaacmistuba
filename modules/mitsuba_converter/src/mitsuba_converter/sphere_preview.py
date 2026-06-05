"""sphere_preview.py — Mitsuba sphere preview renderer.

Renders a small sphere with a given BSDF and caches the result as a PNG.
Used by ``render_daemon`` to serve ``/api/material-preview/*`` image responses.

Returns ``PreviewResult(path, status)``. ``status`` lets the daemon surface the
actual outcome to the frontend via an ``X-Preview-Status`` header rather than
silently substituting a fallback sphere when the real measured BSDF could not
be loaded.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)


class PreviewResult(NamedTuple):
    """Result of a preview-render request.

    ``status`` is one of:
      * ``ok``                 — real measured / preset BSDF rendered
      * ``placeholder``        — colored fallback (file is missing / not downloaded)
      * ``not_downloaded``     — file path provided but file absent on disk
      * ``plugin_unavailable`` — Mitsuba build lacks the required variant for this file
      * ``load_error``         — file present but Mitsuba couldn't parse it
      * ``gpu_oom``            — Dr.Jit ran out of GPU/host-pinned memory loading the BSDF
      * ``optix_unavailable``  — CUDA variant failed because the host driver cannot load OptiX
      * ``mitsuba_unavailable``— ``import mitsuba`` failed entirely
      * ``unknown``            — other failure (preset id not found, etc.)
    """

    path: Path | None
    status: str


# Global lock: Mitsuba's mi.set_variant() mutates process-wide state, so only
# one sphere can render at a time across all threads. Reentrant so that BG
# render tasks can hold the lock across a stage update + a call into
# `get_measured_preview` (which re-acquires it internally) without
# deadlocking — see `_enqueue_measured_render` in render_daemon.py.
_mitsuba_render_lock = threading.RLock()

# Per-key lock so that two concurrent requests for the same preview
# don't both start rendering (outer coordination, cheap path).
_render_locks: dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()


def _get_lock(key: str) -> threading.Lock:
    with _locks_mutex:
        if key not in _render_locks:
            _render_locks[key] = threading.Lock()
        return _render_locks[key]


# ── Variant discovery ───────────────────────────────────────────────────────


def _available_variants() -> list[str]:
    """Return the list of Mitsuba variants compiled into the current build."""
    from .mitsuba_runtime import available_variants

    return available_variants()


def _pick_variant_for(kind: str) -> str | None:
    """Return the first working variant for the given BSDF kind.

    ``kind``:
      * ``"spectral_polarized"`` — required by the ``measured_polarized`` plugin.
      * ``"rgb"`` — any variant that can render a colour sphere.

    Returns None when no suitable variant exists in the build. CUDA variants
    are still preferred, but Docker hosts with an older OptiX runtime can now
    fall back to LLVM/scalar instead of failing the whole preview pipeline.
    """
    from .mitsuba_runtime import MitsubaVariantUnavailable, resolve_variant

    try:
        return resolve_variant(None, kind=kind, allow_cpu=True)
    except MitsubaVariantUnavailable as exc:
        logger.warning("No Mitsuba variant available for %s preview: %s", kind, exc)
        return None


def _pick_fallback_variant_after_failure(kind: str, failed_variant: str, exc: BaseException) -> str | None:
    """Mark a failed CUDA variant and resolve the next CPU-safe candidate."""
    from .mitsuba_runtime import MitsubaVariantUnavailable, mark_variant_unavailable, resolve_variant

    if not str(failed_variant).startswith("cuda_"):
        return None
    mark_variant_unavailable(failed_variant, exc)
    try:
        fallback = resolve_variant("auto", kind=kind, allow_cpu=True)
    except MitsubaVariantUnavailable as fallback_exc:
        logger.warning("No fallback Mitsuba variant after %s failed: %s", failed_variant, fallback_exc)
        return None
    if fallback == failed_variant:
        return None
    return fallback


def _is_optix_unavailable_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "could not initialize optix" in lowered
        or "failed to load optix" in lowered
        or "optix 8.0 requires driver" in lowered
        or "jit_optix_api_init" in lowered
    )


# ── Default BSDF dicts for each preset ──────────────────────────────────────

PRESET_BSDFS: dict[str, dict[str, Any]] = {
    "none": {
        "type": "diffuse",
        "reflectance": {"type": "rgb", "value": [0.78, 0.78, 0.78]},
    },
    "diffuse": {
        "type": "diffuse",
        "reflectance": {"type": "rgb", "value": [0.54, 0.60, 0.70]},
    },
    "roughplastic": {
        "type": "roughplastic",
        "diffuse_reflectance": {"type": "rgb", "value": [0.52, 0.46, 0.38]},
        "alpha": 0.25,
        "int_ior": 1.49,
    },
    "pplastic": {
        # pplastic is a patched BSDF not in stock Mitsuba; approximate with
        # roughplastic for the preview sphere.
        "type": "roughplastic",
        "diffuse_reflectance": {"type": "rgb", "value": [0.54, 0.50, 0.32]},
        "alpha": 0.12,
        "int_ior": 1.49,
    },
    "conductor": {
        "type": "conductor",
        "material": "Ag",
    },
    "roughconductor": {
        "type": "roughconductor",
        "material": "Al",
        "alpha": 0.18,
        "distribution": "ggx",
    },
    "dielectric": {
        "type": "dielectric",
        "int_ior": 1.5,
        "ext_ior": 1.0,
    },
    "principled": {
        "type": "principled",
        "base_color": {"type": "rgb", "value": [0.56, 0.38, 0.22]},
        "roughness": 0.35,
        "metallic": 0.0,
    },
    "glossy_black_lacquer": {
        "type": "roughplastic",
        "diffuse_reflectance": {"type": "rgb", "value": [0.024, 0.024, 0.028]},
        "alpha": 0.032,
        "int_ior": 1.65,
    },
    "mirror_black_enamel": {
        "type": "roughconductor",
        "material": "Ag",
        "alpha": 0.003,
        "distribution": "ggx",
    },
    # ── material_hint aliases used by usd_editor_geometry ────────────────────
    "painted_wall": {
        "type": "roughplastic",
        "diffuse_reflectance": {"type": "rgb", "value": [0.88, 0.87, 0.85]},
        "alpha": 0.40,
        "int_ior": 1.49,
    },
    "tile": {
        "type": "roughplastic",
        "diffuse_reflectance": {"type": "rgb", "value": [0.80, 0.80, 0.78]},
        "alpha": 0.10,
        "int_ior": 1.52,
    },
    "wood": {
        "type": "roughplastic",
        "diffuse_reflectance": {"type": "rgb", "value": [0.55, 0.38, 0.22]},
        "alpha": 0.30,
        "int_ior": 1.49,
    },
    "clear_glass": {
        "type": "dielectric",
        "int_ior": 1.5,
        "ext_ior": 1.0,
    },
    "frosted_glass": {
        "type": "roughdielectric",
        "int_ior": 1.5,
        "ext_ior": 1.0,
        "alpha": 0.25,
        "distribution": "ggx",
    },
    "fabric": {
        "type": "diffuse",
        "reflectance": {"type": "rgb", "value": [0.52, 0.46, 0.60]},
    },
    "mirror": {
        "type": "conductor",
        "material": "Ag",
    },
}


# ── Heuristics for measured material rendering ──────────────────────────────

_METAL_TOKENS = ("gold", "silver", "copper", "aluminum", "aluminium", "chrome", "steel", "brass", "platinum", "metal")
_CERAMIC_TOKENS = ("ceramic", "alumina", "zro", "zirconia", "porcelain")
_SOFT_TOKENS = ("silicone", "rubber", "wax", "skin", "cloth", "fabric", "velvet")


def _alpha_sample_for(dataset_id: str, material_id: str) -> float:
    """Importance-sampling roughness hint for the ``measured_polarized`` plugin.

    This only affects sampling noise, not physics. Crude string-match heuristic
    — an exact per-material table is overkill for a 128-px preview.
    """
    mid = material_id.lower()
    if "fake" in mid and "gold" in mid:
        return 0.03
    if any(tok in mid for tok in _METAL_TOKENS):
        return 0.02
    if any(tok in mid for tok in _CERAMIC_TOKENS):
        return 0.08
    if "billiard" in mid:
        return 0.04
    if any(tok in mid for tok in _SOFT_TOKENS):
        return 0.12
    return 0.08


# ── Scene construction ───────────────────────────────────────────────────────

# Identifier for the current sphere-preview lighting rig. Bump when changing
# anything in `_RIG_SPEC` so cached PNGs are recognised as stale.
PREVIEW_PRESET_ID = "sphere_only_rgba_v1"


# Rig parameters as a plain dict so they can be hashed deterministically and
# emitted into sidecar metadata. Keep this the single source of truth: both
# `_build_scene_dict` and `rig_hash()` consume it.
_RIG_SPEC: dict[str, Any] = {
    "preset": PREVIEW_PRESET_ID,
    # NO floor / NO back wall — the sphere alone gets rendered. Pixels that
    # miss the sphere come back as alpha=0, and `_render_to_png` composites
    # them over `preview_background` (#F7F7F5, matching `.mat-card` /
    # `.mat-thumb` / `.page-materials` in the UI). This sidesteps the whole
    # "render a white floor that matches the page bg" problem — instead of
    # trying to make the rendered floor identical to the surrounding UI
    # colour, we just don't render a floor at all.
    "preview_background": {"rgb": [0.9686, 0.9686, 0.9608]},  # #F7F7F5
    "camera": {"origin": [0.0, 1.79, 5.48], "target": [0.0, 0.05, 0.0], "fov": 28},
    # Brighter env (0.9) compensates for the lost floor bounce — without a
    # ground plane, the sphere's underside has no indirect fill, so the
    # constant emitter has to wrap light around it for the bottom half not
    # to look pitch-dark on dark materials.
    "env": {"radiance": [0.9, 0.9, 0.88]},
    "key_light": {
        "origin": [-2.5, 3.0, 3.5], "target": [0.0, 0.0, 0.0],
        "scale": [3.0, 3.0, 1.0], "radiance": [1.8, 1.8, 1.8],
    },
    "sphere": {"radius": 0.9},
    # max_depth=5 is plenty for the sphere-only rig (env -> sphere -> BSDF ->
    # key_light covers all visible bounces). Was 8 — dropped to halve ray cost
    # without visual change for non-mirror materials.
    "integrator": {"type": "path", "max_depth": 5},
}


# ── Preview-object registry ─────────────────────────────────────────────────
# Pluggable geometry: `?object=sphere` (default) or `?object=french_bread`.
# Adding a new object = one entry below + matching builder fn.
#
# Each object yields a Mitsuba shape dict given the user's BSDF. A sphere
# uses the rig's existing radius. A mesh ("obj") loads from disk and gets
# auto-fitted via `_object_camera_distance` so the shot frames it well
# without per-object camera tweaks.

_REPO_ROOT_FOR_ASSETS = Path(__file__).resolve().parents[4]
"""Best-effort repo root from this file's location, used to resolve mesh
asset paths declared in PREVIEW_OBJECTS without needing the caller to pass
``repo_root`` everywhere. Falls back gracefully if the file moves."""


@dataclass(frozen=True)
class PreviewObject:
    object_id: str
    label_en: str
    label_kr: str
    icon: str
    # Builder takes the user's BSDF dict and returns a Mitsuba shape dict
    # (with ``"bsdf": bsdf_dict`` already wired in). The scene_dict slot
    # the shape lands in is always called ``"object"`` so legacy callers
    # that referred to ``"sphere"`` keep working through the renamed key.
    builder: Callable[[dict[str, Any]], dict[str, Any]] = field(repr=False)
    # Optional camera origin override — for big meshes that need the
    # camera further back. ``None`` = use ``_RIG_SPEC["camera"]["origin"]``.
    camera_origin: tuple[float, float, float] | None = None
    # Optional reference path used for cache-busting (rig_hash includes the
    # mesh's mtime so updating the OBJ on disk invalidates cached PNGs).
    mesh_path: str | None = None


def _sphere_builder(bsdf_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "sphere",
        "radius": _RIG_SPEC["sphere"]["radius"],
        "bsdf": bsdf_dict,
    }


_FRENCH_BREAD_OBJ_REL = (
    "assets/moorelane/Intel_mooreLane_v1_2_0/Intel_mooreLane/textures/SCANS/French_Bread_OBJ.obj"
)


def _french_bread_builder(bsdf_dict: dict[str, Any]) -> dict[str, Any]:
    import mitsuba as mi
    abs_path = _REPO_ROOT_FOR_ASSETS / _FRENCH_BREAD_OBJ_REL
    # Mesh is ~0.02 units tall in OBJ space; scale + center via to_world
    # computed from cached bounds so the shot frames it like the sphere.
    bmin, bmax = _mesh_bounds_cached(abs_path)
    center = (bmin + bmax) * 0.5
    extent = float(np.max(bmax - bmin))
    target_extent = 1.5  # similar visual size to sphere (radius 0.9 → extent 1.8)
    scale = target_extent / extent if extent > 0 else 1.0
    to_world = (
        mi.ScalarTransform4f.translate([0.0, 0.0, 0.0])
        @ mi.ScalarTransform4f.scale([scale, scale, scale])
        @ mi.ScalarTransform4f.translate([-float(center[0]), -float(center[1]), -float(center[2])])
    )
    return {
        "type": "obj",
        "filename": str(abs_path),
        "to_world": to_world,
        "bsdf": bsdf_dict,
        "face_normals": False,
    }


PREVIEW_OBJECTS: dict[str, "PreviewObject"] = {
    "sphere": PreviewObject(
        object_id="sphere",
        label_en="Sphere",
        label_kr="구",
        icon="🟢",
        builder=_sphere_builder,
    ),
    "french_bread": PreviewObject(
        object_id="french_bread",
        label_en="French Bread",
        label_kr="빵",
        icon="🥖",
        builder=_french_bread_builder,
        mesh_path=_FRENCH_BREAD_OBJ_REL,
    ),
}

DEFAULT_PREVIEW_OBJECT = "sphere"


def list_preview_objects() -> list[dict[str, Any]]:
    """Public registry snapshot for the daemon's GET /api/preview-objects."""
    return [
        {
            "object_id": o.object_id,
            "label_en": o.label_en,
            "label_kr": o.label_kr,
            "icon": o.icon,
            "is_default": o.object_id == DEFAULT_PREVIEW_OBJECT,
        }
        for o in PREVIEW_OBJECTS.values()
    ]


def resolve_preview_object(object_id: str | None) -> str:
    """Return ``object_id`` if registered, else fall back to the default."""
    if object_id and object_id in PREVIEW_OBJECTS:
        return object_id
    return DEFAULT_PREVIEW_OBJECT


# Lazy import; only loaded when the bread (or any future mesh) is rendered.
def _mesh_bounds_cached(path: Path) -> tuple["np.ndarray", "np.ndarray"]:
    cache = _MESH_BOUNDS_CACHE
    key = (str(path), path.stat().st_mtime_ns if path.exists() else 0)
    if cache.get("__key") == key:
        return cache["min"], cache["max"]
    from .multimodal import _load_obj_bounds  # type: ignore[attr-defined]
    bmin, bmax = _load_obj_bounds(path)
    cache["__key"] = key
    cache["min"] = bmin
    cache["max"] = bmax
    return bmin, bmax


_MESH_BOUNDS_CACHE: dict[str, Any] = {}
import numpy as np  # noqa: E402  (kept after dataclass section for grouping)


def rig_hash() -> str:
    """Deterministic hash of the current rig spec (rig only, no BSDF).

    Used in sidecar `.meta.json` so the frontend / library can detect when a
    cached preview was rendered with a different rig and mark it stale.

    Includes PREVIEW_OBJECTS metadata + each registered mesh's mtime so
    swapping geometry / replacing an OBJ on disk also flips the hash.
    """
    blob_parts: list[str] = [
        json.dumps(_RIG_SPEC, sort_keys=True, separators=(",", ":")),
    ]
    for oid in sorted(PREVIEW_OBJECTS.keys()):
        obj = PREVIEW_OBJECTS[oid]
        info: dict[str, Any] = {"id": oid, "label_en": obj.label_en}
        if obj.mesh_path:
            mp = _REPO_ROOT_FOR_ASSETS / obj.mesh_path
            info["mesh_path"] = obj.mesh_path
            try:
                info["mesh_mtime"] = mp.stat().st_mtime_ns
            except OSError:
                info["mesh_mtime"] = None
        blob_parts.append(json.dumps(info, sort_keys=True, separators=(",", ":")))
    blob = "|".join(blob_parts).encode("utf-8")
    return "sha1:" + hashlib.sha1(blob).hexdigest()[:16]


def _build_scene_dict(
    bsdf_dict: dict[str, Any],
    *,
    size: int = 128,
    spp: int = 64,
    integrator: dict[str, Any] | None = None,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> dict[str, Any]:
    """Return a ``mi.load_dict()``-compatible scene dict for the preview rig.

    The geometry slot is filled by ``PREVIEW_OBJECTS[object_id].builder``
    (sphere by default). Lighting + camera + film are constant across
    objects unless the registry entry overrides ``camera_origin``.
    """
    import mitsuba as mi

    obj = PREVIEW_OBJECTS.get(object_id) or PREVIEW_OBJECTS[DEFAULT_PREVIEW_OBJECT]

    cam = _RIG_SPEC["camera"]
    cam_origin = list(obj.camera_origin) if obj.camera_origin else cam["origin"]
    look_at = mi.ScalarTransform4f.look_at(
        origin=cam_origin, target=cam["target"], up=[0.0, 1.0, 0.0],
    )

    key = _RIG_SPEC["key_light"]
    key_xform = (
        mi.ScalarTransform4f.look_at(origin=key["origin"], target=key["target"], up=[0.0, 1.0, 0.0])
        @ mi.ScalarTransform4f.scale(key["scale"])
    )

    return {
        "type": "scene",
        "integrator": integrator or _RIG_SPEC["integrator"],
        "sensor": {
            "type": "perspective",
            "fov": cam["fov"],
            "to_world": look_at,
            "film": {
                "type": "hdrfilm",
                "width": size,
                "height": size,
                "rfilter": {"type": "gaussian"},
                # rgba so `_render_to_png` can alpha-composite the object
                # over the off-white card colour. Pixels missing the object
                # return alpha=0.
                "pixel_format": "rgba",
            },
            "sampler": {"type": "independent", "sample_count": spp},
        },
        "env": {
            "type": "constant",
            "radiance": {"type": "rgb", "value": _RIG_SPEC["env"]["radiance"]},
        },
        "key_light": {
            "type": "rectangle",
            "to_world": key_xform,
            "emitter": {
                "type": "area",
                "radiance": {"type": "rgb", "value": key["radiance"]},
            },
        },
        # Always called "object" in the scene dict — the geometry comes
        # from the registry's builder (sphere or mesh). Renamed from
        # "sphere" so the scene structure no longer lies about the type.
        "object": obj.builder(bsdf_dict),
    }


# ── Rendering primitives ────────────────────────────────────────────────────

def _ensure_mitsuba_variant(variant: str) -> None:
    """Set the Mitsuba variant in the current process.

    Must be called **before** any ``mi.ScalarTransform4f`` / ``mi.load_dict``
    access, under ``_mitsuba_render_lock`` because Mitsuba's variant state is a
    process-wide global that is not safe to flip concurrently.
    """
    from .mitsuba_runtime import ensure_mitsuba_variant

    ensure_mitsuba_variant(variant)


_KEEP_KERNEL_CACHE = (
    os.environ.get("ROBOMITUBA_KEEP_KERNEL_CACHE", "1").strip().lower()
    in ("1", "true", "yes", "on")
)


def _release_gpu_pool() -> None:
    """Force Dr.Jit to flush its GPU/CPU allocation pool.

    When ``mi.load_dict`` throws mid-load (e.g. a measured BSDF that fails the
    parser), the partially-allocated GPU buffers stay pinned in Dr.Jit's pool
    until the next garbage collection cycle. Repeated failed renders therefore
    leak ~hundreds of MB to several GB of VRAM each, eventually OOM-ing the
    process. Call this in a ``finally`` after every render attempt so the next
    one starts from a clean slate.

    Phase B-1 (2026-04-30): ``flush_malloc_cache`` stays — it's the actual
    leak defense. ``flush_kernel_cache`` is gated on
    ``ROBOMITUBA_KEEP_KERNEL_CACHE`` (default ``1`` = keep). Flushing the
    kernel cache between renders forces OptiX to re-compile shaders every
    time, which is the dominant cost (~5 min) on driver versions that
    miss the OptiX 8 shader cache. Keeping the cache makes the second
    render of the same variant essentially free.

    Set ``ROBOMITUBA_KEEP_KERNEL_CACHE=0`` to restore the old behavior
    (24-hour rollback escape hatch — see plan Phase B-1).
    """
    try:
        import gc
        import drjit as dr  # type: ignore
        gc.collect()
        # malloc cache: always flush (anti-leak — anti-improvement #4).
        fn = getattr(dr, "flush_malloc_cache", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
        # kernel cache: keep by default (Phase B-1). Flushing forces
        # OptiX shader recompile on every render — the dominant cost.
        if not _KEEP_KERNEL_CACHE:
            fn = getattr(dr, "flush_kernel_cache", None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
    except Exception:
        pass


def _adaptive_chunks(spp: int) -> int:
    """How many chunks to split a render into.

    Each chunk is a separate ``mi.render`` call + GPU->CPU sync + numpy
    running-mean step, so chunks have nontrivial overhead — use them only
    when ``spp`` is large enough to justify multiple passes (so the user
    sees mid-render progress on slow renders, but tiny renders run in a
    single GPU launch with no sync barriers in between).
    """
    if spp <= 1024:
        return 1
    if spp <= 4096:
        return 2
    return 4


# Honour ROBOMITUBA_PREVIEW_SUPERSAMPLE if set, otherwise oversample 2x.
def _supersample_default() -> int:
    try:
        n = int(os.environ.get("ROBOMITUBA_PREVIEW_SUPERSAMPLE", "2"))
    except (TypeError, ValueError):
        return 2
    return max(1, min(4, n))


def _render_to_png(
    scene_dict: dict[str, Any],
    out_path: Path,
    *,
    variant: str,
    spp: int,
    progress_cb: Callable[[int, int], None] | None = None,
    chunks: int | None = None,
    supersample: int = 1,
    target_size: int | None = None,
    bench_label: str | None = None,
) -> None:
    """Render a scene dict and write a sphere-only RGBA PNG.

    Render is split into ``chunks`` independent passes (different seeds) and
    averaged so we can emit progress updates between passes.

    Chunk policy (Phase A-1):
      * If caller supplies ``chunks`` explicitly, honour it.
      * Else if ``progress_cb is None`` (headless / batch / CLI): single chunk
        — chunks only exist to surface mid-render progress.
      * Else (interactive UI with progress): :func:`_adaptive_chunks(spp)`.

    Chunk accumulation (Phase A-3): the running mean is kept on-device as a
    Dr.Jit ``TensorXf``. The ``np.array(...)`` GPU→CPU sync barrier happens
    exactly once at the end, regardless of chunk count.

    ``supersample`` + ``target_size``: if both are >1, the scene_dict is
    assumed to be sized at ``target_size * supersample`` and the final PNG
    is downsampled to ``(target_size, target_size)`` with PIL Lanczos.

    ``bench_label`` is included in the ``preview_bench:`` log line emitted
    on every successful render — operators can grep per-call (e.g.
    ``"curated/aluminum"`` vs ``"measured/pbrdf_2020/chrome"``).
    """
    import mitsuba as mi
    import numpy as np
    from PIL import Image

    # Phase A-4: per-stage timing — emitted as a single structured log line.
    bench: dict[str, float] = {}
    t0 = time.perf_counter()

    _ensure_mitsuba_variant(variant)
    bench["variant_ms"] = (time.perf_counter() - t0) * 1000.0

    # Phase A-1: gate chunking on progress_cb presence.
    if chunks is not None:
        n_chunks = max(1, int(chunks))
    elif progress_cb is None:
        n_chunks = 1
    else:
        n_chunks = max(1, _adaptive_chunks(spp))
    chunk_spp = max(1, spp // n_chunks)

    scene = None
    accum_t: Any = None
    raw: np.ndarray
    try:
        print(
            f"[daemon] preview_render: enter label={bench_label or 'preview'} "
            f"variant={variant} spp={spp} chunks={n_chunks} chunk_spp={chunk_spp}",
            file=sys.stderr, flush=True,
        )
        t_load = time.perf_counter()
        scene = mi.load_dict(scene_dict)
        bench["load_ms"] = (time.perf_counter() - t_load) * 1000.0

        # Phase A-3: GPU running mean — accumulator stays as a Dr.Jit tensor;
        # the single GPU→CPU sync happens at the np.array(...) below.
        t_render = time.perf_counter()
        for k in range(n_chunks):
            t_chunk = time.perf_counter()
            sub = mi.render(scene, spp=chunk_spp, seed=k + 1)
            if accum_t is None:
                accum_t = sub
            else:
                # Running mean on device: avg_{k+1} = (avg_k * k + new) / (k + 1)
                accum_t = (accum_t * k + sub) / (k + 1)
            if n_chunks > 1:
                # Chunked path is the interactive one — surface per-chunk
                # timing so operators can see *which* chunk is slow rather
                # than only the aggregate.
                print(
                    f"[daemon] preview_chunk: label={bench_label or 'preview'} "
                    f"chunk={k + 1}/{n_chunks} chunk_ms={(time.perf_counter() - t_chunk) * 1000.0:.1f}",
                    file=sys.stderr, flush=True,
                )
            if progress_cb is not None:
                try:
                    progress_cb(k + 1, n_chunks)
                except Exception:
                    pass
        bench["render_ms"] = (time.perf_counter() - t_render) * 1000.0

        t_sync = time.perf_counter()
        raw = np.array(accum_t, dtype=np.float32)
        raw = np.maximum(raw, 0.0)
        bench["sync_ms"] = (time.perf_counter() - t_sync) * 1000.0
    finally:
        # Release the scene + flush Dr.Jit's allocator BEFORE leaving the
        # Mitsuba lock — otherwise a failed render leaves multi-GB GPU
        # buffers pinned and the next render fails too (verified with
        # ``jit_malloc_shutdown(): leaked - device memory: 16 GiB``).
        scene = None  # noqa: F841 — drop the only Python ref to the scene
        accum_t = None  # noqa: F841 — drop on-device tensor before flush
        _release_gpu_pool()

    t_post = time.perf_counter()
    if raw.ndim == 3 and raw.shape[2] >= 4:
        rgb = raw[:, :, :3]
        alpha = raw[:, :, 3:4]
        rgb = rgb / (1.0 + rgb * 0.55)
        rgb = rgb ** (1.0 / 2.2)
        rgb_u8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
        alpha_u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
        rgba = np.concatenate([rgb_u8, alpha_u8], axis=-1)
        img = Image.fromarray(rgba, mode="RGBA")
        if supersample > 1 and target_size is not None and target_size > 0:
            img = img.resize((target_size, target_size), Image.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path))
    else:
        # Fallback for callers still using rgb-only film.
        rgb = raw[:, :, :3] if raw.ndim == 3 else raw
        rgb = rgb / (1.0 + rgb * 0.55)
        out_arr = np.clip(rgb ** (1.0 / 2.2) * 255.0, 0, 255).astype(np.uint8)
        img = Image.fromarray(out_arr, mode="RGB")
        if supersample > 1 and target_size is not None and target_size > 0:
            img = img.resize((target_size, target_size), Image.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path))
    bench["postproc_ms"] = (time.perf_counter() - t_post) * 1000.0
    bench["total_ms"] = (time.perf_counter() - t0) * 1000.0

    rh, rw = (int(raw.shape[0]), int(raw.shape[1])) if raw.ndim >= 2 else (0, 0)
    # Direct stderr print: daemon's [http] lines go to stderr without
    # going through Python's logging module (no handler is configured
    # for the daemon root logger), so logger.info(...) was being silently
    # dropped. Match the daemon style so operators see this alongside
    # the http logs.
    print(
        f"[daemon] preview_bench: label={bench_label or 'preview'} variant={variant} "
        f"spp={spp} chunks={n_chunks} render_size={rw}x{rh} "
        f"| variant={bench.get('variant_ms', 0.0):.1f} load={bench.get('load_ms', 0.0):.1f} "
        f"render={bench.get('render_ms', 0.0):.1f} sync={bench.get('sync_ms', 0.0):.1f} "
        f"postproc={bench.get('postproc_ms', 0.0):.1f} | total={bench.get('total_ms', 0.0):.1f}",
        file=sys.stderr, flush=True,
    )
    print(f"[daemon] preview saved: {out_path}", file=sys.stderr, flush=True)


# ── Channel-split (per-wavelength .pbrdf) rendering ─────────────────────────

# RGB+NIR default — must match `HPBRDF_2025_RGBNIR_WAVELENGTHS_NM` in
# material_library.py. Don't import from there to avoid pulling that whole
# module's PyYAML / catalog deps into the render hot path.
RGBNIR_DEFAULT: tuple[int, int, int, int] = (446, 542, 614, 854)
RGBNIR_BAND_ASSIGNMENT = {"B": 446, "G": 542, "R": 614, "NIR": 854}


def _render_single_channel_to_array(
    bsdf_dict: dict[str, Any],
    *,
    variant: str,
    spp: int,
    size: int,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
    bench_label: str | None = None,
) -> "np.ndarray":  # type: ignore[name-defined]
    """Render one sphere with the given BSDF, return the raw RGBA float32
    array (H, W, 4) WITHOUT tone-mapping. Caller composites multiple of
    these into a final image. Acquires the global Mitsuba lock so it is
    safe to call from a daemon BG thread.

    Phase A-1: this path has no per-chunk progress callback consumer
    (channel-split surfaces progress per *wavelength*, not per chunk), so
    chunking is pure waste — forced to a single chunk regardless of spp.

    Phase A-3: GPU-side running mean is moot at chunks=1 but kept symmetric
    with ``_render_to_png`` — single ``np.array`` sync at the end.

    Phase A-4: emits ``preview_bench:`` log line per channel.
    """
    import mitsuba as mi
    import numpy as np

    bench: dict[str, float] = {}
    t0 = time.perf_counter()

    with _mitsuba_render_lock:
        _ensure_mitsuba_variant(variant)
        bench["variant_ms"] = (time.perf_counter() - t0) * 1000.0

        t_dict = time.perf_counter()
        scene_dict = _build_scene_dict(bsdf_dict, size=size, spp=spp, object_id=object_id)
        bench["dict_ms"] = (time.perf_counter() - t_dict) * 1000.0

        scene = None
        accum_t: Any = None
        raw: np.ndarray
        try:
            print(
                f"[daemon] preview_render: enter label={bench_label or 'channel'} "
                f"variant={variant} spp={spp} chunks=1",
                file=sys.stderr, flush=True,
            )
            t_load = time.perf_counter()
            scene = mi.load_dict(scene_dict)
            bench["load_ms"] = (time.perf_counter() - t_load) * 1000.0

            # No progress consumer here → chunks=1 (Phase A-1).
            n_chunks = 1
            chunk_spp = max(1, spp // n_chunks)
            t_render = time.perf_counter()
            for k in range(n_chunks):
                sub = mi.render(scene, spp=chunk_spp, seed=k + 1)
                accum_t = sub if accum_t is None else (accum_t * k + sub) / (k + 1)
            bench["render_ms"] = (time.perf_counter() - t_render) * 1000.0

            t_sync = time.perf_counter()
            raw = np.array(accum_t, dtype=np.float32)
            raw = np.maximum(raw, 0.0)
            bench["sync_ms"] = (time.perf_counter() - t_sync) * 1000.0
        finally:
            scene = None  # noqa: F841 — drop ref so jit_alloc can reclaim
            accum_t = None  # noqa: F841 — drop on-device tensor before flush
            _release_gpu_pool()

        bench["total_ms"] = (time.perf_counter() - t0) * 1000.0
        rh, rw = (int(raw.shape[0]), int(raw.shape[1])) if raw.ndim >= 2 else (0, 0)
        print(
            f"[daemon] preview_bench: label={bench_label or 'channel'} variant={variant} "
            f"spp={spp} chunks=1 render_size={rw}x{rh} "
            f"| variant={bench.get('variant_ms', 0.0):.1f} dict={bench.get('dict_ms', 0.0):.1f} "
            f"load={bench.get('load_ms', 0.0):.1f} render={bench.get('render_ms', 0.0):.1f} "
            f"sync={bench.get('sync_ms', 0.0):.1f} | total={bench.get('total_ms', 0.0):.1f}",
            file=sys.stderr, flush=True,
        )
        return raw


def _render_channel_split(
    material_id: str,
    channels_dir: Path,
    wavelengths_to_render: list[int],
    out_path: Path,
    cache_dir: Path,
    *,
    mode: str = "rgbnir",
    spp: int = 256,
    size: int = 192,
    progress_cb: Any = None,  # Callable[[int, int], None] | None
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> "PreviewResult":
    """Render N monochromatic spheres (one per wavelength), composite into
    a single RGB(A) PNG.

    The whole point of this path: each ``.pbrdf`` is ~191 MB instead of
    the monolithic ``.hpbrdf``'s 13 GB, so under the global Mitsuba lock
    we can serially load + render + release each wavelength without
    OOMing a shared GPU. The composite is done at the end on numpy
    arrays (CPU), no further GPU memory needed.

    Output layout (Phase 9):
        ``cache_dir/channel_split/{material_id}/``
            ``rgb_composite_{size}.png``      # default thumbnail
            ``band_{nm}_{size}.png`` × N      # per-wavelength grayscale
            ``manifest.json``                 # describes everything above

    Plus a duplicate write to ``out_path`` (the legacy flat path) so that
    older daemons / direct readers that don't know about the directory
    layout still find the composite.

    ``mode``:
      * ``"rgbnir"`` — direct band → RGB mapping (4 channels, no CIE
        weighting). Fastest; output PNG is RGB + the NIR channel encoded
        into the alpha pre-multiplication is reserved for future use.
      * ``"visible"`` / ``"hyperspectral"`` — CIE 1931 weighted spectral
        composite. Use ≥ 10 channels for usable colour accuracy.
    """
    import numpy as np
    from PIL import Image
    # tools/hpbrdf/cie_matching is not part of mitsuba_converter package, so
    # pull it via a sys.path hop. Worth the minor coupling because the CIE
    # tables shouldn't be duplicated.
    import sys as _sys
    _tools_root = Path(__file__).resolve().parents[4] / "tools"
    if str(_tools_root) not in _sys.path:
        _sys.path.insert(0, str(_tools_root))
    from hpbrdf.cie_matching import (  # type: ignore[import-not-found]
        spectrum_to_srgb, stack_rgbnir_to_image,
    )

    variant = _pick_variant_for("spectral_polarized")
    if variant is None:
        return PreviewResult(None, "plugin_unavailable")

    # Render each wavelength sequentially under the lock (handled inside
    # `_render_single_channel_to_array`).
    rgba_per_wavelength: dict[int, np.ndarray] = {}
    n = len(wavelengths_to_render)
    fallback_tried = False
    for idx, wl in enumerate(wavelengths_to_render):
        channel_path = channels_dir / f"{wl}.pbrdf"
        if not channel_path.exists():
            logger.warning("channel-split: missing %s", channel_path)
            return PreviewResult(None, "load_error")
        bsdf_dict = {
            "type": "measured_polarized",
            "filename": str(channel_path),
            "alpha_sample": _alpha_sample_for("hpbrdf_2025", channels_dir.name),
        }
        try:
            while True:
                try:
                    raw = _render_single_channel_to_array(
                        bsdf_dict, variant=variant, spp=spp, size=size, object_id=object_id,
                        bench_label=f"channel/{material_id}/{wl}nm",
                    )
                    break
                except Exception as exc:
                    fallback = None if fallback_tried else _pick_fallback_variant_after_failure("spectral_polarized", variant, exc)
                    if fallback is None:
                        raise
                    fallback_tried = True
                    logger.warning(
                        "channel-split falling back after %s failed (%s @ %d nm): %s -> %s",
                        variant, channels_dir.name, wl, exc, fallback,
                    )
                    variant = fallback
        except Exception as exc:
            logger.warning("channel-split render failed (%s @ %d nm): %s",
                            channels_dir.name, wl, exc)
            if _is_optix_unavailable_error(str(exc)):
                return PreviewResult(None, "optix_unavailable")
            return PreviewResult(None, "load_error")
        if raw.ndim != 3 or raw.shape[2] < 4:
            logger.warning("channel-split: unexpected raw shape %s for %d nm",
                            raw.shape, wl)
            return PreviewResult(None, "load_error")
        rgba_per_wavelength[wl] = raw
        if progress_cb is not None:
            try:
                progress_cb(idx + 1, n)
            except Exception:
                pass

    # Build the alpha mask once — sphere geometry is identical across
    # channels, so any channel's alpha is fine. Use the first.
    first = rgba_per_wavelength[wavelengths_to_render[0]]
    alpha = first[:, :, 3:4]

    # Reduce per-channel RGBA → per-channel scalar intensity. Mitsuba's
    # spectral_polarized variant uses spectral upsampling internally; for a
    # .pbrdf that contains only a single λ band, the camera spectral
    # response is what binds the rendered RGB to that wavelength.
    # Empirically the most stable per-pixel intensity proxy is the mean of
    # the RGB channels (luminance is also valid; mean is simpler and
    # numerically equivalent for narrowband input).
    intensity_per_wavelength: dict[int, np.ndarray] = {
        wl: rgba[:, :, :3].mean(axis=-1) for wl, rgba in rgba_per_wavelength.items()
    }

    # Composite based on mode.
    if mode == "rgbnir":
        if set(intensity_per_wavelength.keys()) != set(RGBNIR_DEFAULT):
            logger.warning(
                "channel-split rgbnir mode requires %s; got %s",
                RGBNIR_DEFAULT, sorted(intensity_per_wavelength.keys()),
            )
            return PreviewResult(None, "load_error")
        # (H, W, 4) [R, G, B, NIR] linear-light. Drop NIR for the visible
        # display path; keep the array in case downstream wants it.
        composite_rgbnir = stack_rgbnir_to_image(
            intensity_per_wavelength, RGBNIR_BAND_ASSIGNMENT,
        )
        rgb_linear = composite_rgbnir[:, :, :3]
    else:
        # CIE composite from spectral stack.
        wls_sorted = sorted(intensity_per_wavelength.keys())
        spectrum = np.stack(
            [intensity_per_wavelength[w] for w in wls_sorted], axis=-1,
        )  # (H, W, N)
        rgb_linear = spectrum_to_srgb(spectrum, wls_sorted)

    # Reinhard tone map + gamma + alpha composite over project bg colour.
    rgb_linear = np.maximum(rgb_linear, 0.0)
    rgb_tonemapped = rgb_linear / (1.0 + rgb_linear * 0.55)
    rgb_gamma = np.power(rgb_tonemapped, 1.0 / 2.2)
    rgb_u8 = np.clip(rgb_gamma * 255.0, 0, 255).astype(np.uint8)
    alpha_u8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    rgba = np.concatenate([rgb_u8, alpha_u8], axis=-1)

    # Phase 9: per-material directory layout. Persist the composite PLUS
    # one grayscale PNG per wavelength + a manifest. Each entry is
    # discoverable by the daemon's modalities endpoint without re-rendering.
    band_dir = material_band_dir(material_id, cache_dir, object_id=object_id)
    band_dir.mkdir(parents=True, exist_ok=True)

    composite_in_dir = material_band_composite_path(
        material_id, cache_dir, size=size, object_id=object_id,
    )
    Image.fromarray(rgba, mode="RGBA").save(str(composite_in_dir))

    # RGB composite drops NIR (line 911 strips the 4th channel before
    # tonemapping), so the primary "RGB" view here is visible-only. NIR
    # has its own primary entry pointing at the 854 nm band PNG (added
    # below after the band loop has written it). User-facing intent: show
    # RGB and NIR as two distinct previews, not a fused 4-channel image.
    entries: list[dict[str, Any]] = [
        {
            "kind": "composite",
            "label": "RGB" if mode == "rgbnir" else f"composite ({mode})",
            "file": composite_in_dir.name,
            "group": "composite",
        },
    ]
    nir_band_filename: str | None = None
    for wl in wavelengths_to_render:
        band_intensity = intensity_per_wavelength.get(wl)
        if band_intensity is None:
            continue
        band_path = material_band_png_path(
            material_id, cache_dir, wavelength_nm=wl, size=size, object_id=object_id,
        )
        band_rgba = _tonemap_intensity_to_rgba_u8(band_intensity, alpha)
        Image.fromarray(band_rgba, mode="RGBA").save(str(band_path))
        is_nir = wl >= 800
        entries.append({
            "kind": "band",
            "label": f"{wl} nm (NIR)" if is_nir else f"{wl} nm",
            "file": band_path.name,
            "group": "spectral",
            "wavelength_nm": wl,
            "is_nir": is_nir,
        })
        if is_nir and nir_band_filename is None:
            nir_band_filename = band_path.name

    # Surface NIR as a top-level primary view (composite group) — same PNG
    # file as the band entry, just promoted so the UI's "RGB / NIR" toggle
    # has a stable target. Keeping the spectral band entry as well so the
    # full per-wavelength grid stays complete.
    if mode == "rgbnir" and nir_band_filename is not None:
        entries.insert(1, {
            "kind": "composite",
            "label": "NIR",
            "file": nir_band_filename,
            "group": "composite",
            "is_nir": True,
        })

    _write_modality_manifest(
        band_dir, material_id, mode=mode, size=size,
        source_dir=channels_dir, entries=entries,
    )

    # Backward-compat duplicate write to legacy flat path so older daemons
    # / direct disk readers that don't know about the directory layout
    # still find the composite. New peek_channel_split_preview prefers
    # the directory.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(str(out_path))
    logger.info("channel-split preview saved: %s (%d wavelengths, mode=%s)",
                composite_in_dir, n, mode)
    return PreviewResult(composite_in_dir, "ok")


def get_channel_split_preview(
    material_id: str,
    channels_dir: Path,
    cache_dir: Path,
    *,
    mode: str = "rgbnir",
    wavelengths: list[int] | None = None,
    spp: int = 256,
    size: int = 192,
    progress_cb: Any = None,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> "PreviewResult":
    """Public entry point: cached PNG path for a channel-split material,
    rendering on demand. Cache key includes the mode + object_id so
    RGB+NIR / visible / hyperspectral and sphere / mesh variants don't
    clobber each other.
    """
    object_id = resolve_preview_object(object_id)
    new_path = material_band_composite_path(material_id, cache_dir, size=size, object_id=object_id)
    legacy_path = channel_split_cache_path(
        material_id, cache_dir, mode=mode, size=size, object_id=object_id,
    )
    if new_path.exists():
        return PreviewResult(new_path, "ok")
    if legacy_path.exists():
        return PreviewResult(legacy_path, "ok")

    if wavelengths is None:
        wavelengths = list(RGBNIR_DEFAULT) if mode == "rgbnir" else None
        if wavelengths is None:
            # `visible` / `hyperspectral` modes require explicit wavelength
            # list from the caller (Phase 3 will plug in canonical sets).
            return PreviewResult(None, "load_error")

    lock = _get_lock(f"channel_split:{material_id}:{mode}:{object_id}")
    with lock:
        if new_path.exists():
            return PreviewResult(new_path, "ok")
        if legacy_path.exists():
            return PreviewResult(legacy_path, "ok")
        return _render_channel_split(
            material_id, channels_dir, wavelengths, legacy_path, cache_dir,
            mode=mode, spp=spp, size=size, progress_cb=progress_cb,
            object_id=object_id,
        )


# ── Content-based file signature ────────────────────────────────────────────

def _content_signature(abs_file: Path) -> str:
    """Return a cheap content-based signature for cache keying.

    Hashes the first and last 4 KB plus total size — KAIST .pbsdf files are
    tens of megabytes so full hashing is wasteful, but any legitimate edit will
    change at least one of those chunks (and the size).
    """
    try:
        stat = abs_file.stat()
        with abs_file.open("rb") as f:
            head = f.read(4096)
            if stat.st_size > 8192:
                f.seek(-4096, 2)
                tail = f.read(4096)
            else:
                tail = b""
        content_hash = hashlib.sha1(head + tail).hexdigest()[:12]
        return f"{stat.st_size:x}_{content_hash}"
    except OSError:
        return "unreadable"


# ── Colored placeholder (for files that haven't been downloaded yet) ────────

def _placeholder_color(dataset_id: str, material_id: str) -> tuple[float, float, float]:
    """Deterministic RGB for a placeholder sphere.

    Wider lightness and saturation spread than the previous implementation
    so a KAIST-sized list of ~25 ids doesn't visually collapse into one hue.
    Dataset id is mixed into the hash so different datasets sit in different
    colour territories.
    """
    key = f"{dataset_id}::{material_id}"
    digest = int(hashlib.md5(key.encode()).hexdigest(), 16)
    hue = (digest * 0.6180339887) % 1.0
    sat = 0.35 + ((digest >> 32) & 0xFF) / 255.0 * 0.40           # 0.35–0.75
    lit = 0.35 + ((digest >> 16) & 0xFF) / 255.0 * 0.37           # 0.35–0.72
    r, g, b = colorsys.hls_to_rgb(hue, lit, sat)
    return r, g, b


# ── Public API ───────────────────────────────────────────────────────────────

def _bsdf_preview_base_color(bsdf_dict: dict[str, Any]) -> tuple[float, float, float]:
    for key in ("diffuse_reflectance", "reflectance", "base_color"):
        value = bsdf_dict.get(key)
        if isinstance(value, dict):
            rgb = value.get("value")
            if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
                return tuple(float(max(0.0, min(1.0, c))) for c in rgb[:3])  # type: ignore[return-value]
        elif isinstance(value, (list, tuple)) and len(value) >= 3:
            return tuple(float(max(0.0, min(1.0, c))) for c in value[:3])  # type: ignore[return-value]
    material = str(bsdf_dict.get("material", "")).lower()
    if material in {"ag", "silver"}:
        return (0.86, 0.88, 0.90)
    if material in {"al", "aluminum", "aluminium"}:
        return (0.72, 0.74, 0.76)
    if material in {"au", "gold"}:
        return (0.95, 0.70, 0.32)
    if bsdf_dict.get("type") in {"dielectric", "roughdielectric"}:
        return (0.72, 0.88, 1.0)
    return (0.62, 0.64, 0.68)


def _render_preset_software_preview(
    bsdf_type: str,
    bsdf_dict: dict[str, Any],
    out_path: Path,
    *,
    size: int,
) -> None:
    """Write a deterministic shaded PNG when Mitsuba is unavailable."""
    import numpy as np
    from PIL import Image, ImageDraw

    bsdf_kind = str(bsdf_dict.get("type", "")).lower()
    base = np.array(_bsdf_preview_base_color(bsdf_dict), dtype=np.float32)
    alpha_param = float(bsdf_dict.get("alpha", bsdf_dict.get("roughness", 0.22)) or 0.0)
    roughness = max(0.02, min(1.0, alpha_param))
    metallic = 1.0 if "conductor" in bsdf_kind else float(bsdf_dict.get("metallic", 0.0) or 0.0)
    transparent = bsdf_kind in {"dielectric", "roughdielectric"}

    ss = 3
    w = h = max(32, int(size)) * ss
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = (w - 1) * 0.50
    cy = (h - 1) * 0.48
    radius = min(w, h) * 0.37
    x = (xx - cx) / radius
    y = (yy - cy) / radius
    rr = x * x + y * y
    mask = rr <= 1.0
    z = np.sqrt(np.clip(1.0 - rr, 0.0, 1.0))

    normal = np.dstack([x, -y, z])
    light = np.array([-0.45, 0.55, 0.78], dtype=np.float32)
    light /= np.linalg.norm(light)
    view = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    half_vec = light + view
    half_vec /= np.linalg.norm(half_vec)

    ndotl = np.clip((normal * light).sum(axis=2), 0.0, 1.0)
    ndoth = np.clip((normal * half_vec).sum(axis=2), 0.0, 1.0)
    rim = np.clip(1.0 - z, 0.0, 1.0)
    diffuse = 0.22 + 0.78 * ndotl
    shininess = 16.0 + (1.0 - roughness) * 150.0
    spec = np.power(ndoth, shininess) * (0.25 + 0.65 * (1.0 - roughness) + 0.35 * metallic)

    if transparent:
        tint = base * 0.45 + np.array([0.72, 0.86, 1.0], dtype=np.float32) * 0.55
        color = tint * (0.36 + 0.32 * ndotl[..., None]) + spec[..., None] * 0.95 + rim[..., None] * 0.38
        opacity = 0.34 + rim * 0.52
        if bsdf_kind == "roughdielectric":
            color = color * 0.82 + np.array([0.84, 0.91, 0.96], dtype=np.float32) * 0.18
            opacity = np.maximum(opacity, 0.68)
    elif metallic > 0.5:
        env = np.dstack([0.52 + 0.28 * y, 0.56 + 0.24 * y, 0.62 + 0.20 * y])
        color = base * (0.28 + 0.44 * ndotl[..., None]) + env * 0.34 + spec[..., None] * 0.90
        opacity = np.ones_like(ndotl)
    else:
        color = base * diffuse[..., None] + spec[..., None] * 0.55
        opacity = np.ones_like(ndotl)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = (np.clip(color, 0.0, 1.0) ** (1.0 / 2.2) * 255.0).astype(np.uint8)
    rgba[..., 3] = np.clip(opacity * 255.0, 0, 255).astype(np.uint8)
    rgba[~mask, 3] = 0

    img = Image.fromarray(rgba, mode="RGBA").resize((size, size), Image.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")
    if bsdf_type in {"tile", "painted_wall"}:
        line_color = (100, 116, 139, 70 if bsdf_type == "tile" else 32)
        step = max(16, size // 3)
        for p in range(step, size, step):
            draw.line([(p, size * 0.18), (p, size * 0.82)], fill=line_color, width=1)
            draw.line([(size * 0.18, p), (size * 0.82, p)], fill=line_color, width=1)
    elif bsdf_type == "wood":
        for i in range(5):
            y0 = int(size * (0.35 + i * 0.065))
            draw.arc((size * 0.16, y0 - 16, size * 0.86, y0 + 24), 190, 345, fill=(80, 48, 24, 82), width=1)
    elif bsdf_type == "fabric":
        spacing = max(8, size // 12)
        for p in range(0, size, spacing):
            draw.line([(p, size * 0.20), (p + size * 0.42, size * 0.84)], fill=(255, 255, 255, 42), width=1)
            draw.line([(size - p, size * 0.20), (size - p - size * 0.42, size * 0.84)], fill=(80, 70, 95, 38), width=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))


def get_preset_preview(
    bsdf_type: str,
    cache_dir: Path,
    *,
    size: int = 128,
    spp: int = 64,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> Path | None:
    """Return the cached PNG path for a preset BSDF, rendering on demand."""
    object_id = resolve_preview_object(object_id)
    safe = bsdf_type.replace("/", "_").replace(".", "_")
    out = cache_dir / "presets" / f"{safe}_{size}_{object_id}.png"
    if out.exists():
        return out

    bsdf_dict = PRESET_BSDFS.get(bsdf_type)
    if bsdf_dict is None:
        return None

    lock = _get_lock(f"preset:{bsdf_type}:{size}:{object_id}")
    with lock:
        if out.exists():
            return out
        variant = _pick_variant_for("rgb")
        if variant is None:
            _render_preset_software_preview(bsdf_type, bsdf_dict, out, size=size)
            return out if out.exists() else None
        try:
            with _mitsuba_render_lock:
                _ensure_mitsuba_variant(variant)
                ss = _supersample_default()
                render_size = size * ss
                scene_dict = _build_scene_dict(
                    bsdf_dict, size=render_size, spp=spp, object_id=object_id,
                )
                _render_to_png(
                    scene_dict, out, variant=variant, spp=spp,
                    supersample=ss, target_size=size,
                    bench_label=f"preset/{bsdf_type}/{object_id}",
                )
        except Exception as exc:
            logger.warning("Preset preview render failed (%s): %s", bsdf_type, exc)
            try:
                _render_preset_software_preview(bsdf_type, bsdf_dict, out, size=size)
            except Exception as fallback_exc:
                logger.warning("Preset software preview failed (%s): %s", bsdf_type, fallback_exc)
                return None

    return out if out.exists() else None


def _measured_cache_paths(
    dataset_id: str,
    material_id: str,
    measured_file_path: str,
    repo_root: Path,
    cache_dir: Path,
    *,
    size: int = 128,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> tuple[Path, Path, bool]:
    """Compute (real_render_path, placeholder_path, file_present) for a measured
    material — same path computation as `get_measured_preview` so the daemon
    can peek the cache without entering the render path."""
    object_id = resolve_preview_object(object_id)
    abs_file = (repo_root / measured_file_path).resolve() if measured_file_path else None
    if abs_file is not None:
        try:
            abs_file.relative_to(repo_root.resolve())
        except ValueError:
            abs_file = None
    file_present = bool(abs_file and abs_file.exists())
    if file_present:
        file_sig = _content_signature(abs_file)
    else:
        file_sig = "missing" if measured_file_path else "nofile"
    path_hash = hashlib.sha1(measured_file_path.encode()).hexdigest()[:10] if measured_file_path else "nofile"
    safe = f"{dataset_id}__{material_id}__{path_hash}__{file_sig}".replace("/", "_").replace(".", "_")
    measured_out = cache_dir / "measured" / f"{safe}_{size}_{object_id}.png"
    placeholder_out = cache_dir / "measured" / f"{safe}__placeholder_{size}_{object_id}.png"
    return measured_out, placeholder_out, file_present


def channel_split_cache_path(
    material_id: str,
    cache_dir: Path,
    *,
    mode: str = "rgbnir",
    size: int = 192,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> Path:
    """Legacy flat cache path for a channel-split render.

    Kept for backward compat — Phase 9 added a per-material directory
    layout (see `material_band_dir` below) but we still write this flat
    file alongside so older daemons / direct disk readers don't break.
    `peek_channel_split_preview` prefers the directory layout when it
    exists.
    """
    object_id = resolve_preview_object(object_id)
    safe_id = material_id.replace("/", "_").replace(".", "_")
    return cache_dir / "channel_split" / f"{safe_id}__{mode}_{size}_{object_id}.png"


def material_band_dir(
    material_id: str, cache_dir: Path, *, object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> Path:
    """Per-material subdirectory holding the composite + per-band PNGs +
    manifest.json. New layout introduced in Phase 9.

    The object_id is appended so swapping preview geometry (sphere ↔
    bread) keeps separate sub-trees and the modality picker keeps working
    per-object.
    """
    object_id = resolve_preview_object(object_id)
    safe_id = material_id.replace("/", "_").replace(".", "_")
    return cache_dir / "channel_split" / f"{safe_id}_{object_id}"


def material_band_composite_path(
    material_id: str, cache_dir: Path, *, size: int = 192,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> Path:
    """Composite PNG path inside the per-material dir."""
    return material_band_dir(material_id, cache_dir, object_id=object_id) / f"rgb_composite_{size}.png"


def material_band_manifest_path(
    material_id: str, cache_dir: Path, *, object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> Path:
    return material_band_dir(material_id, cache_dir, object_id=object_id) / "manifest.json"


def material_band_png_path(
    material_id: str, cache_dir: Path, *, wavelength_nm: int, size: int = 192,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> Path:
    """Per-wavelength grayscale PNG path inside the per-material dir."""
    return material_band_dir(material_id, cache_dir, object_id=object_id) / f"band_{wavelength_nm}_{size}.png"


def peek_channel_split_preview(
    material_id: str,
    cache_dir: Path,
    *,
    mode: str = "rgbnir",
    size: int = 192,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> PreviewResult | None:
    """Return the cached channel-split composite PNG if it exists on
    disk, else None. Cache key now includes the object_id so a sphere
    cache hit doesn't shadow the bread render and vice versa.
    """
    object_id = resolve_preview_object(object_id)
    new_path = material_band_composite_path(material_id, cache_dir, size=size, object_id=object_id)
    if new_path.exists():
        return PreviewResult(new_path, "ok")
    legacy = channel_split_cache_path(material_id, cache_dir, mode=mode, size=size, object_id=object_id)
    if legacy.exists():
        return PreviewResult(legacy, "ok")
    return None


def _tonemap_intensity_to_rgba_u8(
    intensity_2d: "np.ndarray",   # type: ignore[name-defined]
    alpha_2d: "np.ndarray",       # type: ignore[name-defined]
) -> "np.ndarray":                # type: ignore[name-defined]
    """Convert a single-channel linear intensity (H, W) into a tone-mapped
    grayscale RGBA uint8 (H, W, 4) using the same Reinhard + gamma curve
    as the colour composite path. Output is ready to feed PIL's RGBA
    encoder. Used to persist per-band PNGs.
    """
    import numpy as np
    intensity = np.maximum(intensity_2d, 0.0)
    # Match the composite tone-map exactly so band PNGs and the composite
    # have visually consistent dynamic range.
    tonemapped = intensity / (1.0 + intensity * 0.55)
    gamma = np.power(tonemapped, 1.0 / 2.2)
    gray_u8 = np.clip(gamma * 255.0, 0, 255).astype(np.uint8)
    rgb = np.stack([gray_u8] * 3, axis=-1)
    alpha_u8 = np.clip(alpha_2d * 255.0, 0, 255).astype(np.uint8)
    if alpha_u8.ndim == 3:
        alpha_u8 = alpha_u8[..., 0:1]
    elif alpha_u8.ndim == 2:
        alpha_u8 = alpha_u8[..., None]
    return np.concatenate([rgb, alpha_u8], axis=-1)


def _write_modality_manifest(
    out_dir: Path,
    material_id: str,
    mode: str,
    size: int,
    source_dir: Path,
    entries: list[dict[str, Any]],
) -> Path:
    """Atomic write of `manifest.json` describing what's in a per-material
    cache directory. Writes to ``manifest.json.tmp`` then ``os.replace``
    so a concurrent reader (the modal grid endpoint) never sees a
    half-written file.
    """
    import datetime as _dt
    payload = {
        "schema": "modality_manifest_v1",
        "material_id": material_id,
        "mode": mode,
        "size": size,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_dir": str(source_dir),
        "entries": entries,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / "manifest.json"
    tmp = out_dir / "manifest.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    import os as _os
    _os.replace(tmp, final)
    return final


def peek_measured_preview(
    dataset_id: str,
    material_id: str,
    measured_file_path: str,
    repo_root: Path,
    cache_dir: Path,
    *,
    size: int = 128,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> PreviewResult | None:
    """Return cached PreviewResult if one exists on disk, else None.

    Cheap cache check used by the daemon to decide between serving the cached
    PNG immediately vs. enqueuing a background render and replying 202.
    """
    object_id = resolve_preview_object(object_id)
    measured_out, placeholder_out, file_present = _measured_cache_paths(
        dataset_id, material_id, measured_file_path, repo_root, cache_dir,
        size=size, object_id=object_id,
    )
    if measured_out.exists():
        return PreviewResult(measured_out, "ok")
    if placeholder_out.exists() and not file_present:
        return PreviewResult(placeholder_out, "placeholder" if measured_file_path else "not_downloaded")
    return None


def get_measured_preview(
    dataset_id: str,
    material_id: str,
    measured_file_path: str,
    repo_root: Path,
    cache_dir: Path,
    *,
    size: int = 128,
    spp: int = 384,
    object_id: str = DEFAULT_PREVIEW_OBJECT,
) -> PreviewResult:
    """Render a sphere for a measured material.

    The previous implementation silently fell back to a ``roughplastic`` BSDF
    whenever the measured plugin failed to load — which meant every KAIST
    ``.pbsdf`` preview actually showed a pink placeholder (because the build
    was configured with ``cuda_rgb``/``scalar_rgb``, not ``*_spectral_polarized``,
    and because the plugin id was ``measured`` instead of ``measured_polarized``).

    Now we dispatch by file extension and report the actual outcome via
    :class:`PreviewResult` so the daemon can surface the true cause.
    """
    if not _available_variants():
        return PreviewResult(None, "mitsuba_unavailable")

    object_id = resolve_preview_object(object_id)

    abs_file = (repo_root / measured_file_path).resolve() if measured_file_path else None
    if abs_file is not None:
        try:
            abs_file.relative_to(repo_root.resolve())
        except ValueError:
            abs_file = None

    ext = abs_file.suffix.lower() if abs_file else ""
    measured_out, placeholder_out, file_present = _measured_cache_paths(
        dataset_id, material_id, measured_file_path, repo_root, cache_dir,
        size=size, object_id=object_id,
    )

    if measured_out.exists():
        return PreviewResult(measured_out, "ok")
    if placeholder_out.exists() and not file_present:
        return PreviewResult(placeholder_out, "placeholder" if measured_file_path else "not_downloaded")

    # Decide BSDF + variant.
    # .hpbrdf uses KAIST's 68-wavelength schema; only the patched
    # measured_polarized.cpp (apply via scripts/apply_hpbrdf_patch.sh + rebuild)
    # can load it. We attempt the render here — without the patch the load
    # will fail with a parser error and surface as ``load_error``, which the
    # daemon's friendly map turns into "패치된 Mitsuba 빌드가 필요해요".
    if file_present and ext in (".pbsdf", ".hpbrdf"):
        measured_bsdf: dict[str, Any] | None = {
            "type": "measured_polarized",
            "filename": str(abs_file),
            "alpha_sample": _alpha_sample_for(dataset_id, material_id),
        }
        variant_kind = "spectral_polarized"
    elif file_present and ext == ".bsdf":
        measured_bsdf = {"type": "measured", "filename": str(abs_file)}
        variant_kind = "rgb"
    elif file_present:
        # Unknown measured format — try the generic ``measured`` plugin.
        measured_bsdf = {"type": "measured", "filename": str(abs_file)}
        variant_kind = "rgb"
    else:
        measured_bsdf = None
        variant_kind = "rgb"

    lock = _get_lock(f"measured:{dataset_id}:{material_id}:{size}:{object_id}")
    with lock:
        if measured_out.exists():
            return PreviewResult(measured_out, "ok")
        if placeholder_out.exists() and not file_present:
            return PreviewResult(placeholder_out, "placeholder" if measured_file_path else "not_downloaded")

        # Try the real measured BSDF first, if we have one.
        if measured_bsdf is not None:
            variant = _pick_variant_for(variant_kind)
            if variant is None:
                logger.warning(
                    "Measured preview %s/%s needs variant kind=%s but none available in build",
                    dataset_id, material_id, variant_kind,
                )
                return PreviewResult(None, "plugin_unavailable")
            fallback_tried = False
            try:
                while True:
                    try:
                        with _mitsuba_render_lock:
                            try:
                                _ensure_mitsuba_variant(variant)
                                ss = _supersample_default()
                                render_size = size * ss
                                scene_dict = _build_scene_dict(
                                    measured_bsdf, size=render_size, spp=spp, object_id=object_id,
                                )
                                _render_to_png(
                                    scene_dict, measured_out, variant=variant, spp=spp,
                                    supersample=ss, target_size=size,
                                    bench_label=f"measured/{dataset_id}/{material_id}/{object_id}",
                                )
                            finally:
                                # Defensive cleanup in case _render_to_png didn't reach
                                # its own finally (e.g. OOM during mi.load_dict before
                                # the scene var was bound).
                                _release_gpu_pool()
                        break
                    except Exception as exc:
                        fallback = None if fallback_tried else _pick_fallback_variant_after_failure(variant_kind, variant, exc)
                        if fallback is None:
                            raise
                        fallback_tried = True
                        logger.warning(
                            "Measured preview falling back after %s failed (%s/%s): %s -> %s",
                            variant, dataset_id, material_id, exc, fallback,
                        )
                        variant = fallback
                if measured_out.exists():
                    return PreviewResult(measured_out, "ok")
            except Exception as exc:
                msg = str(exc)
                is_oom = (
                    "out of memory" in msg.lower()
                    or "jit_malloc" in msg.lower()
                    or "could not allocate" in msg.lower()
                )
                logger.warning(
                    "Measured preview render failed (%s/%s, variant=%s): %s",
                    dataset_id, material_id, variant, msg,
                )
                if is_oom:
                    return PreviewResult(None, "gpu_oom")
                if _is_optix_unavailable_error(msg):
                    return PreviewResult(None, "optix_unavailable")
                return PreviewResult(None, "load_error")

        # File is absent or no measured_file_path given — render a deterministic
        # colored placeholder. We keep this ONLY for the "not downloaded" case,
        # so real load failures surface as ``load_error`` above.
        r, g, b = _placeholder_color(dataset_id, material_id)
        placeholder_bsdf = {
            "type": "roughplastic",
            "diffuse_reflectance": {"type": "rgb", "value": [r, g, b]},
            "alpha": 0.20,
            "int_ior": 1.49,
        }
        variant = _pick_variant_for("rgb")
        if variant is None:
            return PreviewResult(None, "mitsuba_unavailable")
        try:
            with _mitsuba_render_lock:
                _ensure_mitsuba_variant(variant)
                ss = _supersample_default()
                render_size = size * ss
                scene_dict = _build_scene_dict(
                    placeholder_bsdf, size=render_size, spp=spp, object_id=object_id,
                )
                _render_to_png(
                    scene_dict, placeholder_out, variant=variant, spp=spp,
                    supersample=ss, target_size=size,
                    bench_label=f"placeholder/{dataset_id}/{material_id}",
                )
        except Exception as exc:
            logger.warning(
                "Placeholder preview render failed (%s/%s): %s",
                dataset_id, material_id, exc,
            )
            return PreviewResult(None, "unknown")

    if placeholder_out.exists():
        return PreviewResult(placeholder_out, "placeholder" if measured_file_path else "not_downloaded")
    return PreviewResult(None, "unknown")


def invalidate_preset_cache(
    bsdf_type: str,
    cache_dir: Path,
    *,
    size: int = 128,
    object_id: str | None = None,
) -> bool:
    """Delete cached PNGs for a preset.

    ``object_id=None`` deletes every object variant (sphere + bread + …) so
    a one-shot invalidate covers all preview objects. Pass a specific
    ``object_id`` to scope to just that object's PNG.
    """
    safe = bsdf_type.replace("/", "_").replace(".", "_")
    targets: list[Path] = []
    if object_id is None:
        for oid in PREVIEW_OBJECTS.keys():
            targets.append(cache_dir / "presets" / f"{safe}_{size}_{oid}.png")
    else:
        targets.append(cache_dir / "presets" / f"{safe}_{size}_{resolve_preview_object(object_id)}.png")
    removed = False
    for t in targets:
        if t.exists():
            t.unlink()
            removed = True
    return removed
