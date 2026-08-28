"""TextureCan 2K PBR staging and human-reviewed structural registry helpers.

The staging corpus intentionally is *not* a render registry.  It preserves all
downloaded source bundles while the reviewer removes only role-specific preview
tokens.  A separate finalizer creates the small immutable registry consumed by
the structural rematerializer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse

import cv2
import numpy as np


STAGING_SCHEMA = "robomituba.texturecan_pbr_staging.v1"
STAGING_VERSION = "texturecan_staging_v1"
REVIEW_SCHEMA = "robomituba.texturecan_pbr_review.v1"
FINALIZATION_SCHEMA = "robomituba.texturecan_pbr_finalization.v1"
SECOND_PASS_SCHEMA = "robomituba.texturecan_pbr_second_pass.v1"
EXTENDED_PROFILE_SCHEMA = "robomituba.texturecan_pbr_extended_profile.v1"
REGISTRY_SCHEMA = "robomituba.ir_external_structural_pbr_registry.v1"
REGISTRY_VERSION = "texturecan_structural_v1"
SCALE_OVERRIDES_SCHEMA = "robomituba.texturecan_pbr_scale_overrides.v1"
TERMS_URL = "https://www.texturecan.com/terms/"
BASE_URL = "https://www.texturecan.com/"
USER_AGENT = "robomituba-texturecan-pbr/1.0 (+research dataset builder)"
TARGET_RESOLUTION = 2048
CATEGORY_SLUGS = {
    "fabric": "Fabrics", "tile": "Tiles", "metal": "Metal", "wood": "Wood",
    "rock": "Rock", "marble": "Marble", "concrete": "Concrete", "brick": "Bricks",
}
STRUCTURAL_ROLES = ("wall", "floor", "ceiling", "panel", "column")
REVIEW_ROLES = ("wall", "floor", "ceiling", "prop")

# These terms identify a photographed object, an exterior-only finish, or a
# scene prop—not merely an unusual architectural style.  They are the only
# rules eligible for automatic token deferral; subjective appearance rules
# remain in `manual_review` so that diversity is not silently discarded.
_HARD_EXCLUSION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("object_or_fixture", (
        "jacket", "bubble coat", "blister package", "manhole", "drain hole",
        "chainmail", "chain-link", "wire fence", "roll up door", " door ", "tree trunk",
        "tree bark", "bark texture", "cork board", "playground", "rubber mulch", "safety surfacing",
        "cooking pan", "soda can", "pull tab", "bookshelf", "office building facade",
        "facade texture", "carbon fibre", "fur", " hair ", "fence texture",
    )),
    ("exterior_or_site_finish", (
        "rooftop", "roof tile", "pavement", "sidewalk", "tactile pavement",
        "asphalt", "bitumen", "road", "highway", "garden", "forest ground",
        "muddy ground", "ground texture", "tree roots", "volcano", "lava", "planetary",
        "moss texture", "mossy", " moss", "decking", "seashore", "barnacle", "grass",
        "paver", "paving", "gravel", "cobblestone", "puddle",
    )),
)
_MANUAL_REVIEW_TERMS = (
    "aged", "dirty", "damaged", "chipped", "crack", "corroded", "oxidized", "rust",
    "worn", "gritty", "geometric", "flower", "leaf", "wave", "circle", "moroccan",
    "illusion", "graphic", "wallpaper", "pattern", "checker", "perforated", "glossy",
    "polished", "mirror", "shiny", "herringbone", "chevron", "ornament", "decorat",
    "triangle", "hexagonal", "pyramid", "acoustic", "foam", "paper", "sharp edges",
    "stone cladding", "parquet brick", "antique", "rough wood", "medieval", "pebble mosaic",
)
_FAMILY_ALIASES = {
    "fabrics": "fabric", "fabric": "fabric", "tiles": "tile", "tile": "tile",
    "bricks": "brick", "brick": "brick", "metals": "metal", "metal": "metal",
    "woods": "wood", "wood": "wood", "rocks": "rock", "rock": "rock",
    "marble": "marble", "concrete": "concrete",
}

# The 24-material core library intentionally prefers bland, broad-use indoor
# finishes.  The extended profile retains controlled visual diversity without
# admitting photographed props, exterior paving, or damaged/weathered scans.
# Quotas are asset counts (not per-role tokens) and sum to 100.
EXTENDED_FAMILY_QUOTAS = {
    "tile": 44, "wood": 16, "concrete": 15, "brick": 8,
    "metal": 6, "fabric": 6, "marble": 5,
}
_EXTENDED_EXCLUSION_TERMS = (
    "rust", "oxidized", "corroded", "crack", "damaged", "broken", "worn", "moss",
    "bark", "fence", "cobblestone", "pavement", "puddle", "road", "asphalt",
    "treadplate", "tread plate", "chain", "fur", " hair ", "leather", "camouflage",
    "coat", "medieval", "wallpaper", "carbon fibre", "carbon fiber", "foil",
    "shipping container", "cargo container", "steel cable", "wireframe", "perforated",
    "grille", "mesh", "tree trunk", "tree bark", "office building facade",
)
_EXTENDED_POSITIVE_TERMS = (
    "plaster", "concrete", "ceramic", "porcelain", "terracotta", "tile", "wood",
    "plank", "carpet", "rug", "marble", "terrazzo", "galvanized", "brushed",
    "aluminium", "aluminum", "indoor", "bathroom", "office",
)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag.lower() == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag.lower() == "meta":
            key = values.get("name") or values.get("property")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _review_root(staging_root: Path, review_subdir: str) -> Path:
    """Resolve an isolated review profile without permitting path escape."""
    if not review_subdir or Path(review_subdir).is_absolute():
        raise ValueError("review_subdir must be a non-empty staging-relative path")
    root = staging_root.resolve()
    candidate = (root / review_subdir).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("review_subdir must remain below the staging root")
    return candidate


def fetch_text(url: str, *, timeout: int = 60) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def download(url: str, destination: Path, *, timeout: int = 300) -> None:
    """Download atomically and retain a non-empty prior archive for resume."""
    if destination.is_file() and destination.stat().st_size:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if not temporary.stat().st_size:
            raise RuntimeError("empty TextureCan archive")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _parse_page(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    return parser


def _absolute(url: str, base: str = BASE_URL) -> str:
    return urljoin(base, url)


def discover_category_detail_urls(
    category_slug: str,
    *, fetch: Callable[[str], str] = fetch_text,
    base_url: str = BASE_URL,
) -> list[str]:
    """Discover every detail page listed by one paginated TextureCan category."""
    root = _absolute(f"/category/{category_slug}/", base_url)
    parsed_root = urlparse(root)
    pattern = re.compile(rf"^/category/{re.escape(category_slug)}/(?:\d+/)?$")
    pending, visited, details = [root], set(), set()
    while pending:
        page = pending.pop(0)
        if page in visited:
            continue
        visited.add(page)
        parser = _parse_page(fetch(page))
        for href in parser.hrefs:
            absolute = _absolute(href, page)
            parsed = urlparse(absolute)
            if parsed.netloc != parsed_root.netloc:
                continue
            if re.fullmatch(r"/details/\d+/", parsed.path):
                details.add(absolute)
            elif pattern.fullmatch(parsed.path) and absolute not in visited:
                pending.append(absolute)
    return sorted(details, key=lambda value: int(re.search(r"/details/(\d+)/", value).group(1)))


def parse_detail_page(url: str, html: str, *, category: str) -> dict[str, Any]:
    """Extract a stable 2K download record without relying on page layout CSS."""
    parser = _parse_page(html)
    links = [_absolute(href, url) for href in parser.hrefs]
    zip_urls = [link for link in links if re.search(r"_2k_[^/]+\.zip(?:$|\?)", link, re.IGNORECASE)]
    if not zip_urls:
        raise ValueError("detail page has no 2K map archive")
    zip_url = sorted(set(zip_urls))[0]
    match = re.search(r"/downloads/([^/]+)/([^/?]+_2k_[^/?]+\.zip)", zip_url, re.IGNORECASE)
    if not match:
        raise ValueError(f"unrecognised 2K TextureCan archive URL: {zip_url}")
    slug = match.group(1).lower()
    detail_id = re.search(r"/details/(\d+)/", url)
    title = parser.meta.get("og:title") or parser.meta.get("tex1:name") or slug
    description = parser.meta.get("og:description") or ""
    tags = parser.meta.get("tex1:tags") or ""
    return {
        "id": f"texturecan_{slug}", "asset_id": slug, "provider": "TextureCan",
        "category": category.lower(), "detail_id": int(detail_id.group(1)) if detail_id else None,
        "source_url": url, "source_zip_url": zip_url, "source_zip_name": match.group(2),
        "title": title, "description": description, "tags": [part.strip() for part in tags.split(",") if part.strip()],
        "preview_url": parser.meta.get("tex1:preview-image") or parser.meta.get("og:image"),
        "declared_resolution": parser.meta.get("tex1:resolution"),
        "license": "CC0-1.0",
        "license_provenance": {
            "license_url": TERMS_URL,
            "statement": "TextureCan terms declare CC0-1.0; project and 3D-asset redistribution permitted.",
            "texturecan_terms_checked": True,
        },
    }


def _image_member(member: str) -> bool:
    return Path(member).suffix.lower() in {".jpg", ".jpeg", ".png", ".tga", ".tif", ".tiff"}


def _map_kind(member: str) -> str | None:
    name = Path(member).stem.lower().replace("-", "_")
    if not _image_member(member) or "__macosx" in member.lower() or any(
        token in name for token in ("preview", "thumb", "render", "height", "displacement", "ao", "opacity")
    ):
        return None
    if "normal" in name:
        return "normal_gl" if any(token in name for token in ("opengl", "normal_gl", "normalgl", "nor_gl")) else None
    if "rough" in name:
        return "roughness"
    if any(token in name for token in ("metallic", "metalness")):
        return "metallic"
    if any(token in name for token in ("basecolor", "base_color", "color", "albedo", "diffuse")):
        return "base_color"
    return None


def _select_maps(archive: zipfile.ZipFile) -> dict[str, str]:
    candidates: dict[str, list[str]] = {key: [] for key in ("base_color", "roughness", "normal_gl", "metallic")}
    for member in archive.namelist():
        kind = _map_kind(member)
        if kind:
            candidates[kind].append(member)
    selected: dict[str, str] = {}
    for kind in ("base_color", "roughness", "normal_gl"):
        if not candidates[kind]:
            raise ValueError(f"archive lacks required {kind} map")
        selected[kind] = sorted(candidates[kind], key=lambda item: ("2k" not in item.lower(), len(item), item.lower()))[0]
    if candidates["metallic"]:
        selected["metallic"] = sorted(candidates["metallic"], key=lambda item: ("2k" not in item.lower(), len(item), item.lower()))[0]
    return selected


def _decode_shape(path: Path) -> tuple[int, int]:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim < 2:
        raise ValueError(f"cannot decode map: {path.name}")
    return int(image.shape[1]), int(image.shape[0])


def _extract_asset(spec: dict[str, Any], archive_path: Path, root: Path) -> tuple[dict[str, str], dict[str, list[int]]]:
    material_dir = root / "assets" / str(spec["id"])
    material_dir.mkdir(parents=True, exist_ok=True)
    maps, dimensions = {}, {}
    with zipfile.ZipFile(archive_path) as archive:
        selected = _select_maps(archive)
        for kind, member in selected.items():
            extension = Path(member).suffix.lower()
            destination = material_dir / f"{kind}{extension}"
            temporary = destination.with_suffix(destination.suffix + ".partial")
            with archive.open(member) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            os.replace(temporary, destination)
            width, height = _decode_shape(destination)
            if min(width, height) < TARGET_RESOLUTION:
                raise ValueError(f"{kind} map is below 2K: {width}x{height}")
            maps[kind] = str(destination.relative_to(root))
            dimensions[kind] = [width, height]
    return maps, dimensions


def _asset_text(record: dict[str, Any]) -> str:
    return " ".join(
        [str(record.get("category") or ""), str(record.get("title") or ""), str(record.get("description") or "")]
        + [str(item) for item in record.get("tags") or []]
    ).lower()


def provisional_roles(record: dict[str, Any]) -> list[str]:
    """Return broad review candidates; final production use needs human approval."""
    category, text = str(record.get("category") or "").lower(), _asset_text(record)
    roles = {"prop"}
    outdoor = any(token in text for token in ("outdoor", "pavement", "sidewalk", "road", "highway", "garden"))
    if category == "fabric":
        if any(token in text for token in ("carpet", "rug", "mat", "floor")):
            roles.add("floor")
    elif category == "metal":
        roles.update({"wall", "prop"})
        if any(token in text for token in ("ceiling", "panel", "sheet", "plate")):
            roles.add("ceiling")
    elif category in {"wood", "marble", "tile", "rock"}:
        roles.update({"wall", "floor"})
    elif category == "brick":
        roles.add("wall")
        if not outdoor:
            roles.add("floor")
    elif category == "concrete":
        roles.update({"wall", "floor", "ceiling"})
    if any(token in text for token in ("ceiling", "plaster", "acoustic", "light wood")):
        roles.add("ceiling")
    return [role for role in REVIEW_ROLES if role in roles]


def review_state(record: dict[str, Any]) -> str:
    text = _asset_text(record)
    if any(token in text for token in ("mirror", "mirror-like", "glossy marble", "outdoor pavement", "pavement", "sidewalk")):
        return "manual_review_required"
    if any(token in text for token in ("geometric", "christmas", "graphic pattern", "wallpaper")):
        return "manual_review_required"
    return "review_required"


def _source_zip_path(root: Path, record: dict[str, Any]) -> Path:
    return root / str(record["source_zip"])


def stage_one_asset(spec: dict[str, Any], root: Path, *, timeout: int = 300) -> dict[str, Any]:
    """Download, extract, validate, and return one staging manifest record."""
    archive = root / "source_zips" / "texturecan" / str(spec["source_zip_name"])
    try:
        download(str(spec["source_zip_url"]), archive, timeout=timeout)
        maps, dimensions = _extract_asset(spec, archive, root)
        result = dict(spec)
        result.update({
            "status": "accepted", "source_zip": str(archive.relative_to(root)),
            "source_zip_sha256": sha256(archive), "maps": maps,
            "sha256": {kind: sha256(root / rel) for kind, rel in maps.items()},
            "dimensions": dimensions, "normal_convention": "OpenGL",
            "metallic": ({"mode": "texture", "map": "metallic"} if "metallic" in maps
                         else {"mode": "constant", "value": 1.0} if str(spec.get("category")).lower() == "metal"
                         else {"mode": "constant", "value": 0.0}),
            "review_roles": provisional_roles(spec), "review_state": review_state(spec),
            "downloaded_at": utc_now(),
        })
        _atomic_json(root / "assets" / str(spec["id"]) / "asset_manifest.json", result)
        return result
    except Exception as error:
        result = dict(spec)
        result.update({"status": "rejected", "rejection": str(error), "rejected_at": utc_now()})
        return result


def _load_staging_manifest(root: Path) -> dict[str, Any]:
    path = root / "staging_manifest.json"
    if not path.is_file():
        return {"schema": STAGING_SCHEMA, "staging_version": STAGING_VERSION, "materials": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != STAGING_SCHEMA:
        raise ValueError(f"unsupported TextureCan staging manifest: {payload.get('schema')!r}")
    return payload


def mirror_categories(
    root: Path, *, categories: Iterable[str] = CATEGORY_SLUGS, limit: int | None = None,
    workers: int = 4, fetch: Callable[[str], str] = fetch_text, timeout: int = 300,
) -> dict[str, Any]:
    """Mirror all requested 2K categories, retaining rejected records for audit."""
    root = root.resolve()
    requested = [str(category).lower() for category in categories]
    unknown = sorted(set(requested) - set(CATEGORY_SLUGS))
    if unknown:
        raise ValueError(f"unknown TextureCan categories: {', '.join(unknown)}")
    detail_candidates: list[tuple[str, str]] = []
    for category in requested:
        detail_candidates.extend(
            (category, detail_url)
            for detail_url in discover_category_detail_urls(CATEGORY_SLUGS[category], fetch=fetch)
        )
    detail_candidates.sort(key=lambda row: (row[0], row[1]))
    if limit is not None:
        detail_candidates = detail_candidates[:max(0, int(limit))]

    def parse_candidate(candidate: tuple[str, str]) -> dict[str, Any]:
        category, detail_url = candidate
        try:
            return parse_detail_page(detail_url, fetch(detail_url), category=category)
        except Exception as error:
            identifier = f"texturecan_detail_{detail_url.rstrip('/').rsplit('/', 1)[-1]}"
            return {
                "id": identifier, "category": category, "source_url": detail_url,
                "status": "rejected", "rejection": str(error), "rejected_at": utc_now(),
            }

    # Detail pages are independent.  Parallel fetching keeps the crawler
    # practical for an all-category mirror without raising the host's load
    # above the same bounded download worker count.
    specs: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        for spec in executor.map(parse_candidate, detail_candidates):
            specs[str(spec["id"])] = spec
    ordered = [specs[key] for key in sorted(specs)]
    prior_manifest = _load_staging_manifest(root)
    prior = {str(row.get("id")): row for row in prior_manifest.get("materials") or []}
    complete = [row for row in ordered if (prior.get(str(row["id"])) or {}).get("status") == "accepted"]
    pending = [row for row in ordered if row not in complete]
    # A later `--category metal` invocation must resume only Metal while
    # retaining the prior Fabric/Tile/... mirror inventory.  A selected
    # category set is an additive mirror request, never a destructive filter.
    records = dict(prior)
    for row in complete:
        records[str(row["id"])] = row

    def checkpoint(*, in_progress: bool) -> dict[str, Any]:
        material_records = [records[key] for key in sorted(records)]
        payload = {
            "schema": STAGING_SCHEMA, "staging_version": STAGING_VERSION,
            "provider": "TextureCan", "license": "CC0-1.0", "license_url": TERMS_URL,
            "categories": sorted(
                set(str(category).lower() for category in prior_manifest.get("categories") or [])
                | set(requested)
            ),
            "target_resolution": TARGET_RESOLUTION,
            "downloaded_at": utc_now(), "materials": material_records,
        }
        if in_progress:
            payload["status"] = "in_progress"
        payload["digest"] = canonical_digest({key: value for key, value in payload.items() if key != "digest"})
        _atomic_json(root / ("staging_manifest.in_progress.json" if in_progress else "staging_manifest.json"), payload)
        return payload

    checkpoint(in_progress=True)
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        futures = [executor.submit(stage_one_asset, row, root, timeout=timeout) for row in pending if row.get("source_zip_url")]
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            records[str(row["id"])] = row
            checkpoint(in_progress=True)
            print(f"[texturecan] {index}/{len(futures)} {row['id']} {row['status']}", flush=True)
    # Preserve discover-time rejections too.
    for row in pending:
        if not row.get("source_zip_url"):
            records[str(row["id"])] = row
    payload = checkpoint(in_progress=False)
    (root / "staging_manifest.in_progress.json").unlink(missing_ok=True)
    return payload


def validate_staging_record(record: dict[str, Any], root: Path) -> None:
    if record.get("status") != "accepted":
        raise ValueError(f"{record.get('id')}: not an accepted staging record")
    if record.get("license") != "CC0-1.0" or record.get("normal_convention") != "OpenGL":
        raise ValueError(f"{record.get('id')}: missing CC0 provenance or OpenGL normal")
    source_zip = _source_zip_path(root, record).resolve()
    if not source_zip.is_file() or root.resolve() not in source_zip.parents:
        raise FileNotFoundError(f"{record.get('id')}: source zip missing")
    if sha256(source_zip) != record.get("source_zip_sha256"):
        raise ValueError(f"{record.get('id')}: source zip checksum mismatch")
    maps = record.get("maps") or {}
    for kind in ("base_color", "roughness", "normal_gl"):
        path = (root / str(maps.get(kind) or "")).resolve()
        if not path.is_file() or root.resolve() not in path.parents:
            raise FileNotFoundError(f"{record.get('id')} {kind}: missing map")
        if sha256(path) != (record.get("sha256") or {}).get(kind):
            raise ValueError(f"{record.get('id')} {kind}: checksum mismatch")
        width, height = _decode_shape(path)
        if min(width, height) < TARGET_RESOLUTION:
            raise ValueError(f"{record.get('id')} {kind}: below 2K")
    metallic = record.get("metallic") or {}
    if metallic.get("mode") == "texture":
        rel = maps.get(str(metallic.get("map") or "metallic"))
        path = (root / str(rel or "")).resolve()
        if not path.is_file() or root.resolve() not in path.parents:
            raise FileNotFoundError(f"{record.get('id')}: metallic texture missing")
    if str(record.get("category")).lower() == "metal" and metallic.get("mode") not in {"texture", "constant"}:
        raise ValueError(f"{record.get('id')}: metal requires a metallic texture or constant")


def _preview_panel(path: Path, *, normal: bool = False) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"cannot decode preview map: {path}")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    image = image[..., :3]
    if image.dtype != np.uint8:
        maximum = float(np.iinfo(image.dtype).max) if np.issubdtype(image.dtype, np.integer) else 1.0
        image = np.clip(image.astype(np.float32) / max(maximum, 1.0), 0.0, 1.0)
        image = (image * 255.0 + 0.5).astype(np.uint8)
    return cv2.resize(image, (256, 256), interpolation=cv2.INTER_AREA)


def create_review_thumbnails(root: Path, *, reset: bool = False, review_subdir: str = "review") -> dict[str, Any]:
    """Create role-local review tokens.  Removing a JPG is the human approval action."""
    root = root.resolve()
    manifest = _load_staging_manifest(root)
    review = _review_root(root, review_subdir)
    if review.exists():
        if not reset:
            raise FileExistsError(f"review already exists: {review}; refusing to recreate deleted approval tokens")
        shutil.rmtree(review)
    counts = {role: 0 for role in REVIEW_ROLES}
    for record in manifest.get("materials") or []:
        if record.get("status") != "accepted":
            continue
        validate_staging_record(record, root)
        maps = record["maps"]
        panels = [_preview_panel(root / maps["base_color"]), _preview_panel(root / maps["roughness"]), _preview_panel(root / maps["normal_gl"], normal=True)]
        montage = cv2.hconcat(panels)
        label = f"{record['id']} | {record.get('category')} | {record.get('review_state')}"
        cv2.putText(montage, label[:115], (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        for role in record.get("review_roles") or []:
            if role not in REVIEW_ROLES:
                continue
            destination = review / role / f"{record['id']}.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(destination), montage, [cv2.IMWRITE_JPEG_QUALITY, 92]):
                raise RuntimeError(f"cannot write review thumbnail: {destination}")
            counts[role] += 1
    payload = {"schema": REVIEW_SCHEMA, "staging_digest": manifest.get("digest"), "created_at": utc_now(),
               "review_subdir": review_subdir, "counts": counts}
    _atomic_json(review / "review_manifest.json", payload)
    return payload


def approved_roles_from_review(root: Path, *, review_subdir: str = "review") -> dict[str, set[str]]:
    review = _review_root(root.resolve(), review_subdir)
    approved: dict[str, set[str]] = {}
    for role in REVIEW_ROLES:
        role_dir = review / role
        if not role_dir.is_dir():
            continue
        for path in role_dir.glob("*.jpg"):
            asset_id = path.stem
            approved.setdefault(asset_id, set()).add(role)
    return approved


def _refresh_review_manifest(root: Path, *, second_pass_run_id: str | None = None,
                             review_subdir: str = "review") -> None:
    """Keep the lightweight review index truthful after reversible token moves."""
    review = _review_root(root.resolve(), review_subdir)
    path = review / "review_manifest.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != REVIEW_SCHEMA:
        return
    payload["counts"] = {
        role: sum(1 for _ in (review / role).glob("*.jpg"))
        for role in REVIEW_ROLES
    }
    payload["updated_at"] = utc_now()
    if second_pass_run_id:
        payload["last_second_pass_run_id"] = second_pass_run_id
    _atomic_json(path, payload)


def structural_family(record: dict[str, Any]) -> str:
    """Use TextureCan's asset slug before its crawl-category label.

    TextureCan tag/category pages can list an asset from another source family
    (for example, a jacket under a Tiles result).  Structural suitability must
    follow the asset itself, not that discovery-page placement.
    """
    asset_id = str(record.get("asset_id") or record.get("id") or "").lower()
    prefix = asset_id.split("_", 1)[0]
    if prefix:
        return _FAMILY_ALIASES.get(prefix, prefix)
    category = str(record.get("category") or "").lower()
    return _FAMILY_ALIASES.get(category, category or "unknown")


def _roughness_statistics(path: Path) -> dict[str, float]:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"cannot decode roughness map: {path}")
    if image.ndim == 3:
        image = image[..., :3].mean(axis=2)
    # A 512px proxy is sufficient for a physical gate and keeps review of
    # hundreds of 2K maps interactive.  Full-resolution maps remain unchanged.
    if max(image.shape[:2]) > 512:
        image = cv2.resize(image, (512, 512), interpolation=cv2.INTER_AREA)
    if np.issubdtype(image.dtype, np.integer):
        image = image.astype(np.float32) / float(np.iinfo(image.dtype).max)
    else:
        image = image.astype(np.float32)
    values = np.clip(image.reshape(-1), 0.0, 1.0)
    return {
        "p05": float(np.quantile(values, 0.05)),
        "median": float(np.median(values)),
        "p95": float(np.quantile(values, 0.95)),
        "std": float(np.std(values)),
    }


def classify_second_pass(record: dict[str, Any], role: str, *, roughness: dict[str, float] | None = None) -> tuple[str, list[str]]:
    """Classify one retained preview token without touching the raw source asset."""
    if role not in REVIEW_ROLES:
        raise ValueError(f"unsupported review role: {role}")
    if role == "prop":
        return "keep", ["nonstructural_prop_token"]
    text = _asset_text(record)
    identity_text = " ".join((str(record.get("asset_id") or ""), str(record.get("title") or ""))).lower()
    family = structural_family(record)
    hard_reasons = [name for name, terms in _HARD_EXCLUSION_RULES if any(term in identity_text for term in terms)]
    if family in {"ground", "food", "plant", "plants"}:
        hard_reasons.append("nonstructural_asset_family")
    if role == "wall" and family == "fabric" and not any(term in text for term in ("wallcover", "wall covering")):
        hard_reasons.append("nonstructural_fabric_wall")
    if role == "floor" and family == "metal":
        hard_reasons.append("metal_floor_not_in_structural_baseline")
    if role == "floor" and family == "fabric" and not any(term in text for term in ("carpet", "rug", "carpet tile")):
        hard_reasons.append("non_floor_fabric")
    if role == "ceiling" and family == "metal" and not any(term in text for term in ("ceiling", "acoustic")):
        hard_reasons.append("metal_not_a_ceiling_system")
    if hard_reasons:
        return "defer_hard", sorted(set(hard_reasons))

    review_reasons = ["high_style_or_weathering"] if any(term in text for term in _MANUAL_REVIEW_TERMS) else []
    title = str(record.get("title") or "").lower()
    explicit_uses = {
        candidate for candidate in ("wall", "floor", "ceiling")
        if candidate in title or (candidate == "floor" and "flooring" in title)
    }
    if explicit_uses and role not in explicit_uses:
        review_reasons.append("explicit_title_role_mismatch")
    if role == "ceiling" and family not in {"concrete", "tile", "wood", "metal"}:
        review_reasons.append("unusual_ceiling_family")
    if roughness:
        if role == "floor" and (roughness["median"] < 0.20 or roughness["p05"] < 0.04):
            review_reasons.append("near_mirror_floor")
        if role in {"wall", "ceiling"} and roughness["median"] < 0.15:
            review_reasons.append("near_mirror_structure")
        if roughness["std"] < 0.002:
            review_reasons.append("near_uniform_roughness")
    return ("manual_review", sorted(set(review_reasons))) if review_reasons else ("keep", ["interior_finish_candidate"])


def second_pass_structural_review(
    root: Path, *, apply_hard_deferrals: bool = False, apply_manual_deferrals: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Audit retained structural tokens and optionally *move* hard rejects.

    Moves go to `review_deferred/<run-id>/`; no raw map, zip, or manifest is
    removed. `apply_manual_deferrals` is the deliberate "core baseline" mode:
    it leaves only ordinary interior finishes in review and retains specialty
    material candidates in the reversible deferred folder.
    """
    root = root.resolve()
    manifest = _load_staging_manifest(root)
    records = {str(row.get("id")): row for row in manifest.get("materials") or []}
    roughness_cache: dict[str, dict[str, float] | None] = {}
    decisions: list[dict[str, Any]] = []
    # Panel and column inherit the human-reviewed wall token.  There is no
    # separate panel/column review folder, so evaluate each physical token once.
    for review_role in ("wall", "floor", "ceiling"):
        for token in sorted((root / "review" / review_role).glob("*.jpg")):
            record = records.get(token.stem)
            if record is None or record.get("status") != "accepted":
                decisions.append({"role": review_role, "asset_id": token.stem, "status": "defer_hard", "reasons": ["orphan_review_token"]})
                continue
            cache_key = str(record["id"])
            if cache_key not in roughness_cache:
                try:
                    roughness_cache[cache_key] = _roughness_statistics(root / str((record.get("maps") or {}).get("roughness") or ""))
                except (OSError, ValueError):
                    roughness_cache[cache_key] = None
            status, reasons = classify_second_pass(record, review_role, roughness=roughness_cache[cache_key])
            decisions.append({
                "role": review_role, "asset_id": cache_key, "status": status, "reasons": reasons,
                "family": structural_family(record), "title": record.get("title"),
                "roughness": roughness_cache[cache_key], "review_token": str(token.relative_to(root)),
            })
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    moved: list[dict[str, str]] = []
    if apply_hard_deferrals:
        for row in decisions:
            if row["status"] != "defer_hard" and not (apply_manual_deferrals and row["status"] == "manual_review"):
                continue
            source = root / str(row.get("review_token") or f"review/{row['role']}/{row['asset_id']}.jpg")
            if not source.is_file():
                continue
            destination = root / "review_deferred" / run_id / row["role"] / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append({"from": str(source.relative_to(root)), "to": str(destination.relative_to(root))})
        _refresh_review_manifest(root, second_pass_run_id=run_id)
    counts = {status: sum(row["status"] == status for row in decisions) for status in ("keep", "manual_review", "defer_hard")}
    payload = {
        "schema": SECOND_PASS_SCHEMA, "run_id": run_id, "staging_digest": manifest.get("digest"),
        "created_at": utc_now(), "applied_hard_deferrals": bool(apply_hard_deferrals),
        "applied_manual_deferrals": bool(apply_manual_deferrals),
        "counts": counts, "moved": moved, "decisions": decisions,
    }
    _atomic_json(root / "second_pass_reports" / f"{run_id}.json", payload)
    _atomic_json(root / "second_pass_reports" / "latest.json", payload)
    return payload


