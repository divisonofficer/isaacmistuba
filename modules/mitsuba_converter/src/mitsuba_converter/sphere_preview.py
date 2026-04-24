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
import logging
import threading
from pathlib import Path
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
# one sphere can render at a time across all threads.
_mitsuba_render_lock = threading.Lock()

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


_POLARIZED_ORDER = (
    "cuda_ad_spectral_polarized",
    "llvm_ad_spectral_polarized",
    "scalar_spectral_polarized",
)

_RGB_ORDER = (
    # Spectral variants can render RGB content via spectral upsampling and are
    # preferred because the daemon's polarized build also enables spectral.
    "cuda_ad_spectral",
    "llvm_ad_spectral",
    "scalar_spectral",
    "cuda_ad_rgb",
    "llvm_ad_rgb",
    "cuda_rgb",
    "scalar_rgb",
)


def _pick_variant_for(kind: str) -> str | None:
    """Return the first available variant for the given BSDF kind.

    ``kind``:
      * ``"spectral_polarized"`` — required by the ``measured_polarized`` plugin.
      * ``"rgb"`` — any variant that can render a colour sphere.
    """
    available = set(_available_variants())
    if not available:
        return None
    order = _POLARIZED_ORDER if kind == "spectral_polarized" else _RGB_ORDER
    for v in order:
        if v in available:
            return v
    # If caller asked for spectral_polarized but none exist, that's a hard fail.
    if kind == "spectral_polarized":
        return None
    # Last-ditch for rgb: anything goes.
    for v in available:
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

def _build_scene_dict(
    bsdf_dict: dict[str, Any],
    *,
    size: int = 128,
    spp: int = 64,
    integrator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a ``mi.load_dict()``-compatible scene dict.

    The rig matches the "big soft area light + grey floor" layout that makes
    measured polarised materials (gold, billiard, ceramic) read clearly — the
    previous version had no floor and used a black env constant that swallowed
    the specular lobe entirely.
    """
    import mitsuba as mi

    look_at = mi.ScalarTransform4f.look_at(
        origin=[0.0, 0.85, 2.8],
        target=[0.0, 0.2, 0.0],
        up=[0.0, 1.0, 0.0],
    )
    # Large soft key light, top-right.
    key_xform = (
        mi.ScalarTransform4f.look_at(
            origin=[2.4, 3.6, 2.4],
            target=[0.0, 0.0, 0.0],
            up=[0.0, 1.0, 0.0],
        )
        @ mi.ScalarTransform4f.scale([3.2, 3.2, 1.0])
    )
    # Softer fill, opposite side, cooler.
    fill_xform = (
        mi.ScalarTransform4f.look_at(
            origin=[-2.8, 1.6, 2.0],
            target=[0.0, 0.2, 0.0],
            up=[0.0, 1.0, 0.0],
        )
        @ mi.ScalarTransform4f.scale([2.2, 2.2, 1.0])
    )
    # Floor under the sphere, flipped to face up.
    floor_xform = (
        mi.ScalarTransform4f.translate([0.0, -1.0, 0.0])
        @ mi.ScalarTransform4f.rotate(axis=[1.0, 0.0, 0.0], angle=-90.0)
        @ mi.ScalarTransform4f.scale([6.0, 6.0, 1.0])
    )

    return {
        "type": "scene",
        "integrator": integrator or {"type": "path", "max_depth": 8},
        "sensor": {
            "type": "perspective",
            "fov": 30,
            "to_world": look_at,
            "film": {
                "type": "hdrfilm",
                "width": size,
                "height": size,
                "rfilter": {"type": "gaussian"},
                "pixel_format": "rgb",
            },
            "sampler": {"type": "independent", "sample_count": spp},
        },
        "floor": {
            "type": "rectangle",
            "to_world": floor_xform,
            "bsdf": {
                "type": "diffuse",
                "reflectance": {"type": "rgb", "value": [0.62, 0.62, 0.64]},
            },
        },
        "key_light": {
            "type": "rectangle",
            "to_world": key_xform,
            "emitter": {
                "type": "area",
                "radiance": {"type": "rgb", "value": [16.0, 16.0, 16.0]},
            },
        },
        "fill_light": {
            "type": "rectangle",
            "to_world": fill_xform,
            "emitter": {
                "type": "area",
                "radiance": {"type": "rgb", "value": [3.5, 3.8, 4.2]},
            },
        },
        "sphere": {
            "type": "sphere",
            "radius": 0.9,
            "bsdf": bsdf_dict,
        },
    }


# ── Rendering primitives ────────────────────────────────────────────────────

def _render_to_png(
    scene_dict: dict[str, Any],
    out_path: Path,
    *,
    variant: str,
    spp: int,
) -> None:
    """Render a scene dict and write a tone-mapped PNG."""
    import mitsuba as mi
    import numpy as np
    from PIL import Image

    mi.set_variant(variant)
    scene = mi.load_dict(scene_dict)
    raw = np.array(mi.render(scene, spp=spp), dtype=np.float32)

    # Reinhard-like tone map + gamma 2.2
    raw = np.maximum(raw, 0.0)
    raw = raw / (1.0 + raw * 0.55)
    raw = np.clip(raw ** (1.0 / 2.2) * 255.0, 0, 255).astype(np.uint8)
    rgb = raw[:, :, :3] if raw.ndim == 3 and raw.shape[2] >= 3 else raw

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(str(out_path))
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
            scene_dict = _build_scene_dict(bsdf_dict, size=size, spp=spp)
            with _mitsuba_render_lock:
                _render_to_png(scene_dict, out, variant=variant, spp=spp)
        except Exception as exc:
            logger.warning("Preset preview render failed (%s): %s", bsdf_type, exc)
            return None

    return out if out.exists() else None


def get_measured_preview(
    dataset_id: str,
    material_id: str,
    measured_file_path: str,
    repo_root: Path,
    cache_dir: Path,
    *,
    size: int = 128,
    spp: int = 96,
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
                scene_dict = _build_scene_dict(measured_bsdf, size=size, spp=spp)
                with _mitsuba_render_lock:
                    _render_to_png(scene_dict, measured_out, variant=variant, spp=spp)
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
            scene_dict = _build_scene_dict(placeholder_bsdf, size=size, spp=spp)
            with _mitsuba_render_lock:
                _render_to_png(scene_dict, placeholder_out, variant=variant, spp=spp)
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
