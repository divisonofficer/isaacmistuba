#!/usr/bin/env python3
"""Select quality-approved parents and emit 4 independent child-scene specs each."""
from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path

def score(row: dict) -> float | None:
    s = row.get("scene_statistics") or row
    per = s.get("nonstructural_objects_per_m2")
    visible = ((s.get("selected_visible_object_count") or {}).get("median")
               if isinstance(s.get("selected_visible_object_count"), dict) else s.get("median_visible_objects"))
    sparse = s.get("sparse_pose_fraction")
    if per is None or visible is None or sparse is None or float(per) < 3 or float(visible) < 2 or float(sparse) > .15:
        return None
    return float(per) * 2 + float(visible) * 3 - float(sparse) * 10

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--scene-statistics",type=Path,required=True); p.add_argument("--out",type=Path,required=True); p.add_argument("--limit",type=int,default=24); p.add_argument("--variants",type=int,default=4); p.add_argument("--seed",type=int,default=20260818); a=p.parse_args()
    source=json.loads(a.scene_statistics.read_text())
    rows=source.get("scenes") or source.get("rows") or []
    ranked=sorted(((score(row),row) for row in rows if score(row) is not None),key=lambda x:(-x[0],str(x[1].get("dataset_name") or x[1].get("scene_id"))))[:a.limit]
    children=[]
    for parent_rank,(_,row) in enumerate(ranked):
        parent=str(row.get("scene_id") or row.get("dataset_name"))
        fingerprint=str(row.get("fingerprint") or row.get("dataset_fingerprint") or "")
        for variant in range(a.variants):
            seed=int.from_bytes(hashlib.sha256(f"{a.seed}:{parent}:{variant}".encode()).digest()[:8],"big")
            suffix=f"pbrv{variant+1:02d}"
            children.append({"parent_scene_id":parent,"parent_dataset_fingerprint":fingerprint,"rank":parent_rank+1,
                "material_variant_id":suffix,"material_seed":seed,"scene_id":f"{parent}__{suffix}",
                "dataset_name":f"{parent}_{suffix}_rgb_active_nir_v3"})
    result={"schema":"robomituba.ir_structural_rematerialization_plan.v1","selection":{"limit":a.limit,"variants_per_parent":a.variants,"accepted_parents":len(ranked)},"children":children}
    a.out.parent.mkdir(parents=True,exist_ok=True); tmp=a.out.with_suffix('.tmp'); tmp.write_text(json.dumps(result,indent=2)+'\n'); os.replace(tmp,a.out)
    print(f"[rematerialize-plan] parents={len(ranked)} independent_children={len(children)}")
    return 0
if __name__=='__main__': raise SystemExit(main())
