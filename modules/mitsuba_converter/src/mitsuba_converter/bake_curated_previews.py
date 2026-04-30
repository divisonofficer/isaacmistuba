"""bake_curated_previews.py — Render the curated material catalog to PNG.

Run from `apps/bake_curated_previews.py` (CLI wrapper). Output PNGs are written
to ``assets/material_previews/curated/{material_id}.png`` and intended to be
committed to the repo so the frontend can serve them as static thumbnails.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path

from .curated_library import (
    CuratedMaterial,
    curated_preview_path,
    list_curated_materials,
)
from .sphere_preview import (
    PREVIEW_PRESET_ID,
    _build_scene_dict,
    _mitsuba_render_lock,
    _pick_variant_for,
    _render_to_png,
    rig_hash,
)

logger = logging.getLogger(__name__)

CATALOG_VERSION = "v1.0"


def curated_meta_path(repo_root: Path, material_id: str) -> Path:
    return curated_preview_path(repo_root, material_id).with_suffix(".meta.json")


def _mitsuba_version() -> str:
    try:
        import mitsuba as mi
        return getattr(mi, "MI_VERSION", getattr(mi, "__version__", "unknown"))
    except Exception:
        return "unknown"


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_meta_sidecar(
    mat: CuratedMaterial,
    meta_path: Path,
    *,
    variant: str,
    size: int,
    spp: int,
) -> None:
    payload = {
        "material_id": mat.material_id,
        "display_name": mat.display_name,
        "category": mat.category,
        "rendered_at": _utc_now_iso(),
        "preview_preset": PREVIEW_PRESET_ID,
        "resolution": [size, size],
        "spp": spp,
        "mitsuba_variant": variant,
        "mitsuba_version": _mitsuba_version(),
        "source_version": CATALOG_VERSION,
        "rig_hash": rig_hash(),
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def bake_one(
    mat: CuratedMaterial,
    out_path: Path,
    *,
    variant: str,
    size: int,
    spp: int,
) -> None:
    import mitsuba as mi

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with _mitsuba_render_lock:
        # Variant must be set before _build_scene_dict runs because the rig
        # constructs `mi.ScalarTransform4f` instances inline.
        mi.set_variant(variant)
        scene_dict = _build_scene_dict(mat.bsdf_spec, size=size, spp=spp)
        _render_to_png(
            scene_dict, out_path, variant=variant, spp=spp,
            bench_label=f"bake/curated/{mat.material_id}",
        )
    write_meta_sidecar(
        mat,
        out_path.with_suffix(".meta.json"),
        variant=variant,
        size=size,
        spp=spp,
    )


def bake_all(
    repo_root: Path,
    *,
    size: int = 192,
    spp: int = 2048,
    force: bool = False,
    only: list[str] | None = None,
    variant: str | None = None,
) -> dict[str, str]:
    """Bake all curated materials. Returns ``{material_id: status}``.

    Status values:
      * ``"baked"`` — newly rendered
      * ``"skipped"`` — already on disk (use ``force=True`` to re-render)
      * ``"error"`` — render failed (see logs)

    ``variant`` overrides the auto-pick (use e.g. ``"scalar_rgb"`` to bypass
    GPU contention when the daemon is holding OptiX).
    """
    if variant is None:
        variant = _pick_variant_for("rgb")
    if variant is None:
        raise SystemExit(
            "No usable Mitsuba RGB variant found. "
            "Activate a Python environment with a working Mitsuba install (3.10 ABI)."
        )

    statuses: dict[str, str] = {}
    materials = list_curated_materials()
    if only:
        wanted = set(only)
        materials = [m for m in materials if m.material_id in wanted]
        missing = wanted - {m.material_id for m in materials}
        for mid in sorted(missing):
            statuses[mid] = "unknown"
            logger.warning("Unknown curated material id requested: %s", mid)

    for mat in materials:
        dest = curated_preview_path(repo_root, mat.material_id)
        if dest.exists() and not force:
            statuses[mat.material_id] = "skipped"
            print(f"[skip ] {mat.material_id}")
            continue
        try:
            bake_one(mat, dest, variant=variant, size=size, spp=spp)
            statuses[mat.material_id] = "baked"
            print(f"[bake ] {mat.material_id:<20s} -> {dest.relative_to(repo_root)}")
        except Exception as exc:
            statuses[mat.material_id] = "error"
            logger.exception("Bake failed for %s: %s", mat.material_id, exc)
            print(f"[ERROR] {mat.material_id}: {exc}")
    return statuses
