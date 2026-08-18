"""Read-only catalog and visualization helpers for Principled IR datasets."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from mitsuba_converter.ir_dataset_contract import (
    ARTIFACT_SCHEMA,
    DATASET_SCHEMA,
    DISTANCE_MODALITIES,
    HDR_MODALITIES,
    ID_MODALITIES,
    LINEAR_RGB_MODALITIES,
    MASK_MODALITIES,
    NORMAL_MODALITIES,
    OVERVIEW_SCHEMA,
    SCALAR_MODALITIES,
    _read_json,
    _safe_artifact_path,
    _safe_artifact_relative_path,
)

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

MODALITY_GROUPS = [
    {"id": "observation", "label": "Observation", "modalities": ["rgb", "nir_active"]},
    {"id": "pbr", "label": "PBR", "modalities": ["base_color_rgb", "base_color_nir", "roughness", "metallic"]},
    {"id": "geometry", "label": "Geometry", "modalities": ["normal_geometry_world", "normal_shading_world", "depth", "range"]},
    {"id": "id", "label": "ID", "modalities": ["object_id", "material_id"]},
    {"id": "mask", "label": "Mask", "modalities": sorted(MASK_MODALITIES)},
    {"id": "diffuse", "label": "Diffuse decomposition", "modalities": [
        "diffuse_component_rgb", "diffuse_component_nir", "diffuse_reflectance_rgb",
        "diffuse_reflectance_nir", "diffuse_shading_rgb", "diffuse_shading_nir",
    ]},
]


@dataclass(frozen=True)
class DatasetOrigin:
    kind: str
    root: Path
    path: Path

    def payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.path.name, "path": str(self.path)}


@dataclass
class DatasetRecord:
    dataset_id: str
    fingerprint: str
    name: str
    primary: DatasetOrigin
    origins: list[DatasetOrigin]
    config: dict[str, Any]
    contract: dict[str, Any]
    qc: dict[str, Any]
    scene_statistics: dict[str, Any] | None
    rows: dict[str, dict[str, Any]]
    index_mtime_ns: int
    warnings: list[str] = field(default_factory=list)

    @property
    def modalities(self) -> list[str]:
        names: set[str] = set()
        for row in self.rows.values():
            names.update(str(x) for x in (row.get("paths") or {}).keys())
        return sorted(names)

    def summary(self) -> dict[str, Any]:
        views = {str(row.get("viewpoint_id") or "") for row in self.rows.values()}
        origin_kinds = {origin.kind for origin in self.origins}
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "fingerprint": self.fingerprint,
            "schema": self.config.get("schema"),
            "frame_count": len(self.rows),
            "viewpoint_count": len(views - {""}),
            "width": self.config.get("width"),
            "height": self.config.get("height"),
            "modalities": self.modalities,
            "modality_groups": _available_groups(self.modalities),
            "origins": [origin.payload() for origin in self.origins],
            "primary_origin": self.primary.kind,
            "published": "bean" in origin_kinds,
            "publishable": bool(origin_kinds & {"out", "work"}) and "bean" not in origin_kinds,
            "qc": self.qc,
            "scene_statistics": _compact_scene_statistics(self.scene_statistics),
            "warnings": self.warnings,
        }


def _available_groups(modalities: Iterable[str]) -> list[dict[str, Any]]:
    available = set(modalities)
    result = []
    for group in MODALITY_GROUPS:
        found = [name for name in group["modalities"] if name in available]
        if found:
            result.append({**group, "modalities": found})
    known = {name for group in result for name in group["modalities"]}
    other = sorted(available - known)
    if other:
        result.append({"id": "other", "label": "Other", "modalities": other})
    return result


def _compact_scene_statistics(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != "robomituba.ir_scene_statistics.v1":
        return {"known": False, "density_class": "unknown", "unknown_reason": "artifact_missing"}
    keys = ("room_type", "requested_furnishing_density", "content_audit_status", "statistics_provenance", "object_count",
            "nonstructural_object_count", "room_area_m2", "nonstructural_objects_per_m2", "density_class",
            "unknown_reason", "selected_sparse_pose_fraction", "selected_pose_count")
    result = {"known": True, **{key: value.get(key) for key in keys}}
    result["selected_visible_object_median"] = (value.get("selected_visible_object_count") or {}).get("median")
    result["selected_nonstructural_fraction_median"] = (value.get("selected_nonstructural_fraction") or {}).get("median")
    for key in ("material_mix_profile", "high_metallic_material_count", "texture_metallic_material_count",
                "high_metallic_valid_pixel_fraction", "metallic_visibility_pose_fraction",
                "dominant_metal_object_ratio", "material_mix_status", "material_visibility_status"):
        result[key] = value.get(key)
    coverage = result.get("high_metallic_valid_pixel_fraction")
    if coverage is None:
        result["metal_class"] = "unknown"
    elif 0.03 <= float(coverage) <= 0.12 and result.get("material_visibility_status") == "passed":
        result["metal_class"] = "balanced-metal"
    elif float(coverage) < 0.03:
        result["metal_class"] = "metal-sparse"
    else:
        result["metal_class"] = "metal-rich"
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_statistics_overlay(path: Path, fingerprint: str) -> dict[str, Any] | None:
    """Accept only a sidecar still bound to this dataset and its source JSON files."""
    try:
        value = _read_json(path)
        binding = value.get("backfill") or {}
        if value.get("schema") != "robomituba.ir_scene_statistics.v1" or binding.get("dataset_fingerprint") != fingerprint:
            return None
        for source in binding.get("sources") or []:
            source_path = Path(str(source.get("path") or ""))
            if not source_path.is_file() or _sha256_file(source_path) != str(source.get("sha256") or ""):
                return None
        value["statistics_provenance"] = "backfilled"
        return value
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def load_dataset_origin(origin: DatasetOrigin, *, statistics_root: Path | None = None) -> DatasetRecord:
    config_path = origin.path / "dataset_config.json"
    contract_path = origin.path / "artifact_contract.json"
    index_path = origin.path / "index.jsonl"
    if not (config_path.is_file() and contract_path.is_file() and index_path.is_file()):
        raise ValueError("dataset_config.json, artifact_contract.json, and index.jsonl are required")
    config = _read_json(config_path)
    contract = _read_json(contract_path)
    if config.get("schema") != DATASET_SCHEMA:
        raise ValueError(f"unsupported dataset schema: {config.get('schema')!r}")
    if contract.get("schema") != ARTIFACT_SCHEMA:
        raise ValueError(f"unsupported artifact schema: {contract.get('schema')!r}")
    fingerprint = str(config.get("dataset_fingerprint") or contract.get("dataset_fingerprint") or "")
    if not fingerprint or fingerprint != str(contract.get("dataset_fingerprint") or ""):
        raise ValueError("dataset/artifact fingerprint mismatch")
    rows: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    with index_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            frame_id = str(row.get("frame_id") or "")
            if not frame_id:
                raise ValueError(f"index line {line_number} lacks frame_id")
            if frame_id in rows:
                raise ValueError(f"duplicate frame_id: {frame_id}")
            if row.get("dataset_fingerprint") != fingerprint:
                raise ValueError(f"frame fingerprint mismatch: {frame_id}")
            for modality, relative in (row.get("paths") or {}).items():
                try:
                    _safe_artifact_relative_path(str(relative))
                except ValueError as exc:
                    raise ValueError(f"{frame_id}/{modality}: {exc}") from exc
            rows[frame_id] = row
    qc = _read_json(origin.path / "qc_summary.json") if (origin.path / "qc_summary.json").is_file() else {}
    stats_path = origin.path / "quality" / "scene_statistics.json"
    statistics = _read_json(stats_path) if stats_path.is_file() else None
    if isinstance(statistics, dict):
        statistics.setdefault("statistics_provenance", "native")
    elif statistics_root is not None:
        statistics = _load_statistics_overlay(statistics_root / f"{fingerprint}.json", fingerprint)
    return DatasetRecord(
        dataset_id=fingerprint,
        fingerprint=fingerprint,
        name=origin.path.name,
        primary=origin,
        origins=[origin],
        config=config,
        contract=contract,
        qc=qc,
        scene_statistics=statistics,
        rows=rows,
        index_mtime_ns=index_path.stat().st_mtime_ns,
        warnings=warnings[:100],
    )


class DatasetCatalog:
    """TTL-refreshed, fingerprint-deduplicated dataset catalog."""

    def __init__(self, roots: Iterable[tuple[str, Path]], *, ttl_s: float = 5.0,
                 statistics_root: Path | None = None):
        self.roots = [(kind, Path(root)) for kind, root in roots]
        self.ttl_s = float(ttl_s)
        self.statistics_root = Path(statistics_root) if statistics_root else None
        self._lock = threading.RLock()
        self._last_scan = 0.0
        self._records: dict[str, DatasetRecord] = {}
        self._errors: list[dict[str, str]] = []
        self._overview_cache: dict[tuple[str, int], dict[str, Any]] = {}
        # Parsing every JSONL index on each short catalog TTL makes browsing a
        # large immutable dataset unnecessarily expensive.  Cache per-origin
        # records by the small authority files' stat signatures instead.
        self._origin_cache: dict[tuple[str, str], tuple[tuple[int, ...], DatasetRecord]] = {}

    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and time.monotonic() - self._last_scan < self.ttl_s:
                return
            records: dict[str, DatasetRecord] = {}
            errors: list[dict[str, str]] = []
            live_origins: set[tuple[str, str]] = set()
            for kind, root in self.roots:
                if not root.is_dir():
                    continue
                for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                    if not path.is_dir() or path.name.startswith(".") or path.is_symlink():
                        continue
                    if not (path / "index.jsonl").is_file():
                        continue
                    try:
                        config_stat = (path / "dataset_config.json").stat()
                        contract_stat = (path / "artifact_contract.json").stat()
                        index_stat = (path / "index.jsonl").stat()
                        stats_path = path / "quality" / "scene_statistics.json"
                        stats_stat = stats_path.stat() if stats_path.is_file() else None
                        overlay_path = self.statistics_root / f"{json.loads((path / 'dataset_config.json').read_text(encoding='utf-8')).get('dataset_fingerprint', '')}.json" if self.statistics_root else None
                        overlay_stat = overlay_path.stat() if overlay_path and overlay_path.is_file() else None
                        signature = (config_stat.st_mtime_ns, config_stat.st_size,
                                     contract_stat.st_mtime_ns, contract_stat.st_size,
                                     index_stat.st_mtime_ns, index_stat.st_size,
                                     stats_stat.st_mtime_ns if stats_stat else 0, stats_stat.st_size if stats_stat else 0,
                                     overlay_stat.st_mtime_ns if overlay_stat else 0, overlay_stat.st_size if overlay_stat else 0)
                        cache_key = (kind, str(path.resolve()))
                        live_origins.add(cache_key)
                        cached = self._origin_cache.get(cache_key)
                        base = cached[1] if cached and cached[0] == signature else load_dataset_origin(DatasetOrigin(kind, root, path), statistics_root=self.statistics_root)
                        # Deduplication below appends origins/warnings; do not
                        # retain that per-refresh merge state in the cache.
                        candidate = copy.copy(base)
                        candidate.origins = [candidate.primary]
                        candidate.warnings = list(base.warnings)
                        self._origin_cache[cache_key] = (signature, base)
                    except Exception as exc:  # catalog should retain other usable datasets
                        errors.append({"path": str(path), "error": str(exc)})
                        continue
                    current = records.get(candidate.fingerprint)
                    if current is None:
                        records[candidate.fingerprint] = candidate
                        continue
                    current.origins.append(candidate.primary)
                    # Published copies are canonical for browsing.
                    if candidate.primary.kind == "bean" and current.primary.kind != "bean":
                        candidate.origins = current.origins
                        records[candidate.fingerprint] = candidate
                    elif candidate.name != current.name:
                        current.warnings.append(f"same fingerprint also appears as {candidate.name}")
            self._origin_cache = {key: value for key, value in self._origin_cache.items() if key in live_origins}
            self._records = records
            self._errors = errors
            self._last_scan = time.monotonic()

    def list_payload(self, *, force: bool = False) -> dict[str, Any]:
        self.refresh(force=force)
        with self._lock:
            datasets = [record.summary() for record in self._records.values()]
            datasets.sort(key=lambda row: (not row["published"], row["name"].lower()))
            return {"datasets": datasets, "errors": list(self._errors), "roots": [
                {"kind": kind, "path": str(root)} for kind, root in self.roots
            ]}

    def get(self, dataset_id: str) -> DatasetRecord:
        self.refresh()
        with self._lock:
            record = self._records.get(dataset_id)
            if record is None:
                raise KeyError(dataset_id)
            return record

    def out_origin(self, dataset_id: str) -> DatasetOrigin:
        record = self.get(dataset_id)
        for origin in record.origins:
            if origin.kind == "out":
                return origin
        raise ValueError("dataset has no out origin")

    def publish_origin(self, dataset_id: str) -> DatasetOrigin:
        """Return a mutable, completed source eligible for immutable publish."""
        record = self.get(dataset_id)
        for kind in ("work", "out"):
            for origin in record.origins:
                if origin.kind == kind:
                    return origin
        raise ValueError("dataset has no work or out origin")

    def viewpoints_payload(self, dataset_id: str) -> dict[str, Any]:
        record = self.get(dataset_id)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in record.rows.values():
            viewpoint = str(row.get("viewpoint_id") or row["frame_id"].split("__", 1)[0])
            paths = row.get("paths") or {}
            grouped[viewpoint].append({
                "frame_id": row["frame_id"],
                "heading_deg": float(row.get("heading_deg") or 0.0),
                # The index is the compact catalog authority. Exact file availability
                # is checked when a frame is selected, avoiding tens of thousands of
                # NFS stat calls on every catalog refresh.
                "available": sorted(paths),
            })
        viewpoints = []
        for viewpoint_id, frames in grouped.items():
            frames.sort(key=lambda item: (item["heading_deg"], item["frame_id"]))
            viewpoints.append({"viewpoint_id": viewpoint_id, "frames": frames})
        viewpoints.sort(key=lambda item: item["viewpoint_id"])
        return {"dataset_id": dataset_id, "viewpoints": viewpoints}

    def scenes_payload(self, filters: dict[str, str]) -> dict[str, Any]:
        self.refresh()
        rows = [record.summary() for record in self._records.values()]
        text = filters.get("text", "").lower().strip()
        include_unknown = filters.get("include_unknown", "true").lower() not in {"0", "false", "no"}
        def number(name: str) -> float | None:
            try: return float(filters[name]) if filters.get(name, "") else None
            except ValueError: raise ValueError(f"{name} must be numeric")
        minimums = {"nonstructural_object_count": number("min_nonstructural"),
                    "object_count": number("min_total_objects"),
                    "nonstructural_objects_per_m2": number("min_objects_per_m2"),
                    "selected_visible_object_median": number("min_visible_objects"), "room_area_m2": number("min_area_m2")}
        max_sparse = number("max_sparse_fraction")
        max_area = number("max_area_m2")
        max_total_objects = number("max_total_objects")
        def accepts(row: dict[str, Any]) -> bool:
            stats = row["scene_statistics"]
            if text and text not in row["name"].lower() and text not in str(stats.get("room_type") or "").lower(): return False
            if filters.get("room_type") and stats.get("room_type") != filters["room_type"]: return False
            if filters.get("origin") and row["primary_origin"] != filters["origin"]: return False
            if filters.get("audit_status") and stats.get("content_audit_status") != filters["audit_status"]: return False
            wanted = {item for item in filters.get("density_class", "").split(",") if item}
            if wanted and stats.get("density_class") not in wanted: return False
            metal = {item for item in filters.get("metal_class", "").split(",") if item}
            if metal and stats.get("metal_class") not in metal: return False
            if not include_unknown and not stats.get("known"): return False
            for key, minimum in minimums.items():
                if minimum is not None and (stats.get(key) is None or float(stats[key]) < minimum): return False
            if max_area is not None and (stats.get("room_area_m2") is None or float(stats["room_area_m2"]) > max_area): return False
            if max_total_objects is not None and (stats.get("object_count") is None or float(stats["object_count"]) > max_total_objects): return False
            return not (max_sparse is not None and (stats.get("selected_sparse_pose_fraction") is None or float(stats["selected_sparse_pose_fraction"]) > max_sparse))
        rows = [row for row in rows if accepts(row)]
        sort = filters.get("sort", "name")
        key_map = {"name": lambda r: r["name"].lower(), "sparse": lambda r: (r["scene_statistics"].get("density_class") != "sparse", r["name"].lower()),
                   "objects": lambda r: -(r["scene_statistics"].get("nonstructural_object_count") or -1),
                   "visible": lambda r: -(r["scene_statistics"].get("selected_visible_object_median") or -1),
                   "area": lambda r: -(r["scene_statistics"].get("room_area_m2") or -1),
                   "density": lambda r: -(r["scene_statistics"].get("nonstructural_objects_per_m2") or -1),
                   "metal": lambda r: -(r["scene_statistics"].get("high_metallic_valid_pixel_fraction") or -1)}
        rows.sort(key=key_map.get(sort, key_map["name"]))
        all_stats = [record.summary()["scene_statistics"] for record in self._records.values()]
        known = [item for item in all_stats if item.get("known")]
        distribution = {name: sum(item.get("density_class") == name for item in all_stats) for name in ("sparse", "moderate", "dense", "unknown")}
        def median(key: str) -> float | None:
            values = sorted(float(item[key]) for item in known if item.get(key) is not None)
            return values[len(values)//2] if values else None
        facets = {
            "room_types": sorted({str(item["room_type"]) for item in known if item.get("room_type")}),
            "origins": sorted({str(record.summary()["primary_origin"]) for record in self._records.values()}),
            "audit_statuses": sorted({str(item["content_audit_status"]) for item in known if item.get("content_audit_status")}),
        }
        return {"scenes": rows, "total": len(all_stats), "filtered": len(rows), "distribution": distribution,
                "medians": {"objects_per_m2": median("nonstructural_objects_per_m2"), "visible_objects": median("selected_visible_object_median"),
                            "total_objects": median("object_count"), "nonstructural_objects": median("nonstructural_object_count"),
                            "room_area_m2": median("room_area_m2")}, "facets": facets}

    def scene_payload(self, dataset_id: str) -> dict[str, Any]:
        record = self.get(dataset_id)
        return {"scene": record.summary(), "statistics": record.scene_statistics,
                "browse_url": f"/?dataset={record.dataset_id}"}

    def frame_payload(self, dataset_id: str, frame_id: str) -> dict[str, Any]:
        record = self.get(dataset_id)
        row = record.rows.get(frame_id)
        if row is None:
            raise KeyError(frame_id)
        available = {}
        for name, rel in (row.get("paths") or {}).items():
            available[name] = (record.primary.path / str(rel)).is_file()
        return {"dataset": record.summary(), "frame": row, "available": available}

    def overview_payload(self, dataset_id: str) -> dict[str, Any]:
        """Return compact, self-contained camera/frustum metadata.

        Published v2 datasets predate the optional overview asset.  Their index
        still contains canonical camera poses, so pose-only inspection never
        needs to reach back into a mutable OpticalNav scene directory.
        """
        record = self.get(dataset_id)
        overview_path = record.primary.path / "scene_overview.json"
        overview_stat = overview_path.stat() if overview_path.is_file() else None
        cache_key = (record.dataset_id, record.index_mtime_ns,
                     overview_stat.st_mtime_ns if overview_stat else 0,
                     overview_stat.st_size if overview_stat else 0)
        with self._lock:
            cached = self._overview_cache.get(cache_key)
            if cached is not None:
                return cached
        if overview_path.is_file():
            overview = _read_json(_safe_artifact_path(record.primary.path, "scene_overview.json"))
            if overview.get("schema") != OVERVIEW_SCHEMA:
                raise ValueError("unsupported scene overview schema")
            if overview.get("dataset_fingerprint") != record.fingerprint:
                raise ValueError("scene overview fingerprint mismatch")
            _validate_overview(overview)
            result = {**overview, "dataset_id": record.dataset_id, "fallback": False}
        else:
            result = _overview_from_rows(record)
        with self._lock:
            self._overview_cache = {cache_key: result}
        return result


def _number3(value: Any, fallback: list[float]) -> list[float]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return [float(value[0]), float(value[1]), float(value[2])]
        except (TypeError, ValueError):
            pass
    return list(fallback)


def _validate_overview(overview: dict[str, Any]) -> None:
    if overview.get("coordinate_system") != "mitsuba_y_up":
        raise ValueError("scene overview coordinate system must be mitsuba_y_up")
    bounds = overview.get("bounds") or {}
    low, high = _number3(bounds.get("min"), []), _number3(bounds.get("max"), [])
    if len(low) != 3 or len(high) != 3 or not np.isfinite(low + high).all() or any(a > b for a, b in zip(low, high)):
        raise ValueError("scene overview bounds are invalid")
    for pose in overview.get("poses") or []:
        if not isinstance(pose, dict) or not str(pose.get("frame_id") or ""):
            raise ValueError("scene overview pose is invalid")
        vectors = _number3(pose.get("origin"), []) + _number3(pose.get("target"), []) + _number3(pose.get("up"), [])
        if len(vectors) != 9 or not np.isfinite(vectors).all():
            raise ValueError("scene overview pose vector is invalid")
        fov, aspect = float(pose.get("fov_deg") or 0), float(pose.get("aspect") or 0)
        if not 1.0 < fov < 179.0 or aspect <= 0.0 or not math.isfinite(fov + aspect):
            raise ValueError("scene overview camera FOV/aspect is invalid")
    proxy = overview.get("proxy_mesh")
    if proxy is not None:
        if not isinstance(proxy, dict) or proxy.get("coordinate_system") != "mitsuba_y_up":
            raise ValueError("scene overview proxy is invalid")
        _safe_artifact_relative_path(str(proxy.get("path") or ""))
        if int(proxy.get("triangles") or 0) < 1 or int(proxy.get("triangles") or 0) > 50_000:
            raise ValueError("scene overview proxy triangle count is invalid")
        if len(str(proxy.get("sha256") or "")) != 64:
            raise ValueError("scene overview proxy digest is invalid")
        proxy_bounds = proxy.get("bounds") or {}
        proxy_low, proxy_high = _number3(proxy_bounds.get("min"), []), _number3(proxy_bounds.get("max"), [])
        if len(proxy_low) != 3 or len(proxy_high) != 3 or not np.isfinite(proxy_low + proxy_high).all() or any(a > b for a, b in zip(proxy_low, proxy_high)):
            raise ValueError("scene overview proxy bounds are invalid")


def _overview_from_rows(record: DatasetRecord) -> dict[str, Any]:
    """Build a portable pose-only overview for immutable legacy datasets."""
    nodes: dict[str, dict[str, Any]] = {}
    poses: list[dict[str, Any]] = []
    lighting_ids: set[str] = set()
    for row in record.rows.values():
        camera = row.get("camera") or {}
        heading = float(row.get("heading_deg") or 0.0)
        radians = math.radians(heading)
        origin = _number3(camera.get("origin_mitsuba"), [0.0, 1.2, 0.0])
        target = _number3(camera.get("target_mitsuba"), [origin[0] + math.cos(radians), origin[1], origin[2] + math.sin(radians)])
        viewpoint_id = str(row.get("viewpoint_id") or row.get("frame_id", "").split("__", 1)[0])
        nodes.setdefault(viewpoint_id, {"viewpoint_id": viewpoint_id, "origin": origin})
        lighting = row.get("lighting") or {}
        lighting_id = str(lighting.get("id") or "legacy")
        lighting_ids.add(lighting_id)
        intrinsics = row.get("intrinsics") or {}
        width, height = max(1, int(row.get("width") or record.config.get("width") or 1)), max(1, int(row.get("height") or record.config.get("height") or 1))
        poses.append({
            "frame_id": str(row["frame_id"]), "viewpoint_id": viewpoint_id,
            "heading_deg": heading, "origin": origin, "target": target,
            "up": _number3(camera.get("up_mitsuba"), [0.0, 1.0, 0.0]),
            "fov_deg": float(row.get("fov_deg") or intrinsics.get("fov_deg") or record.config.get("fov") or 60.0),
            "aspect": width / height, "lighting_id": lighting_id,
        })
    points = [node["origin"] for node in nodes.values()]
    if points:
        array = np.asarray(points, dtype=np.float32)
        mins, maxs = array.min(axis=0), array.max(axis=0)
        margin = max(0.5, float(np.max(maxs[[0, 2]] - mins[[0, 2]]) * 0.08))
        bounds = {"min": [float(mins[0] - margin), float(mins[1]), float(mins[2] - margin)],
                  "max": [float(maxs[0] + margin), float(maxs[1]), float(maxs[2] + margin)]}
    else:
        bounds = {"min": [-1.0, 0.0, -1.0], "max": [1.0, 1.0, 1.0]}
    return {
        "schema": OVERVIEW_SCHEMA, "dataset_id": record.dataset_id, "dataset_fingerprint": record.fingerprint,
        "coordinate_system": "mitsuba_y_up", "graph_available": False, "traversability_available": False,
        "fallback": True, "bounds": bounds, "nodes": list(nodes.values()), "edges": [],
        "poses": poses, "lighting_ids": sorted(lighting_ids),
    }


def decode_artifact(path: Path, modality: str) -> tuple[np.ndarray, str]:
    import cv2

    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"cannot decode artifact: {path}")
    if value.ndim == 3 and value.shape[2] >= 3:
        value = value[..., :3][..., ::-1]
    if modality in HDR_MODALITIES:
        return np.asarray(value, dtype=np.float32), "scene_linear"
    if modality in LINEAR_RGB_MODALITIES:
        return np.asarray(value, dtype=np.float32) / 65535.0, "linear_rgb"
    if modality in SCALAR_MODALITIES:
        return np.asarray(value, dtype=np.float32) / 65535.0, "unit_interval"
    if modality in NORMAL_MODALITIES:
        decoded = np.asarray(value, dtype=np.float32) / 65535.0 * 2.0 - 1.0
        norm = np.linalg.norm(decoded, axis=-1, keepdims=True)
        decoded = np.where(norm > 1e-8, decoded / np.maximum(norm, 1e-8), decoded)
        return decoded, "world_xyz_unit"
    if modality in DISTANCE_MODALITIES:
        return np.asarray(value, dtype=np.float32) / 1000.0, "meters"
    if modality in ID_MODALITIES:
        return np.asarray(value, dtype=np.int32), "uint16_id"
    if modality in MASK_MODALITIES or modality.endswith("_mask"):
        return np.asarray(value > 0, dtype=np.bool_), "boolean"
    return np.asarray(value), str(value.dtype)


class DecodedRasterCache:
    def __init__(self, max_bytes: int = 512 * 1024**2):
        self.max_bytes = int(max_bytes)
        self._bytes = 0
        self._items: OrderedDict[tuple[str, str, int, int], tuple[np.ndarray, str]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, path: Path, modality: str) -> tuple[np.ndarray, str]:
        stat = path.stat()
        key = (str(path), modality, stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._items.pop(key, None)
            if cached is not None:
                self._items[key] = cached
                return cached
        decoded = decode_artifact(path, modality)
        with self._lock:
            self._items[key] = decoded
            self._bytes += int(decoded[0].nbytes)
            while self._bytes > self.max_bytes and self._items:
                _, old = self._items.popitem(last=False)
                self._bytes -= int(old[0].nbytes)
        return decoded


def _linear_to_srgb(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    return np.where(value <= 0.0031308, value * 12.92, 1.055 * np.power(value, 1.0 / 2.4) - 0.055)


def _as_rgb(value: np.ndarray) -> np.ndarray:
    if value.ndim == 2:
        return np.repeat(value[..., None], 3, axis=-1)
    if value.shape[-1] == 1:
        return np.repeat(value, 3, axis=-1)
    return value[..., :3]


def _id_palette(value: np.ndarray) -> np.ndarray:
    ids = value.astype(np.uint32)
    x = ids * np.uint32(2654435761)
    rgb = np.stack(((x >> 0) & 255, (x >> 8) & 255, (x >> 16) & 255), axis=-1).astype(np.uint8)
    rgb[ids == 0] = 0
    return rgb


def _preview_format(modality: str, requested: str) -> str:
    if requested not in {"auto", "png", "webp"}:
        raise ValueError("preview format must be auto, png, or webp")
    if requested == "png" or modality in ID_MODALITIES or modality in MASK_MODALITIES or modality.endswith("_mask"):
        return "png"
    return "webp" if requested in {"auto", "webp"} else "png"


def render_preview(array: np.ndarray, modality: str, *, exposure_ev: float = 0.0,
                   minimum: float = 0.0, maximum: float = 10.0,
                   overlay: np.ndarray | None = None, overlay_opacity: float = 0.45,
                   max_width: int | None = None, image_format: str = "png", quality: int = 88) -> bytes:
    import cv2

    if modality in HDR_MODALITIES:
        linear = np.nan_to_num(_as_rgb(array.astype(np.float32)), nan=0.0, posinf=0.0, neginf=0.0)
        linear = np.maximum(linear * float(2.0 ** exposure_ev), 0.0)
        mapped = linear / (1.0 + linear)
        rgb = np.rint(_linear_to_srgb(mapped) * 255.0).astype(np.uint8)
    elif modality in LINEAR_RGB_MODALITIES:
        rgb = np.rint(_linear_to_srgb(_as_rgb(array.astype(np.float32))) * 255.0).astype(np.uint8)
    elif modality in SCALAR_MODALITIES:
        gray = np.rint(np.clip(array.astype(np.float32), 0.0, 1.0) * 255.0).astype(np.uint8)
        rgb = _as_rgb(gray)
    elif modality in NORMAL_MODALITIES:
        rgb = np.rint(np.clip((array.astype(np.float32) + 1.0) * 0.5, 0.0, 1.0) * 255.0).astype(np.uint8)
    elif modality in DISTANCE_MODALITIES:
        denom = max(float(maximum) - float(minimum), 1e-8)
        scalar = np.clip((array.astype(np.float32) - float(minimum)) / denom, 0.0, 1.0)
        colored = cv2.applyColorMap(np.rint(scalar * 255.0).astype(np.uint8), cv2.COLORMAP_TURBO)
        rgb = colored[..., ::-1]
        rgb[array <= 0] = 0
    elif modality in ID_MODALITIES:
        rgb = _id_palette(array)
    elif modality in MASK_MODALITIES or modality.endswith("_mask"):
        gray = np.where(array, 255, 0).astype(np.uint8)
        rgb = _as_rgb(gray)
    else:
        value = np.asarray(array, dtype=np.float32)
        lo, hi = np.nanpercentile(value, [1.0, 99.0]) if value.size else (0.0, 1.0)
        gray = np.rint(np.clip((value - lo) / max(hi - lo, 1e-8), 0, 1) * 255).astype(np.uint8)
        rgb = _as_rgb(gray)
    if overlay is not None:
        mask = np.asarray(overlay, dtype=bool)
        alpha = float(np.clip(overlay_opacity, 0.0, 1.0))
        color = np.array([255, 55, 35], dtype=np.float32)
        rgb = rgb.astype(np.float32)
        rgb[mask] = rgb[mask] * (1.0 - alpha) + color * alpha
        rgb = np.rint(rgb).astype(np.uint8)
    if max_width and rgb.shape[1] > max_width:
        height = max(1, round(rgb.shape[0] * max_width / rgb.shape[1]))
        rgb = cv2.resize(rgb, (int(max_width), int(height)), interpolation=cv2.INTER_AREA)
    extension = ".webp" if image_format == "webp" else ".png"
    options = [cv2.IMWRITE_WEBP_QUALITY, int(quality)] if image_format == "webp" else []
    ok, encoded = cv2.imencode(extension, rgb[..., ::-1], options)
    if not ok:
        raise RuntimeError("OpenCV failed to encode preview")
    return encoded.tobytes()


class PreviewService:
    def __init__(self, catalog: DatasetCatalog, cache_dir: Path,
                 *, disk_max_bytes: int = 5 * 1024**3, memory_max_bytes: int = 512 * 1024**2):
        self.catalog = catalog
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.disk_max_bytes = int(disk_max_bytes)
        self.rasters = DecodedRasterCache(memory_max_bytes)
        self._lock = threading.RLock()

    def _artifact(self, dataset_id: str, frame_id: str, modality: str) -> tuple[DatasetRecord, Path]:
        record = self.catalog.get(dataset_id)
        row = record.rows.get(frame_id)
        if row is None:
            raise KeyError(frame_id)
        relative = (row.get("paths") or {}).get(modality)
        if not relative:
            raise KeyError(modality)
        return record, _safe_artifact_path(record.primary.path, str(relative))

    def _descriptor(self, dataset_id: str, frame_id: str, modality: str, *, exposure_ev: float = 0.0,
                    minimum: float = 0.0, maximum: float = 10.0, overlay_modality: str | None = None,
                    overlay_opacity: float = 0.45, max_width: int | None = None,
                    image_format: str = "png") -> tuple[DatasetRecord, Path, Path | None, str, Path]:
        """Resolve an immutable cache key without decoding or reading preview bytes."""
        image_format = _preview_format(modality, image_format)
        record, path = self._artifact(dataset_id, frame_id, modality)
        stat = path.stat()
        params = {
            "fingerprint": record.fingerprint, "path": str(path), "mtime": stat.st_mtime_ns,
            "size": stat.st_size, "modality": modality, "ev": round(float(exposure_ev), 4),
            "minimum": round(float(minimum), 6), "maximum": round(float(maximum), 6),
            "overlay": overlay_modality, "overlay_opacity": round(float(overlay_opacity), 3),
            "max_width": max_width, "tonemap": "reinhard_srgb_v1",
            "encoder": f"{image_format}_q88_v1",
        }
        overlay_path = None
        if overlay_modality:
            _, overlay_path = self._artifact(dataset_id, frame_id, overlay_modality)
            overlay_stat = overlay_path.stat()
            params["overlay_source"] = {"path": str(overlay_path), "mtime": overlay_stat.st_mtime_ns, "size": overlay_stat.st_size}
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        return record, path, overlay_path, key, self.cache_dir / key[:2] / f"{key}.{image_format}"

    def etag(self, dataset_id: str, frame_id: str, modality: str, **kwargs: Any) -> tuple[str, str, bool]:
        record, _, _, key, _ = self._descriptor(dataset_id, frame_id, modality, **kwargs)
        return key, _preview_format(modality, str(kwargs.get("image_format") or "png")), record.primary.kind == "bean"

    def preview(self, dataset_id: str, frame_id: str, modality: str, *, exposure_ev: float = 0.0,
                minimum: float = 0.0, maximum: float = 10.0, overlay_modality: str | None = None,
                overlay_opacity: float = 0.45, max_width: int | None = None,
                image_format: str = "png") -> tuple[bytes, str]:
        _, path, overlay_path, key, cached = self._descriptor(
            dataset_id, frame_id, modality, exposure_ev=exposure_ev, minimum=minimum, maximum=maximum,
            overlay_modality=overlay_modality, overlay_opacity=overlay_opacity, max_width=max_width,
            image_format=image_format,
        )
        if cached.is_file():
            os.utime(cached, None)
            return cached.read_bytes(), key
        array, _ = self.rasters.get(path, modality)
        overlay = None
        if overlay_modality and overlay_path is not None:
            overlay, _ = self.rasters.get(overlay_path, overlay_modality)
        data = render_preview(array, modality, exposure_ev=exposure_ev, minimum=minimum, maximum=maximum,
                              overlay=overlay, overlay_opacity=overlay_opacity, max_width=max_width,
                              image_format=_preview_format(modality, image_format))
        with self._lock:
            cached.parent.mkdir(parents=True, exist_ok=True)
            temporary = cached.with_suffix(".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, cached)
            self._prune_disk_cache()
        return data, key

    def pixels(self, dataset_id: str, frame_id: str, x: int, y: int,
               modalities: Iterable[str]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        width = height = None
        for modality in dict.fromkeys(modalities):
            try:
                _, path = self._artifact(dataset_id, frame_id, modality)
                array, unit = self.rasters.get(path, modality)
            except (KeyError, FileNotFoundError):
                values[modality] = {"available": False}
                continue
            height, width = array.shape[:2]
            if x < 0 or y < 0 or x >= width or y >= height:
                raise ValueError(f"pixel ({x}, {y}) outside {width}x{height}")
            value = array[y, x]
            if isinstance(value, np.ndarray):
                decoded: Any = [float(v) if np.issubdtype(value.dtype, np.floating) else int(v) for v in value.tolist()]
            elif np.issubdtype(np.asarray(value).dtype, np.bool_):
                decoded = bool(value)
            elif np.issubdtype(np.asarray(value).dtype, np.floating):
                decoded = float(value)
            else:
                decoded = int(value)
            values[modality] = {"available": True, "value": decoded, "unit": unit}
        return {"frame_id": frame_id, "x": x, "y": y, "width": width, "height": height, "values": values}

    def _prune_disk_cache(self) -> None:
        files = [path for path in self.cache_dir.glob("*/*")
                 if path.is_file() and path.suffix in {".png", ".webp"}]
        total = sum(path.stat().st_size for path in files)
        if total <= self.disk_max_bytes:
            return
        for path in sorted(files, key=lambda item: item.stat().st_atime_ns):
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
            if total <= self.disk_max_bytes:
                break


def default_exposure(record: DatasetRecord, modality: str) -> float:
    exposures = record.contract.get("exposure_ev") or record.config.get("exposure_ev") or {}
    if modality == "rgb" or modality.endswith("_rgb"):
        return float(exposures.get("rgb", 0.0))
    if modality == "nir_active" or modality.endswith("_nir"):
        return float(exposures.get("nir_active", 0.0))
    return 0.0
