"""Profile-aware, self-contained OpticalNav export helpers.

The renderer deliberately keeps rich debug products next to an observation.
That is useful while rendering, but copying every polarization visualisation and
the fully-expanded Stokes NPZ into a training archive makes a dataset needlessly
large.  This module is intentionally renderer-independent: it repackages an
already rendered observation into a portable bundle without changing the source
scene or its render products.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable


POLAR_STOKES_CORE_SCHEMA = "opticalnav.stokes_core.v1"
POLAR_STOKES_CORE_KEYS = ("rgb", "s0", "s1", "s2", "s3", "mask")
POLAR_LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)
POLAR_PREVIEW_RECIPE = "mitsuba_converter.save_polarization_products.v1"


@dataclass(frozen=True)
class ExportProfile:
    """Immutable packaging contract exposed through the export API."""

    name: str
    split_polar_extension: bool
    include_stokes_core: bool
    include_legacy_stokes: bool
    include_polar_thumbnails: bool
    webp_lossless_rgb: bool
    include_exr: bool = False


EXPORT_PROFILES: dict[str, ExportProfile] = {
    "compact_with_polar_extension": ExportProfile(
        name="compact_with_polar_extension",
        split_polar_extension=True,
        include_stokes_core=True,
        include_legacy_stokes=False,
        include_polar_thumbnails=True,
        webp_lossless_rgb=True,
    ),
    "single_lossless_core": ExportProfile(
        name="single_lossless_core",
        split_polar_extension=False,
        include_stokes_core=True,
        include_legacy_stokes=False,
        include_polar_thumbnails=True,
        webp_lossless_rgb=True,
    ),
    "navigation_only": ExportProfile(
        name="navigation_only",
        split_polar_extension=False,
        include_stokes_core=False,
        include_legacy_stokes=False,
        include_polar_thumbnails=True,
        webp_lossless_rgb=True,
    ),
    "legacy_full": ExportProfile(
        name="legacy_full",
        split_polar_extension=False,
        include_stokes_core=False,
        include_legacy_stokes=True,
        include_polar_thumbnails=False,
        webp_lossless_rgb=False,
        include_exr=True,
    ),
}


def resolve_export_profile(value: str | None) -> ExportProfile:
    """Return an explicit profile, defaulting to the compact public contract."""
    key = str(value or "compact_with_polar_extension").strip().lower()
    try:
        return EXPORT_PROFILES[key]
    except KeyError as exc:
        allowed = ", ".join(sorted(EXPORT_PROFILES))
        raise ValueError(f"Unknown export_profile={value!r}; expected one of {allowed}") from exc


@dataclass(frozen=True)
class PlannedFile:
    src: Path
    dst: str


@dataclass
class PolarThumbnailPlan:
    dst: str
    sources: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class PolarCorePlan:
    src: Path
    dst: str


@dataclass
class CompactBundlePlan:
    profile: ExportProfile
    copied: list[PlannedFile] = field(default_factory=list)
    webp_rgb: list[PlannedFile] = field(default_factory=list)
    polar_thumbnails: list[PolarThumbnailPlan] = field(default_factory=list)
    polar_core: list[PolarCorePlan] = field(default_factory=list)
    omitted: list[PlannedFile] = field(default_factory=list)

    @property
    def source_file_count(self) -> int:
        return len(self.copied) + len(self.webp_rgb) + sum(
            len(item.sources) for item in self.polar_thumbnails
        ) + len(self.polar_core) + len(self.omitted)


def _is_polar_visual(src: Path, polar_dirs: set[Path]) -> bool:
    return src.parent.resolve() in polar_dirs and src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def _webp_destination(dst: str) -> str:
    return str(Path(dst).with_suffix(".webp")).replace("\\", "/")


def plan_compact_bundle_files(
    files: Iterable[tuple[Path, str]],
    profile: ExportProfile,
) -> CompactBundlePlan:
    """Classify resolved observation files without mutating the source tree.

    ``iter_export_files`` is retained as the one authoritative resolver for
    episode/panorama/variant selection.  This planner only decides whether each
    resolved file is copied, losslessly transcoded, represented by one polar
    thumbnail, or moved to the optional polarization extension.
    """
    entries = [PlannedFile(Path(src), str(dst).replace("\\", "/")) for src, dst in files]
    polar_dirs = {item.src.parent.resolve() for item in entries if item.src.name == "stokes_data.npz"}
    thumbnail_sources: dict[str, dict[str, Path]] = {}
    plan = CompactBundlePlan(profile=profile)

    if profile.name == "legacy_full":
        plan.copied.extend(entries)
        return plan

    for item in entries:
        src = item.src
        if src.name == "stokes_data.npz" and src.parent.resolve() in polar_dirs:
            if profile.include_stokes_core:
                plan.polar_core.append(
                    PolarCorePlan(src=src, dst=str(Path(item.dst).with_name("stokes_core_v1.npz")).replace("\\", "/"))
                )
            else:
                plan.omitted.append(item)
            continue
        if _is_polar_visual(src, polar_dirs):
            if profile.include_polar_thumbnails:
                thumb_dst = str(Path(item.dst).with_name("polar_thumbnail.webp")).replace("\\", "/")
                thumbnail_sources.setdefault(thumb_dst, {})[src.name] = src
            plan.omitted.append(item)
            continue
        if src.suffix.lower() in {".exr", ".hdr", ".npz"}:
            # Compact profiles never expose unrelated raw buffers.  Stokes is
            # handled above, where it remains available as a lossless core.
            plan.omitted.append(item)
            continue
        if profile.webp_lossless_rgb and src.name == "rgb.png":
            plan.webp_rgb.append(PlannedFile(src=src, dst=_webp_destination(item.dst)))
            continue
        plan.copied.append(item)

    plan.polar_thumbnails = [
        PolarThumbnailPlan(dst=dst, sources=sources)
        for dst, sources in sorted(thumbnail_sources.items())
    ]
    return plan


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transcode_rgb_png_to_lossless_webp(src: Path, dst: Path) -> int:
    """Write RGB pixels as lossless WebP and verify exact decode equality."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as image:
        source = image.convert("RGB")
        pixels = np.asarray(source)
        source.save(dst, "WEBP", lossless=True, method=6)
    with Image.open(dst) as written:
        restored = np.asarray(written.convert("RGB"))
    if pixels.shape != restored.shape or not np.array_equal(pixels, restored):
        raise ValueError(f"Lossless WebP verification failed for {src}")
    return dst.stat().st_size


