#!/usr/bin/env python3
"""Validate a structural CC0 rematerialization manifest before Stage 2."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules" / "mitsuba_converter" / "src"))
from mitsuba_converter.ir_structural_quality import audit_manifest
p=argparse.ArgumentParser(); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--registry-root",type=Path,required=True); p.add_argument("--out",type=Path,required=True); a=p.parse_args()
result=audit_manifest(json.loads(a.manifest.read_text()), registry_root=a.registry_root)
a.out.parent.mkdir(parents=True,exist_ok=True); tmp=a.out.with_suffix(a.out.suffix+".tmp"); tmp.write_text(json.dumps(result,indent=2)+"\n"); os.replace(tmp,a.out)
print(f"[structural-quality] {result['status']} bindings={len(result['bindings'])}")
raise SystemExit(0 if result["status"] == "passed" else 2)
