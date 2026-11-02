"""Explicit vegetation/soil/container supports,including actual full-depth soil volume."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r58.blend';out=base/'scene_candidate_r59.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
parts=[o for o in bpy.data.objects if o.name.startswith('R58_office_')];soil=next(o for o in parts if o.get('program_key')=='soil_4');pot=next(o for o in parts if o.get('program_key')=='pot_4')
pot['audit_kind']='ground_container';soil['audit_kind']='container_contents';soil['support_object']=pot.name
for o in parts:
 if 'Indoor_leaf_' in o.name:o['audit_kind']='vegetation';o['support_object']=soil.name
# Soil fills the cavity to2mm above the closed inner bottom,instead of a floating thin surface disc.
for v in soil.data.vertices:
 oldz=v.co.z;r=(v.co.x*v.co.x+v.co.y*v.co.y)**.5
 target_z=.027 if oldz<0 else .3625;target_r=.150 if oldz<0 else .214
 if r>1e-9:v.co.x*=target_r/r;v.co.y*=target_r/r
 v.co.z=target_z-.350
soil.data.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r59.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'changes':['Leaf roots explicitly supported by soil,soil byhollow pot,pot byfloor','Full-depth tapered soil volume from27to362.5mm above planter base;2mm bottom support gap','Audit vegetation uses actual mesh root height rather than rotated bbox corners'],'scope':'One plant support metadata andsoil cavity volume only;leaf shapes/shaders,planter andrest scene unchanged','photorealism_accepted':False,'requires':'Actual support/container intersection audits andsame wide render'},indent=2));print('SAVED',out,flush=True)
