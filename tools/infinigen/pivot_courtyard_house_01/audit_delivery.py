"""Audit actual scene-delivery artifacts; visual judgement stays in iteration_reviews.json."""
from pathlib import Path
import argparse,json,datetime
from PIL import Image,ImageStat
ROOT=Path(__file__).resolve().parents[3];B=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full'
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);a=p.parse_args();tag=f'r{a.revision}'
refs=json.loads((B/'reference_manifest.json').read_text());top=json.loads((B/'topology_validation.json').read_text());pack=json.loads((F/f'scene_candidate_{tag}.audit.json').read_text());views=json.loads((F/('review_views_r21.json' if a.revision>=21 else ('review_views_r20.json' if a.revision>=20 else 'review_views_r19.json'))).read_text());rows=[]
for v in views:
 path=B/f'renders/interior_gpu_{tag}'/(v['name']+'.png');row={'view':v['name'],'exists':path.exists(),'reference_id':v.get('reference_id')}
 if path.exists():
  with Image.open(path) as im:
   rgb=im.convert('RGB');row.update(dimensions=list(im.size),mean_rgb=ImageStat.Stat(rgb).mean,nonblack=any(e[1]>8 for e in rgb.getextrema()))
 rows.append(row)
reference_rows=[]
for q in refs['rooms']:
 path=B/q['image']
 with Image.open(path) as im:reference_rows.append({'id':q['id'],'path':q['image'],'dimensions':list(im.size)})
manifest=json.loads((ROOT/'out/scene_gallery/infinigen_2.2/manifest.json').read_text());entries=manifest.get('scenes',[]) if isinstance(manifest,dict) else manifest;ph=next((q for q in entries if q.get('id')=='PH'),{})
checks={'24_generated_room_references':len(reference_rows)==24,'source_and_generated_plan':all((B/p).exists() for p in ['source.png','floorplan_v1.png']),'authored_28_cells_connected':top['rooms']==28 and not top['errors'] and not top['unreachable'],'packed_28_room_floors':pack['room_floor_count']==28,'packed_five_bedroom_families':len(pack['bedrooms'])==5 and all(pack['bedrooms'].values()),'all_24_reference_spaces_have_cameras':{q['id'] for q in reference_rows}.issubset({q.get('reference_id') for q in rows}),'packed_no_invalid_mesh_dimensions':not pack['invalid_mesh_dimensions'],'packed_no_nonfinite_vertices':not pack['nonfinite_vertex_meshes'],'packed_no_missing_images':not pack['missing_external_images'],'33_full_resolution_nonblack_images':len(rows)==33 and all(q.get('dimensions')==[1024,768] and q.get('nonblack') for q in rows),'dataset_points_to_current_candidate':ph.get('paths',{}).get('blend')==str(F/f'scene_candidate_{tag}.blend'),'dataset_revision_current':ph.get('round')==a.revision}
d={'scene_id':'pivot_courtyard_house_01','revision':tag,'audited_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'scope_notice':'Image statistics verify output presence/dimensions/nonblack only; visual/reference findings are human-readable session direct inspection in iteration_reviews.json. Authored topology checks do not prove furnished navigation traversability.','references':reference_rows,'views':rows,'packed_audit':str(F/f'scene_candidate_{tag}.audit.json'),'dataset_entry':ph,'all_checks_pass':all(checks.values()),'not_training_promoted':True};(B/f'delivery_audit_{tag}.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'revision':tag,'checks':checks},ensure_ascii=False))
