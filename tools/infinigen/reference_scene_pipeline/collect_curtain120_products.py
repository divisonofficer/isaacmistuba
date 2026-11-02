"""Copy two named native cloth products and exact dependencies into project assets."""
from pathlib import Path
import json,hashlib,shutil
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=d/'curtain120_products';assert not p.exists();p.mkdir();out=r/'assets/opticalnav_curated/residential_curtains120';assert not out.exists();out.mkdir();a=json.loads((d/'curtain120_metadata_screen.json').read_text());wanted=['HSSD_3ba480f5ac90ffd829b38acb17e344602f952c06','HSSD_634c2c24ba86aa2d543ab13c586cd37465f4283c'];rows=[];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for key in wanted:
 e=next(x for x in a['candidates'] if x['id']==key);src=Path(e['source']);assert sha(src)==e['source_sha256'];dst=out/key/src.name;dst.parent.mkdir();shutil.copyfile(src,dst);deps=[]
 for kind in ['buffers','images']:
  for dep in json.loads(src.read_text()).get(kind,[]):
   uri=dep.get('uri','')
   if not uri or uri.startswith('data:'):continue
   rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;target=dst.parent/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src.parent/rel,target);assert sha(target)==sha(src.parent/rel);deps.append({'uri':uri,'sha256':sha(target)})
 rows.append({**e,'path':str(dst.relative_to(r)),'copied_sha256':sha(dst),'dependencies':deps,'mr_override':{}})
(p/'asset_manifest.json').write_text(json.dumps({'assets':rows,'scope':'Native cream pair and natural curtain products copied byte-identically with dependencies; no resizing, shader remediation or visual/room approval.'},indent=2));print('CURTAIN120_NATIVE_PRODUCTS_COPIED',len(rows))