def _extended_candidate(record: dict[str, Any], staging_root: Path) -> dict[str, Any] | None:
    """Return the role-safe extended candidate for one staged TextureCan asset."""
    if record.get("status") != "accepted":
        return None
    family = structural_family(record)
    if family not in EXTENDED_FAMILY_QUOTAS:
        return None
    title = str(record.get("title") or "").lower()
    text = _asset_text(record)
    if any(term in text for term in _EXTENDED_EXCLUSION_TERMS):
        return None
    roughness = _roughness_statistics(staging_root / str((record.get("maps") or {}).get("roughness") or ""))
    roles: list[str] = []
    for role in provisional_roles(record):
        if role == "prop":
            continue
        status, _ = classify_second_pass(record, role, roughness=roughness)
        if status == "defer_hard":
            continue
        if family == "fabric" and (role != "floor" or not any(token in title for token in ("carpet", "rug", "matting"))):
            continue
        if family == "metal" and role != "wall":
            continue
        if "wall" in title and role != "wall":
            continue
        if ("floor" in title or "flooring" in title) and role != "floor":
            continue
        if "ceiling" in title and role != "ceiling":
            continue
        if role == "floor" and (roughness["median"] < 0.25 or roughness["p05"] < 0.08):
            continue
        if role in {"wall", "ceiling"} and roughness["median"] < 0.18:
            continue
        roles.append(role)
    if not roles:
        return None
    score = 10 * sum(token in title for token in _EXTENDED_POSITIVE_TERMS)
    score -= sum(token in title for token in (
        "old", "vintage", "retro", "shiny", "glossy", "geometric", "pattern", "fan",
        "flower", "star", "moroccan", "victorian", "industrial", "bumpy", "wavy",
    ))
    return {
        "id": str(record["id"]), "family": family, "roles": sorted(set(roles)), "score": score,
        "title": record.get("title"), "roughness": roughness,
    }


