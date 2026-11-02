"""Two native high-poly indoor trees;material-profile-aware studio screen."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).parent));from curated_gltf_materials import import_curated_gltf
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_indoor_tree_candidates';out=d/'review_studio.blend';assert not out.exists();manifest=json.loads((d/'asset_manifest.json').read_text());bpy.ops.wm.read_factory_settings(use_empty=True);views=[];rows=[]
for idx,entry in enumerate(manifest['assets']):
 new,objects,profile=import_curated_gltf(entry,repair_nonpositive_ior=1.5);matrices={o.name:o.matrix_world.copy() for o in objects}
 for o in objects:o.parent=None;o.matrix_world=matrices[o.name]
 for o in new:
  if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
 bpy.context.view_layer.update();points=[o.matrix_world@v.co for o in objects for v in o.data.vertices];lo=Vector([min(p[k] for p in points) for k in range(3)]);hi=Vector([max(p[k] for p in points) for k in range(3)]);size=hi-lo;assert 1.5<size.z<2.4,(entry['id'],list(size));cx=idx*6.;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
 for o in objects:o.location+=delta;o['original_asset_id']=entry['id'];o['original_asset_sha256']=entry['copied_sha256']
 target=Vector((cx,0,size.z*.5));views.append({'name':entry['id']+'_whole','location':[cx+3,-5,2.6],'target':list(target),'overview':True,'ortho_scale':size.z*1.43,'render_width':768,'samples':32});views.append({'name':entry['id']+'_leaf_detail','location':[cx+.65,-1.8,size.z*.72+.15],'target':[cx,0,size.z*.72],'overview':True,'ortho_scale':.85,'render_width':768,'samples':32})
 for j,(offset,power,span) in enumerate([((-2,-3,3.5),220,2.5),((2,2,2.8),100,2)]):
  ld=bpy.data.lights.new(entry['id']+f'_area{j}','AREA');ld.energy=power;ld.shape='DISK';ld.size=span;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=Vector((cx,0,0))+Vector(offset);o.rotation_euler=(target-o.location).to_track_quat('-Z','Y').to_euler()
 rows.append({'id':entry['id'],'name':entry['name'],'source_sha256':entry['copied_sha256'],'objects':[o.name for o in objects],'polygons':sum(len(o.data.polygons) for o in objects),'native_extent_m':list(size),'translation_only':list(delta),'native_geometry_uv_unchanged':True,'material_profile_contract':profile})
images=[]
for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}:
 assert min(im.size)>0;im.pack();assert im.packed_file;images.append({'name':im.name,'dimensions':list(im.size),'packed_sha256':hashlib.sha256(bytes(im.packed_file.data)).hexdigest()})
bpy.ops.mesh.primitive_plane_add(size=40,location=(3,0,-.003));floor=bpy.context.object;mat=bpy.data.materials.new('Diagnostic_tree_studio_floor');mat.use_nodes=True;bs=mat.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.22,.22,.22,1);bs.inputs['Roughness'].default_value=.75;floor.data.materials.append(mat);w=bpy.data.worlds.new('Neutral_tree_studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.12;bpy.context.scene.world=w;bpy.ops.wm.save_as_mainfile(filepath=str(out));(d/'review_views.json').write_text(json.dumps(views,indent=2));(d/'review_scope.json').write_text(json.dumps({'assets':rows,'packed_images':images,'scope':'Actual source tree mesh/UV/base/normal images,declared inferred MR overrides and explicit invalidIOR repair1.5. No leaf translucency or real-measured BRDF claim;no scene integration/photo approval.','photorealism_accepted':False},indent=2));print('REAL_INDOOR_TREES_STUDIO_SAVED',flush=True)
