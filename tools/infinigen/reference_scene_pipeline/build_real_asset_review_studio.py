"""Separate real source assemblies for image review; no scene integration or proxy meshes."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_asset_candidates';src=p/'moorelane_candidates_imported.blend';out=p/'review_studio.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));meshes=[o for o in bpy.data.objects if o.type=='MESH'];assert len(meshes)==15
worlds={o.name:o.matrix_world.copy() for o in meshes}
for o in meshes:o.parent=None;o.matrix_world=worlds[o.name]
for o in list(bpy.data.objects):
 if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
groups={'door':[o for o in meshes if o.name.startswith('Entry') or o.name=='mesh_0'],'fig':[o for o in meshes if o.name.startswith('fig')],'lounge_pair':[o for o in meshes if o.name.startswith(('Chari','living_'))]};assert sorted(len(v) for v in groups.values())==[4,5,6];assert sum(len(v) for v in groups.values())==15
rows=[];views=[]
for idx,(key,objects) in enumerate(groups.items()):
 points=[o.matrix_world@Vector(c) for o in objects for c in o.bound_box];lo=Vector(tuple(min(v[k] for v in points) for k in range(3)));hi=Vector(tuple(max(v[k] for v in points) for k in range(3)));cx=idx*14.;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
 for o in objects:o.location+=delta
 h=hi.z-lo.z;w=hi.x-lo.x;d=hi.y-lo.y;target=Vector((cx,0,h/2));span=max(w,h*4/3,d,1);views.append({'name':'native_'+key,'location':list(target+Vector((span*.5,-span*1.5,span*.48))),'target':list(target),'overview':True,'ortho_scale':span*1.30,'render_width':1280,'samples':48});rows.append({'group':key,'objects':[o.name for o in objects],'original_world_bounds_m':[list(lo),list(hi)],'translation_only_m':list(delta),'unbound_material_objects':[o.name for o in objects if not len(o.material_slots)]})
 for num,(offset,power,size) in enumerate([((0,-3,4.5),450,3),((3,1,3),250,2)]):
  ld=bpy.data.lights.new(f'{key}_studio_area{num}','AREA');ld.energy=power;ld.shape='DISK';ld.size=size;ob=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(ob);ob.location=Vector((cx,0,0))+Vector(offset);ob.rotation_euler=(target-ob.location).to_track_quat('-Z','Y').to_euler()
mat=bpy.data.materials.new('Diagnostic_studio_floor_only');mat.use_nodes=True;bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.25,.25,.25,1);bs.inputs['Roughness'].default_value=.7
me=bpy.data.meshes.new('Diagnostic_floor_quad');me.from_pydata([(-10,-10,-.003),(40,-10,-.003),(40,10,-.003),(-10,10,-.003)],[],[(0,1,2,3)]);me.materials.append(mat);ob=bpy.data.objects.new('Diagnostic_floor_only',me);bpy.context.scene.collection.objects.link(ob)
world=bpy.data.worlds.new('Neutral_asset_review');world.use_nodes=True;world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=world;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(p/'review_studio_views.json').write_text(json.dumps(views,indent=2)+'\n');(p/'review_studio_scope.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'studio':str(out),'groups':rows,'scope':'All15 actual source meshes and native materials preserved;only object translations/parent flattening for separate review. Neutral floor/lights are diagnostic stage,not furniture stand-ins. No office/residential scene integration. Three unbound source chair components remain visibly default material and not approved.','photorealism_accepted':False},indent=2)+'\n');print('Saved real asset review studio',flush=True)
