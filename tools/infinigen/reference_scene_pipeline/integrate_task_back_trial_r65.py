"""Replace one private-office task chair back only for a source-bound room trial."""
import bpy,json,hashlib
from pathlib import Path
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r63.blend';dst=base/'scene_candidate_r65.blend';assert not dst.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));target=next(o for o in bpy.data.objects if o.get('program_key')=='private_1_chair');matrix=target.matrix_world.copy();materials=list(target.data.materials)
def signatures(mesh,exclude_back=False):
 return sorted((f.material_index,tuple(sorted(tuple(round(float(c),6) for c in mesh.vertices[i].co) for i in f.vertices))) for f in mesh.polygons if not(exclude_back and f.material_index==3))
expected=signatures(target.data,True)
names=('Prototype_native_base_curved_back','Rounded curved back frame','Curved mesh back')
with bpy.data.libraries.load(str(ref/'task_chair_back_studio01/studio.blend'),link=False) as (a,b):b.objects=list(names)
objects=list(b.objects);assert all(objects)
proto=objects[0];target.data=proto.data.copy();face_indices=[f.material_index for f in target.data.polygons];target.data.materials.clear()
for m in materials:target.data.materials.append(m)
for f,index in zip(target.data.polygons,face_indices):f.material_index=index
assert signatures(target.data)==expected,'Native base/seat face geometry or material index changed'
bpy.data.objects.remove(proto,do_unlink=True)
added=[]
for i,o in enumerate(objects[1:]):
 bpy.context.scene.collection.objects.link(o);o.matrix_world=matrix;o['reference_scene_owner']='commercial_office_floor_02';o['program_key']='private_1_chair_back_'+str(i);o['audit_kind']='detail';added.append(o.name)
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r65.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(dst),'target':'private_1_chair','added':added,'change':'single chair: native seat/base retained, slot3 rectangular back replaced by reviewed curved frame and woven-alpha sheet prototype; no other chair modified','base_seat_geometry_and_material_index_signatures_preserved':True,'fix':'r64 material clear reset polygon assignments; restore and verify exact source face signatures','photorealism_accepted':False,'requires':'saved-source audits and same private_office camera direct/blind comparison; manufacturing/support limitations remain'},indent=2));print(dst,flush=True)
