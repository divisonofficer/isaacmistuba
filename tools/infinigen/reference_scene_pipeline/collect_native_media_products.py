"""Portable native media donors with declared provisional optical profiles; not approval."""
from pathlib import Path
import json,hashlib,shutil
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'native_media_products';assets=r/'assets/opticalnav_curated/residential_media_products';assert not out.exists() and not assets.exists();out.mkdir();assets.mkdir();data=json.loads((d/'native_media_product_screen.json').read_text());wanted={'24348214a4389ad5c9ad24fe4f5a5d06f118ba98':[(0,.15),(0,.5),(1,.2)],'63b7d75b724e079aab99030084f0eae1b43b7498':[(0,.5),(0,.55),(1,.2)],'82853146797ce9b1ec5fa02d085f6cf816c243f5':[(0,.4),(0,.5),(1,.18)],'1efdc3d37dfab1eb9f99117bb84c59003d684811':[(0,.4),(0,.08),(0,.4),(0,.65)],'f359e92c249c96d0121f40252c856f99008f9c2e':[(0,.08),(0,.65),(0,.4)]};rows=[];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for key,profiles in wanted.items():
 e=next(x for x in data['candidates'] if x['id']=='HSSD_'+key);src=Path(e['source']);assert sha(src)==e['source_sha256'];dst=assets/e['id']/'asset.gltf';dst.parent.mkdir();shutil.copyfile(src,dst);deps=[];a=json.loads(src.read_text())
 for kind in ['buffers','images']:
  for dep in a.get(kind,[]):
   uri=dep.get('uri','')
   if not uri or uri.startswith('data:'):continue
   rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;q=dst.parent/rel;q.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(src.parent/rel,q);assert sha(q)==sha(src.parent/rel);deps.append({'uri':uri,'sha256':sha(q)})
 assert len(a['materials'])==len(profiles);override={m['name']:{'metallic':p[0],'roughness':p[1]} for m,p in zip(a['materials'],profiles) if 'metallicRoughnessTexture' not in m.get('pbrMetallicRoughness',{})};rows.append({**e,'path':str(dst.relative_to(r)),'copied_sha256':sha(dst),'dependencies':deps,'mr_override':override,'profile_scope':'Provisional inferred material-role constants: console textured wood/dielectric, separate low-rough hardware metal; TV glass/plastic/label dielectrics. Base/normal/transmission maps retained. Native defaults include metallic1 and IOR0; role mapping needs visible geometry and shader QC. Not measured BRDF or reference/room approval.'})
(out/'asset_manifest.json').write_text(json.dumps({'assets':rows,'scope':'Five real native models copied byte-identically with dependencies; original source shaders recorded separately from declared provisional optical correction. No scaling or scene integration.','accepted':False},indent=2));print('NATIVE_MEDIA_PRODUCTS_COPIED',len(rows))
