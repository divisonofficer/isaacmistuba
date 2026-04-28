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
import threading
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

_VARIANTS_CACHE: list[str] | None = None


def _available_variants() -> list[str]:
    """Return the list of Mitsuba variants compiled into the current build."""
    global _VARIANTS_CACHE
    if _VARIANTS_CACHE is not None:
        return _VARIANTS_CACHE
    try:
        import mitsuba as mi
    except ImportError:
        _VARIANTS_CACHE = []
        return _VARIANTS_CACHE
    try:
        variants_fn = getattr(mi, "variants", None)
        if callable(variants_fn):
            _VARIANTS_CACHE = list(variants_fn())
            return _VARIANTS_CACHE
    except Exception as exc:
        logger.warning("mi.variants() call failed: %s", exc)
    # Fall back to probing a fixed list.
    probe = [
        "cuda_ad_spectral_polarized", "llvm_ad_spectral_polarized", "scalar_spectral_polarized",
        "cuda_ad_spectral", "llvm_ad_spectral", "scalar_spectral",
        "cuda_ad_rgb", "llvm_ad_rgb", "cuda_rgb", "scalar_rgb",
    ]
    found: list[str] = []
    for v in probe:
        try:
            mi.set_variant(v)
            found.append(v)
        except Exception:
            continue
    _VARIANTS_CACHE = found
    return found


# GPU-only policy: sphere previews must run on CUDA. Falling back to LLVM /
# scalar (CPU) variants makes a single 128x128 render take 30+ seconds, which
# blocks the daemon worker and looks like a hang to the user. If no CUDA
# variant is available, we return None and surface ``plugin_unavailable`` so
# the failure is explicit instead of a silent slow render.
#
# Variant priority: prefer non-AD ("cuda_rgb" / "cuda_spectral") because the
# autodiff machinery is dead weight for forward-only previews — it carries
# extra GPU memory and JIT overhead per render. AD variants stay as the
# fallback for builds that haven't enabled the leaner ones yet.
_POLARIZED_ORDER = (
    "cuda_ad_spectral_polarized",
)

_RGB_ORDER = (
    "cuda_rgb",                # NEW: lightest (no AD, RGB-only)
    "cuda_spectral",           # NEW: when spectral upsampling is needed (no AD)
    "cuda_ad_spectral",        # fallback (AD present but unused)
    "cuda_ad_rgb",
)


def _pick_variant_for(kind: str) -> str | None:
    """Return the first available CUDA variant for the given BSDF kind.

    ``kind``:
      * ``"spectral_polarized"`` — required by the ``measured_polarized`` plugin.
      * ``"rgb"`` — any CUDA variant that can render a colour sphere.

    Returns None when no suitable CUDA variant exists in the build. CPU
    variants (``scalar_*`` / ``llvm_*``) are intentionally never selected —
    falling back to CPU made previews unbearably slow.
    """
    available = set(_available_variants())
    if not available:
        return None
    order = _POLARIZED_ORDER if kind == "spectral_polarized" else _RGB_ORDER
    for v in order:
        if v in available:
            return v
    return None


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


