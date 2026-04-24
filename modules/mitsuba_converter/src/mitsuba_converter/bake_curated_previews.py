"""bake_curated_previews.py — Render the curated material catalog to PNG.

Run from `apps/bake_curated_previews.py` (CLI wrapper). Output PNGs are written
to ``assets/material_previews/curated/{material_id}.png`` and intended to be
committed to the repo so the frontend can serve them as static thumbnails.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .curated_library import (
    CuratedMaterial,
    curated_preview_path,
    list_curated_materials,
)
from .sphere_preview import (
    _build_scene_dict,
    _mitsuba_render_lock,
    _pick_variant_for,
    _render_to_png,
)

logger = logging.getLogger(__name__)


def bake_one(
    mat: CuratedMaterial,
    out_path: Path,
    *,
    variant: str,
    size: int,
    spp: int,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scene_dict = _build_scene_dict(mat.bsdf_spec, size=size, spp=spp)
    with _mitsuba_render_lock:
        _render_to_png(scene_dict, out_path, variant=variant, spp=spp)


def bake_all(
    repo_root: Path,
    *,
    size: int = 192,
    spp: int = 256,
    force: bool = False,
    only: list[str] | None = None,
) -> dict[str, str]:
    """Bake all curated materials. Returns ``{material_id: status}``.

    Status values:
      * ``"baked"`` — newly rendered
      * ``"skipped"`` — already on disk (use ``force=True`` to re-render)
      * ``"error"`` — render failed (see logs)
    """
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