_POLAR_THUMBNAIL_ORDER = (
    ("polar_rgb_preview.png", "Polar RGB"),
    ("dop_red_black_colorbar.png", "DoLP"),
    ("aolp_rainbow_colorbar.png", "AoLP"),
    ("s1_over_s0_bwr_colorbar.png", "S1/S0"),
    ("s2_over_s0_bwr_colorbar.png", "S2/S0"),
    ("s1_bwr_colorbar.png", "S1"),
    ("s2_bwr_colorbar.png", "S2"),
)


def write_polar_thumbnail(plan: PolarThumbnailPlan, root: Path, *, tile_width: int = 128) -> int:
    """Create one descriptive, non-canonical WebP sheet for a polar observation."""
    from PIL import Image, ImageDraw, ImageOps  # noqa: PLC0415

    selected = [(label, plan.sources[name]) for name, label in _POLAR_THUMBNAIL_ORDER if name in plan.sources]
    if not selected:
        return 0
    tile_height = max(1, round(tile_width * 0.8))
    label_height = 16
    columns = 4
    rows = (len(selected) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), (15, 23, 42))
    draw = ImageDraw.Draw(sheet)
    for index, (label, source_path) in enumerate(selected):
        with Image.open(source_path) as source:
            tile = ImageOps.contain(source.convert("RGB"), (tile_width, tile_height))
        x = (index % columns) * tile_width
        y = (index // columns) * (tile_height + label_height)
        sheet.paste(tile, (x + (tile_width - tile.width) // 2, y + (tile_height - tile.height) // 2))
        draw.text((x + 3, y + tile_height + 1), label, fill=(226, 232, 240))
    dst = root / plan.dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst, "WEBP", quality=82, method=6)
    return dst.stat().st_size


def write_stokes_core(src: Path, dst: Path) -> dict[str, Any]:
    """Repack canonical Stokes inputs without lossy dtype conversion."""
    import numpy as np  # noqa: PLC0415

    with np.load(src, allow_pickle=False) as source:
        missing = [key for key in POLAR_STOKES_CORE_KEYS if key not in source.files]
        if missing:
            raise ValueError(f"{src} lacks required Stokes arrays: {', '.join(missing)}")
        arrays = {key: np.asarray(source[key]) for key in POLAR_STOKES_CORE_KEYS}
    for key in ("rgb", "s0", "s1", "s2", "s3"):
        if arrays[key].dtype != np.float32:
            raise ValueError(f"{src} has non-float32 {key}: {arrays[key].dtype}")
    if arrays["mask"].dtype != np.bool_:
        raise ValueError(f"{src} has non-bool mask: {arrays['mask'].dtype}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, **arrays)
    with np.load(dst, allow_pickle=False) as restored:
        for key, value in arrays.items():
            check = np.asarray(restored[key])
            if (
                check.dtype != value.dtype
                or check.shape != value.shape
                or check.tobytes(order="C") != value.tobytes(order="C")
            ):
                raise ValueError(f"Stokes core byte round-trip verification failed for {src}:{key}")
    return {
        "schema": POLAR_STOKES_CORE_SCHEMA,
        "source_sha256": sha256_file(src),
        "core_sha256": sha256_file(dst),
        "bytes": dst.stat().st_size,
        "arrays": {
            key: {"dtype": str(value.dtype), "shape": list(value.shape)}
            for key, value in arrays.items()
        },
    }


def estimate_bundle_plan(plan: CompactBundlePlan) -> dict[str, Any]:
    """Return a cheap, intentionally conservative estimate before materialization.

    The breakdown is deliberately based on package destinations, not source
    bridge-job paths.  It makes base/perturbed and sensor payload growth visible
    without opening every source image or NPZ during the preflight stage.
    """
    def destination_group(dst: str) -> tuple[str, str]:
        parts = Path(dst).parts
        variant = "metadata"
        sensor = "metadata"
        for index, part in enumerate(parts):
            if part == "observations":
                variant = "base"
            elif part == "observations_perturbed":
                variant = "perturbed"
            elif part == "sensors" and index + 1 < len(parts):
                sensor = parts[index + 1]
        return variant, sensor

    def empty_group() -> dict[str, int]:
        return {
            "source_bytes": 0,
            "source_files": 0,
            "output_artifacts": 0,
            "core_estimated_bytes": 0,
            "polar_extension_estimated_bytes": 0,
        }

    by_variant: dict[str, dict[str, int]] = {}
    by_sensor: dict[str, dict[str, int]] = {}
    source_seen: set[Path] = set()

    def record(
        dst: str,
        *,
        source: Path | None = None,
        core_bytes: int = 0,
        polar_bytes: int = 0,
        artifact: bool = True,
    ) -> None:
        variant, sensor = destination_group(dst)
        groups = (
            by_variant.setdefault(variant, empty_group()),
            by_sensor.setdefault(sensor, empty_group()),
        )
        if source is not None:
            resolved = source.resolve()
            if resolved not in source_seen:
                source_seen.add(resolved)
                source_bytes = source.stat().st_size if source.is_file() else 0
                for group in groups:
                    group["source_bytes"] += source_bytes
                    group["source_files"] += 1
        for group in groups:
            group["core_estimated_bytes"] += core_bytes
            group["polar_extension_estimated_bytes"] += polar_bytes
            if artifact:
                group["output_artifacts"] += 1

    # Sampled renderer output measured for this project: lossless RGB WebP is
    # normally ~65% of PNG, and one 128px contact sheet is conservatively 40 KiB.
    for item in plan.copied:
        record(
            item.dst,
            source=item.src,
            core_bytes=item.src.stat().st_size if item.src.is_file() else 0,
        )
    for item in plan.webp_rgb:
        record(
            item.dst,
            source=item.src,
            core_bytes=int(item.src.stat().st_size * 0.70) if item.src.is_file() else 0,
        )
    for thumbnail in plan.polar_thumbnails:
        sources = list(thumbnail.sources.values())
        if sources:
            record(thumbnail.dst, source=sources[0], core_bytes=40 * 1024)
            for source in sources[1:]:
                record(thumbnail.dst, source=source, artifact=False)
        else:
            record(thumbnail.dst, core_bytes=40 * 1024)
    for item in plan.polar_core:
        raw_estimate = int(item.src.stat().st_size * (3.383 / 5.368)) if item.src.is_file() else 0
        record(
            item.dst,
            source=item.src,
            core_bytes=0 if plan.profile.split_polar_extension else raw_estimate,
            polar_bytes=raw_estimate if plan.profile.split_polar_extension else 0,
        )
    # Omitted sources are part of the legacy-size comparison, but never of the
    # new package estimate.
    for item in plan.omitted:
        record(item.dst, source=item.src, artifact=False)

    core_estimate = sum(group["core_estimated_bytes"] for group in by_variant.values())
    polar_estimate = sum(group["polar_extension_estimated_bytes"] for group in by_variant.values())
    source_bytes = sum(group["source_bytes"] for group in by_variant.values())
    return {
        "source_bytes": source_bytes,
        "legacy_selected_bytes": source_bytes,
        "core_estimated_bytes": core_estimate,
        "polar_extension_estimated_bytes": polar_estimate,
        "single_estimated_bytes": core_estimate + polar_estimate,
        "breakdown": {
            "by_variant": dict(sorted(by_variant.items())),
            "by_sensor": dict(sorted(by_sensor.items())),
        },
        "file_counts": {
            "copy": len(plan.copied),
            "webp_rgb": len(plan.webp_rgb),
            "polar_thumbnails": len(plan.polar_thumbnails),
            "polar_core": len(plan.polar_core),
            "omitted": len(plan.omitted),
        },
        "estimate_method": "conservative_profile_v2",
    }

def rewrite_observation_manifests(
    root: Path,
    *,
    profile: ExportProfile,
    source_to_exported: dict[str, str],
    polar_extension: dict[str, Any] | None = None,
) -> int:
    """Remove stale source-only artifact paths from copied observation manifests."""
    root = Path(root)
    rewritten = 0
    for manifest_path in root.rglob("manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        changed = False
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            original = artifact.get("artifact_paths")
            if not isinstance(original, dict):
                continue
            exported: dict[str, Any] = {}
            for key, value in original.items():
                if not isinstance(value, str):
                    continue
                mapped = source_to_exported.get(value)
                if mapped is None:
                    continue
                if mapped.endswith("polar_thumbnail.webp"):
                    exported["polar_thumbnail"] = mapped
                else:
                    exported["webp" if mapped.endswith(".webp") else key] = mapped
            if any(key == "stokes_npz" for key in original):
                if profile.include_stokes_core and not profile.split_polar_extension:
                    original_core = original.get("stokes_npz")
                    core = source_to_exported.get(original_core) if isinstance(original_core, str) else None
                    if core:
                        exported["stokes_core_v1"] = core
                elif profile.include_stokes_core and polar_extension is not None:
                    artifact["polarization_extension"] = polar_extension
                elif profile.include_polar_thumbnails:
                    original_png = original.get("png")
                    thumb = source_to_exported.get(original_png) if isinstance(original_png, str) else None
                    if thumb:
                        exported["polar_thumbnail"] = thumb
            artifact["artifact_paths"] = exported
            artifact["export_profile"] = profile.name
            changed = True
        if changed:
            payload["bundle_export"] = {
                "profile": profile.name,
                "polar_stokes_schema": POLAR_STOKES_CORE_SCHEMA if profile.include_stokes_core else None,
                "preview_recipe": POLAR_PREVIEW_RECIPE if profile.include_polar_thumbnails else None,
            }
            manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            rewritten += 1
    return rewritten


def build_perturbation_pair_index(destinations: Iterable[str]) -> dict[str, Any]:
    """Describe matched and unpaired base/perturbed observations explicitly."""
    base: set[tuple[str, str, str]] = set()
    perturbed: set[tuple[str, str, str]] = set()
    for dst in destinations:
        parts = Path(dst).parts
        if len(parts) < 6 or parts[0] != "scenes":
            continue
        if parts[2] not in {"observations", "observations_perturbed"}:
            continue
        key = (parts[1], parts[3], parts[4])
        (perturbed if parts[2] == "observations_perturbed" else base).add(key)
    paired = sorted(base & perturbed)
    return {
        "schema": "opticalnav.perturbation_pairs.v1",
        "pair_count": len(paired),
        "pairs": [
            {
                "scene_id": scene_id,
                "vp_id": vp_id,
                "heading_id": heading_id,
                "base_ref": f"scenes/{scene_id}/observations/{vp_id}/{heading_id}",
                "perturbed_ref": f"scenes/{scene_id}/observations_perturbed/{vp_id}/{heading_id}",
            }
            for scene_id, vp_id, heading_id in paired
        ],
        "unpaired_base": [
            {"scene_id": scene_id, "vp_id": vp_id, "heading_id": heading_id}
            for scene_id, vp_id, heading_id in sorted(base - perturbed)
        ],
        "unpaired_perturbed": [
            {"scene_id": scene_id, "vp_id": vp_id, "heading_id": heading_id}
            for scene_id, vp_id, heading_id in sorted(perturbed - base)
        ],
    }
