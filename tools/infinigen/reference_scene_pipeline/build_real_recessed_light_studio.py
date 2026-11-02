"""Actual small product lamp, unlit material/shape views before ceiling mounting."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_recessed_light_candidate';O=D/'review_studio.blend';assert not O.exists();e=json.loads((D/'asset_manifest.json').read_text())['asset'];bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(R/e['path']));bpy.context.view_layer.update();objects=[o for o in bpy.context.scene.objects if o.type=='MESH'];assert objects;matrices={o.name:o.matrix_world.copy() for o in objects}
for o in objects:o.parent=None;o.matrix_world=matrices[o.name]
for o in list(bpy.context.scene.objects):
 if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
pts=[o.matrix_world@v.co for o in objects for v in o.data.vertices];lo=Vector([min(p[k] for p in pts) for k in range(3)]);hi=Vector([max(p[k] for p in pts) for k in range(3)]);center=(lo+hi)/2
for o in objects:o.location-=center;o['original_asset_id']=e['id']
images=[]
for m in bpy.data.materials:
 if not m.use_nodes:continue
 for n in m.node_tree.nodes:
  if n.type=='TEX_IMAGE' and n.image:
   im=n.image;assert min(im.size)>0;im.pack();images.append({'name':im.name,'sha256':hashlib.sha256(bytes(im.packed_file.data)).hexdigest()})
w=bpy.data.worlds.new('Neutral_small_light_studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.2;bpy.context.scene.world=w
for name,loc,power in [('Below_key',(.1,-.2,-.25),2.5),('Above_fill',(-.1,.2,.25),1.5)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.shape='DISK';d.size=.25;o=bpy.data.objects.new(name,d);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(-o.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'product_below','location':[.12,-.2,-.13],'target':[0,0,0],'overview':True,'ortho_scale':.17,'render_width':768,'samples':32},{'name':'product_above','location':[-.12,.2,.13],'target':[0,0,0],'overview':True,'ortho_scale':.17,'render_width':768,'samples':32}];bpy.ops.wm.save_as_mainfile(filepath=str(O));(D/'review_views.json').write_text(json.dumps(views,indent=2)+'\n');(D/'review_scope.json').write_text(json.dumps({'asset_id':e['id'],'source':e['path'],'objects':[o.name for o in objects],'actual_dimensions_m':list(hi-lo),'native_faces':sum(len(o.data.polygons) for o in objects),'packed_images':images,'geometry_uv_materials_unchanged':True,'translation_only':list(-center),'scope':'Actual source lamp model unlit native material/shape studio. No ceiling integration, invented housing or emission/photometric claims.','photorealism_accepted':False},indent=2)+'\n');print('REAL_LIGHT_STUDIO_SAVED',flush=True)