def rig_hash() -> str:
    """Deterministic hash of the current rig spec (rig only, no BSDF).

    Used in sidecar `.meta.json` so the frontend / library can detect when a
    cached preview was rendered with a different rig and mark it stale.
    """
    blob = json.dumps(_RIG_SPEC, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha1:" + hashlib.sha1(blob).hexdigest()[:16]


def _build_scene_dict(
    bsdf_dict: dict[str, Any],
    *,
    size: int = 128,
    spp: int = 64,
    integrator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a ``mi.load_dict()``-compatible scene dict for the sphere-only rig.

    Only the sphere, key light, and constant env emitter are in the scene —
    no floor, no back wall. The film is RGBA so `_render_to_png` can
    alpha-composite the sphere over `preview_background`; pixels that miss
    the sphere come back as alpha=0 and get the off-white card colour in
    post. Means there's no contact shadow and no "white floor that doesn't
    quite match the UI" patch — just the sphere on the card colour.
    """
    import mitsuba as mi

    cam = _RIG_SPEC["camera"]
    look_at = mi.ScalarTransform4f.look_at(
        origin=cam["origin"], target=cam["target"], up=[0.0, 1.0, 0.0],
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
                # rgba so `_render_to_png` can alpha-composite the sphere
                # over solid white. Background pixels (rays that miss the
                # sphere geometry) return alpha=0 since there's no floor or
                # back wall — only the constant env emitter.
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
        "sphere": {
            "type": "sphere",
            "radius": _RIG_SPEC["sphere"]["radius"],
            "bsdf": bsdf_dict,
        },
    }


# ── Rendering primitives ────────────────────────────────────────────────────

def _ensure_mitsuba_variant(variant: str) -> None:
    """Set the Mitsuba variant in the current process.

    Must be called **before** any ``mi.ScalarTransform4f`` / ``mi.load_dict``
    access, under ``_mitsuba_render_lock`` because Mitsuba's variant state is a
    process-wide global that is not safe to flip concurrently.
    """
    import mitsuba as mi

    if getattr(mi, "variant", lambda: None)() != variant:
        mi.set_variant(variant)


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
) -> None:
    """Render a scene dict and write a sphere-only RGBA PNG.

    Render is split into ``chunks`` independent passes (different seeds) and
    averaged so we can emit progress updates between passes. ``chunks=None``
    picks a sensible value via :func:`_adaptive_chunks` based on ``spp`` —
    small renders go in a single launch (no per-chunk sync overhead), big
    ones get a few chunks for progress.

    ``supersample`` + ``target_size``: if both are >1, the scene_dict is
    assumed to be sized at ``target_size * supersample`` and the final PNG
    is downsampled to ``(target_size, target_size)`` with PIL Lanczos.
    Bigger render = better GPU saturation + sharper anti-alias.
    """
    import mitsuba as mi
    import numpy as np
    from PIL import Image

    _ensure_mitsuba_variant(variant)
    scene = mi.load_dict(scene_dict)

    n_chunks = chunks if chunks is not None else _adaptive_chunks(spp)
    n_chunks = max(1, int(n_chunks))
    chunk_spp = max(1, spp // n_chunks)
    accum = np.zeros(0, dtype=np.float32)
    for k in range(n_chunks):
        sub = np.array(mi.render(scene, spp=chunk_spp, seed=k + 1), dtype=np.float32)
        if accum.size == 0:
            accum = sub.copy()
        else:
            # Running mean: avg_{k+1} = (avg_k * k + new) / (k + 1)
            accum = (accum * k + sub) / (k + 1)
        if progress_cb is not None:
            try:
                progress_cb(k + 1, n_chunks)
            except Exception:
                pass
    raw = np.maximum(accum, 0.0)

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
    logger.info("Sphere preview saved: %s", out_path)


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

def get_preset_preview(
    bsdf_type: str,
    cache_dir: Path,
    *,
    size: int = 128,
    spp: int = 64,
) -> Path | None:
    """Return the cached PNG path for a preset BSDF, rendering on demand."""
    safe = bsdf_type.replace("/", "_").replace(".", "_")
    out = cache_dir / "presets" / f"{safe}_{size}.png"
    if out.exists():
        return out

    bsdf_dict = PRESET_BSDFS.get(bsdf_type)
    if bsdf_dict is None:
        return None

    lock = _get_lock(f"preset:{bsdf_type}:{size}")
    with lock:
        if out.exists():
            return out
        variant = _pick_variant_for("rgb")
        if variant is None:
            return None
        try:
            with _mitsuba_render_lock:
                _ensure_mitsuba_variant(variant)
                ss = _supersample_default()
                render_size = size * ss
                scene_dict = _build_scene_dict(bsdf_dict, size=render_size, spp=spp)
                _render_to_png(
                    scene_dict, out, variant=variant, spp=spp,
                    supersample=ss, target_size=size,
                )
        except Exception as exc:
            logger.warning("Preset preview render failed (%s): %s", bsdf_type, exc)
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
) -> tuple[Path, Path, bool]:
    """Compute (real_render_path, placeholder_path, file_present) for a measured
    material — same path computation as `get_measured_preview` so the daemon
    can peek the cache without entering the render path."""
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
    measured_out = cache_dir / "measured" / f"{safe}_{size}.png"
    placeholder_out = cache_dir / "measured" / f"{safe}__placeholder_{size}.png"
    return measured_out, placeholder_out, file_present


def peek_measured_preview(
    dataset_id: str,
    material_id: str,
    measured_file_path: str,
    repo_root: Path,
    cache_dir: Path,
    *,
    size: int = 128,
) -> PreviewResult | None:
    """Return cached PreviewResult if one exists on disk, else None.

    Cheap cache check used by the daemon to decide between serving the cached
    PNG immediately vs. enqueuing a background render and replying 202.
    """
    measured_out, placeholder_out, file_present = _measured_cache_paths(
        dataset_id, material_id, measured_file_path, repo_root, cache_dir, size=size
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

    abs_file = (repo_root / measured_file_path).resolve() if measured_file_path else None
    if abs_file is not None:
        try:
            abs_file.relative_to(repo_root.resolve())
        except ValueError:
            abs_file = None

    ext = abs_file.suffix.lower() if abs_file else ""
    file_present = bool(abs_file and abs_file.exists())

    if file_present:
        file_sig = _content_signature(abs_file)
    else:
        file_sig = "missing" if measured_file_path else "nofile"

    path_hash = hashlib.sha1(measured_file_path.encode()).hexdigest()[:10] if measured_file_path else "nofile"
    safe = f"{dataset_id}__{material_id}__{path_hash}__{file_sig}".replace("/", "_").replace(".", "_")
    measured_out = cache_dir / "measured" / f"{safe}_{size}.png"
    placeholder_out = cache_dir / "measured" / f"{safe}__placeholder_{size}.png"

    if measured_out.exists():
        return PreviewResult(measured_out, "ok")
    if placeholder_out.exists() and not file_present:
        return PreviewResult(placeholder_out, "placeholder" if measured_file_path else "not_downloaded")

    # Decide BSDF + variant.
    if file_present and ext == ".hpbrdf":
        # KAIST hpBRDF (.hpbrdf) uses a custom tensor schema (no theta_i field
        # etc.) that the upstream `measured` / `measured_polarized` plugins
        # cannot parse — only the patched build from third_party/hpbrdf_patch
        # supports it. Until that build is detected, fail fast with a clear
        # signal instead of throwing a parser error on every render attempt
        # and spamming the daemon log.
        logger.info(
            "Measured preview %s/%s skipped — hpBRDF needs patched Mitsuba build",
            dataset_id, material_id,
        )
        return PreviewResult(None, "plugin_unavailable")
    if file_present and ext == ".pbsdf":
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

    lock = _get_lock(f"measured:{dataset_id}:{material_id}:{size}")
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
            try:
                with _mitsuba_render_lock:
                    _ensure_mitsuba_variant(variant)
                    ss = _supersample_default()
                    render_size = size * ss
                    scene_dict = _build_scene_dict(measured_bsdf, size=render_size, spp=spp)
                    _render_to_png(
                        scene_dict, measured_out, variant=variant, spp=spp,
                        supersample=ss, target_size=size,
                    )
                if measured_out.exists():
                    return PreviewResult(measured_out, "ok")
            except Exception as exc:
                logger.warning(
                    "Measured preview render failed (%s/%s, variant=%s): %s",
                    dataset_id, material_id, variant, exc,
                )
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
                scene_dict = _build_scene_dict(placeholder_bsdf, size=render_size, spp=spp)
                _render_to_png(
                    scene_dict, placeholder_out, variant=variant, spp=spp,
                    supersample=ss, target_size=size,
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


def invalidate_preset_cache(bsdf_type: str, cache_dir: Path, *, size: int = 128) -> bool:
    """Delete cached PNG for a preset so it will be re-rendered next request."""
    safe = bsdf_type.replace("/", "_").replace(".", "_")
    out = cache_dir / "presets" / f"{safe}_{size}.png"
    if out.exists():
        out.unlink()
        return True
    return False
