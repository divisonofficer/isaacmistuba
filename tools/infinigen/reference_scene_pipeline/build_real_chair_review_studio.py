"""Actual ABO/HSSD chairs with unmodified imported materials; two views per model."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_chair_candidates';manifest=json.loads((p/'asset_candidates_manifest.json').read_text());out=p/'review_studio.blend';assert not out.exists();bpy.ops.wm.read_factory_settings(use_empty=True);views=[];rows=[]
for idx,entry in enumerate(manifest['assets']):
 src=Path(entry['path']);assert hashlib.sha256(src.read_bytes()).hexdigest()==entry['copied_sha256'];before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(src));new=[o for o in bpy.data.objects if o not in before];objects=[o for o in new if o.type=='MESH'];assert objects;world={o.name:o.matrix_world.copy() for o in objects}
 for o in objects:o.parent=None;o.matrix_world=world[o.name]
 for o in new:
  if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
 points=[o.matrix_world@v.co for o in objects for v in o.data.vertices];lo=Vector(tuple(min(v[k] for v in points) for k in range(3)));hi=Vector(tuple(max(v[k] for v in points) for k in range(3)));h=hi.z-lo.z;assert .7<h<1.5,(entry['id'],h);cx=idx*5.;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
 for o in objects:o.location+=delta;o['original_asset_id']=entry['id'];o['original_asset_sha256']=entry['copied_sha256']
 target=Vector((cx,0,h/2));span=max(hi.x-lo.x,h*4/3,hi.y-lo.y)
 for side,offset in [('a',(1.2,-2,1.15)),('b',(-1.2,2,1.15))]:views.append({'name':entry['id']+'_view_'+side,'location':list(Vector((cx,0,0))+Vector(offset)),'target':list(target),'overview':True,'ortho_scale':span*1.35,'render_width':1280,'samples':64})
 for j,(offset,power,size) in enumerate([((0,-2,3),130,1.5),((2,1,2),70,1.2)]):
  ld=bpy.data.lights.new(entry['id']+f'_area{j}','AREA');ld.energy=power;ld.shape='DISK';ld.size=size;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=Vector((cx,0,0))+Vector(offset);o.rotation_euler=(target-o.location).to_track_quat('-Z','Y').to_euler()
 rows.append({'id':entry['id'],'source':entry['path'],'source_sha256':entry['copied_sha256'],'objects':[o.name for o in objects],'vertices':sum(len(o.data.vertices) for o in objects),'polygons':sum(len(o.data.polygons) for o in objects),'original_world_extents_m':list(hi-lo),'translation_only_m':list(delta),'materials':sorted({s.material.name for o in objects for s in o.material_slots if s.material}),'native_materials_unmodified':True})
images=[]
for im in bpy.data.images:
 if im.source!='FILE':continue
 assert min(im.size)>0,im.name
 im.pack();assert im.packed_file,('Embedded texture not persisted;extract/rebind original PNG before RGB',im.name);images.append({'name':im.name,'dimensions':list(im.size),'packed':bool(im.packed_file)})
mat=bpy.data.materials.new('Diagnostic_floor_only');mat.use_nodes=True;bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.22,.22,.22,1);bs.inputs['Roughness'].default_value=.75;me=bpy.data.meshes.new('Diagnostic_floor_quad');me.from_pydata([(-4,-6,-.003),(14,-6,-.003),(14,6,-.003),(-4,6,-.003)],[],[(0,1,2,3)]);me.materials.append(mat);o=bpy.data.objects.new('Diagnostic_floor_only',me);bpy.context.scene.collection.objects.link(o);w=bpy.data.worlds.new('Neutral_chair_studio');w.use_nodes=True;w.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=w;bpy.ops.wm.save_as_mainfile(filepath=str(out));(p/'review_views.json').write_text(json.dumps(views,indent=2)+'\n');(p/'review_scope.json').write_text(json.dumps({'assets':rows,'images':images,'views':6,'scope':'Real source mesh/UV/PBR materials unmodified;parent transforms preserved andtranslation tostudio/floor only. Two opposing quarter views perchair,no front orientation claim yet. Diagnosticfloor/light stage isnot a furniture stand-in. No office scene integration orvisual acceptance. HSSD material factors partly inferred peroriginal index,not measured PBR.','photorealism_accepted':False},indent=2)+'\n');print('Built actual chair studio3 models6 views',flush=True)
