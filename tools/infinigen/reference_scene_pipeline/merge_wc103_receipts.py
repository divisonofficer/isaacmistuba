"""Merge two independent immutable same-source matched frame receipts, preserve originals."""
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];D=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';W=D/'wc_access103';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();records=[]
for batch in ['render_101','render_102']:
 p=W/batch/'render_receipt.json';r=json.load(open(p));assert r['source_unchanged'] and len(r['frames'])==1;assert r['phase']=='rendered_visual_review_pending';assert sha(r['source'])==r['source_sha256'];f=r['frames'][0];assert sha(f['path'])==f['sha256'];records.append((p,r))
first=records[0][1]
for _,r in records[1:]:
 for key in ['source','source_sha256','samples','renderer_sha256','lighting_policy','lighting_overrides','denoising']:assert r[key]==first[key],key
merged=dict(first);merged['frames']=[r['frames'][0] for _,r in records];merged['independent_batch_receipts']=[{'path':str(p),'sha256':sha(p)} for p,_ in records];out=W/'candidate_r103';out.mkdir(exist_ok=True);p=out/'render_receipt.json';assert not p.exists();p.write_text(json.dumps(merged,indent=2));print('2 source-bound frame receipts merged; originals retained')
