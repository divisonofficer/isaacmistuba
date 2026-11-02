"""Native-sized product studio with front/back diagnostics; no scene integration."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector,Matrix
import math
sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/curtain120_products';out=p/'review_studio.blend';assert not out.exists();bpy.ops.wm.read_factory_settings(use_empty=True);views=[];rows=[]
for i,e in enumerate(json.loads((p/'asset_manifest.json').read_text())['assets']):
 new,objs,profile=import_curated_gltf(e,repair_nonpositive_ior=1.5);matrices={o:o.matrix_world.copy() for o in objs}
 for o in objs:o.parent=None;o.matrix_world=matrices[o]
 orientation=0
 if e['id']=='HSSD_634c2c24ba86aa2d543ab13c586cd37465f4283c':
  orientation=90
  for o in objs:o.matrix_world=Matrix.Rotation(math.pi/2,4,'X')@o.matrix_world
 bpy.context.view_layer.update();pts=[o.matrix_world@v.co for o in objs for v in o.data.vertices];lo=Vector([min(v[k] for v in pts) for k in range(3)]);hi=Vector([max(v[k] for v in pts) for k in range(3)]);size=hi-lo;cx=i*4.;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z));assert 2.2<size.z<2.5,(e['id'],list(size))
 for o in objs:o.location+=delta;o['original_asset_id']=e['id']
 target=Vector((cx,0,size.z*.5))
 for side,offset in [('front',(1.5,-4,1.7)),('rear',(-1.5,4,1.7))]:views.append({'name':e['id']+'_'+side,'location':list(Vector((cx,0,0))+Vector(offset)),'target':list(target),'overview':True,'ortho_scale':max(size)*1.65,'render_width':1024,'samples':48})
 views.append({'name':e['id']+'_top_detail','location':[cx+.55,-1.0,size.z-.20],'target':[cx,0,size.z-.25],'hfov':45,'render_width':1280,'samples':48})
 for j,(off,power) in enumerate([((0,-2,3),130),((2,1,2),70)]):
  ld=bpy.data.lights.new(e['id']+str(j),'AREA');ld.energy=power;ld.size=1.4;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=Vector((cx,0,0))+Vector(off);o.rotation_euler=(target-o.location).to_track_quat('-Z','Y').to_euler()
 rows.append({'id':e['id'],'objects':[o.name for o in objs],'extents_m':list(size),'placement_translation_m':list(delta),'rigid_x_reorientation_deg':orientation,'material_profile':profile})
images={n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image};packed=[preserve_native_packed_image(im) for im in images];world=bpy.data.worlds.new('Neutral_native_curtain_studio');world.use_nodes=True;world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=world
bpy.ops.wm.save_as_mainfile(filepath=str(out));(p/'review_views.json').write_text(json.dumps(views,indent=2));(p/'review_scope.json').write_text(json.dumps({'assets':rows,'packed_images':packed,'scope':'Native geometry/size/material data, native source coordinates retained under rigid placement;natural curtain requires90degreeX reorientation to Z-up. Neutral diagnostic lighting. No visual or scene approval.'},indent=2));print('CURTAIN120_PRODUCT_STUDIO_SAVED')
