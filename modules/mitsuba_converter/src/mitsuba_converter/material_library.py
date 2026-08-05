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

_PBRDF_2020_BASE = "https://vclab.kaist.ac.kr/siggraph2020/pbrdfdataset"

# Hugging Face dataset repo for hpBRDF 2025 (raw .hpbrdf files, ~13 GB each).
_HPBRDF_2025_HF_REPO = "yunseongmoon/Hyperspectral-Polarimetric-BRDF"
# Approximate per-file size for the catalog UI (each .hpbrdf is ~13 GB).
_HPBRDF_2025_FILE_SIZE_BYTES = 13_000_000_000

# KAIST pBRDF — 25 materials (SIGGRAPH 2020 official list)
# Tuple: (material_id, display_name, native_file, download_zip_url)
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

# Local mirror of the channel-split hpBRDF dataset, keyed by *catalog*
# material_id (bean has different names — see tools/hpbrdf/_catalog.py
# for the bean↔catalog mapping table). Each subdirectory contains one
# `.pbrdf` file per wavelength (414…950 nm in 8-nm steps), and the
# default render tier reads only RGB+NIR (446 / 542 / 614 / 854).
#
# When a material's subdirectory exists here AND contains the requested
# wavelengths, the daemon will dispatch to the channel-split renderer
# (sphere_preview._render_channel_split, ~200 MB / channel) instead of
# loading the monolithic 13 GB .hpbrdf — which previously OOMed any
# shared GPU.
HPBRDF_2025_CHANNELS_LOCAL_SUBDIR = "data/hpbrdf_2025/channels"

# RGB+NIR default render tier — must all be present for the catalog to
# advertise the directory as ready. Mirrors `RGBNIR_WAVELENGTHS` in
# tools/hpbrdf/_catalog.py (kept inline here to avoid taking a tools/
# dependency on the package; if these drift, both must change.)
HPBRDF_2025_RGBNIR_WAVELENGTHS_NM = (446, 542, 614, 854)


def hpbrdf_channels_dir(repo_root: Path, material_id: str) -> Path | None:
    """Return the local channels dir for a catalog hpBRDF material if it
    exists AND contains all 4 RGB+NIR `.pbrdf` files, else None.

    Strict check — an empty dir (created by an aborted mirror run) does
    NOT count, otherwise the daemon would advertise the material as
    channel-split-ready and then fail at render time.
    """
    p = repo_root / HPBRDF_2025_CHANNELS_LOCAL_SUBDIR / material_id
    if not (p.exists() and p.is_dir()):
        return None
    for w in HPBRDF_2025_RGBNIR_WAVELENGTHS_NM:
        if not (p / f"{w}.pbrdf").exists():
            return None
    return p


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


def dataset_deprecation(repo_root: Path, dataset_id: str) -> dict[str, Any] | None:
    """The `deprecated:` block for a dataset, or None when it is live.

    Measured pBRDF (pbrdf_2020, hpbrdf_2025) was deleted locally on 2026-08-05
    to reclaim ~203 GB while the project runs full-analytic BSDFs. The data is
    recoverable, so a miss is not corruption - callers should surface the
    restore recipe. datasets.yaml is the single source of truth.
    """
    for entry in load_dataset_config(repo_root):
        if entry.get("id") == dataset_id:
            block = entry.get("deprecated")
            return dict(block) if isinstance(block, dict) else None
    return None


def deprecation_message(repo_root: Path, dataset_id: str) -> str | None:
    """One-line, actionable message for a deprecated dataset (None if live)."""
    block = dataset_deprecation(repo_root, dataset_id)
    if not block:
        return None
    parts = [f"dataset '{dataset_id}' is deprecated since {block.get('since', '?')}"]
    if block.get("reason"):
        parts.append(str(block["reason"]).strip())
    restore = block.get("restore_command") or block.get("restore")
    if restore:
        parts.append(f"restore: {str(restore).strip()}")
    if block.get("restore_url"):
        parts.append(str(block["restore_url"]))
    return " | ".join(parts)


