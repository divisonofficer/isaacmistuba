"""Actual mesh-back office chair candidate; preserve native geometry and exact embedded images."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_tall_meshback_chair_candidate';manifest=json.loads((p/'asset_candidates_manifest.json').read_text());out=p/'review_studio.blend';assert not out.exists();bpy.ops.wm.read_factory_settings(use_empty=True);views=[];rows=[]
for idx,entry in enumerate(manifest['assets']):
 src=root/entry['path'];assert hashlib.sha256(src.read_bytes()).hexdigest()==entry['copied_sha256'];before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(src));new=[o for o in bpy.data.objects if o not in before];objects=[o for o in new if o.type=='MESH'];assert objects;bpy.context.view_layer.update();world={o.name:o.matrix_world.copy() for o in objects}
 for o in objects:o.parent=None;o.matrix_world=world[o.name]
 for o in new:
  if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
 # Imported embedded image handles may fail to persist; bind exact original bytes by native image index.
 import re,struct
 raw_glb=src.read_bytes();json_length=struct.unpack_from('<I',raw_glb,12)[0];gltf_doc=json.loads(raw_glb[20:20+json_length]);native_names={im.get('name',''):i for i,im in enumerate(gltf_doc.get('images',[]))}
 replacements={}
 for obj in objects:
  for slot in obj.material_slots:
   if not slot.material or not slot.material.use_nodes:continue
   for node in slot.material.node_tree.nodes:
    if node.type!='TEX_IMAGE' or not node.image:continue
    old=node.image
    if old.name not in replacements:
     match=re.match(r'Image_(\d+)',old.name)
     base_name=re.sub(r'\.\d{3}$','',old.name);image_index=native_names.get(base_name)
     if image_index is None:
      prefix_matches=[i for name,i in native_names.items() if name.startswith(base_name)]
      if len(prefix_matches)==1:image_index=prefix_matches[0]
     if image_index is None and match:image_index=int(match.group(1))
     assert image_index is not None,(old.name,native_names)
     image_entry=next(x for x in entry['native_images'] if x['index']==image_index)
     original=root/image_entry['path'];assert hashlib.sha256(original.read_bytes()).hexdigest()==image_entry['sha256']
     image=bpy.data.images.load(str(original),check_existing=False);image.colorspace_settings.name=old.colorspace_settings.name;image.pack();assert image.packed_file and hashlib.sha256(bytes(image.packed_file.data)).hexdigest()==image_entry['sha256'];replacements[old.name]=image
    node.image=replacements[old.name]
 points=[o.matrix_world@v.co for o in objects for v in o.data.vertices];lo=Vector(tuple(min(v[k] for v in points) for k in range(3)));hi=Vector(tuple(max(v[k] for v in points) for k in range(3)));h=hi.z-lo.z;assert .65<h<1.3,(entry['id'],h);cx=idx*8.;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
 for o in objects:o.location+=delta;o['original_asset_id']=entry['id'];o['original_asset_sha256']=entry['copied_sha256']
 target=Vector((cx,0,h/2));span=max(hi.x-lo.x,h*4/3,hi.y-lo.y)
 for side,offset in [('a',(2.8,-4,2.3)),('b',(-2.8,4,2.3))]:views.append({'name':entry['id']+'_view_'+side,'location':list(Vector((cx,0,0))+Vector(offset)),'target':list(target),'overview':True,'ortho_scale':span*1.35,'render_width':1280,'samples':64})
 for j,(offset,power,size) in enumerate([((0,-2,3),130,1.5),((2,1,2),70,1.2)]):
  ld=bpy.data.lights.new(entry['id']+f'_area{j}','AREA');ld.energy=power;ld.shape='DISK';ld.size=size;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=Vector((cx,0,0))+Vector(offset);o.rotation_euler=(target-o.location).to_track_quat('-Z','Y').to_euler()
 rows.append({'id':entry['id'],'source':entry['path'],'source_sha256':entry['copied_sha256'],'objects':[o.name for o in objects],'vertices':sum(len(o.data.vertices) for o in objects),'polygons':sum(len(o.data.polygons) for o in objects),'original_world_extents_m':list(hi-lo),'translation_only_m':list(delta),'materials':sorted({s.material.name for o in objects for s in o.material_slots if s.material}),'native_materials_unmodified':True})
images=[]
used_images={n.image for mat in bpy.data.materials if mat.use_nodes for n in mat.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}
for im in used_images:
 if im.source!='FILE':continue
 assert min(im.size)>0,im.name
 im.pack();assert im.packed_file,('Embedded texture not persisted;extract/rebind original PNG before RGB',im.name);images.append({'name':im.name,'dimensions':list(im.size),'packed':bool(im.packed_file)})
mat=bpy.data.materials.new('Diagnostic_floor_only');mat.use_nodes=True;bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.22,.22,.22,1);bs.inputs['Roughness'].default_value=.75;me=bpy.data.meshes.new('Diagnostic_floor_quad');me.from_pydata([(-4,-6,-.003),(22,-6,-.003),(22,6,-.003),(-4,6,-.003)],[],[(0,1,2,3)]);me.materials.append(mat);o=bpy.data.objects.new('Diagnostic_floor_only',me);bpy.context.scene.collection.objects.link(o);w=bpy.data.worlds.new('Neutral_sofa_studio');w.use_nodes=True;w.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=w;bpy.ops.wm.save_as_mainfile(filepath=str(out));(p/'review_views.json').write_text(json.dumps(views,indent=2)+'\n');(p/'review_scope.json').write_text(json.dumps({'assets':rows,'images':images,'views':len(views),'scope':'Real source mesh/UV/PBR materials unmodified;parent transforms preserved andtranslation tostudio/floor only. Two opposing quarter views per sofa,no front orientation claim yet. Diagnosticfloor/light stage isnot a furniture stand-in. No office scene integration orvisual acceptance. Original ABO product PBR preserved,not claimed measured BRDF.','photorealism_accepted':False},indent=2)+'\n');print('Built actual meshback chair studio: 1 model, 2 views',flush=True)
