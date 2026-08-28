#!/usr/bin/env python3
"""QA external structural bindings before a v3 render is allowed to proceed."""
from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
import cv2
import numpy as np

def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20), b""): h.update(b)
    return h.hexdigest()

def variance(path: Path, normal: bool=False) -> dict:
    image=cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None: raise RuntimeError(f"cannot decode {path}")
    x=image.astype(np.float32)
    x/=float(np.iinfo(image.dtype).max) if np.issubdtype(image.dtype, np.integer) else 1.0
    if normal and x.ndim == 3:
        n=x[..., :3][:, :, ::-1]*2-1; n/=np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-6)
        mean=n.reshape(-1,3).mean(0); mean/=max(np.linalg.norm(mean),1e-6)
        angle=np.degrees(np.arccos(np.clip((n*mean).sum(-1),-1,1)))
        return {"p95_angular_deviation_deg":float(np.percentile(angle,95))}
    return {"p95_minus_p05":float(np.percentile(x,95)-np.percentile(x,5))}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--out",type=Path,required=True); a=p.parse_args()
    m=json.loads(a.manifest.read_text()); rows=[]; failures=[]; seen={}
    for b in m.get("bindings",[]):
        maps=b.get("resolved_maps") or {}; row={"unit_id":b.get("unit_id"),"slot_index":b.get("slot_index"),"material_id":b.get("material_id"),"projection":b.get("projection"),"maps":{}}
        for key in ("base_color","roughness","normal_gl"):
            path=Path(str(maps.get(key) or "")); actual=digest(path); expected=(b.get("map_sha256") or {}).get(key)
            row["maps"][key]={"path":str(path),"sha256":actual}
            if expected and actual != expected: failures.append(f"{row['unit_id']}:{row['slot_index']} {key} checksum")
        row["roughness_variance"]=variance(Path(maps["roughness"]))
        row["normal_variance"]=variance(Path(maps["normal_gl"]),normal=True)
        if row["roughness_variance"]["p95_minus_p05"] < .06: failures.append(f"{row['unit_id']}:{row['slot_index']} roughness variance")
        if row["normal_variance"]["p95_angular_deviation_deg"] < 3: failures.append(f"{row['unit_id']}:{row['slot_index']} normal variance")
        signature=tuple(row["maps"][key]["sha256"] for key in ("base_color","roughness","normal_gl"))
        if signature in seen and seen[signature] != row["material_id"]: failures.append(f"cross-slot map reuse {seen[signature]} / {row['material_id']}")
        seen[signature]=row["material_id"]; rows.append(row)
    result={"schema":"robomituba.background_material_qc.v1","manifest_digest":digest(a.manifest),"status":"passed" if not failures else "failed","failures":failures,"bindings":rows}
    a.out.parent.mkdir(parents=True,exist_ok=True); tmp=a.out.with_suffix('.tmp'); tmp.write_text(json.dumps(result,indent=2)+'\n'); os.replace(tmp,a.out)
    print(f"[background-qc] {result['status']} bindings={len(rows)}")
    return 0 if not failures else 2
if __name__=='__main__': raise SystemExit(main())
