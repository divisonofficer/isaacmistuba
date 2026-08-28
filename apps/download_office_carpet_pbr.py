#!/usr/bin/env python3
"""Build the hash-locked CC0 office-carpet PBR corpus.

The corpus intentionally lives beside, rather than inside,
``cc0_structural_v1``.  It is an input library for later scene assignment;
this tool does not modify any scene or material binding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA = "robomituba.ir_external_structural_pbr_registry.v1"
REGISTRY_VERSION = "cc0_office_surfaces_v1"
USER_AGENT = "robomituba-office-pbr/1.0 (research dataset builder)"


@dataclass(frozen=True)
class AssetSpec:
    identifier: str
    provider: str
    source_url: str
    archive_url: str
    archive_name: str
    physical_size_m: tuple[float, float]
    size_source: str
    description: str


ASSETS = (
    AssetSpec(
        "ambientcg_carpet_016", "ambientCG", "https://ambientcg.com/view?id=Carpet016",
        "https://acg-download.struffelproductions.com/file/ambientCG-Web/download/Carpet016_dnZavRoU/Carpet016_2K-JPG.zip",
        "Carpet016_2K-JPG.zip", (1.7, 1.7), "provider_published_dimensions",
        "beige wool carpet",
    ),
    AssetSpec(
        "ambientcg_carpet_011", "ambientCG", "https://ambientcg.com/view?id=Carpet011",
        "https://acg-download.struffelproductions.com/file/ambientCG-Web/download/Carpet011_mb1eM2I4/Carpet011_2K-JPG.zip",
        "Carpet011_2K-JPG.zip", (2.0, 2.0), "project_standard_repeat_size",
        "light-yellow carpet",
    ),
    AssetSpec(
        "ambientcg_fabric_022", "ambientCG", "https://ambientcg.com/view?id=Fabric022",
        "https://acg-download.struffelproductions.com/file/ambientCG-Web/download/Fabric022_ubzdJ7qK/Fabric022_2K-JPG.zip",
        "Fabric022_2K-JPG.zip", (2.0, 2.0), "project_standard_repeat_size",
        "dark-blue carpet-like fabric",
    ),
    AssetSpec(
        "texturecan_fabric_0009", "TextureCan", "https://www.texturecan.com/details/66/",
        "https://www.texturecan.com/downloads/fabric_0009/fabric_0009_2k_Exp9Lh.zip",
        "fabric_0009_2k.zip", (2.0, 2.0), "project_standard_repeat_size",
        "blue office carpet",
    ),
)

MAP_KEYS = ("base_color", "roughness", "normal_gl")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path, *, timeout: int = 300) -> None:
    """Atomically download one archive, retaining a valid prior download."""
    if destination.is_file() and destination.stat().st_size:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if not partial.stat().st_size:
            raise RuntimeError("empty archive")
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _image_member(member: str) -> bool:
    return Path(member).suffix.lower() in {".jpg", ".jpeg", ".png", ".tga", ".tif", ".tiff"}


def _map_kind(member: str) -> str | None:
    name = Path(member).stem.lower().replace("-", "_")
    if not _image_member(member) or any(token in name for token in ("preview", "thumb", "render", "displacement", "height", "ao")):
        return None
    if "rough" in name:
        return "roughness"
    if "normal" in name or "nor_gl" in name or "nor_dx" in name:
        return "normal_gl"
    if any(token in name for token in ("basecolor", "base_color", "color", "albedo", "diffuse")):
        return "base_color"
    return None


def _select_maps(archive: zipfile.ZipFile) -> dict[str, str]:
    candidates: dict[str, list[str]] = {key: [] for key in MAP_KEYS}
    for member in archive.namelist():
        kind = _map_kind(member)
        if kind:
            candidates[kind].append(member)
    selected: dict[str, str] = {}
    for key, options in candidates.items():
        if not options:
            raise ValueError(f"archive lacks required {key} map")
        # Prefer 2K named members and OpenGL normals; both providers package one
        # target set, but this makes a mixed archive deterministic.
        options.sort(key=lambda item: (
            "2k" not in item.lower(),
            key == "normal_gl" and not any(token in item.lower() for token in ("normalgl", "normal_gl", "nor_gl")),
            len(item), item.lower(),
        ))
        selected[key] = options[0]
    return selected


def _write_normal_gl(source: Path, target: Path) -> None:
    """Copy GL normals, converting an explicitly DirectX normal when needed."""
    lower = source.stem.lower()
    if not any(token in lower for token in ("normaldx", "normal_dx", "nor_dx")):
        shutil.copy2(source, target)
        return
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - only DX-only provider paths
        raise RuntimeError("Pillow is required to convert a DirectX normal map") from error
    with Image.open(source) as image:
        output_format = image.format or "PNG"
        image = image.convert("RGB")
        red, green, blue = image.split()
        green = green.point(lambda value: 255 - value)
        Image.merge("RGB", (red, green, blue)).save(target, format=output_format, quality=95)


def extract_asset(spec: AssetSpec, archive_path: Path, root: Path) -> dict[str, str]:
    """Extract exactly the required PBR maps, normalising the output names."""
    provider_dir = spec.provider.lower().replace(" ", "")
    material_dir = root / provider_dir / spec.identifier
    material_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        selected = _select_maps(archive)
        maps: dict[str, str] = {}
        for kind, member in selected.items():
            extension = Path(member).suffix.lower()
            target = material_dir / f"{kind}{extension}"
            temporary = target.with_suffix(target.suffix + ".partial")
            with archive.open(member) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if kind == "normal_gl":
                converted = target.with_suffix(target.suffix + ".converted")
                _write_normal_gl(temporary, converted)
                temporary.unlink(missing_ok=True)
                os.replace(converted, target)
            else:
                os.replace(temporary, target)
            maps[kind] = str(target.relative_to(root))
    return maps


def make_record(spec: AssetSpec, archive_path: Path, maps: dict[str, str], root: Path) -> dict[str, Any]:
    return {
        "id": spec.identifier,
        "provider": spec.provider,
        "source_url": spec.source_url,
        "source_zip": str(archive_path.relative_to(root)),
        "source_zip_url": spec.archive_url,
        "source_zip_sha256": sha256(archive_path),
        "asset_id": spec.identifier.rsplit("_", 1)[-1],
        "license": "CC0-1.0",
        "license_provenance": {
            "license_url": "https://ambientcg.com/list?type=Material" if spec.provider == "ambientCG" else "https://www.texturecan.com/terms/",
            "statement": "CC0-1.0 source asset; dataset and 3D-asset redistribution permitted.",
            "texturecan_terms_checked": spec.provider == "TextureCan",
        },
        "description": spec.description,
        "surface_family": "carpet",
        "maps": maps,
        "sha256": {kind: sha256(root / rel) for kind, rel in maps.items()},
        "physical_size_m": {"width": spec.physical_size_m[0], "height": spec.physical_size_m[1], "source": spec.size_source},
        "semantic_compatibility": ["floor", "interior_floor", "office", "room", "corridor"],
        "scale_range": [1.0, 1.0],
        "variant_contract": {
            "assignment_scope": "scene_assignment_only",
            "material_id": "recorded_per_room",
            "rotation_deg": [0, 90, 180, 270],
            "albedo_tint": "weak_scene_assignment_only",
            "roughness_offset": [-0.03, 0.03],
            "scale_policy": "physical_size_m_only_no_variant_scale",
        },
    }


def validate_registry(payload: dict[str, Any], root: Path) -> None:
    if payload.get("schema") != REGISTRY_SCHEMA or payload.get("registry_version") != REGISTRY_VERSION:
        raise ValueError("unexpected office-surface registry schema/version")
    records = payload.get("materials")
    if not isinstance(records, list) or len(records) != len(ASSETS):
        raise ValueError("office carpet registry must contain the four curated assets")
    for record in records:
        if record.get("license") != "CC0-1.0" or record.get("surface_family") != "carpet":
            raise ValueError(f"{record.get('id')}: missing CC0 carpet provenance")
        maps = record.get("maps") or {}
        for kind in MAP_KEYS:
            relative = maps.get(kind)
            path = (root / str(relative)).resolve()
            if not relative or not path.is_file() or root.resolve() not in path.parents:
                raise FileNotFoundError(f"{record.get('id')} {kind}: missing map")
            if sha256(path) != (record.get("sha256") or {}).get(kind):
                raise ValueError(f"{record.get('id')} {kind}: SHA-256 mismatch")
        size = record.get("physical_size_m") or {}
        if float(size.get("width") or 0) <= 0 or float(size.get("height") or 0) <= 0:
            raise ValueError(f"{record.get('id')}: invalid physical size")
        archive = root / str(record.get("source_zip") or "")
        if not archive.is_file() or sha256(archive) != record.get("source_zip_sha256"):
            raise ValueError(f"{record.get('id')}: source archive SHA-256 mismatch")


def build(root: Path, specs: tuple[AssetSpec, ...] = ASSETS, *, timeout: int = 300) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for spec in specs:
        provider_dir = spec.provider.lower().replace(" ", "")
        archive = root / "source_zips" / provider_dir / spec.archive_name
        download(spec.archive_url, archive, timeout=timeout)
        maps = extract_asset(spec, archive, root)
        records.append(make_record(spec, archive, maps, root))
        print(f"[asset] {spec.identifier}", flush=True)
    payload = {"schema": REGISTRY_SCHEMA, "registry_version": REGISTRY_VERSION, "materials": records}
    validate_registry(payload, root)
    registry = root / "registry.lock.json"
    temporary = registry.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, registry)
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/bean/ir_pbr_assets/cc0_office_surfaces_v1"))
    parser.add_argument("--asset", action="append", choices=[spec.identifier for spec in ASSETS])
    parser.add_argument("--verify", action="store_true", help="verify the existing registry without downloading")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.verify:
        payload = json.loads((root / "registry.lock.json").read_text(encoding="utf-8"))
        validate_registry(payload, root)
        print(f"[verified] {root / 'registry.lock.json'}")
        return
    specs = tuple(spec for spec in ASSETS if not args.asset or spec.identifier in args.asset)
    if args.dry_run:
        for spec in specs:
            print(f"[would download] {spec.identifier}: {spec.archive_url}")
        return
    if len(specs) != len(ASSETS):
        raise ValueError("a partial corpus cannot produce the locked four-asset registry")
    registry = build(root, specs, timeout=args.timeout)
    print(f"[done] materials={len(specs)} root={root} registry={registry}")


if __name__ == "__main__":
    main()
