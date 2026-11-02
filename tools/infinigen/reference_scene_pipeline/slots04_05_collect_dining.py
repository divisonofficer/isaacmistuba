import json,hashlib,shutil
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/shared_dining_residence_05';rows=[]
for folder,id,name in [('hssd_104862513_172226580_pipeline_v1','cdc5ea4b23fbf633b1b59b72870d7db8695938ec','Jessica Single Cabin Bed - Frame Only'),('hssd_107734254_176000121_pipeline_v1','b29f18c61b925bf549c484a58bd2e7515d11eef8','Castello 71 inch round dining table'),('hssd_104348202_171513150_pipeline_v1','52db011b9552d54097709a8a8f9bb1d745fe158e','Spencer round dining table')]:
 src=Path('/bean/datasets/hssd/derived_alpha')/folder/'assets'/id;dst=D/'native_products'/id;assert not dst.exists();shutil.copytree(src,dst);p=dst/'asset.gltf';g=json.loads(p.read_text());deps=[]
 for e in g.get('buffers',[])+g.get('images',[]):
  if 'uri' in e and not e['uri'].startswith('data:'):
   q=dst/e['uri'];deps.append({'uri':e['uri'],'sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
 rows.append({'id':'HSSD_'+id,'name':name,'path':str(p),'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'original_path':str(src/'asset.gltf'),'dependencies':deps,'mr_override':{},'scope':'Unchanged native mesh and source material maps; optical classification unreviewed'})
(D/'native_products_manifest.json').write_text(json.dumps({'assets':rows},indent=2));print('NATIVE_DINING_PRODUCTS_COPIED')
