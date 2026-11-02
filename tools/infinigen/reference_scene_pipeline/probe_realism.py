"""Inspect actual mesh and assigned materials without accepting image realism."""
import bpy,json,argparse,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';root=Path(__file__).resolve().parents[3];scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;rev=18 if office else 22;source=root/'out/infinigen_v2'/f'kr_{scene}_{seed}/full'/f'scene_review_r{rev}_packed.blend';bpy.ops.wm.open_mainfile(filepath=str(source));rows=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('reference_scene_owner')!=scene:continue
 key=o.get('program_key','')
 if not any(t in key for t in (('coffee_','sink_','tap_','private_1_') if office else ('dressing','living_sectional','bathroom2_vanity','bathroom2_wc'))):continue
 slots=[]
 for i,m in enumerate(o.data.materials):
  if not m:continue
  bs=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None) if m.use_nodes else None
  slots.append({'index':i,'name':m.name,'kind':m.get('reference_pbr_kind'),'faces':sum(f.material_index==i for f in o.data.polygons),'roughness':bs.inputs['Roughness'].default_value if bs else None,'roughness_linked':bool(bs and bs.inputs['Roughness'].is_linked),'normal_linked':bool(bs and bs.inputs['Normal'].is_linked)})
 rows.append({'object':o.name,'role':key,'vertices':len(o.data.vertices),'faces':len(o.data.polygons),'smooth_faces':sum(f.use_smooth for f in o.data.polygons),'modifiers':[{'type':m.type,'name':m.name} for m in o.modifiers],'location':list(o.location),'rotation':list(o.rotation_euler),'scale':list(o.scale),'dimensions':list(o.dimensions),'materials':slots})
ref=root/'data/venue_refs/floor_plans_v3'/scene;(ref/'realism_baseline_geometry.json').write_text(json.dumps({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'objects':rows,'visual_realism_accepted':False},indent=2));print(json.dumps({'scene':scene,'objects':len(rows)}),flush=True)
