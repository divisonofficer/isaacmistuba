"""
material_library.py — Measured BRDF dataset catalog for the Material Library UI.

Reads configs/datasets/datasets.yaml and merges it with per-dataset material
lists to produce a grouped JSON structure consumed by /api/material-library.

Groups match publication sources (논문 출처별 그룹화):
  - KAIST pBRDF  (SIGGRAPH 2020)
  - hpBRDF       (SIGGRAPH Asia 2025)
  - RGL material database
  - UTIA         (conversion target)
  - MERL         (conversion target)
  - OpenSVBRDF   (SVBRDF asset bank)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


# ---------------------------------------------------------------------------
# UI display metadata (not in datasets.yaml — purely frontend info)
# ---------------------------------------------------------------------------

DATASET_DISPLAY_META: dict[str, dict[str, Any]] = {
    "pbrdf_2020": {
        "display_name": "KAIST pBRDF",
        "paper_title": "Simultaneous Acquisition of Polarimetric SVBRDF and Normals",
        "venue": "SIGGRAPH 2020",
        "source_url": "https://vclab.kaist.ac.kr/siggraph2020/pbrdfdataset/kaistdataset.html",
        "swatch_hue": 38,   # warm gold-ish
        "mitsuba_strategy": "measured_polarized",
    },
    "hpbrdf_2025": {
        "display_name": "hpBRDF",
        "paper_title": "Hyperspectral Polarimetric BRDF Acquisition",
        "venue": "SIGGRAPH Asia 2025",
        "source_url": "https://vclab.kaist.ac.kr/siggraphasia2025p3/",
        "swatch_hue": 270,  # purple-ish
        "mitsuba_strategy": "measured_polarized",
    },
    "rgl_material_db": {
        "display_name": "RGL Material Database",
        "paper_title": "A Versatile Differentiable Rendering Framework for Material Acquisition",
        "venue": "EPFL RGL",
        "source_url": "https://rgl.epfl.ch/pages/lab/material-database",
        "swatch_hue": 160,  # teal-ish
        "mitsuba_strategy": "measured",
    },
    "utia": {
        "display_name": "UTIA BRDF Database",
        "paper_title": "UTIA BTF & BRDF Database",
        "venue": "UTIA Prague",
        "source_url": "https://btf.utia.cas.cz/?brdf_dat_dwn=",
        "swatch_hue": 30,   # orange-brown
        "mitsuba_strategy": "conversion_target",
    },
    "merl": {
        "display_name": "MERL BRDF Database",
        "paper_title": "A Data-Driven Reflectance Model",
        "venue": "SIGGRAPH 2003",
        "source_url": "https://www.merl.com/research/downloads/BRDF",
        "swatch_hue": 200,  # cool blue-gray
        "mitsuba_strategy": "conversion_target",
    },
    "opensvbrdf": {
        "display_name": "OpenSVBRDF",
        "paper_title": "OpenSVBRDF: A Large-Scale Database of Spatially Varying BRDFs",
        "venue": "SIGGRAPH Asia 2023",
        "source_url": "https://opensvbrdf.github.io/",
        "swatch_hue": 120,  # green-ish
        "mitsuba_strategy": "svbrdf_adapter",
    },
}


# ---------------------------------------------------------------------------
# Per-dataset material catalogs
# ---------------------------------------------------------------------------

# KAIST pBRDF — 25 materials (SIGGRAPH 2020 official list)
_PBRDF_2020_MATERIALS = [
    ("spectralon",        "Spectralon",        "data/pbrdf_2020/mitsuba/1_spectralon_inpainted.pbsdf"),
    ("white_billiard",    "White Billiard",    "data/pbrdf_2020/mitsuba/2_white_billiard_inpainted.pbsdf"),
    ("chrome",            "Chrome",            "data/pbrdf_2020/mitsuba/3_chrome_inpainted.pbsdf"),
    ("black_billiard",    "Black Billiard",    "data/pbrdf_2020/mitsuba/4_black_billiard_inpainted.pbsdf"),
    ("brass",             "Brass",             "data/pbrdf_2020/mitsuba/5_brass_inpainted.pbsdf"),
    ("gold",              "Gold",              "data/pbrdf_2020/mitsuba/6_gold_inpainted.pbsdf"),
    ("fake_gold",         "Fake Gold",         "data/pbrdf_2020/mitsuba/7_fake_gold_inpainted.pbsdf"),
    ("red_billiard",      "Red Billiard",      "data/pbrdf_2020/mitsuba/8_red_billiard_inpainted.pbsdf"),
    ("blue_billiard",     "Blue Billiard",     "data/pbrdf_2020/mitsuba/9_blue_billiard_inpainted.pbsdf"),
    ("green_billiard",    "Green Billiard",    "data/pbrdf_2020/mitsuba/10_green_billiard_inpainted.pbsdf"),
    ("zro2",              "ZrO2",              "data/pbrdf_2020/mitsuba/11_zro2_inpainted.pbsdf"),
    ("fake_pearl",        "Fake Pearl",        "data/pbrdf_2020/mitsuba/12_fake_pearl_inpainted.pbsdf"),
    ("yellow_silicone",   "Yellow Silicone",   "data/pbrdf_2020/mitsuba/13_yellow_silicone_inpainted.pbsdf"),
    ("ceramic_alumina",   "Ceramic Alumina",   "data/pbrdf_2020/mitsuba/14_ceramic_alumina_inpainted.pbsdf"),
    ("white_silicone",    "White Silicone",    "data/pbrdf_2020/mitsuba/15_white_silicone_inpainted.pbsdf"),
    ("pink_silicone",     "Pink Silicone",     "data/pbrdf_2020/mitsuba/16_pink_silicone_inpainted.pbsdf"),
    ("peek",              "PEEK",              "data/pbrdf_2020/mitsuba/17_peek_inpainted.pbsdf"),
    ("suj2",              "SUJ2",              "data/pbrdf_2020/mitsuba/18_suj2_inpainted.pbsdf"),
    ("mint_silicone",     "Mint Silicone",     "data/pbrdf_2020/mitsuba/19_mint_silicone_inpainted.pbsdf"),
    ("ocher_silicone",    "Ocher Silicone",    "data/pbrdf_2020/mitsuba/20_ocher_silicone_inpainted.pbsdf"),
    ("pom",               "POM",               "data/pbrdf_2020/mitsuba/21_pom_inpainted.pbsdf"),
    ("lightgreen_silicone","Lightgreen Silicone","data/pbrdf_2020/mitsuba/22_lightgreen_silicone_inpainted.pbsdf"),
    ("purple_silicone",   "Purple Silicone",   "data/pbrdf_2020/mitsuba/23_purple_silicone_inpainted.pbsdf"),
    ("blue_silicone",     "Blue Silicone",     "data/pbrdf_2020/mitsuba/24_blue_silicone_inpainted.pbsdf"),
    ("orange_silicone",   "Orange Silicone",   "data/pbrdf_2020/mitsuba/25_orange_silicone_inpainted.pbsdf"),
]

# hpBRDF — 14 materials (SIGGRAPH Asia 2025 official list)
_HPBRDF_2025_MATERIALS = [
    ("aluminum",            "Aluminum",            "data/hpbrdf_2025/raw/Aluminum.hpbrdf"),
    ("black_glass",         "Black Glass",         "data/hpbrdf_2025/raw/Black glass.hpbrdf"),
    ("black_rough_plastic", "Black Rough Plastic", "data/hpbrdf_2025/raw/Black rough plastic.hpbrdf"),
    ("fake_gold",           "Fake Gold",           "data/hpbrdf_2025/raw/Fake gold.hpbrdf"),
    ("gray_silicone",       "Gray Silicone",       "data/hpbrdf_2025/raw/Gray silicone.hpbrdf"),
    ("green_silicone",      "Green Silicone",      "data/hpbrdf_2025/raw/Green silicone.hpbrdf"),
    ("plum_rough_plastic",  "Plum Rough Plastic",  "data/hpbrdf_2025/raw/Plum rough plastic.hpbrdf"),
    ("red_rough_plastic",   "Red Rough Plastic",   "data/hpbrdf_2025/raw/Red rough plastic.hpbrdf"),
    ("suj2",                "SUJ2",                "data/hpbrdf_2025/raw/SUJ2.hpbrdf"),
    ("silver_rough_plastic","Silver Rough Plastic","data/hpbrdf_2025/raw/Silver rough plastic.hpbrdf"),
    ("white_billiard",      "White Billiard",      "data/hpbrdf_2025/raw/White billiard.hpbrdf"),
    ("white_rough_plastic", "White Rough Plastic", "data/hpbrdf_2025/raw/White rough plastic.hpbrdf"),
    ("white_smooth_plastic","White Smooth Plastic","data/hpbrdf_2025/raw/White smooth plastic.hpbrdf"),
    ("yellow_rough_plastic","Yellow Rough Plastic","data/hpbrdf_2025/raw/Yellow rough plastic.hpbrdf"),
]

# RGL — dynamically scanned from data/rgl_bsdf/spec/ at runtime.
# Empty here; get_library_grouped() fills it by scanning the filesystem.
_RGL_MATERIALS: list[tuple[str, str, str]] = []

# UTIA / MERL / OpenSVBRDF — conversion targets, empty catalogs for now.
_UTIA_MATERIALS: list[tuple[str, str, str]] = []
_MERL_MATERIALS: list[tuple[str, str, str]] = []
_OPENSVBRDF_MATERIALS: list[tuple[str, str, str]] = []

MATERIAL_CATALOG: dict[str, list[tuple[str, str, str]]] = {
    "pbrdf_2020":    _PBRDF_2020_MATERIALS,
    "hpbrdf_2025":   _HPBRDF_2025_MATERIALS,
    "rgl_material_db": _RGL_MATERIALS,
    "utia":          _UTIA_MATERIALS,
    "merl":          _MERL_MATERIALS,
    "opensvbrdf":    _OPENSVBRDF_MATERIALS,
}

# Preferred order for UI display
DATASET_ORDER = [
    "pbrdf_2020",
    "hpbrdf_2025",
    "rgl_material_db",
    "utia",
    "merl",
    "opensvbrdf",
]


# ---------------------------------------------------------------------------
# Helper: load datasets.yaml
# ---------------------------------------------------------------------------

def load_dataset_config(repo_root: Path) -> list[dict[str, Any]]:
    """Read configs/datasets/datasets.yaml and return the datasets list."""
    cfg_path = repo_root / "configs" / "datasets" / "datasets.yaml"
    if not cfg_path.exists():
        return []
    if yaml is None:
        raise ImportError("PyYAML is required for material_library: pip install pyyaml")
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("datasets", [])


def _dataset_config_by_id(configs: list[dict]) -> dict[str, dict]:
    return {d["id"]: d for d in configs}


# ---------------------------------------------------------------------------
# Helper: material status check
# ---------------------------------------------------------------------------

def _material_status(repo_root: Path, native_file: str, requires_patch: bool) -> str:
    """
    Returns one of:
      'available'       — file exists on disk
      'needs_patch'     — dataset requires Mitsuba patch (hpBRDF) but file also exists
      'not_downloaded'  — file does not exist
    """
    if not native_file:
        return "not_downloaded"
    abs_path = repo_root / native_file
    if abs_path.exists():
        return "needs_patch" if requires_patch else "available"
    return "not_downloaded"


# ---------------------------------------------------------------------------
# Helper: scan RGL spec directory
# ---------------------------------------------------------------------------

def _scan_rgl_materials(repo_root: Path) -> list[tuple[str, str, str]]:
    """Walk data/rgl_bsdf/spec/ and collect *_spec.bsdf files."""
    spec_dir = repo_root / "data" / "rgl_bsdf" / "spec"
    if not spec_dir.is_dir():
        return []
    results = []
    for bsdf_file in sorted(spec_dir.glob("**/*_spec.bsdf")):
        # material_id = filename stem without _spec suffix
        stem = bsdf_file.stem  # e.g. "cc_northern_aurora_spec"
        mat_id = stem[:-5] if stem.endswith("_spec") else stem
        display = mat_id.replace("_", " ").title()
        native = str(bsdf_file.relative_to(repo_root)).replace("\\", "/")
        results.append((mat_id, display, native))
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_library_grouped(repo_root: Path) -> list[dict[str, Any]]:
    """
    Return the material library as a list of dataset groups, each with:
      dataset_id, display_name, paper_title, venue, source_url,
      swatch_hue, mitsuba_strategy, patch_required,
      capabilities: {polarization, nir, spectral_range_nm},
      materials: [{material_id, display_name, native_file, status}, ...]
    """
    configs = load_dataset_config(repo_root)
    cfg_by_id = _dataset_config_by_id(configs)

    # Refresh dynamic datasets
    MATERIAL_CATALOG["rgl_material_db"] = _scan_rgl_materials(repo_root)

    groups: list[dict[str, Any]] = []

    for ds_id in DATASET_ORDER:
        display_meta = DATASET_DISPLAY_META.get(ds_id, {})
        cfg = cfg_by_id.get(ds_id, {})

        polarization = cfg.get("polarization", "none_measured")
        has_polarization = polarization == "full_mueller"
        spectral_range = cfg.get("spectral_range_nm", [400, 700])
        nir = spectral_range[1] >= 800 if spectral_range else False
        requires_patch = cfg.get("requires_patch", False)

        raw_materials = MATERIAL_CATALOG.get(ds_id, [])
        materials_out: list[dict[str, Any]] = []
        for (mat_id, mat_name, native_file) in raw_materials:
            status = _material_status(repo_root, native_file, requires_patch)
            materials_out.append({
                "material_id": mat_id,
                "display_name": mat_name,
                "native_file": native_file,
                "status": status,
            })

        group: dict[str, Any] = {
            "dataset_id": ds_id,
            "display_name": display_meta.get("display_name", ds_id),
            "paper_title": display_meta.get("paper_title", ""),
            "venue": display_meta.get("venue", ""),
            "source_url": display_meta.get("source_url", ""),
            "swatch_hue": display_meta.get("swatch_hue", 200),
            "mitsuba_strategy": display_meta.get(
                "mitsuba_strategy", cfg.get("kind", "unknown")
            ),
            "patch_required": requires_patch,
            "capabilities": {
                "polarization": has_polarization,
                "nir": nir,
                "spectral_range_nm": spectral_range,
            },
            "materials": materials_out,
        }
        groups.append(group)

    return groups
