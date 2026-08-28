#!/usr/bin/env python3
"""Read-only inventory of legacy structural PBR quality in prepared IR scenes."""
from __future__ import annotations
import argparse, hashlib, json, os
from collections import Counter
from pathlib import Path
from typing import Any
import cv2
import numpy as np

SCHEMA = "robomituba.ir_legacy_structural_inventory.v1"
STRUCTURAL = (".wall", ".floor", ".ceiling", ".column", ".panel")

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def image_stats(path: Path, *, rgb: bool = False) -> dict[str, Any]:
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if im is None: return {"available": False}
    scale = float(np.iinfo(im.dtype).max) if np.issubdtype(im.dtype, np.integer) else 1.0
    v = im.astype(np.float32) / scale
    scalar = v.mean(axis=2) if v.ndim == 3 else v
    out = {"available": True, "width": int(im.shape[1]), "height": int(im.shape[0]),
           "p05": round(float(np.quantile(scalar,.05)),6), "median": round(float(np.median(scalar)),6),
           "p95": round(float(np.quantile(scalar,.95)),6), "zero_ratio": round(float((scalar <= 1/255).mean()),6)}
    if rgb and v.ndim == 3: out["mean_rgb"] = [round(float(x),6) for x in v[..., :3].mean(axis=(0,1))]
    return out

def category(object_id: str) -> str | None:
    x = object_id.lower()
    for suffix in STRUCTURAL:
        if x.endswith(suffix): return suffix[1:]
    return None

def audit_contract(path: Path, *, dataset_root: Path) -> dict[str, Any] | None:
    try: c = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError): return None
    stage1 = Path(str(c.get("stage1_dir") or ""))
    if not stage1.is_dir(): return None
    pipeline = path.parents[1]
    rows, findings = [], []
    for m in c.get("materials") or []:
        role = category(str(m.get("object_id") or ""))
        if not role: continue
        effective, source = m.get("effective_inputs") or {}, m.get("source_channels") or {}
        def source_path(channel: str) -> Path | None:
            ref = (effective.get(channel) or {}).get("artifact") or (source.get(channel.replace("_rgb", "")) or {}).get("ref")
            return stage1 / str(ref) if ref else None
        base, rough, normal = source_path("base_color_rgb"), source_path("roughness"), source_path("normal_shading_world")
        base_s = image_stats(base, rgb=True) if base else {"available": False}
        rough_s = image_stats(rough) if rough else {"available": False}
        normal_s = image_stats(normal) if normal else {"available": False}
        flags=[]
        if base_s.get("available") and min(base_s["width"],base_s["height"]) <= 512: flags.append("legacy_512_structural_atlas")
        if role == "floor" and rough_s.get("available") and (rough_s["median"] < .20 or rough_s["p05"] < .04): flags.append("low_structural_roughness")
        source_name = str(m.get("source_material") or "").lower()
        if any(x in source_name for x in ("tile_tile", "brick", "rectangle_tile")): flags.append("repetitive_structural_pattern")
        rows.append({"object_id":m.get("object_id"), "role":role, "source_material":m.get("source_material"),
                     "base_color":base_s, "roughness":rough_s, "normal":normal_s,
                     "metallic_route":(effective.get("metallic") or {}).get("route"), "flags":flags})
        findings.extend(flags)
    scene_id = str(c.get("stage1_scene_id") or "")
    # A historical mapping bug put a balcony room into a meeting-room named dataset.
    name = pipeline.name.lower().replace("_", "-")
    if "meeting-room" in name and "balcony" in " ".join(str(r.get("object_id")) for r in rows).lower():
        findings.append("scene_identity_mismatch")
    status = "reject" if any(x in findings for x in ("low_structural_roughness","scene_identity_mismatch")) else ("review" if findings else "pass")
    return {"pipeline":str(pipeline), "dataset_name":pipeline.name, "dataset_published":(dataset_root/pipeline.name).is_dir(),
            "scene_id":scene_id, "contract_schema":c.get("schema"), "structural_units":rows,
            "findings":sorted(set(findings)), "status":status}

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--pipeline-root",type=Path,required=True); p.add_argument("--dataset-root",type=Path,required=True); p.add_argument("--out",type=Path,required=True); a=p.parse_args()
    scenes=[]
    for contract in sorted(a.pipeline_root.glob("*/principled_stage2/principled_material_contract.json")):
        row=audit_contract(contract,dataset_root=a.dataset_root)
        if row: scenes.append(row)
    counts=Counter(flag for s in scenes for flag in s["findings"])
    result={"schema":SCHEMA,"pipeline_root":str(a.pipeline_root),"dataset_root":str(a.dataset_root),"scene_count":len(scenes),
            "structural_scene_count":sum(bool(s["structural_units"]) for s in scenes),
            "structural_unit_count":sum(len(s["structural_units"]) for s in scenes),
            "finding_counts":dict(sorted(counts.items())),"status_counts":dict(Counter(s["status"] for s in scenes)),"scenes":scenes}
    result["inventory_digest"]=digest(result)
    a.out.parent.mkdir(parents=True,exist_ok=True); temp=a.out.with_suffix(a.out.suffix+".tmp"); temp.write_text(json.dumps(result,indent=2)+"\n"); os.replace(temp,a.out)
    print(json.dumps({"scenes":len(scenes),"findings":result["finding_counts"],"out":str(a.out)}))
    return 0
if __name__ == "__main__": raise SystemExit(main())
