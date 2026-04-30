"""Shared constants for the hpBRDF channel-split pipeline.

Maps between (a) the catalog `material_id` we expose through the daemon
and (b) the directory name KAIST uses on bean. Also defines the canonical
wavelength sets for the 3 quality tiers (RGB+NIR / visible / hyperspectral).

Single source of truth — every tool under `tools/hpbrdf/` imports from
here so the bean↔catalog name mapping never drifts. If a new material is
added to `_HPBRDF_2025_MATERIALS` in `material_library.py`, mirror it here
along with its bean dir name.
"""
from __future__ import annotations

from typing import Final

# Catalog material_id (used in URLs, daemon job keys, UI badges) →
# bean directory name under /bean_yunseong/hpbrdf/table_publish_final/.
# Verified by `ls /bean_yunseong/hpbrdf/table_publish_final/` against
# `_HPBRDF_2025_MATERIALS` in material_library.py.
#
# 주의: "plastic_pure_*" ↔ "*_rough_plastic" 매핑은 이름 자체로는 비자명.
# Phase 8 visual sample compare 에서 색이 맞는지 사용자 검증 필요.
BEAN_NAME_BY_MATERIAL_ID: Final[dict[str, str]] = {
    "aluminum":             "aluminium",
    "white_billiard":       "billiard_white",
    "fake_gold":            "fake_gold",
    "black_glass":          "glass_black",
    "black_rough_plastic":  "plastic_diffuse_black",
    "silver_rough_plastic": "plastic_diffuse_silver",
    "white_rough_plastic":  "plastic_diffuse_white",
    "plum_rough_plastic":   "plastic_pure_plum",
    "red_rough_plastic":    "plastic_pure_red",
    "yellow_rough_plastic": "plastic_pure_yellow",
    "white_smooth_plastic": "plastic_specular_white",
    "gray_silicone":        "silicon_gray",
    "green_silicone":       "silicon_green",
    "suj2":                 "suj2",
}

MATERIAL_ID_BY_BEAN_NAME: Final[dict[str, str]] = {
    v: k for k, v in BEAN_NAME_BY_MATERIAL_ID.items()
}


# Wavelength set for each quality tier. The bean dataset spans 414…950 nm
# in 8 nm steps (68 bands), so every value listed here must be in
# {414, 422, 430, ..., 950}.
RGBNIR_WAVELENGTHS: Final[tuple[int, ...]] = (446, 542, 614, 854)
"""Default — 4 bands. B/G/R/NIR mapped 1:1 to image channels (no CIE
weighting). Fastest path, ~190 MB × 4 = 764 MB read per material."""

VISIBLE_WAVELENGTHS: Final[tuple[int, ...]] = (
    414, 446, 478, 510, 542, 574, 606, 638, 670, 702,
)
"""10 bands across the visible range, used with CIE 1931 weighting for
colour-accurate previews. ~1.9 GB read per material."""

FULL_WAVELENGTHS: Final[tuple[int, ...]] = tuple(range(414, 951, 8))
"""All 68 bands in the bean dataset. Used for hyperspectral analysis;
NIR (>700 nm) channels carry no CIE-visible weight but are kept for
spectral research. ~13 GB read per material."""

assert len(FULL_WAVELENGTHS) == 68, "wavelength grid drift"


MODE_WAVELENGTHS: Final[dict[str, tuple[int, ...]]] = {
    "rgbnir":         RGBNIR_WAVELENGTHS,
    "visible":        VISIBLE_WAVELENGTHS,
    "hyperspectral":  FULL_WAVELENGTHS,
}


# Path to the bean canonical share, used as fallback / hyperspectral source.
BEAN_ROOT: Final[str] = "/bean_yunseong/hpbrdf/table_publish_final"

# Project-local mirror destination. Subdirectories use catalog
# `material_id` (NOT bean dir name) so the rest of the codebase doesn't
# have to know about the bean naming scheme.
LOCAL_CHANNELS_DIR: Final[str] = "data/hpbrdf_2025/channels"
