"""Bounded local product metadata screening; no visual or room-fit acceptance."""
import csv,json,hashlib,datetime
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';csvpath=Path('/bean/datasets/hssd/hssd-hab/semantics/objects.csv');roots=[x for x in Path('/bean/datasets/hssd/derived_alpha').iterdir() if x.is_dir() and x.name.endswith('pipeline_v1')];candidates=[];screened=0
with csvpath.open() as f:
 for row in csv.DictReader(f):
  if row.get('main_category')!='curtain' or 'shower' in row['name'].lower():continue
  try:size=[float(x) for x in row['aligned.dims'].split(',')]
  except ValueError:continue
  if len(size)!=3 or not(2.2<=size[1]<=2.7 and .35<=size[0]<=2.6 and .02<=size[2]<=.55):continue
  screened+=1;paths=[root/'assets'/row['id']/'asset.gltf' for root in roots];src=next((p for p in paths if p.exists()),None)
  if src is None:continue
  gltf=json.loads(src.read_text());indices=gltf.get('accessors',[]);triangles=sum(indices[x['indices']]['count']//3 for m in gltf.get('meshes',[]) for x in m.get('primitives',[]) if 'indices' in x and x.get('mode',4)==4);mats=[]
  for m in gltf.get('materials',[]):
   b=m.get('pbrMetallicRoughness',{});mats.append({'name':m.get('name'),'baseColorFactor':b.get('baseColorFactor',[1,1,1,1]),'metallicFactor':b.get('metallicFactor',1),'roughnessFactor':b.get('roughnessFactor',1),'baseColorTexture':'baseColorTexture' in b,'metallicRoughnessTexture':'metallicRoughnessTexture' in b,'normalTexture':'normalTexture' in m,'alphaMode':m.get('alphaMode','OPAQUE'),'doubleSided':m.get('doubleSided',False)})
  candidates.append({'id':'HSSD_'+row['id'],'name':row['name'],'native_metadata_dimensions_width_height_depth_m':size,'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'triangles':triangles,'material_slots':mats,'orientation_metadata':{'up':row.get('up'),'front':row.get('front')}})
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'metadata_source':str(csvpath),'metadata_sha256':hashlib.sha256(csvpath.read_bytes()).hexdigest(),'bounded_derived_scene_roots':len(roots),'metadata_matches_screened':screened,'available_native_candidates':len(candidates),'candidates':sorted(candidates,key=lambda x:-x['triangles']),'scope':'Actual native curtain products only, metadata height2.2–2.7m. No shape rescaling, copying or room integration. Native mesh/UV/materials and cloth construction still require studio render, support/rod and room-fit tests. Metallic defaults and textile role are explicitly unvalidated.','accepted':False};(d/'curtain120_metadata_screen.json').write_text(json.dumps(result,indent=2));print('CURTAIN120_SCREEN',screened,len(candidates));print([(x['id'],x['name'],x['triangles'],x['native_metadata_dimensions_width_height_depth_m']) for x in sorted(candidates,key=lambda x:-x['triangles'])[:8]])
