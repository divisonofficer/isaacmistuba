#!/usr/bin/env python3
"""Atomically archive a legacy published dataset after a verified replacement exists."""
from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path

def load(p: Path): return json.loads(p.read_text())
def fp(root: Path) -> str:
    return str(load(root/'dataset_config.json').get('fingerprint') or '')
def main():
    a=argparse.ArgumentParser(); a.add_argument('--parent',type=Path,required=True); a.add_argument('--child',type=Path,required=True); a.add_argument('--archive-root',type=Path,required=True); a.add_argument('--reason',default='structural_cc0_remediation_verified'); a.add_argument('--commit',action='store_true'); x=a.parse_args()
    parent,child=x.parent.resolve(),x.child.resolve()
    if not (parent/'publish_manifest.json').is_file() or not (child/'publish_manifest.json').is_file(): raise SystemExit('both parent and child must be immutable published datasets')
    pfp,cfp=fp(parent),fp(child)
    if not pfp or not cfp or pfp==cfp: raise SystemExit('parent/child fingerprints must exist and differ')
    destination=x.archive_root.resolve()/f'{parent.name}.{pfp[:12]}'
    manifest={'schema':'robomituba.ir_dataset_retirement.v1','parent_name':parent.name,'parent_fingerprint':pfp,'child_name':child.name,'child_fingerprint':cfp,'reason':x.reason,'retired_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}
    manifest['retirement_digest']=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if not x.commit:
        print(json.dumps({'dry_run':True,'from':str(parent),'to':str(destination),'manifest':manifest},indent=2)); return
    if destination.exists(): raise SystemExit(f'archive destination already exists: {destination}')
    x.archive_root.mkdir(parents=True,exist_ok=True)
    os.replace(parent,destination)
    tmp=destination/'retirement_manifest.json.tmp'; tmp.write_text(json.dumps(manifest,indent=2)+'\n'); os.replace(tmp,destination/'retirement_manifest.json')
    print(json.dumps({'archived':str(destination),'manifest':manifest}))
if __name__=='__main__': main()
