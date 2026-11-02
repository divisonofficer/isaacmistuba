"""Door veneer grain-axis control only; no manufactured joinery or realism claim."""
import bpy,json,math,hashlib
from pathlib import Path
root=Path('/jarvis/project/robomituba');base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r78.blend';out=base/'scene_candidate_r79.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));m=bpy.data.materials['office02_door_oak'];mapping=[n for n in m.node_tree.nodes if n.type=='MAPPING'];assert len(mapping)==1;mp=mapping[0];before=list(mp.inputs['Rotation'].default_value);assert max(abs(x) for x in before)<1e-6
users=[o for o in bpy.data.objects if o.type=='MESH' and m in list(o.data.materials)];assert users and all('DoorFactory' in o.name for o in users),[o.name for o in users]
rows=[]
for o in users:
 fs=[f for f in o.data.polygons if o.data.materials[f.material_index]==m];ids={i for f in fs for i in f.vertices};vs=[o.data.vertices[i].co for i in ids];ext=[max(v[k] for v in vs)-min(v[k] for v in vs) for k in range(3)];assert ext[2]>1.8 and ext[0]<.2 and ext[1]>.5,(o.name,ext);rows.append({'object':o.name,'local_wood_extents_m':ext,'raw_mesh_sha256':hashlib.sha256(repr([tuple(v.co) for v in o.data.vertices]).encode()).hexdigest()})
# Native realized doors have local X thickness, Y width, Z height. On BOX ±X faces,
# source horizontal grain runs along mapped Y. Rotate around X to map height to Y.
mp.inputs['Rotation'].default_value=(math.pi/2,0,0)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r79.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'material':m.name,'rotation_radians_before':before,'rotation_radians_after':list(mp.inputs['Rotation'].default_value),'users':rows,'change':'One shared door veneer coordinate rotation; all linked albedo,roughness,normal images use the same rotated coordinates. All raw geometry,material indices,shader parameters,lights,cameras andlayout unchanged.','limitations':'Veneer axis control only. Does not create separate solid-timber rails/stiles,endgrain,joinery or fix tangent-space normal/triplanar reconstruction. Must compare visible grain and shading before any adoption.','photorealism_accepted':False},indent=2));print('Saved candidate79 grain-axis trial',len(rows),flush=True)
