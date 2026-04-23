"""sphere_preview.py — Mitsuba sphere preview renderer.

Renders a 128 × 128 (or custom size) sphere with a given BSDF and caches
the result as a PNG.  Used by render_daemon to serve
/api/material-preview/* image responses.

Rendering is done lazily on the first request; subsequent requests for the
same material are served from cache without touching Mitsuba.
"""

from __future__ import annotations

import colorsys
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global lock: Mitsuba's mi.set_variant() mutates global GPU state, so only
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


# ── Default BSDF dicts for each preset ──────────────────────────────────────
# These are Mitsuba mi.load_dict()-compatible BSDF sub-dicts.

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
        # pplastic is a patched BSDF not in stock Mitsuba scalar_rgb;
        # approximate with roughplastic for the preview sphere.
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


# ── Scene construction ───────────────────────────────────────────────────────

def _build_scene_dict(
    bsdf_dict: dict[str, Any],
    *,
    size: int = 128,
    spp: int = 64,
) -> dict[str, Any]:
    """Return a Mitsuba mi.load_dict()-compatible scene dict.

    Lighting rig:
      * key light   — large area rectangle, top-left (dominant)
      * fill light  — medium area rectangle, top-right (soft fill)
      * rim light   — small area rectangle, back-bottom (edge separation)
      * env         — constant low-level ambient

    Camera looks at the origin from slightly above, with a 30° FOV.
    """
    import mitsuba as mi  # imported lazily to allow import at module level

    look_at = mi.ScalarTransform4f.look_at(
        origin=[0.0, 0.55, 2.55],
        target=[0.0, 0.0, 0.0],
        up=[0.0, 1.0, 0.0],
    )
    key_xform = (
        mi.ScalarTransform4f.look_at(
            origin=[3.2, 4.8, 2.6],
            target=[0.0, 0.0, 0.0],
            up=[0.0, 1.0, 0.0],
        )
        @ mi.ScalarTransform4f.scale([2.8, 2.8, 1.0])
    )
    fill_xform = (
        mi.ScalarTransform4f.look_at(
            origin=[-2.4, 2.2, 2.0],
            target=[0.0, 0.0, 0.0],
            up=[0.0, 1.0, 0.0],
        )
        @ mi.ScalarTransform4f.scale([2.0, 2.0, 1.0])
    )
    rim_xform = (
        mi.ScalarTransform4f.look_at(
            origin=[-1.8, -0.6, -2.6],
            target=[0.0, 0.0, 0.0],
            up=[0.0, 1.0, 0.0],
        )
        @ mi.ScalarTransform4f.scale([1.4, 1.4, 1.0])
    )

    return {
        "type": "scene",
        "integrator": {"type": "path", "max_depth": 8},
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
        "key_light": {
            "type": "rectangle",
            "to_world": key_xform,
            "emitter": {
                "type": "area",
                "radiance": {"type": "rgb", "value": [18.0, 18.0, 18.0]},
            },
        },
        "fill_light": {
            "type": "rectangle",
            "to_world": fill_xform,
            "emitter": {
                "type": "area",
                "radiance": {"type": "rgb", "value": [4.5, 4.5, 5.0]},
            },
        },
        "rim_light": {
            "type": "rectangle",
            "to_world": rim_xform,
            "emitter": {
                "type": "area",
                "radiance": {"type": "rgb", "value": [2.5, 2.5, 3.5]},
            },
        },
        "env": {
            "type": "constant",
            "radiance": {"type": "rgb", "value": [0.09, 0.09, 0.12]},
        },
        "sphere": {
            "type": "sphere",
            "radius": 1.0,
            "bsdf": bsdf_dict,
        },
    }


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


def _pick_variant() -> str | None:
    """Return the first available Mitsuba variant suitable for preview."""
    try:
        import mitsuba as mi
        for v in ("cuda_rgb", "scalar_rgb"):
            try:
                mi.set_variant(v)
                return v
            except Exception:
                continue
    except ImportError:
        pass
    return None


def _material_color(material_id: str) -> tuple[float, float, float]:
    """Deterministic unique RGB color for a material based on its ID hash.

    Uses golden-ratio hue stepping so adjacent hashes spread across the
    colour wheel rather than clustering.
    """
    digest = int(hashlib.md5(material_id.encode()).hexdigest(), 16)
    hue = (digest * 0.6180339887) % 1.0  # golden-ratio scramble
    sat = 0.38 + (digest & 0xFF) / 255.0 * 0.22  # 0.38–0.60
    lit = 0.42 + ((digest >> 8) & 0xFF) / 255.0 * 0.12  # 0.42–0.54
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
    """Return the cached PNG path for a preset BSDF, rendering on demand.

    Returns None if Mitsuba is unavailable or the bsdf_type is unknown.
    """
    safe = bsdf_type.replace("/", "_").replace(".", "_")
    out = cache_dir / "presets" / f"{safe}_{size}.png"
    if out.exists():
        return out

    bsdf_dict = PRESET_BSDFS.get(bsdf_type)
    if bsdf_dict is None:
        return None

    lock = _get_lock(f"preset:{bsdf_type}:{size}")
    with lock:
        if out.exists():  # another thread may have rendered while we waited
            return out
        variant = _pick_variant()
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
) -> Path | None:
    """Return cached PNG for a measured material, rendering on demand.

    Always renders a sphere — even if the material file is not downloaded.
    When the file is missing or fails to load, a roughplastic with a
    deterministic per-material colour is used so every card looks distinct.
    """
    safe = f"{dataset_id}__{material_id}".replace("/", "_").replace(".", "_")
    out = cache_dir / "measured" / f"{safe}_{size}.png"
    if out.exists():
        return out

    lock = _get_lock(f"measured:{dataset_id}:{material_id}:{size}")
    with lock:
        if out.exists():
            return out
        variant = _pick_variant()
        if variant is None:
            return None

        # Build a material-specific roughplastic fallback (unique colour per ID).
        r, g, b = _material_color(material_id)
        colored_fallback: dict[str, Any] = {
            "type": "roughplastic",
            "diffuse_reflectance": {"type": "rgb", "value": [r, g, b]},
            "alpha": 0.20,
            "int_ior": 1.49,
        }

        # Try measured BSDF if file is available; always fall back to coloured roughplastic.
        abs_file = (repo_root / measured_file_path).resolve() if measured_file_path else None
        candidates: list[dict[str, Any]] = []
        if abs_file and abs_file.exists():
            candidates.append({"type": "measured", "filename": str(abs_file)})
        candidates.append(colored_fallback)

        for bsdf_dict in candidates:
            try:
                scene_dict = _build_scene_dict(bsdf_dict, size=size, spp=spp)
                with _mitsuba_render_lock:
                    _render_to_png(scene_dict, out, variant=variant, spp=spp)
                break
            except Exception as exc:
                logger.warning(
                    "Measured preview attempt failed (%s/%s): %s",
                    dataset_id,
                    material_id,
                    exc,
                )
        else:
            return None

    return out if out.exists() else None


def invalidate_preset_cache(bsdf_type: str, cache_dir: Path, *, size: int = 128) -> bool:
    """Delete cached PNG for a preset so it will be re-rendered next request."""
    safe = bsdf_type.replace("/", "_").replace(".", "_")
    out = cache_dir / "presets" / f"{safe}_{size}.png"
    if out.exists():
        out.unlink()
        return True
    return False