def require_dataset(repo_root: Path, dataset_id: str) -> None:
    """Raise with the restore recipe when a deprecated dataset is actually used.

    Call this at the point of real consumption (loading a .pbsdf / channel
    slice), not at import time - listing materials in the UI should keep
    working and simply report them unavailable.
    """
    message = deprecation_message(repo_root, dataset_id)
    if message:
        raise FileNotFoundError(
            f"{message}\nLocal data was removed; see data/{dataset_id}/RESTORE.md"
        )


# ---------------------------------------------------------------------------
# Helper: material status check
# ---------------------------------------------------------------------------

def _material_status(
    repo_root: Path,
    native_file: str,
    requires_patch: bool,
    dataset_id: str = "",
    dataset_local_root: str | None = None,
    material_id: str = "",
) -> str:
    """
    Returns one of:
      'available'       — source data on disk and ready to render
      'needs_patch'     — file present but daemon's Mitsuba build doesn't have
                          the required plugin patch (legacy / non-hpbrdf cases)
      'not_downloaded'  — no source data on disk

    For hpBRDF (`hpbrdf_2025`): the channel-split mirror at
    `data/hpbrdf_2025/channels/{material_id}/` is treated as a first-class
    source. If it's present we report "available" (no patch warning) since:
      (a) channel-split renders use the same patched `measured_polarized`
          plugin as monolithic — the patch is a *system requirement*, not
          a per-material warning, and badging every card with "패치 필요"
          when the user has already applied it is misleading.
      (b) the legacy 13 GB monolithic `.hpbrdf` is no longer the canonical
          source — channel-split is. Reporting "not_downloaded" just because
          the user deleted the monolithic blob would be wrong.
    """
    # hpBRDF channel-split takes precedence over monolithic file probing.
    if dataset_id == "hpbrdf_2025" and material_id:
        ch = hpbrdf_channels_dir(repo_root, material_id)
        if ch is not None:
            return "available"

    if not native_file:
        return "not_downloaded"
    from .user_settings import resolve_dataset_path
    abs_path = resolve_dataset_path(repo_root, dataset_id, native_file, dataset_local_root)
    if abs_path.exists():
        return "needs_patch" if requires_patch else "available"
    return "not_downloaded"


# ---------------------------------------------------------------------------
# Helper: preview file probing (status + mtime + sidecar metadata)
# ---------------------------------------------------------------------------

def _file_mtime_iso(p: Path) -> str | None:
    try:
        ts = p.stat().st_mtime
    except OSError:
        return None
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_sidecar(meta_path: Path) -> dict | None:
    if not meta_path.exists():
        return None
    try:
        import json as _json
        return _json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _curated_preview_status(
    repo_root: Path,
    material_id: str,
    current_rig_hash: str,
) -> tuple[str, str | None, dict | None]:
    """Return (preview_status, preview_mtime, preview_meta) for a curated id.

    preview_status:
      * 'baked'  — repo PNG present, sidecar rig_hash matches current rig
      * 'stale'  — repo PNG present but sidecar rig_hash differs (or missing)
      * 'cached' — only the on-demand cache PNG exists (no committed bake)
      * 'missing' — neither baked nor cached
    """
    from .curated_library import curated_preview_path

    baked = curated_preview_path(repo_root, material_id)
    if baked.exists():
        meta = _read_sidecar(baked.with_suffix(".meta.json"))
        if meta and meta.get("rig_hash") == current_rig_hash:
            return ("baked", _file_mtime_iso(baked), meta)
        # PNG present but sidecar missing or rig changed — treat as stale.
        return ("stale", _file_mtime_iso(baked), meta)
    cache = repo_root / "out" / "material_previews" / "curated" / f"{material_id}.png"
    if cache.exists():
        return ("cached", _file_mtime_iso(cache), None)
    return ("missing", None, None)


