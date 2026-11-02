"""Native front/back media-donor views; no shape rescaling or room adoption."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector,Matrix
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
from compact_wc_contract import mesh_geometry_hash
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/native_media_products';dst=d/'review_studio.blend';assert not dst.exists();bpy.ops.wm.read_factory_settings(use_empty=True);views=[];rows=[]
for i,e in enumerate(json.loads((d/'asset_manifest.json').read_text())['assets']):
 new,objs,profile=import_curated_gltf(e,repair_nonpositive_ior=1.5);matrices={o:o.matrix_world.copy() for o in objs};native_hashes={o.name:mesh_geometry_hash(o.data) for o in objs}
 for o in objs:o.parent=None;o.matrix_world=matrices[o]
 for o in new:
  if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
 def bounds():
  p=[o.matrix_world@v.co for o in objs for v in o.data.vertices];return Vector([min(v[k] for v in p) for k in range(3)]),Vector([max(v[k] for v in p) for k in range(3)])
 lo,hi=bounds();size=hi-lo;expected=e['native_metadata_dimensions_width_height_depth_m'];target=Vector((expected[0],expected[2],expected[1]));orient='native imported Z-up'
 if max(abs(size[k]-target[k]) for k in range(3))>.005:
  accepted=False
  for angle in [math.pi/2,-math.pi/2]:
   rotation=Matrix.Rotation(angle,4,'X');pp=[rotation@o.matrix_world@v.co for o in objs for v in o.data.vertices];sz=Vector([max(v[k] for v in pp)-min(v[k] for v in pp) for k in range(3)])
   if max(abs(sz[k]-target[k]) for k in range(3))<.005:
    for o in objs:o.matrix_world=rotation@o.matrix_world
    orient='rigid X reorientation '+str(math.degrees(angle));accepted=True;break
  assert accepted,(e['id'],list(size),list(target))
 lo,hi=bounds();size=hi-lo;cx=i*4.;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
 for o in objs:o.location+=delta;o['original_asset_id']=e['id'];assert mesh_geometry_hash(o.data)==native_hashes[o.name]
 optical=[]
 for m in {m for o in objs for m in o.data.materials if m and m.use_nodes}:
  bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');s=bs.inputs['IOR']
  if not s.is_linked and s.default_value<=1:optical.append({'material':m.name,'before_ior':float(s.default_value),'after_ior':1.5,'inferred_ordinary_dielectric_role':True});s.default_value=1.5
 target_point=Vector((cx,0,size.z*.5));span=max(size)*1.4
 for label,offset in [('front',(.6,-2.7,1.1)),('rear',(-.6,2.7,1.1))]:
  views.append({'name':e['id']+'_'+label,'location':list(Vector((cx,0,0))+Vector(offset)),'target':list(target_point),'overview':True,'ortho_scale':span,'render_width':1280,'samples':48})
 for j,(offset,power) in enumerate([((-.7,-2.0,2.5),160),((1.5,1.5,1.8),80)]):
  ld=bpy.data.lights.new(e['id']+'_studio_'+str(j),'AREA');ld.energy=power;ld.size=1.3;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=Vector((cx,0,0))+Vector(offset);o.rotation_euler=(target_point-o.location).to_track_quat('-Z','Y').to_euler()
 rows.append({'id':e['id'],'name':e['name'],'objects':[o.name for o in objs],'actual_dimensions_xyz_m':list(size),'orientation':orient,'native_geometry_sha256':native_hashes,'native_polygons':sum(len(o.data.polygons) for o in objs),'post_import_rigid_translation_m':list(delta),'material_profile':profile,'additional_explicit_ior_role_corrections':optical})
images={n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image};packed=[preserve_native_packed_image(im) for im in images];w=bpy.data.worlds.new('Native_media_neutral_studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.12;bpy.context.scene.world=w;bpy.ops.wm.save_as_mainfile(filepath=str(dst));(d/'views.json').write_text(json.dumps(views,indent=2));(d/'scope.json').write_text(json.dumps({'assets':rows,'packed_images':packed,'scope':'Five actual native meshes, no post-import resizing, source UV/images retained, rigid orientation/place only. Material constants explicitly inferred, not measured; source1M/IOR0 defaults corrected provisionally. Front/back actual renders and independent construction/material/ref fit required before any room integration.','accepted':False},indent=2));print('NATIVE_MEDIA_STUDIO_SAVED',[(x['name'],x['native_polygons'],x['actual_dimensions_xyz_m']) for x in rows])
