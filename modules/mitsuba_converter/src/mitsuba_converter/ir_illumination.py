"""Immutable HDRI-bank validation and paired illumination curriculum."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "robomituba.ir_illumination_bank.v1"
CONTRACT = "illumination-diversity-paired-v1"


def stable_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def default_manifest(repo_root: Path) -> Path:
    return repo_root / "configs" / "ir_lighting" / "illumination_diversity_v1.json"


def load_bank(repo_root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    path = manifest_path or default_manifest(repo_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA or payload.get("contract") != CONTRACT:
        raise ValueError("unsupported illumination bank manifest")
    assets = payload.get("assets") or {}
    conditions = payload.get("conditions") or []
    if len(conditions) != 6 or len({item.get("id") for item in conditions}) != 6:
        raise ValueError("illumination bank must provide exactly six unique conditions")
    resolved: dict[str, dict[str, Any]] = {}
    for ident, item in assets.items():
        rel = Path(str(item.get("path") or ""))
        if not rel.parts or rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"unsafe HDRI asset path: {ident}")
        asset = (repo_root / rel).resolve()
        if not asset.is_file() or sha256(asset) != str(item.get("sha256") or ""):
            raise ValueError(f"HDRI asset missing or digest mismatch: {ident}")
        resolved[ident] = {**item, "path": str(asset), "relative_path": str(rel)}
    for condition in conditions:
        if str(condition.get("external_asset") or "") not in resolved:
            raise ValueError(f"condition references unavailable HDRI: {condition.get('id')}")
    core = {"schema": payload["schema"], "contract": payload["contract"], "license": payload.get("license"),
            "assets": {key: {**value, "path": value["relative_path"]} for key, value in resolved.items()}, "conditions": conditions}
    return {**core, "manifest_path": str(path.resolve()), "manifest_digest": stable_digest(core), "resolved_assets": resolved}


def audit_bank(repo_root: Path, out: Path) -> dict[str, Any]:
    bank = load_bank(repo_root)
    result = {"schema": "robomituba.ir_illumination_audit.v1", "available": True,
              "contract": CONTRACT, "manifest_digest": bank["manifest_digest"],
              "assets": bank["assets"], "conditions": bank["conditions"]}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    tmp.replace(out)
    return result