def _extended_scale(record: dict[str, Any]) -> float:
    """Project-standard meter repeat used only where TextureCan gives no size."""
    family, title = structural_family(record), str(record.get("title") or "").lower()
    if family == "fabric":
        return 2.0
    if family == "wood":
        return 2.4 if any(token in title for token in ("plank", "long", "flooring")) else 2.0
    if family == "brick":
        return 2.0
    if family == "marble":
        return 1.5
    if family == "metal":
        return 1.5
    if family == "concrete":
        return 1.2 if any(token in title for token in ("plate", "slab", "waffle", "tile")) else 2.0
    if family == "tile":
        return 0.6 if any(token in title for token in ("small", "mosaic", "hexagonal", "terracotta")) else 1.2
    raise ValueError(f"unsupported extended family: {family}")


def create_extended_structural_review_profile(staging_root: Path, *, review_subdir: str = "review_extended_v1",
                                              profile_name: str = "extended_v1", max_assets: int = 100) -> dict[str, Any]:
    """Create a deterministic ~100-asset interior-extended review profile.

    The core `review/` directory remains untouched.  This profile is an
    isolated, auditable selection of role-safe assets; it is suitable for an
    extended registry but remains independent from the conservative core.
    """
    if max_assets <= 0:
        raise ValueError("max_assets must be positive")
    staging_root = staging_root.resolve()
    manifest = _load_staging_manifest(staging_root)
    records = {str(row.get("id")): row for row in manifest.get("materials") or []}
    review = _review_root(staging_root, review_subdir)
    profile_dir = staging_root / "extended_profiles" / profile_name
    if review.exists() or profile_dir.exists():
        raise FileExistsError(f"extended review profile already exists: {review_subdir}")

    candidates = {entry["id"]: entry for entry in (
        _extended_candidate(record, staging_root) for record in records.values()
    ) if entry is not None}
    core_roles = approved_roles_from_review(staging_root)
    selected: dict[str, dict[str, Any]] = {}
    family_counts = {family: 0 for family in EXTENDED_FAMILY_QUOTAS}

    # Keep every accepted core material in the extended profile as a stable
    # subset.  Prop-only approvals are intentionally ignored.
    for asset_id, approved_roles in sorted(core_roles.items()):
        record = records.get(asset_id)
        if record is None:
            continue
        family = structural_family(record)
        roles = sorted(set(approved_roles) & set(STRUCTURAL_ROLES))
        if family not in EXTENDED_FAMILY_QUOTAS or not roles:
            continue
        candidate = candidates.get(asset_id) or {
            "id": asset_id, "family": family, "roles": roles, "score": 1_000,
            "title": record.get("title"), "roughness": _roughness_statistics(staging_root / record["maps"]["roughness"]),
        }
        candidate = {**candidate, "roles": roles, "score": max(int(candidate["score"]), 1_000), "core": True}
        selected[asset_id] = candidate
        family_counts[family] += 1

    def ordered(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(entries, key=lambda row: (-int(row["score"]), str(row["title"] or ""), str(row["id"])))

    for family, quota in EXTENDED_FAMILY_QUOTAS.items():
        for candidate in ordered(row for row in candidates.values() if row["family"] == family):
            if len(selected) >= max_assets or family_counts[family] >= quota:
                break
            if candidate["id"] in selected:
                continue
            selected[candidate["id"]] = candidate
            family_counts[family] += 1
    # If one family cannot satisfy its quota, use the remaining safe candidates
    # from other families rather than silently lowering the requested budget.
    for candidate in ordered(candidates.values()):
        if len(selected) >= max_assets:
            break
        if candidate["id"] not in selected:
            selected[candidate["id"]] = candidate
            family_counts[candidate["family"]] += 1

    selected_rows = ordered(selected.values())[:max_assets]
    if not selected_rows:
        raise ValueError("extended profile found no eligible structural assets")
    review.mkdir(parents=True, exist_ok=False)
    counts = {role: 0 for role in REVIEW_ROLES}
    for candidate in selected_rows:
        record = records[candidate["id"]]
        maps = record["maps"]
        panels = [_preview_panel(staging_root / maps["base_color"]), _preview_panel(staging_root / maps["roughness"]),
                  _preview_panel(staging_root / maps["normal_gl"], normal=True)]
        montage = cv2.hconcat(panels)
        label = f"{record['id']} | extended_v1 | {candidate['family']}"
        cv2.putText(montage, label[:115], (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        for role in candidate["roles"]:
            destination = review / role / f"{record['id']}.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(destination), montage, [cv2.IMWRITE_JPEG_QUALITY, 92]):
                raise RuntimeError(f"cannot write review thumbnail: {destination}")
            counts[role] += 1
    review_manifest = {
        "schema": REVIEW_SCHEMA, "staging_digest": manifest.get("digest"), "created_at": utc_now(),
        "review_subdir": review_subdir, "profile": profile_name, "counts": counts,
    }
    _atomic_json(review / "review_manifest.json", review_manifest)
    payload = {
        "schema": EXTENDED_PROFILE_SCHEMA, "profile": profile_name, "review_subdir": review_subdir,
        "staging_digest": manifest.get("digest"), "max_assets": max_assets,
        "family_quotas": EXTENDED_FAMILY_QUOTAS, "family_counts": family_counts,
        "selected": selected_rows, "candidate_asset_count": len(candidates), "created_at": utc_now(),
    }
    payload["digest"] = canonical_digest({key: value for key, value in payload.items() if key != "digest"})
    _atomic_json(profile_dir / "selection.json", payload)
    return payload


def write_extended_scale_overrides(staging_root: Path, destination: Path, *, review_subdir: str) -> dict[str, Any]:
    """Write explicit, versioned project-standard scales for an extended profile."""
    staging_root = staging_root.resolve()
    manifest = _load_staging_manifest(staging_root)
    records = {str(row.get("id")): row for row in manifest.get("materials") or []}
    assets: dict[str, Any] = {}
    for asset_id, roles in sorted(approved_roles_from_review(staging_root, review_subdir=review_subdir).items()):
        record = records.get(asset_id)
        structural_roles = sorted(set(roles) & set(STRUCTURAL_ROLES))
        if record is None or not structural_roles:
            continue
        repeat = _extended_scale(record)
        assets[asset_id] = {
            "width": repeat, "height": repeat, "source": "project_standard_repeat_size_extended_v1",
            "approved_roles": structural_roles,
        }
    payload = {
        "schema": SCALE_OVERRIDES_SCHEMA, "staging_digest": manifest.get("digest"),
        "review_subdir": review_subdir, "assets": assets,
    }
    _atomic_json(destination.resolve(), payload)
    return payload


def write_scale_overrides_template(staging_root: Path, destination: Path, *, review_subdir: str = "review") -> dict[str, Any]:
    """Emit a deliberately incomplete physical-size worksheet for approved roles.

    Values are null on purpose: a guessed repeat size would violate the
    explicit meter-repeat contract.  The reviewer fills the numbers after
    deleting unwanted role thumbnails, then passes the completed file to the
    finalizer.
    """
    staging_root = staging_root.resolve()
    manifest = _load_staging_manifest(staging_root)
    records = {str(row.get("id")): row for row in manifest.get("materials") or []}
    assets: dict[str, Any] = {}
    for asset_id, roles in sorted(approved_roles_from_review(staging_root, review_subdir=review_subdir).items()):
        record = records.get(asset_id)
        if record is None or record.get("status") != "accepted":
            continue
        structural = set(roles) & set(STRUCTURAL_ROLES)
        if str(record.get("category")).lower() == "metal" and "wall" in structural:
            structural.add("panel")
        if structural:
            assets[asset_id] = {
                "width": None,
                "height": None,
                "source": "manual_review_required",
                "approved_roles": sorted(structural),
            }
    payload = {
        "schema": SCALE_OVERRIDES_SCHEMA,
        "staging_digest": manifest.get("digest"),
        "review_subdir": review_subdir,
        "assets": assets,
    }
    _atomic_json(destination.resolve(), payload)
    return payload


def _load_scales(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCALE_OVERRIDES_SCHEMA or not isinstance(payload.get("assets"), dict):
        raise ValueError("scale overrides must use TextureCan scale-overrides v1")
    result: dict[str, dict[str, Any]] = {}
    for asset_id, value in payload["assets"].items():
        if not isinstance(value, dict):
            raise ValueError(f"{asset_id}: invalid physical-size override")
        width, height = float(value.get("width") or 0), float(value.get("height") or 0)
        if width <= 0 or height <= 0:
            raise ValueError(f"{asset_id}: physical repeat width and height must be positive")
        result[str(asset_id)] = {"width": width, "height": height, "source": str(value.get("source") or "manual_review")}
    return result


def finalize_structural_registry(staging_root: Path, final_root: Path, scale_overrides: Path, *,
                                 purge_unselected: bool = False, review_subdir: str = "review") -> dict[str, Any]:
    """Copy approved review tokens into an immutable explicit-role render registry."""
    staging_root, final_root = staging_root.resolve(), final_root.resolve()
    manifest = _load_staging_manifest(staging_root)
    review_manifest = _review_root(staging_root, review_subdir) / "review_manifest.json"
    if not review_manifest.is_file():
        raise FileNotFoundError("missing review/review_manifest.json; generate thumbnails before finalizing")
    approved = approved_roles_from_review(staging_root, review_subdir=review_subdir)
    scales = _load_scales(scale_overrides.resolve())
    records = {str(row.get("id")): row for row in manifest.get("materials") or []}
    selected_ids = sorted(approved)
    if not selected_ids:
        raise ValueError("no review thumbnails remain; no TextureCan assets were approved")
    if final_root.exists():
        raise FileExistsError(f"final TextureCan registry root already exists: {final_root}")
    # Build beside the final root, then atomically expose the registry only
    # after every copied map and both manifests have been committed. This keeps
    # an interrupted finalization from looking like a usable registry.
    work_root = final_root.parent / f".{final_root.name}.staging-{uuid.uuid4().hex}"
    work_root.mkdir(parents=True, exist_ok=False)
    selected_records = []
    try:
        for asset_id in selected_ids:
            record = records.get(asset_id)
            if record is None or record.get("status") != "accepted":
                raise ValueError(f"{asset_id}: review token has no accepted source record")
            roles = sorted(approved[asset_id])
            structural_roles = set(roles) & set(STRUCTURAL_ROLES)
            # The review UI intentionally exposes the ergonomic "wall" token
            # rather than a separate tiny panel bucket.  A human-approved metal
            # wall sheet is also a valid interior panel finish; no other class
            # receives this promotion automatically.
            if str(record.get("category")).lower() == "metal" and "wall" in structural_roles:
                structural_roles.add("panel")
            # A structural column is a wall-like dielectric finish, rather
            # than a separate material family.  Promote approved non-metal
            # wall finishes so a scene with columns cannot fail binding merely
            # because the ergonomic review UI has no dedicated column bucket.
            # Metal sheets remain panel-only to avoid turning supports into
            # arbitrary conductors.
            if str(record.get("category")).lower() != "metal" and "wall" in structural_roles:
                structural_roles.add("column")
            structural_roles = sorted(structural_roles)
            if not structural_roles:
                # Prop-only tokens are intentionally not structural overrides.
                continue
            validate_staging_record(record, staging_root)
            if asset_id not in scales:
                raise ValueError(f"{asset_id}: no physical_size_m entry in scale_overrides.json")
            maps: dict[str, str] = {}
            for kind, relative in (record.get("maps") or {}).items():
                source = (staging_root / str(relative)).resolve()
                destination = work_root / "texturecan" / asset_id / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                maps[str(kind)] = str(destination.relative_to(work_root))
            source_zip = _source_zip_path(staging_root, record)
            zipped = work_root / "source_zips" / "texturecan" / source_zip.name
            zipped.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_zip, zipped)
            metallic = dict(record.get("metallic") or {"mode": "constant", "value": 0.0})
            if metallic.get("mode") == "texture" and str(metallic.get("map") or "metallic") not in maps:
                raise ValueError(f"{asset_id}: selected metallic texture was not copied")
            if str(record.get("category")).lower() == "metal" and metallic.get("mode") not in {"texture", "constant"}:
                raise ValueError(f"{asset_id}: metal lacks an approved metallic route")
            selected_records.append({
                "id": asset_id, "provider": "TextureCan", "asset_id": record.get("asset_id"),
                "category": record.get("category"), "title": record.get("title"), "description": record.get("description"),
                "source_url": record.get("source_url"), "source_zip": str(zipped.relative_to(work_root)),
                "source_zip_url": record.get("source_zip_url"), "source_zip_sha256": sha256(zipped),
                "license": "CC0-1.0", "license_provenance": record.get("license_provenance"),
                "maps": maps, "sha256": {key: sha256(work_root / value) for key, value in maps.items()},
                "normal_convention": "OpenGL", "physical_size_m": scales[asset_id],
                "approved_roles": structural_roles, "review_roles": roles,
                "semantic_compatibility": structural_roles, "metallic": metallic,
                "surface_family": record.get("category"), "projection": "object_meter_repeat_v3",
            })
        if not selected_records:
            raise ValueError("review only approved prop tokens; no structural roles remain")
        payload = {
            "schema": REGISTRY_SCHEMA, "registry_version": REGISTRY_VERSION,
            "role_policy": "explicit_approved_roles_v1", "provider": "TextureCan",
            "source_staging_digest": manifest.get("digest"), "scale_overrides_sha256": sha256(scale_overrides),
            "review_subdir": review_subdir,
            "materials": sorted(selected_records, key=lambda row: str(row["id"])),
        }
        payload["digest"] = canonical_digest({key: value for key, value in payload.items() if key != "digest"})
        _atomic_json(work_root / "registry.lock.json", payload)
        finalization = {
            "schema": FINALIZATION_SCHEMA, "staging_root": str(staging_root), "staging_digest": manifest.get("digest"),
            "registry_digest": payload["digest"], "selected_asset_count": len(selected_records),
            "selected_asset_ids": [row["id"] for row in selected_records], "review_subdir": review_subdir,
            "created_at": utc_now(),
        }
        _atomic_json(work_root / "finalization_manifest.json", finalization)
    except Exception:
        shutil.rmtree(work_root, ignore_errors=True)
        raise
    work_root.replace(final_root)
    if purge_unselected:
        selected = {row["id"] for row in selected_records}
        for asset_id, record in records.items():
            if record.get("status") == "accepted" and asset_id not in selected:
                shutil.rmtree(staging_root / "assets" / asset_id, ignore_errors=True)
                _source_zip_path(staging_root, record).unlink(missing_ok=True)
    return payload


def repair_wall_column_promotions(final_root: Path) -> dict[str, Any]:
    """Atomically repair a pre-release registry made before column promotion.

    This is deliberately narrow: it only updates an unpublished TextureCan
    registry whose explicit approved wall roles already passed the same human
    review, and never promotes metal sheets. The repair is recorded in the
    finalization manifest so the corrected digest remains auditable.
    """
    root = final_root.resolve()
    registry_path = root / "registry.lock.json"
    finalization_path = root / "finalization_manifest.json"
    if not registry_path.is_file() or not finalization_path.is_file():
        raise FileNotFoundError("expected completed TextureCan registry and finalization manifest")
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("schema") != REGISTRY_SCHEMA or payload.get("role_policy") != "explicit_approved_roles_v1":
        raise ValueError("unsupported registry for wall/column promotion repair")
    changed: list[str] = []
    for record in payload.get("materials") or []:
        roles = {str(value) for value in record.get("approved_roles") or []}
        if str(record.get("category") or "").lower() != "metal" and "wall" in roles and "column" not in roles:
            roles.add("column")
            record["approved_roles"] = sorted(roles)
            record["semantic_compatibility"] = sorted(roles)
            changed.append(str(record.get("id") or ""))
    if not changed:
        return payload
    payload["digest"] = canonical_digest({key: value for key, value in payload.items() if key != "digest"})
    _atomic_json(registry_path, payload)
    finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
    finalization["registry_digest"] = payload["digest"]
    finalization["post_finalization_repairs"] = [
        *(finalization.get("post_finalization_repairs") or []),
        {"kind": "wall_to_column_role_promotion_v1", "changed_asset_ids": changed, "at": utc_now()},
    ]
    _atomic_json(finalization_path, finalization)
    return payload
