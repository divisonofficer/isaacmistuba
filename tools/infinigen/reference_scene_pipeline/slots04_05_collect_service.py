import json,hashlib,shutil,csv
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/shared_dining_residence_05';base=Path('/bean/datasets/hssd/derived_alpha');ids=['031024e00569909d466d87df9fead90355ba29e5','041c06dd0009364a773620e1eb2fd1dc3808222a','048d80c36ddc6ac63785ca08ccf231431195717c','2155fdf43148aabbd9beb63943df5606fe0c5945','c48c42dccc86b2f952e52a76e46ae4cdf7744a18'];found={}
for folder in base.iterdir():
 if folder.name.startswith('hssd_'):
  for id in ids:
   if id not in found and (folder/'assets'/id/'asset.gltf').exists():found[id]=folder/'assets'/id
 if len(found)==len(ids):break
assert len(found)==len(ids),found
with open('/bean/datasets/hssd/hssd-hab/semantics/objects.csv') as f:metadata={r['id']:r for r in csv.DictReader(f) if r['id'] in ids}
rows=[]
for id in ids:
 src=found[id];dst=D/'native_service_products'/id;assert not dst.exists();shutil.copytree(src,dst);p=dst/'asset.gltf';g=json.loads(p.read_text());deps=[]
 for e in g.get('buffers',[])+g.get('images',[]):
  if 'uri' in e and not e['uri'].startswith('data:'):
   q=dst/e['uri'];deps.append({'uri':e['uri'],'sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
 rows.append({'id':'HSSD_'+id,'name':metadata[id]['name'],'path':str(p),'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'original_path':str(src/'asset.gltf'),'dependencies':deps,'mr_override':{},'declared_aligned_dims_y_up':metadata[id]['aligned.dims'],'scope':'Native unchanged geometry, UV and textures. Constant invalid IOR may be repaired explicitly at import; material appearance not accepted.'})
(D/'native_service_products_manifest.json').write_text(json.dumps({'assets':rows},indent=2));print('SERVICE_PRODUCTS_COPIED')
