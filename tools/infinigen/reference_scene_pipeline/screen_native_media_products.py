"""Native-size catalogue donors for correcting TV/sofa layout without shrinking props."""
from pathlib import Path
import csv,json,hashlib,re
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';csvpath=Path('/bean/datasets/hssd/hssd-hab/semantics/objects.csv');roots=[p for p in Path('/bean/datasets/hssd/derived_alpha').iterdir() if p.is_dir() and p.name.endswith('pipeline_v1')];rows=[];matches=0
with csvpath.open() as f:
 for row in csv.DictReader(f):
  text=str(row).lower()
  if not any(w in text for w in ['tv_stand','television_receiver','television_set','tv stand','tv bench','tv cabinet']):continue
  try:size=[float(x) for x in row['aligned.dims'].split(',')]
  except ValueError:continue
  if len(size)!=3 or not (1.15<=size[0]<=1.8 and .3<=size[1]<=1.05 and .015<=size[2]<=.55):continue
  matches+=1;src=next((p/'assets'/row['id']/'asset.gltf' for p in roots if (p/'assets'/row['id']/'asset.gltf').exists()),None)
  if not src:continue
  a=json.loads(src.read_text());access=a.get('accessors',[]);tris=sum(access[p['indices']]['count']//3 for m in a.get('meshes',[]) for p in m.get('primitives',[]) if p.get('mode',4)==4 and 'indices' in p);mats=[]
  for m in a.get('materials',[]):
   q=m.get('pbrMetallicRoughness',{});mats.append({'name':m.get('name'),'metallic':q.get('metallicFactor',1),'roughness':q.get('roughnessFactor',1),'ior_extension':m.get('extensions',{}).get('KHR_materials_ior'),'basecolor_map':'baseColorTexture' in q,'normal_map':'normalTexture' in m})
  rows.append({'id':'HSSD_'+row['id'],'name':row['name'],'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'native_metadata_dimensions_width_height_depth_m':size,'triangles':tris,'material_slots_unvalidated':mats})
result={'metadata_source':str(csvpath),'metadata_sha256':hashlib.sha256(csvpath.read_bytes()).hexdigest(),'bounded_roots':len(roots),'metadata_size_matches':matches,'available_candidates':len(rows),'candidates':sorted(rows,key=lambda x:-x['triangles']),'scope':'Native dimensionsW1.15–1.8m andH0.3–1.05m; donors to correct side-facing125TV/sofa layout while preserving entry clearance. No product/size/material/room approval, no rescale, no mesh replacement yet. High triangle count is not appearance proof. Source constants include invalid/inferred defaults and need optical classification/visual QC.','accepted':False};(d/'native_media_product_screen.json').write_text(json.dumps(result,indent=2));print('NATIVE_MEDIA_CATALOGUE',matches,len(rows));print([(x['id'],x['name'],x['triangles'],x['native_metadata_dimensions_width_height_depth_m']) for x in sorted(rows,key=lambda x:-x['triangles'])[:18]])
