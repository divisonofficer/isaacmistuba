#!/usr/bin/env python3
"""Audit place-catalog assets for texture-modulated measured pBRDF readiness.

The audit opens each selected/placeable USD asset, extracts per-child mesh parts
into a temporary OBJ cache, reads USD material bindings, and simulates the render
material selection used by render_daemon. It reports whether the asset is ready
for the texture-modulated measured-BRDF path or needs catalog/material work.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "navigation_dataset" / "src",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from robomituba_bridge.paths import resolve_repo_path  # noqa: E402
from mitsuba_converter.render_daemon import (  # noqa: E402
    _infer_material_class,
    _material_index,
    _select_part_render_material,
    _should_emit_asset_mesh_part,
)
from mitsuba_converter.glb_texture_adapter import materialize_glb_texture_parts  # noqa: E402
from mitsuba_converter.usd_material_extract import extract_material_for_prim  # noqa: E402
from mitsuba_converter.usd_prim_obj import extract_prim_mesh_to_obj  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _type_for_asset(asset: dict[str, Any]) -> str:
    key = " ".join(str(asset.get(k) or "") for k in ("label", "source_path", "category")).lower()
    if "chair" in key or "seat" in key:
        return "chair"
    if "table" in key or "desk" in key:
        return "table"
    if any(tok in key for tok in ("cabinet", "shelf", "bookcase", "bookshelf", "sideboard")):
        return "shelf"
    if "plant" in key or "palm" in key or "succulent" in key:
        return "plant"
    return "landmark"



def _dtc_category_from_name(name: str) -> str:
    key = name.lower()
    for category, tokens in {
        "furniture": ("chair", "table", "desk", "sofa", "stool", "cabinet", "shelf"),
        "electronics": ("camera", "phone", "laptop", "keyboard", "remote", "mouse", "monitor", "screen", "speaker"),
        "kitchenware": ("cup", "bowl", "plate", "mug", "pan", "pot", "bottle", "spoon", "knife", "dish", "teapot"),
        "tool": ("hammer", "key", "tool"),
        "plant": ("plant", "vase"),
        "object": (),
    }.items():
        if any(token in key for token in tokens):
            return category
    return "object"


def _dtc_material_hint_from_name(name: str) -> str:
    key = name.lower()
    if any(tok in key for tok in ("metal", "chrome", "steel", "hammer", "key", "dumbbell", "can_")):
        return "metal"
    if any(tok in key for tok in ("ceramic", "teapot", "bowl", "dish", "vase", "pottery")):
        return "ceramic"
    if any(tok in key for tok in ("marker", "plastic", "bottle", "spoon", "knife")):
        return "plastic"
    return "pbrdf_2020:white_billiard"


def _discover_dtc_assets(repo_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    root = repo_root / "vendor_datasets" / "dtc_objects"
    if not root.exists():
        return out
    import hashlib
    for glb in sorted(root.rglob("3d-asset.glb")):
        try:
            source_ref = glb.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        name = glb.parent.name
        digest = hashlib.sha1(source_ref.encode("utf-8")).hexdigest()[:12]
        metadata_path = glb.parent / "metadata.json"
        label = name.replace("_", " ").replace("-", " ").strip()
        try:
            if metadata_path.exists():
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                for key in ("name", "object_name", "label", "title"):
                    if isinstance(meta, dict) and meta.get(key):
                        label = str(meta[key])
                        break
        except Exception:
            pass
        out.append({
            "asset_id": f"dtc_asset_{digest}",
            "label": label,
            "category": _dtc_category_from_name(name),
            "material_hint": _dtc_material_hint_from_name(name),
            "source_ref": source_ref,
            "source_type": "dtc_glb_object",
            "source_dataset": "DigitalTwinCatalog",
            "source_format": "glb",
            "selected": True,
            "_catalog_ref": "auto:dtc_glb_discovery",
        })
    return out

def _load_catalog_assets(repo_root: Path, *, active_only: bool) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    catalog_dir = repo_root / "out" / "opticalnav" / "asset_library" / "catalogs"
    for path in sorted(catalog_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for asset in payload.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            if active_only and asset.get("selected") is False:
                continue
            item = dict(asset)
            item["_catalog_ref"] = path.relative_to(repo_root).as_posix()
            assets.append(item)
    seen_refs = {str(asset.get("source_ref") or "") for asset in assets}
    for item in _discover_dtc_assets(repo_root):
        if str(item.get("source_ref") or "") in seen_refs:
            continue
        if active_only and item.get("selected") is False:
            continue
        assets.append(item)
    if assets:
        return assets

    # Fallback: manifests before API import has generated catalogs.
    curated_dir = repo_root / "assets" / "opticalnav_curated"
    for path in sorted(curated_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        source_usd = str(payload.get("source_usd") or "")
        for raw in payload.get("assets") or []:
            if not isinstance(raw, dict) or not raw.get("source_path"):
                continue
            item = dict(raw)
            item.setdefault("asset_id", item.get("source_path", "").rsplit("/", 1)[-1])
            item["usd_ref"] = source_usd
            item["source_ref"] = f"{source_usd}#{item['source_path']}"
            item["source_type"] = "curated_usd_asset"
            item["source_dataset"] = "MooreLane"
            item["selected"] = bool(item.get("selected", item.get("use", True)))
            item["_catalog_ref"] = path.relative_to(repo_root).as_posix()
            if active_only and item.get("selected") is False:
                continue
            assets.append(item)
    return assets


def _material_dict(stage: Any, prim_path: str, usd_abs: Path, scene_tmp: Path) -> dict[str, Any] | None:
    prim = stage.GetPrimAtPath(prim_path)
    em = extract_material_for_prim(prim, stage=stage, usd_path=usd_abs)
    if em is None:
        return None
    em_dict = em.to_dict()
    em_dict["source"] = "usd_prim"

    def resolve_asset(raw: str | None) -> str | None:
        if not raw:
            return None
        p = Path(str(raw))
        if p.is_absolute():
            return str(p) if p.exists() else None
        # USD material asset paths are usually relative to the USD file dir.
        candidates = [usd_abs.parent / p, REPO_ROOT / p]
        for c in candidates:
            if c.exists():
                try:
                    return c.relative_to(REPO_ROOT).as_posix()
                except Exception:
                    return str(c)
        return None

    em_dict["base_color_texture_ref"] = resolve_asset(em.base_color_asset)
    em_dict["normal_texture_ref"] = resolve_asset(em.normal_asset)
    em_dict["roughness_texture_ref"] = resolve_asset(em.roughness_asset)
    return em_dict


@dataclass
class PartAudit:
    part_id: str
    mesh_name: str
    mesh_prim_path: str
    emitted: bool
    triangle_count: int
    material_class: str | None
    render_material_id: str | None
    has_base_texture: bool
    has_base_factor: bool
    has_normal_texture: bool
    has_roughness_texture: bool
    texture_ref: str | None


@dataclass
class AssetAudit:
    asset_id: str
    label: str
    category: str | None
    placement_type: str
    source_ref: str
    status: str
    render_readiness: str
    ready: bool
    usable_by_agent: bool
    reason: str
    mesh_part_count: int = 0
    emitted_part_count: int = 0
    textured_emitted_parts: int = 0
    measured_emitted_parts: int = 0
    factor_emitted_parts: int = 0
    dropped_part_count: int = 0
    material_classes: dict[str, int] | None = None
    render_materials: dict[str, int] | None = None
    notes: list[str] | None = None
    parts: list[PartAudit] | None = None



def _status_to_readiness(status: str, reason: str) -> tuple[str, bool, bool]:
    if status == "ready":
        return "texture_ready", True, True
    if status == "not_applicable":
        return "analytic_ok", True, True
    if status == "partial":
        return "partial", False, False
    if status in {"blocked", "error"}:
        return "blocked", False, False
    return "unknown", False, False


def _asset_audit(
    asset_id: str,
    label: str,
    category: str | None,
    placement_type: str,
    source_ref: str,
    status: str,
    reason: str,
    **kwargs: Any,
) -> AssetAudit:
    render_readiness, ready, usable_by_agent = _status_to_readiness(status, reason)
    return AssetAudit(
        asset_id=asset_id,
        label=label,
        category=category,
        placement_type=placement_type,
        source_ref=source_ref,
        status=status,
        render_readiness=render_readiness,
        ready=ready,
        usable_by_agent=usable_by_agent,
        reason=reason,
        **kwargs,
    )

def audit_glb_asset(asset: dict[str, Any], tmp_root: Path, material_idx: dict[str, dict[str, Any]]) -> AssetAudit:
    asset_id = str(asset.get("asset_id") or asset.get("id") or "asset")
    label = str(asset.get("label") or asset_id)
    source_ref = str(asset.get("source_ref") or "")
    try:
        glb_abs = resolve_repo_path(REPO_ROOT, source_ref)
    except Exception:
        glb_abs = Path(source_ref)
    if not glb_abs.exists():
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", "glb_missing")

    try:
        import trimesh  # type: ignore
        scene = trimesh.load(str(glb_abs), force="scene")
    except Exception as exc:
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", f"glb_load_failed:{exc}")

    geometries = getattr(scene, "geometry", None)
    if isinstance(geometries, dict):
        geom_items = [(str(name), mesh) for name, mesh in geometries.items()]
    else:
        geom_items = [("mesh", scene)]
    geom_items = [
        (name, mesh) for name, mesh in geom_items
        if hasattr(mesh, "vertices") and hasattr(mesh, "faces") and len(getattr(mesh, "vertices", [])) > 0 and len(getattr(mesh, "faces", [])) > 0
    ]
    if not geom_items:
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", "no_geometry")

    def _has_texture(mat: Any, name: str) -> bool:
        try:
            return getattr(mat, name, None) is not None
        except Exception:
            return False

    def _main_color(mat: Any) -> list[float] | None:
        raw = getattr(mat, "main_color", None)
        if raw is None:
            return None
        try:
            vals = list(raw)
            return [max(0.0, min(1.0, float(v) / 255.0)) for v in vals[:3]]
        except Exception:
            return None

    metadata = dict(asset.get("metadata") or {})
    metadata.setdefault("asset_category", asset.get("category"))
    metadata.setdefault("asset_id", asset_id)
    metadata.setdefault("asset_source_ref", source_ref)
    obj = {
        "id": asset_id,
        "type": _type_for_asset(asset),
        "label": label,
        "material": asset.get("material_hint"),
        "metadata": metadata,
        "source_ref": source_ref,
    }
    parts: list[PartAudit] = []
    material_classes: Counter[str] = Counter()
    render_materials: Counter[str] = Counter()
    texture_slot_counts: Counter[str] = Counter()
    for index, (name, mesh) in enumerate(geom_items):
        visual = getattr(mesh, "visual", None)
        mat = getattr(visual, "material", None)
        material_name = str(getattr(mat, "name", "") or f"material_{index}") if mat is not None else f"material_{index}"
        has_base = bool(mat is not None and _has_texture(mat, "baseColorTexture"))
        has_normal = bool(mat is not None and _has_texture(mat, "normalTexture"))
        has_mr = bool(mat is not None and _has_texture(mat, "metallicRoughnessTexture"))
        if has_base:
            texture_slot_counts["base_color"] += 1
        if has_normal:
            texture_slot_counts["normal"] += 1
        if has_mr:
            texture_slot_counts["metallic_roughness"] += 1
        em = {
            "source": "glb_pbr",
            "material_id": material_name,
            "surface_shader_id": "glTF.PBR",
            "base_color_factor": _main_color(mat) if mat is not None else None,
            "base_color_texture_ref": f"embedded://{asset_id}/{index}/base_color" if has_base else None,
            "normal_texture_ref": f"embedded://{asset_id}/{index}/normal" if has_normal else None,
            "metallic_roughness_texture_ref": f"embedded://{asset_id}/{index}/metallic_roughness" if has_mr else None,
            "metallic_factor": getattr(mat, "metallicFactor", None) if mat is not None else None,
            "roughness_factor": getattr(mat, "roughnessFactor", None) if mat is not None else None,
        }
        part = {
            "part_id": f"part_{index:03d}_{name}",
            "mesh_name": name,
            "mesh_prim_path": f"/GLB/{name}",
            "triangle_count": int(len(getattr(mesh, "faces", []))),
            "extracted_material": em,
            "asset_category": metadata.get("asset_category"),
            "object_type": obj.get("type"),
            "object_material": obj.get("material"),
            "source_ref": source_ref,
        }
        emitted = _should_emit_asset_mesh_part(obj, part)
        selected_material, material_class = _select_part_render_material(
            str(asset.get("material_hint") or "") or None,
            part,
            em,
            material_idx,
            repo_root=REPO_ROOT,
        )
        if emitted:
            material_classes[material_class or "unknown"] += 1
            render_materials[selected_material or "none"] += 1
        parts.append(PartAudit(
            part_id=str(part.get("part_id") or ""),
            mesh_name=name,
            mesh_prim_path=str(part.get("mesh_prim_path") or ""),
            emitted=bool(emitted),
            triangle_count=int(part.get("triangle_count") or 0),
            material_class=material_class,
            render_material_id=selected_material,
            has_base_texture=has_base,
            has_base_factor=bool(em.get("base_color_factor")),
            has_normal_texture=has_normal,
            has_roughness_texture=has_mr,
            texture_ref=em.get("base_color_texture_ref"),
        ))

    emitted_parts = [p for p in parts if p.emitted]
    textured = [p for p in emitted_parts if p.has_base_texture]
    factored = [p for p in emitted_parts if p.has_base_factor and not p.has_base_texture]
    measured = [p for p in emitted_parts if p.render_material_id and (p.render_material_id.startswith("hpbrdf_2025:") or p.render_material_id.startswith("pbrdf_2020:"))]
    dropped = [p for p in parts if not p.emitted]
    analytic_expected = bool(emitted_parts) and all((p.material_class in {"glass", "metal"}) for p in emitted_parts)
    notes = [f"glb_texture_slots={dict(texture_slot_counts)}"]
    if dropped:
        notes.append(f"filtered_parts={len(dropped)}")
    if not emitted_parts:
        status, reason = "blocked", "no_emitted_parts"
    elif analytic_expected and not measured:
        status, reason = "not_applicable", "analytic_glass_or_metal_expected"
    elif not measured:
        status, reason = "blocked", "no_measured_or_pbrdf_material"
    elif textured:
        status, reason = "ready", "texture_modulated_measured"
    elif factored:
        status, reason = "partial", "factor_modulated_measured_no_bitmap"
    else:
        status, reason = "partial", "measured_without_asset_albedo"

    return _asset_audit(
        asset_id,
        label,
        asset.get("category"),
        obj["type"],
        source_ref,
        status,
        reason,
        mesh_part_count=len(parts),
        emitted_part_count=len(emitted_parts),
        textured_emitted_parts=len(textured),
        measured_emitted_parts=len(measured),
        factor_emitted_parts=len(factored),
        dropped_part_count=len(dropped),
        material_classes=dict(material_classes),
        render_materials=dict(render_materials),
        notes=notes,
        parts=parts,
    )


def audit_asset(asset: dict[str, Any], tmp_root: Path, stage_cache: dict[str, Any], material_idx: dict[str, dict[str, Any]]) -> AssetAudit:
    asset_id = str(asset.get("asset_id") or asset.get("id") or "asset")
    label = str(asset.get("label") or asset_id)
    source_ref = str(asset.get("source_ref") or "")
    if "#" not in source_ref:
        if source_ref.lower().endswith((".glb", ".gltf")):
            return audit_glb_asset(asset, tmp_root, material_idx)
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", "missing_source_ref")
    usd_ref, prim_path = source_ref.split("#", 1)
    try:
        usd_abs = resolve_repo_path(REPO_ROOT, usd_ref)
    except Exception as exc:
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", f"usd_resolve_failed:{exc}")
    if not usd_abs.exists():
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", "usd_missing")
    try:
        from pxr import Usd  # type: ignore
    except Exception as exc:
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", f"pxr_unavailable:{exc}")

    stage = stage_cache.get(str(usd_abs))
    if stage is None:
        stage = Usd.Stage.Open(str(usd_abs))
        stage_cache[str(usd_abs)] = stage
    if stage is None or not stage.GetPrimAtPath(prim_path):
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", "prim_missing")

    out_obj = tmp_root / f"{asset_id}.obj"
    try:
        stats = extract_prim_mesh_to_obj(usd_abs, prim_path, out_obj, stage=stage)
    except Exception as exc:
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", f"extract_failed:{exc}")
    if stats is None:
        return _asset_audit(asset_id, label, asset.get("category"), _type_for_asset(asset), source_ref, "error", "no_mesh")

    metadata = dict(asset.get("metadata") or {})
    metadata.setdefault("asset_category", asset.get("category"))
    metadata.setdefault("asset_id", asset_id)
    metadata.setdefault("asset_source_ref", source_ref)
    obj = {
        "id": asset_id,
        "type": _type_for_asset(asset),
        "label": label,
        "material": asset.get("material_hint"),
        "metadata": metadata,
        "source_ref": source_ref,
    }
    parts: list[PartAudit] = []
    notes: list[str] = []
    material_classes: Counter[str] = Counter()
    render_materials: Counter[str] = Counter()

    for raw_part in stats.to_dict().get("mesh_parts") or []:
        part = dict(raw_part)
        em = _material_dict(stage, str(part.get("mesh_prim_path") or ""), usd_abs, tmp_root)
        part["extracted_material"] = em
        part["asset_category"] = metadata.get("asset_category")
        part["object_type"] = obj.get("type")
        part["object_material"] = obj.get("material")
        part["source_ref"] = source_ref
        part["material_class"] = _infer_material_class(part, em)
        emitted = _should_emit_asset_mesh_part(obj, part)
        selected_material, material_class = _select_part_render_material(
            str(asset.get("material_hint") or "") or None,
            part,
            em,
            material_idx,
            repo_root=REPO_ROOT,
        )
        if emitted:
            material_classes[material_class or "unknown"] += 1
            render_materials[selected_material or "none"] += 1
        has_base_texture = bool((em or {}).get("base_color_texture_ref"))
        has_base_factor = bool((em or {}).get("base_color_factor"))
        parts.append(PartAudit(
            part_id=str(part.get("part_id") or ""),
            mesh_name=str(part.get("mesh_name") or ""),
            mesh_prim_path=str(part.get("mesh_prim_path") or ""),
            emitted=bool(emitted),
            triangle_count=int(part.get("triangle_count") or 0),
            material_class=material_class,
            render_material_id=selected_material,
            has_base_texture=has_base_texture,
            has_base_factor=has_base_factor,
            has_normal_texture=bool((em or {}).get("normal_texture_ref")),
            has_roughness_texture=bool((em or {}).get("roughness_texture_ref")),
            texture_ref=(em or {}).get("base_color_texture_ref"),
        ))

    emitted_parts = [p for p in parts if p.emitted]
    textured = [p for p in emitted_parts if p.has_base_texture]
    factored = [p for p in emitted_parts if p.has_base_factor and not p.has_base_texture]
    measured = [p for p in emitted_parts if p.render_material_id and (p.render_material_id.startswith("hpbrdf_2025:") or p.render_material_id.startswith("pbrdf_2020:"))]
    dropped = [p for p in parts if not p.emitted]

    if dropped:
        notes.append(f"filtered_parts={len(dropped)}")
    analytic_expected = bool(emitted_parts) and all((p.material_class in {"glass", "metal"}) for p in emitted_parts)
    if not emitted_parts:
        status, ready, reason = "blocked", False, "no_emitted_parts"
    elif analytic_expected and not measured:
        status, ready, reason = "not_applicable", True, "analytic_glass_or_metal_expected"
    elif not measured:
        status, ready, reason = "blocked", False, "no_measured_or_pbrdf_material"
    elif textured:
        status, ready, reason = "ready", True, "texture_modulated_measured"
    elif factored:
        status, ready, reason = "partial", False, "factor_modulated_measured_no_bitmap"
    else:
        status, ready, reason = "partial", False, "measured_without_asset_albedo"

    return _asset_audit(
        asset_id,
        label,
        asset.get("category"),
        obj["type"],
        source_ref,
        status,
        reason,
        mesh_part_count=len(parts),
        emitted_part_count=len(emitted_parts),
        textured_emitted_parts=len(textured),
        measured_emitted_parts=len(measured),
        factor_emitted_parts=len(factored),
        dropped_part_count=len(dropped),
        material_classes=dict(material_classes),
        render_materials=dict(render_materials),
        notes=notes,
        parts=parts,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--active-only", action=argparse.BooleanOptionalAction, default=False)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--asset-id", action="append", default=[])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "out" / "opticalnav" / "asset_library" / "asset_readiness.json")
    ap.add_argument("--legacy-out", type=Path, default=None, help="Optional compatibility copy of the full audit payload.")
    args = ap.parse_args()

    assets = _load_catalog_assets(REPO_ROOT, active_only=args.active_only)
    if args.asset_id:
        wanted = set(args.asset_id)
        assets = [a for a in assets if str(a.get("asset_id")) in wanted]
    if args.limit and args.limit > 0:
        assets = assets[:args.limit]
    material_idx = _material_index({"materials": []})
    stage_cache: dict[str, Any] = {}
    audits: list[AssetAudit] = []
    with tempfile.TemporaryDirectory(prefix="robomituba_asset_audit_") as tmp:
        tmp_root = Path(tmp)
        for i, asset in enumerate(assets, 1):
            print(f"[{i}/{len(assets)}] {asset.get('asset_id')} {asset.get('label')}")
            audits.append(audit_asset(asset, tmp_root, stage_cache, material_idx))

    summary = Counter(a.render_readiness for a in audits)
    legacy_summary = Counter(a.status for a in audits)
    reason_counts = Counter(a.reason for a in audits)
    payload = {
        "schema_version": 1,
        "generated_at": _utc_now_iso(),
        "asset_count": len(audits),
        "summary": dict(summary),
        "legacy_status_summary": dict(legacy_summary),
        "reason_counts": dict(reason_counts),
        "usable_statuses": ["texture_ready", "analytic_ok"],
        "assets": [
            {
                **{k: v for k, v in asdict(a).items() if k != "parts"},
                "parts": [asdict(p) for p in (a.parts or [])],
            }
            for a in audits
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.legacy_out is not None:
        args.legacy_out.parent.mkdir(parents=True, exist_ok=True)
        args.legacy_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("summary", dict(summary))
    print("legacy_status", dict(legacy_summary))
    print("reasons", dict(reason_counts))
    print("out", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
