"""Deterministic quality audit for CC0-rematerialized interior structures."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any
import cv2
import numpy as np
SCHEMA = "robomituba.ir_structural_material_quality_audit.v1"
def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def _image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None: raise ValueError(f"cannot decode texture: {path}")
    scale = float(np.iinfo(image.dtype).max) if np.issubdtype(image.dtype, np.integer) else 1.0
    return image.astype(np.float32) / scale
def _quantiles(path: Path) -> dict[str, Any]:
    value = _image(path)
    if value.ndim == 3: value = value[..., 0]
    return {"width": int(value.shape[1]), "height": int(value.shape[0]), "p05": float(np.quantile(value,.05)), "median": float(np.median(value)), "p95": float(np.quantile(value,.95)), "zero_ratio": float((value <= 1/255).mean())}
def audit_manifest(manifest: dict[str, Any], *, registry_root: Path) -> dict[str, Any]:
    rows, failures = [], []
    for binding in manifest.get("bindings") or []:
        role = str(binding.get("role") or (binding.get("eligibility") or {}).get("subtype") or "")
        maps = binding.get("resolved_maps") or {}
        base, rough, normal = (Path(str(maps.get(key) or "")) for key in ("base_color","roughness","normal_gl"))
        if not all(path.is_file() for path in (base,rough,normal)):
            failures.append(f"{binding.get('unit_id')}: missing external map"); continue
        if any(registry_root.resolve() not in path.resolve().parents for path in (base,rough,normal)):
            failures.append(f"{binding.get('unit_id')}: map outside registry root"); continue
        base_stats, rough_stats, normal_stats = _quantiles(base), _quantiles(rough), _quantiles(normal)
        metallic_spec = binding.get("metallic")
        if not isinstance(metallic_spec, dict):
            metallic_spec = {"mode": "constant", "value": float(metallic_spec or 0.0)}
        metallic_mode = str(metallic_spec.get("mode") or "constant")
        metallic_stats = None
        is_metal = False
        if metallic_mode == "texture":
            metallic_path = Path(str(maps.get(str(metallic_spec.get("map") or "metallic")) or ""))
            if not metallic_path.is_file() or registry_root.resolve() not in metallic_path.resolve().parents:
                failures.append(f"{binding.get('unit_id')}: missing metallic texture"); continue
            metallic_stats = _quantiles(metallic_path)
            is_metal = True
        elif metallic_mode == "constant":
            metallic_value = float(metallic_spec.get("value") or 0.0)
            if not 0.0 <= metallic_value <= 1.0:
                failures.append(f"{binding.get('unit_id')}: invalid metallic constant"); continue
            is_metal = metallic_value >= 1.0 - 1e-6
        else:
            failures.append(f"{binding.get('unit_id')}: invalid metallic route"); continue
        reasons=[]
        if min(base_stats["width"],base_stats["height"]) < 2048: reasons.append("base_color_below_2048")
        if min(rough_stats["width"],rough_stats["height"]) < 2048: reasons.append("roughness_below_2048")
        if min(normal_stats["width"],normal_stats["height"]) < 2048: reasons.append("normal_below_2048")
        if is_metal and role not in {"wall", "panel"}: reasons.append("metallic_structural_role_not_allowed")
        if role == "floor" and (rough_stats["median"] < .20 or rough_stats["p05"] < .04): reasons.append("floor_near_mirror")
        if not is_metal and role in {"wall","ceiling","panel","column"} and rough_stats["median"] < .15: reasons.append("structure_near_mirror")
        row={"unit_id":binding.get("unit_id"),"slot_index":binding.get("slot_index"),"role":role,"material_id":binding.get("material_id"),"projection":binding.get("projection"),"base_color":base_stats,"roughness":rough_stats,"normal":normal_stats,"metallic":metallic_spec,"metallic_stats":metallic_stats,"failures":reasons}
        rows.append(row); failures.extend(f"{row['unit_id']}:{reason}" for reason in reasons)
    result={"schema":SCHEMA,"status":"failed" if failures else "passed","manifest_digest":_digest(manifest),"bindings":rows,"failures":failures}
    result["audit_digest"]=_digest(result); return result