def _measured_preview_status(
    repo_root: Path,
    dataset_id: str,
    material_id: str,
) -> tuple[str, str | None]:
    """Return (preview_status, preview_mtime) for a measured material.

    Measured previews have no committed bake; they live only in the on-demand
    cache (``out/material_previews/measured/*.png``). We glob the cache for any
    PNG whose stem contains both dataset_id and material_id.
    """
    cache_dir = repo_root / "out" / "material_previews" / "measured"
    if not cache_dir.exists():
        return ("missing", None)
    candidates = [
        p for p in cache_dir.glob("*.png")
        if dataset_id in p.stem and material_id in p.stem
    ]
    if not candidates:
        return ("missing", None)
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    return ("cached", _file_mtime_iso(newest))


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

def _build_curated_group(repo_root: Path) -> dict[str, Any]:
    """Build the synthetic 'curated' dataset group prepended to the library."""
    from .curated_library import curated_preview_path, list_curated_materials
    from .sphere_preview import rig_hash

    current_hash = rig_hash()
    materials_out: list[dict[str, Any]] = []
    for mat in list_curated_materials():
        baked = curated_preview_path(repo_root, mat.material_id)
        preview_status, preview_mtime, preview_meta = _curated_preview_status(
            repo_root, mat.material_id, current_hash,
        )
        materials_out.append({
            "material_id": mat.material_id,
            "display_name": mat.display_name,
            "native_file": "",
            "status": "available",
            "download_url": None,
            "kind": "curated",
            "category": mat.category,
            "description": mat.description,
            "preview_baked": baked.exists(),
            "preview_status": preview_status,
            "preview_mtime": preview_mtime,
            "preview_meta": preview_meta,
            "download_size_bytes": None,
        })

    group = {
        "dataset_id": "curated",
        "display_name": "큐레이션",
        "paper_title": "Robomituba Curated Library",
        "venue": "—",
        "source_url": "",
        "swatch_hue": 200,
        "mitsuba_strategy": "curated",
        "patch_required": False,
        "capabilities": {
            "polarization": False,
            "nir": False,
            "spectral_range_nm": [400, 700],
        },
        "materials": materials_out,
    }
    group["summary"] = _summarize_materials(materials_out)
    return group


def _summarize_materials(materials: list[dict[str, Any]]) -> dict[str, int]:
    """Count downloaded / preview_ok / preview_failed / errors across a list."""
    total = len(materials)
    downloaded = sum(1 for m in materials if m["status"] in ("available", "needs_patch"))
    preview_ok = sum(
        1 for m in materials
        if m.get("preview_status") in ("baked", "cached")
    )
    preview_failed = sum(
        1 for m in materials if m.get("preview_status") == "failed"
    )
    # Treat needs_patch + stale + missing-but-downloaded as "errors / 주의" so
    # the summary card has meaningful surface area.
    errors = sum(
        1 for m in materials
        if m["status"] == "needs_patch" or m.get("preview_status") == "stale"
    )
    return {
        "total": total,
        "downloaded": downloaded,
        "preview_ok": preview_ok,
        "preview_failed": preview_failed,
        "errors": errors,
    }


def _aggregate_summaries(groups: list[dict[str, Any]]) -> dict[str, int]:
    out = {"total": 0, "downloaded": 0, "preview_ok": 0, "preview_failed": 0, "errors": 0}
    for g in groups:
        s = g.get("summary") or {}
        for key in out:
            out[key] += int(s.get(key, 0))
    return out


