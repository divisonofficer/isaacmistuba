#!/usr/bin/env python3
"""Auto-link OpticalNav authoring objects to curated asset source_refs.

This is intentionally conservative: it only writes source_ref for point objects
that have no source_ref and whose best catalog match is comfortably above the
score threshold. Ambiguous or unsupported objects are reported but left alone.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = "opticalnav-v0.2"
DEFAULT_SCENE = "cglab_conference_room"
CURATED_DIR = REPO_ROOT / "assets" / "opticalnav_curated"

_TOKEN_ALIASES = {
    "의자": "chair",
    "테이블": "table",
    "회의": "conference",
    "회의테이블": "table",
    "소파": "couch",
    "화이트보드": "whiteboard",
    "유리": "glass",
    "유리벽": "glass window",
    "유리창문": "glass window",
    "유리문": "glass door",
    "여닫이문": "door",
    "문": "door",
    "공기청정기": "air purifier appliance",
    "제습기": "dehumidifier appliance",
    "조명": "light lamp",
    "천장": "ceiling",
    "철기둥": "pillar metal",
    "기둥": "pillar metal",
    "대형": "large",
    "소형": "small",
    "책": "books",
    "화분": "plant pot",
}

_EXCLUDE_TYPES = {"wall", "glass_wall", "glass_door", "mirror_wall", "transparent_partition"}
_EXCLUDE_ID_PREFIXES = ("pillar_", "ceil_light_")

# High-confidence scene/domain hints. These only select from the catalog; they
# do not invent source_refs outside known curated assets.
_EXPLICIT_ASSET_HINTS: tuple[tuple[tuple[str, ...], str, int], ...] = (
    (("main", "couch"), "moorelane_living_main_couch", 120),
    (("couch",), "moorelane_living_main_couch", 110),
    (("sofa",), "moorelane_living_main_couch", 110),
    (("dining", "table", "chair"), "moorelane_dining_table_set", 110),
    (("chair",), "moorelane_living_accent_armchair", 92),
    (("armchair",), "moorelane_living_accent_armchair", 100),
    (("glass", "door"), "moorelane_glass_door", 80),
    (("glass", "window"), "moorelane_glass_front_left", 72),
    (("whiteboard",), "moorelane_art_studio_wide", 25),
    (("books",), "moorelane_living_bookshelf_books", 75),
    (("plant",), "moorelane_living_potted_palm", 78),
)


@dataclass
class AssetCandidate:
    asset_id: str
    label: str
    source_ref: str
    category: str
    material_hint: str | None
    tags: list[str]
    bounds_size: list[float] | None
    manifest_ref: str | None
    raw: dict[str, Any]


@dataclass
class LinkDecision:
    object_id: str
    label: str
    object_type: str
    current_source_ref: str | None
    action: str
    asset_id: str | None = None
    source_ref: str | None = None
    asset_category: str | None = None
    material_hint: str | None = None
    score: float = 0.0
    reason: str = ""
    alternatives: list[dict[str, Any]] | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tokens(value: Any) -> set[str]:
    text = str(value or "").lower()
    for src, repl in _TOKEN_ALIASES.items():
        text = text.replace(src.lower(), f" {repl} ")
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    raw = re.findall(r"[a-z0-9가-힣]+", text)
    out: set[str] = set()
    for tok in raw:
        out.add(tok)
        if tok.endswith("s") and len(tok) > 3:
            out.add(tok[:-1])
    return out


def _object_tokens(obj: dict[str, Any]) -> set[str]:
    fields = [obj.get("id"), obj.get("type"), obj.get("label"), obj.get("material")]
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    fields.extend([meta.get("semantic"), meta.get("asset_hint"), meta.get("asset_id")])
    toks: set[str] = set()
    for field in fields:
        toks |= _tokens(field)
    return toks


def _asset_tokens(asset: AssetCandidate) -> set[str]:
    toks = _tokens(asset.asset_id) | _tokens(asset.label) | _tokens(asset.category) | _tokens(asset.material_hint)
    for tag in asset.tags:
        toks |= _tokens(tag)
    toks |= _tokens(asset.raw.get("description")) | _tokens(asset.raw.get("source_path"))
    return toks


def _load_curated_assets(repo_root: Path) -> list[AssetCandidate]:
    assets: list[AssetCandidate] = []
    root = repo_root / "assets" / "opticalnav_curated"
    for manifest in sorted(root.glob("*.json")):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        source_usd = str(payload.get("source_usd") or "")
        if not source_usd:
            continue
        for item in payload.get("assets") or []:
            if not isinstance(item, dict):
                continue
            source_path = str(item.get("source_path") or "")
            if not source_path:
                continue
            bounds = item.get("bounds") if isinstance(item.get("bounds"), dict) else {}
            size = bounds.get("size") if isinstance(bounds, dict) else None
            try:
                bounds_size = [float(v) for v in list(size or [])[:3]] if size else None
            except Exception:
                bounds_size = None
            asset_id = str(item.get("asset_id") or source_path.rsplit("/", 1)[-1])
            assets.append(AssetCandidate(
                asset_id=asset_id,
                label=str(item.get("label") or asset_id),
                source_ref=f"{source_usd}#{source_path}",
                category=str(item.get("category") or "object"),
                material_hint=str(item.get("material_hint")) if item.get("material_hint") else None,
                tags=[str(t) for t in item.get("tags", [])],
                bounds_size=bounds_size,
                manifest_ref=manifest.relative_to(repo_root).as_posix(),
                raw=dict(item),
            ))
    return assets


def _size_similarity(obj: dict[str, Any], asset: AssetCandidate) -> float:
    geom = obj.get("geometry") if isinstance(obj.get("geometry"), dict) else {}
    obj_size = geom.get("size_m") if isinstance(geom, dict) else None
    if not isinstance(obj_size, list) or len(obj_size) < 3 or not asset.bounds_size:
        return 0.0
    try:
        a = [max(1e-3, float(v)) for v in obj_size[:3]]
        b = [max(1e-3, float(v)) for v in asset.bounds_size[:3]]
    except Exception:
        return 0.0
    # Ignore axis swaps in floor plane by comparing sorted X/Z footprint plus height.
    obj_sig = [min(a[0], a[2]), max(a[0], a[2]), a[1]]
    ast_sig = [min(b[0], b[2]), max(b[0], b[2]), b[1]]
    log_err = sum(abs(math.log(obj_sig[i] / ast_sig[i])) for i in range(3)) / 3.0
    return max(0.0, 1.0 - min(log_err, 1.5) / 1.5)


def _score_asset(obj: dict[str, Any], asset: AssetCandidate) -> tuple[float, str]:
    ot = _object_tokens(obj)
    at = _asset_tokens(asset)
    score = 0.0
    reasons: list[str] = []

    for required, asset_id, boost in _EXPLICIT_ASSET_HINTS:
        if asset.asset_id == asset_id and all(tok in ot for tok in required):
            score += boost
            reasons.append(f"explicit:{'+'.join(required)}")

    overlap = sorted(ot & at)
    if overlap:
        score += 10.0 * len(overlap)
        reasons.append("tokens:" + ",".join(overlap[:6]))

    obj_type = str(obj.get("type") or "").lower()
    if obj_type and obj_type in at:
        score += 18.0
        reasons.append(f"type:{obj_type}")
    if obj_type == "landmark" and asset.category in {"object", "plant", "electronics", "furniture"}:
        score += 4.0
        reasons.append("landmark-compatible")
    if obj_type == "table" and "table" in at:
        score += 20.0
        reasons.append("table-compatible")
    if obj_type == "chair" and "chair" in at:
        score += 22.0
        reasons.append("chair-compatible")

    material = str(obj.get("material") or "").lower()
    if material and asset.material_hint and material in _tokens(asset.material_hint):
        score += 12.0
        reasons.append(f"material:{material}")
    if material in at:
        score += 8.0
        reasons.append(f"asset-token-material:{material}")

    if "table" in ot and not ({"chair", "chairs", "set", "dining"} & ot):
        if {"chair", "chairs", "assembly", "set"} & at:
            score -= 70.0
            reasons.append("penalty:table-only-vs-set")
    if "conference" in ot and not ({"conference", "dining"} & at):
        score -= 45.0
        reasons.append("penalty:conference-table-mismatch")

    size_score = _size_similarity(obj, asset)
    if size_score > 0:
        score += 12.0 * size_score
        reasons.append(f"size:{size_score:.2f}")

    # Penalize known bad semantic mismatches.
    if "air" in ot or "purifier" in ot or "dehumidifier" in ot or "appliance" in ot:
        if not ({"appliance", "electronics", "purifier", "dehumidifier"} & at):
            score -= 35.0
            reasons.append("penalty:appliance-mismatch")
    if "whiteboard" in ot and not ({"whiteboard", "board", "glass"} & at):
        score -= 25.0
        reasons.append("penalty:whiteboard-mismatch")
    if "light" in ot or "lamp" in ot:
        if not ({"light", "lamp", "chandelier"} & at):
            score -= 25.0
            reasons.append("penalty:light-mismatch")

    return score, ";".join(reasons) or "no-match"


def _should_skip(obj: dict[str, Any], *, include_lines: bool) -> str | None:
    if obj.get("source_ref"):
        return "already_has_source_ref"
    if obj.get("is_emitter"):
        return "emitter_keeps_proxy"
    obj_id = str(obj.get("id") or "")
    if obj_id.startswith(_EXCLUDE_ID_PREFIXES):
        return "excluded_structural_or_light"
    if str(obj.get("placement") or "") == "line" and not include_lines:
        return "line_geometry"
    if str(obj.get("type") or "") in _EXCLUDE_TYPES and not include_lines:
        return "structural_geometry"
    return None


def _best_decision(obj: dict[str, Any], assets: list[AssetCandidate], *, min_score: float, include_lines: bool) -> LinkDecision:
    skip = _should_skip(obj, include_lines=include_lines)
    if skip:
        return LinkDecision(
            object_id=str(obj.get("id") or ""),
            label=str(obj.get("label") or ""),
            object_type=str(obj.get("type") or ""),
            current_source_ref=obj.get("source_ref"),
            action="skip",
            reason=skip,
        )
    scored: list[tuple[float, str, AssetCandidate]] = []
    for asset in assets:
        score, reason = _score_asset(obj, asset)
        scored.append((score, reason, asset))
    scored.sort(key=lambda item: item[0], reverse=True)
    alternatives = [
        {"asset_id": a.asset_id, "label": a.label, "score": round(s, 2), "reason": r, "source_ref": a.source_ref}
        for s, r, a in scored[:5]
        if s > 0
    ]
    if not scored or scored[0][0] < min_score:
        return LinkDecision(
            object_id=str(obj.get("id") or ""),
            label=str(obj.get("label") or ""),
            object_type=str(obj.get("type") or ""),
            current_source_ref=None,
            action="unmatched",
            score=round(scored[0][0], 2) if scored else 0.0,
            reason="below_threshold" if scored else "no_assets",
            alternatives=alternatives,
        )
    score, reason, asset = scored[0]
    return LinkDecision(
        object_id=str(obj.get("id") or ""),
        label=str(obj.get("label") or ""),
        object_type=str(obj.get("type") or ""),
        current_source_ref=None,
        action="link",
        asset_id=asset.asset_id,
        source_ref=asset.source_ref,
        asset_category=asset.category,
        material_hint=asset.material_hint,
        score=round(score, 2),
        reason=reason,
        alternatives=alternatives,
    )


def _scene_dir(project: str, scene: str) -> Path:
    return REPO_ROOT / "out" / "opticalnav" / project / "scenes" / scene


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any], *, backup: bool) -> None:
    if backup and path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, path.with_suffix(path.suffix + f".{stamp}.bak"))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _apply_decisions(payload: dict[str, Any], decisions: Iterable[LinkDecision]) -> int:
    by_id = {d.object_id: d for d in decisions if d.action == "link" and d.source_ref}
    changed = 0
    for obj in payload.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        decision = by_id.get(str(obj.get("id") or ""))
        if not decision:
            continue
        if obj.get("source_ref"):
            continue
        obj["source_ref"] = decision.source_ref
        meta = dict(obj.get("metadata") or {})
        if decision.asset_id:
            meta["asset_id"] = decision.asset_id
        if decision.asset_category:
            meta["asset_category"] = decision.asset_category
        if decision.source_ref:
            meta["asset_source_ref"] = decision.source_ref
            if "#" in decision.source_ref:
                usd_ref, source_path = decision.source_ref.split("#", 1)
                meta["usd_ref"] = usd_ref
                meta["asset_source_path"] = source_path
        if decision.material_hint and not obj.get("material"):
            obj["material"] = decision.material_hint
        meta["asset_auto_link"] = {
            "asset_id": decision.asset_id,
            "asset_category": decision.asset_category,
            "score": decision.score,
            "reason": decision.reason,
            "linked_at": _utc_now_iso(),
            "tool": "apps/auto_link_opticalnav_assets.py",
        }
        obj["metadata"] = meta
        changed += 1
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--scene", default=DEFAULT_SCENE)
    ap.add_argument("--map", dest="map_path", type=Path, default=None, help="Override authoring_map.json path.")
    ap.add_argument("--min-score", type=float, default=80.0)
    ap.add_argument("--include-lines", action="store_true", help="Also consider line/structural objects. Off by default.")
    ap.add_argument("--apply", action="store_true", help="Write source_ref changes. Default is dry-run.")
    ap.add_argument("--update-overlays", action=argparse.BooleanOptionalAction, default=True,
                    help="When applying a scene map, mirror source_ref changes into render_scene_overlays.json.")
    ap.add_argument("--backup", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()

    assets = _load_curated_assets(REPO_ROOT)
    if not assets:
        raise SystemExit("No curated assets found under assets/opticalnav_curated.")

    scene_dir = _scene_dir(args.project, args.scene)
    map_path = args.map_path or scene_dir / "authoring_map.json"
    if not map_path.exists():
        raise SystemExit(f"authoring map not found: {map_path}")
    payload = _load_json(map_path)
    decisions = [
        _best_decision(obj, assets, min_score=args.min_score, include_lines=args.include_lines)
        for obj in payload.get("objects") or []
        if isinstance(obj, dict)
    ]

    link_count = sum(1 for d in decisions if d.action == "link")
    unmatched_count = sum(1 for d in decisions if d.action == "unmatched")
    skip_count = sum(1 for d in decisions if d.action == "skip")
    print(f"scene={payload.get('scene_id') or args.scene} assets={len(assets)} link={link_count} unmatched={unmatched_count} skip={skip_count} min_score={args.min_score}")
    for d in decisions:
        if d.action == "link":
            print(f"LINK {d.object_id:24s} -> {d.asset_id:36s} score={d.score:5.1f} {d.reason}")
        elif d.action == "unmatched":
            alt = d.alternatives[0] if d.alternatives else None
            hint = f" best={alt['asset_id']} score={alt['score']}" if alt else ""
            print(f"MISS {d.object_id:24s} score={d.score:5.1f} {d.reason}{hint}")

    report = {
        "generated_at": _utc_now_iso(),
        "project": args.project,
        "scene": args.scene,
        "map_path": str(map_path),
        "min_score": args.min_score,
        "apply": bool(args.apply),
        "summary": {"link": link_count, "unmatched": unmatched_count, "skip": skip_count},
        "decisions": [asdict(d) for d in decisions],
    }
    report_path = args.report or (scene_dir / "asset_source_ref_autolink_report.json" if scene_dir.exists() else map_path.with_name("asset_source_ref_autolink_report.json"))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"report={report_path}")

    if args.apply:
        changed = _apply_decisions(payload, decisions)
        _write_json(map_path, payload, backup=args.backup)
        overlay_changed = 0
        overlay_path = scene_dir / "render_scene_overlays.json"
        if args.update_overlays and overlay_path.exists() and map_path.resolve() != overlay_path.resolve():
            overlay = _load_json(overlay_path)
            overlay_changed = _apply_decisions(overlay, decisions)
            _write_json(overlay_path, overlay, backup=args.backup)
        print(f"applied authoring_map={changed} overlays={overlay_changed}")
    else:
        print("dry-run only; pass --apply to write source_ref changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
