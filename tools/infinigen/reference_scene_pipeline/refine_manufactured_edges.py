"""Small physical radii on remaining coarse rigid blocks; never bevel dense native meshes."""
import argparse,bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;previous,revision=(22,23) if office else (28,29);base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_candidate_r{previous}.blend';out=base/f'scene_candidate_r{revision}.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));changes=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('reference_scene_owner')!=scene or len(o.data.polygons)!=6 or any(m.type=='BEVEL' for m in o.modifiers):continue
 if min(o.dimensions)<.008 or 'ceiling_fixture' in o.get('program_key',''):continue
 kinds={m.get('reference_pbr_kind') for m in o.data.materials if m}
 if 'textile' in kinds or any(t in o.get('program_key','') for t in ('duvet','pillow','garment','folded_knit')):continue
 width=min(.0015 if kinds&{'stone','floor_stone'} or o.get('audit_kind')=='stair_tread' else .0008,min(o.dimensions)*.055)
 modifier=o.modifiers.new('FineR4_manufacturing_radius','BEVEL');modifier.width=width;modifier.segments=3;modifier.use_clamp_overlap=True;weighted=o.modifiers.new('FineR4_weighted_planar_normals','WEIGHTED_NORMAL');weighted.keep_sharp=True;changes.append({'object':o.name,'role':o.get('program_key'),'radius_m':width})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before;(ref/f'realism_refinement_r{revision}.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'physical_edge_changes':changes,'count':len(changes),'scope':'Only remaining owner-tagged rigid6-face blocks; inward rounded edge with overlap clamp. Dense native meshes and fabrics excluded.','photorealism_accepted':False},indent=2));print(json.dumps({'saved':str(out),'edge_objects':len(changes)}),flush=True)