def get_library_grouped(repo_root: Path) -> list[dict[str, Any]]:
    """
    Return the material library as a list of dataset groups, each with:
      dataset_id, display_name, paper_title, venue, source_url,
      swatch_hue, mitsuba_strategy, patch_required,
      capabilities: {polarization, nir, spectral_range_nm},
      materials: [{material_id, display_name, native_file, status}, ...]

    The synthetic ``curated`` group is prepended at index 0; its entries
    additionally carry ``kind="curated"`` plus ``category`` / ``description``
    / ``preview_baked`` for category-chip filtering and pre-baked thumbnails.
    """
    configs = load_dataset_config(repo_root)
    cfg_by_id = _dataset_config_by_id(configs)

    # Refresh dynamic datasets
    MATERIAL_CATALOG["rgl_material_db"] = _scan_rgl_materials(repo_root)

    groups: list[dict[str, Any]] = [_build_curated_group(repo_root)]

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
        dataset_local_root = cfg.get("local_root")
        for idx, (mat_id, mat_name, native_file) in enumerate(raw_materials):
            status = _material_status(
                repo_root, native_file, requires_patch,
                dataset_id=ds_id, dataset_local_root=dataset_local_root,
                material_id=mat_id,
            )
            download_url: str | None = None
            if ds_id == "pbrdf_2020":
                n = idx + 1
                download_url = f"{_PBRDF_2020_BASE}/{n}_{mat_id}_mitsuba.zip"
            elif ds_id == "hpbrdf_2025" and native_file:
                # Phase 7: monolithic 13 GB .hpbrdf is deprecated.
                # If the channel-split mirror is present we hide the HF
                # download URL entirely so the UI doesn't tempt the user
                # into a 13 GB download they don't need (and which would
                # OOM on shared GPUs anyway). When the mirror is missing
                # we still expose the URL as a recovery option.
                if hpbrdf_channels_dir(repo_root, mat_id) is None:
                    fname = Path(native_file).name
                    download_url = f"hf-dataset://{_HPBRDF_2025_HF_REPO}/{fname}"
                else:
                    download_url = None
            preview_status, preview_mtime = _measured_preview_status(repo_root, ds_id, mat_id)
            size_bytes: int | None = None
            if native_file:
                from .user_settings import resolve_dataset_path
                abs_path = resolve_dataset_path(repo_root, ds_id, native_file, dataset_local_root)
                try:
                    size_bytes = abs_path.stat().st_size
                except OSError:
                    size_bytes = None
            # Pre-download size hint for hpBRDF (each .hpbrdf is ~13 GB).
            if size_bytes is None and ds_id == "hpbrdf_2025":
                size_bytes = _HPBRDF_2025_FILE_SIZE_BYTES
            entry: dict[str, Any] = {
                "material_id": mat_id,
                "display_name": mat_name,
                "native_file": native_file,
                "status": status,
                "download_url": download_url,
                "kind": "measured",
                "preview_status": preview_status,
                "preview_mtime": preview_mtime,
                "preview_meta": None,
                "download_size_bytes": size_bytes,
            }
            # Surface the channel-split mirror state for hpBRDF entries —
            # frontend uses this to render the spectralBadge ("RGB+NIR (4ch)"
            # vs "monolithic 13 GB"). The `channels_dir` is exposed as a
            # repo-relative string so the UI can deep-link it without
            # leaking absolute filesystem paths.
            if ds_id == "hpbrdf_2025":
                ch_dir = hpbrdf_channels_dir(repo_root, mat_id)
                if ch_dir is not None:
                    entry["channels_dir"] = str(ch_dir.relative_to(repo_root))
                    entry["preview_source"] = "channel_split"
                else:
                    entry["channels_dir"] = None
                    # `status` is "available" or "needs_patch" when the
                    # monolithic .hpbrdf is on disk — both mean we *can*
                    # render via the legacy 13 GB path (just needs the
                    # patched build). Only "not_downloaded" → "missing".
                    entry["preview_source"] = (
                        "missing" if status == "not_downloaded" else "monolithic"
                    )
            materials_out.append(entry)

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
        group["summary"] = _summarize_materials(materials_out)
        groups.append(group)

    return groups


def get_library_response(repo_root: Path) -> dict[str, Any]:
    """Top-level material library payload: groups + aggregate summary.

    The daemon returns this directly from ``GET /api/material-library``. The
    summary is the union of every group's summary so the frontend's stat cards
    don't have to recompute it on every render.
    """
    groups = get_library_grouped(repo_root)
    return {
        "groups": groups,
        "summary": _aggregate_summaries(groups),
    }
