from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


JsonDict = dict[str, Any]


OFFICE_TAXONOMY: dict[str, tuple[str, ...]] = {
    "shell": ("wall", "floor", "ceiling", "corridor"),
    "glass_partition": ("glass", "transparent", "partition", "window", "glazing"),
    "door": ("door",),
    "desk": ("desk", "workstation", "office table", "liteoffice table"),
    "office_chair": ("office chair", "chair", "seat", "stool", "armchair"),
    "monitor_computer": ("monitor", "computer", "screen", "bigscreen", "keyboard", "mouse", "calculator"),
    "keyboard_mouse": ("keyboard", "mouse"),
    "printer_copier": ("printer", "copier", "scanner"),
    "storage": ("cabinet", "shelf", "drawer", "locker", "bookcase", "bookshelf", "sideboard"),
    "ceiling_light": ("ceiling light", "chandelier", "lamp", "fixture", "led", "nightlight"),
    "fire_safety": ("fire extinguisher", "extinguisher", "fire alarm", "firealarm"),
    "decor_plant": ("plant", "planter", "palm", "vase", "rug", "books", "centerpiece"),
    "reflective_surface": ("mirror", "metal", "chrome", "aluminum", "brass", "polished", "stone", "glass"),
}

REQUIRED_OFFICE_CATEGORIES = {
    "shell",
    "glass_partition",
    "door",
    "desk",
    "office_chair",
    "monitor_computer",
    "printer_copier",
    "storage",
    "ceiling_light",
    "fire_safety",
    "reflective_surface",
}

_MATERIAL_KEYS = {"material", "materials", "material_hint", "composition"}


@dataclass(frozen=True)
class OfficeAssetCandidate:
    asset_id: str
    label: str
    source: str
    status: str
    categories: list[str] = field(default_factory=list)
    source_ref: str | None = None
    material_hint: str | None = None
    metadata_ref: str | None = None
    license_ref: str | None = None

    def to_payload(self) -> JsonDict:
        return asdict(self)


def classify_office_asset_text(*parts: object) -> list[str]:
    text = " ".join(str(part or "") for part in parts).lower()
    categories = [
        category
        for category, tokens in OFFICE_TAXONOMY.items()
        if any(token in text for token in tokens)
    ]
    return categories


def default_office_material_hint(category: str, label: str = "") -> str | None:
    key = f"{category} {label}".lower()
    if category in {"glass", "glass_partition"} or "glass" in key:
        return "clear_glass"
    if category in {"mirror", "reflective_surface"} or "mirror" in key:
        return "mirror"
    if "metal" in key or "chrome" in key or "aluminum" in key:
        return "pbrdf_2020:chrome"
    if "stone" in key or "tile" in key:
        return "tile"
    if category in {"furniture", "desk", "storage"} or any(token in key for token in ("desk", "table", "cabinet", "shelf", "sideboard")):
        return "pbrdf_2020:peek"
    if category == "office_chair" or "chair" in key or "seat" in key:
        return "hpbrdf_2025:black_rough_plastic"
    if category in {"electronics", "monitor_computer", "keyboard_mouse"} or any(token in key for token in ("keyboard", "mouse", "monitor", "screen", "computer")):
        return "pbrdf_2020:black_billiard"
    if category in {"ceiling_light", "lighting"} or "lamp" in key or "light" in key:
        return "pbrdf_2020:brass"
    if category == "fire_safety" or "fire" in key:
        return "pbrdf_2020:red_billiard"
    return None


