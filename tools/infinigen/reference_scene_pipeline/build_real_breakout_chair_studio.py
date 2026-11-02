"""Actual source dining-chair assemblies and native materials; four studio views, no room integration."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
import sys
sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
root=Path(__file__).resolve().parents[3];ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';p=ref/'real_breakout_chair_candidates';assert p.exists();out=p/'review_studio.blend';assert not out.exists();manifest=json.loads((p/'asset_manifest.json').read_text());bpy.ops.wm.read_factory_settings(use_empty=True);views=[];rows=[]
for idx,e in enumerate(manifest['assets']):
 src=root/e['path'];assert hashlib.sha256(src.read_bytes()).hexdigest()==e['copied_sha256'];new,objects,material_profile=import_curated_gltf(e,repair_nonpositive_ior=1.5);matrices={o.name:o.matrix_world.copy() for o in objects}
 for o in objects:o.parent=None;o.matrix_world=matrices[o.name]
 for o in new:
  if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
 bpy.context.view_layer.update();points=[o.matrix_world@v.co for o in objects for v in o.data.vertices];lo=Vector(tuple(min(q[k] for q in points) for k in range(3)));hi=Vector(tuple(max(q[k] for q in points) for k in range(3)));size=hi-lo;assert .7<size.z<1.2,(e['id'],list(size));cx=idx*5.;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
 for o in objects:o.location+=delta;o['original_asset_id']=e['id'];o['original_asset_sha256']=e['copied_sha256']
 target=Vector((cx,0,size.z*.55));span=max(size.x,size.y,size.z*4/3)
 for side,offset in [('a',(1.8,-2.8,1.8))]:views.append({'name':e['id']+'_view_'+side,'location':list(Vector((cx,0,0))+Vector(offset)),'target':list(target),'overview':True,'ortho_scale':span*1.45,'render_width':768,'samples':32})
 for j,(offset,power,light_size) in enumerate([((0,-2,3),130,1.5),((2,1,2),70,1.2)]):
  ld=bpy.data.lights.new(e['id']+f'_area{j}','AREA');ld.energy=power;ld.shape='DISK';ld.size=light_size;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=Vector((cx,0,0))+Vector(offset);o.rotation_euler=(target-o.location).to_track_quat('-Z','Y').to_euler()
 rows.append({'id':e['id'],'source':e['path'],'source_sha256':e['copied_sha256'],'objects':[o.name for o in objects],'polygons':sum(len(o.data.polygons) for o in objects),'extents_m':list(size),'translation_only':list(delta),'native_geometry_uv_unchanged':True,'material_profile_contract':material_profile,'material_metadata':e.get('pbr',[])})
used={n.image for mat in bpy.data.materials if mat.use_nodes for n in mat.node_tree.nodes if n.type=='TEX_IMAGE' and n.image};images=[]
for im in used:
 assert min(im.size)>0,im.name
 im.pack();assert im.packed_file,im.name;images.append({'name':im.name,'dimensions':list(im.size),'packed_sha256':hashlib.sha256(bytes(im.packed_file.data)).hexdigest(),'colorspace':im.colorspace_settings.name})
mat=bpy.data.materials.new('Diagnostic_floor_only');mat.use_nodes=True;bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.22,.22,.22,1);bs.inputs['Roughness'].default_value=.75;me=bpy.data.meshes.new('Diagnostic_floor_quad');me.from_pydata([(-4,-6,-.003),(10,-6,-.003),(10,6,-.003),(-4,6,-.003)],[],[(0,1,2,3)]);me.materials.append(mat);o=bpy.data.objects.new(me.name,me);bpy.context.scene.collection.objects.link(o);w=bpy.data.worlds.new('Neutral_table_studio');w.use_nodes=True;w.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=w;bpy.ops.wm.save_as_mainfile(filepath=str(out));(p/'review_views.json').write_text(json.dumps(views,indent=2)+'\n');(p/'review_scope.json').write_text(json.dumps({'assets':rows,'packed_images':images,'scope':'Actual product table geometry/UV unchanged; declared role material profiles applied, diagnostic lights/floor only. Inferred source material parameters retained, not claimed measured PBR. No residential integration, no photorealism approval.','photorealism_accepted':False},indent=2)+'\n');print('BREAKOUT_CHAIR_STUDIO_SAVED',flush=True)
