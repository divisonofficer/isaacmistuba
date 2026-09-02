"""Immutable HDRI-bank validation and paired illumination curriculum."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "robomituba.ir_illumination_bank.v1"
CONTRACT = "illumination-diversity-paired-v1"
SCHEMA_V2 = "robomituba.ir_illumination_bank.v2"
CONTRACT_V2 = "illumination-fixture-diversity-v2"
MIN_CONDITIONS = 6
MAX_CONDITIONS = 12
#: Portals are excluded: the worker rewrites their energy from the HDRI recipe
#: after fixtures are applied, so a mask here would be silently overwritten.
SWITCHABLE_FIXTURE_GROUPS = ("ceiling", "lamp", "accent", "ambient_fill")


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
    schema, contract = payload.get("schema"), payload.get("contract")
    is_v2 = schema == SCHEMA_V2 and contract == CONTRACT_V2
    if not is_v2 and (schema != SCHEMA or contract != CONTRACT):
        raise ValueError("unsupported illumination bank manifest")
    assets = payload.get("assets") or {}
    conditions = payload.get("conditions") or []
    unique = len({item.get("id") for item in conditions})
    if is_v2:
        # v2 relaxes the fixed six only because per-fixture conditions are worth
        # enumerating more finely; v1's exact-six rule is left untouched so its
        # manifest_digest cannot move.
        if not MIN_CONDITIONS <= len(conditions) <= MAX_CONDITIONS or unique != len(conditions):
            raise ValueError(
                f"illumination bank v2 requires {MIN_CONDITIONS}-{MAX_CONDITIONS} unique conditions")
        groups = set(payload.get("fixture_groups") or [])
        if not groups or not groups <= set(SWITCHABLE_FIXTURE_GROUPS):
            raise ValueError("illumination bank v2 has an unsupported fixture group set")
        for condition in conditions:
            spec = condition.get("fixtures") or {}
            for name, rule in (spec.get("groups") or {}).items():
                if name not in groups:
                    raise ValueError(f"{condition.get('id')}: fixture group {name!r} not declared")
                if not 0.0 <= float(rule.get("on_probability", 1.0)) <= 1.0:
                    raise ValueError(f"{condition.get('id')}: on_probability outside [0, 1]")
                if float(rule.get("energy_scale", 1.0)) <= 0.0:
                    raise ValueError(f"{condition.get('id')}: energy_scale must be positive")
                kelvin = rule.get("color_temperature_k")
                if kelvin is not None and not 1000.0 <= float(kelvin) <= 12000.0:
                    raise ValueError(f"{condition.get('id')}: color_temperature_k outside [1000, 12000]")
                if float(rule.get("color_temperature_jitter_k", 0.0) or 0.0) < 0.0:
                    raise ValueError(f"{condition.get('id')}: negative colour-temperature jitter")
    elif len(conditions) != 6 or unique != 6:
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
            **({"fixture_groups": payload.get("fixture_groups"),
                "condition_count": payload.get("condition_count")} if is_v2 else {}),
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