def build_office_asset_coverage(repo_root: str | Path) -> JsonDict:
    root = Path(repo_root)
    candidates = [
        *_scan_builtin_assets(root),
        *_scan_asset_library(root),
        *_scan_local_dtc(root),
        *_scan_dtc_download_index(root),
    ]
    candidates = _dedupe_candidates(candidates)
    summary: dict[str, JsonDict] = {}
    for category in OFFICE_TAXONOMY:
        items = [candidate for candidate in candidates if category in candidate.categories]
        available = [candidate for candidate in items if candidate.status == "available"]
        download = [candidate for candidate in items if candidate.status == "download_candidate"]
        missing_material = [
            candidate
            for candidate in available
            if not candidate.material_hint and default_office_material_hint(category, candidate.label) is None
        ]
        if available:
            status = "available"
        elif download:
            status = "download_candidate"
        else:
            status = "external_needed" if category in REQUIRED_OFFICE_CATEGORIES else "optional_missing"
        summary[category] = {
            "status": status,
            "required": category in REQUIRED_OFFICE_CATEGORIES,
            "available_count": len(available),
            "download_candidate_count": len(download),
            "material_missing_count": len(missing_material),
            "examples": [candidate.to_payload() for candidate in [*available, *download][:8]],
        }
    return {
        "taxonomy": list(OFFICE_TAXONOMY),
        "summary": summary,
        "totals": {
            "candidates": len(candidates),
            "available": sum(1 for candidate in candidates if candidate.status == "available"),
            "download_candidates": sum(1 for candidate in candidates if candidate.status == "download_candidate"),
            "external_needed_categories": [
                category
                for category, item in summary.items()
                if item["required"] and item["status"] == "external_needed"
            ],
        },
        "candidates": [candidate.to_payload() for candidate in candidates],
    }


def _scan_builtin_assets(root: Path) -> list[OfficeAssetCandidate]:
    path = root / "apps" / "webui" / "src" / "lib" / "opticalnavBuiltInAssets.ts"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    candidates: list[OfficeAssetCandidate] = []
    for match in re.finditer(r"(moorelaneAsset|dtcAsset)\((.*?)\)", text, re.DOTALL):
        args = _extract_string_args(match.group(2))
        if len(args) < 5:
            continue
        asset_id, label = args[0], args[1]
        source_ref = args[2] if match.group(1) == "moorelaneAsset" else f"vendor_datasets/dtc_objects/{asset_id}/3d-asset.glb"
        material_hint = args[5] if match.group(1) == "moorelaneAsset" and len(args) > 5 else args[4] if len(args) > 4 else None
        categories = classify_office_asset_text(asset_id, label, " ".join(args))
        if categories:
            candidates.append(OfficeAssetCandidate(
                asset_id=f"builtin:{asset_id}",
                label=label,
                source="built_in",
                status="available",
                categories=categories,
                source_ref=source_ref,
                material_hint=material_hint,
            ))
    for asset_id, label, category, material_hint in (
        ("wall", "Wall", "shell", "painted_wall"),
        ("glass_wall", "Glass Wall", "glass", "clear_glass"),
        ("mirror_wall", "Mirror Wall", "mirror", "mirror"),
    ):
        candidates.append(OfficeAssetCandidate(
            asset_id=f"builtin:{asset_id}",
            label=label,
            source="built_in",
            status="available",
            categories=classify_office_asset_text(asset_id, label, category),
            material_hint=material_hint,
        ))
    return candidates


def _scan_asset_library(root: Path) -> list[OfficeAssetCandidate]:
    catalog_dir = root / "out" / "opticalnav" / "asset_library" / "catalogs"
    candidates: list[OfficeAssetCandidate] = []
    for path in sorted(catalog_dir.glob("*.json")) if catalog_dir.exists() else []:
        payload = _read_json(path)
        for asset in payload.get("assets", []) if isinstance(payload, Mapping) else []:
            if not isinstance(asset, Mapping):
                continue
            label = str(asset.get("label") or asset.get("asset_id") or "asset")
            categories = classify_office_asset_text(
                label,
                asset.get("category"),
                asset.get("source_path"),
                asset.get("source_ref"),
                " ".join(str(tag) for tag in asset.get("tags", []) or []),
            )
            if not categories:
                continue
            candidates.append(OfficeAssetCandidate(
                asset_id=str(asset.get("asset_id") or label),
                label=label,
                source="asset_library",
                status="available" if _coerce_bool(asset.get("selected"), True) else "available",
                categories=categories,
                source_ref=_maybe_str(asset.get("source_ref")),
                material_hint=_maybe_str(asset.get("material_hint")),
                metadata_ref=_maybe_str(asset.get("metadata_ref")),
                license_ref=_maybe_str(asset.get("license_ref")),
            ))
    return candidates


