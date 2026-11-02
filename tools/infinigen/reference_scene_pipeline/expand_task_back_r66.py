"""Expand locally reviewed r65 back to all native task chairs, preserving base face/material signatures."""
import bpy,json,hashlib
from pathlib import Path
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r65.blend';dst=base/'scene_candidate_r66.blend';assert not dst.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
targets=[o for o in bpy.data.objects if o.type=='MESH' and 'TaskChairFactory' in o.name];assert len(targets)==31,len(targets)
for o in list(bpy.data.objects):
 if o.get('program_key','').startswith('private_1_chair_back_'):bpy.data.objects.remove(o,do_unlink=True)
def signatures(mesh,exclude_back=False):return sorted((f.material_index,tuple(sorted(tuple(round(float(c),6) for c in mesh.vertices[i].co) for i in f.vertices))) for f in mesh.polygons if not(exclude_back and f.material_index==3))
names=('Prototype_native_base_curved_back','Rounded curved back frame','Curved mesh back')
with bpy.data.libraries.load(str(ref/'task_chair_back_studio01/studio.blend'),link=False) as (a,b):b.objects=list(names)
proto,frame,sheet=b.objects;assert proto and frame and sheet;rows=[]
for target in targets:
 expected=signatures(target.data,True);materials=list(target.data.materials);target.data=proto.data.copy();indices=[f.material_index for f in target.data.polygons];target.data.materials.clear()
 for m in materials:target.data.materials.append(m)
 for f,index in zip(target.data.polygons,indices):f.material_index=index
 assert signatures(target.data)==expected,(target.name,'base changed')
 for i,template in enumerate([frame,sheet]):
  o=template.copy();bpy.context.scene.collection.objects.link(o);o.matrix_world=target.matrix_world.copy();o.name='R66_'+target.get('program_key')+'_back_'+str(i);o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=target.get('program_key')+'_back_'+str(i);o['audit_kind']='detail'
 rows.append({'chair':target.name,'key':target.get('program_key'),'base_seat_face_geometry_material_indices_preserved':True})
for o in [proto,frame,sheet]:bpy.data.objects.remove(o,do_unlink=True)
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r66.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(dst),'change':'locally reviewed r65 curved mesh back expanded to31 task chairs; all base/seat face geometry and material-index signatures verified; locations unchanged','chairs':rows,'photorealism_accepted':False,'remaining':'whole scene comparison/support/required-space/texture checks; angular arms/base and repetitive planting not solved'},indent=2));print(dst,flush=True)