def _scan_local_dtc(root: Path) -> list[OfficeAssetCandidate]:
    dtc_root = root / "vendor_datasets" / "dtc_objects"
    candidates: list[OfficeAssetCandidate] = []
    for glb in sorted(dtc_root.glob("*/3d-asset.glb")) if dtc_root.exists() else []:
        metadata_path = glb.parent / "metadata.json"
        metadata = _read_json(metadata_path)
        label = _metadata_value(metadata, {"name", "object_name", "instance_name", "label", "title"}) or glb.parent.name
        material = _metadata_value(metadata, _MATERIAL_KEYS)
        metadata_text = _flatten_text(metadata)
        categories = classify_office_asset_text(glb.parent.name, label, metadata_text)
        if not categories:
            continue
        candidates.append(OfficeAssetCandidate(
            asset_id=f"local_dtc:{glb.parent.name}",
            label=str(label),
            source="local_dtc",
            status="available",
            categories=categories,
            source_ref=glb.relative_to(root).as_posix(),
            material_hint=", ".join(str(item) for item in material[:4]) if isinstance(material, list) else _maybe_str(material),
            metadata_ref=metadata_path.relative_to(root).as_posix() if metadata_path.exists() else None,
            license_ref=_first_existing_ref(root, glb.parent, ("CC_BY-SA.txt", "LICENSE", "license.txt", "License.txt")),
        ))
    return candidates


def _scan_dtc_download_index(root: Path) -> list[OfficeAssetCandidate]:
    path = root / "assets" / "dtc_object" / "DTC_objects_all_download_urls.json"
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        return []
    names = _collect_downloadable_object_names(payload)
    candidates: list[OfficeAssetCandidate] = []
    for name in sorted(names):
        categories = classify_office_asset_text(name)
        if not categories:
            continue
        candidates.append(OfficeAssetCandidate(
            asset_id=f"dtc_index:{name}",
            label=name.replace("_", " "),
            source="dtc_download_index",
            status="download_candidate",
            categories=categories,
            source_ref=f"vendor_datasets/dtc_objects/{name}/3d-asset.glb",
            material_hint=default_office_material_hint(categories[0], name),
        ))
    return candidates


def _collect_downloadable_object_names(payload: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()

    def visit(node: Any, parent_key: str | None = None) -> None:
        if isinstance(node, Mapping):
            filenames = [
                str(value.get("filename") or "")
                for value in node.values()
                if isinstance(value, Mapping) and value.get("filename")
            ]
            if parent_key and any("_3d-asset" in filename for filename in filenames):
                names.add(parent_key)
            for key, value in node.items():
                visit(value, str(key))
        elif isinstance(node, list):
            for item in node:
                visit(item, parent_key)

    visit(payload)
    return names


def _extract_string_args(text: str) -> list[str]:
    return [match.group(1) or match.group(2) for match in re.finditer(r"'([^']*)'|\"([^\"]*)\"", text)]


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _metadata_value(metadata: Any, keys: set[str]) -> Any:
    if isinstance(metadata, Mapping):
        for key, value in metadata.items():
            if str(key).lower() in keys:
                return value
        for value in metadata.values():
            found = _metadata_value(value, keys)
            if found is not None:
                return found
    elif isinstance(metadata, list):
        for value in metadata:
            found = _metadata_value(value, keys)
            if found is not None:
                return found
    return None


def _flatten_text(value: Any) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, val in item.items():
                parts.append(str(key))
                walk(val)
        elif isinstance(item, list):
            for val in item:
                walk(val)
        elif item is not None:
            parts.append(str(item))

    walk(value)
    return " ".join(parts)


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _first_existing_ref(root: Path, base: Path, names: Iterable[str]) -> str | None:
    for name in names:
        path = base / name
        if path.exists():
            return path.relative_to(root).as_posix()
    return None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "selected", "active"}
    return default


def _dedupe_candidates(candidates: Iterable[OfficeAssetCandidate]) -> list[OfficeAssetCandidate]:
    deduped: dict[tuple[str, str], OfficeAssetCandidate] = {}
    for candidate in candidates:
        key = (candidate.source_ref or candidate.asset_id, candidate.source)
        existing = deduped.get(key)
        if existing is None or (existing.status != "available" and candidate.status == "available"):
            deduped[key] = candidate
    return sorted(deduped.values(), key=lambda item: (item.status != "available", item.source, item.label))
