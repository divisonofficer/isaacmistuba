"""Isolated three native-profile toiletries,not room integration."""
import bpy,json,hashlib,argparse
from pathlib import Path
from mathutils import Vector
from native_toiletry_factory import create_toiletry,material
root=Path('/jarvis/project/robomituba');ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';ap=argparse.ArgumentParser();ap.add_argument('--variant',default='configured');args=ap.parse_args();assert args.variant.replace('_','').isalnum();out=ref/('native_toiletries_studio68_'+args.variant);assert not out.exists();out.mkdir();bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False);records=[]
for i,(h,r,c) in enumerate([(.13,.024,(.72,.71,.65)),(.16,.026,(.21,.35,.29)),(.19,.027,(.56,.40,.23))]):
 objects,row=create_toiletry(48712600+i,h,r,c);bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();bottom=1e6
 for o in objects:
  ev=o.evaluated_get(deps);me=ev.to_mesh();bottom=min(bottom,min((o.matrix_world@v.co).z for v in me.vertices));ev.to_mesh_clear()
 for o in objects:o.location+=Vector(((i-1)*.17,0,-bottom));o['studio_asset_index']=i
 row['prototype_objects']=[o.name for o in objects];row['placement_floor_correction_m']=-bottom;records.append(row)
bpy.ops.mesh.primitive_plane_add(size=10);bpy.context.object.data.materials.append(material('neutral_floor',(.34,.35,.36),.7));w=bpy.context.scene.world or bpy.data.worlds.new('neutral_world');bpy.context.scene.world=w;w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.25
for name,loc,power,size in [('key',(-.5,-.6,.7),35,.5),('fill',(.6,.1,.5),12,.35)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.1))-o.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'configured_native_toiletries_three','location':[.35,-.75,.38],'target':[0,0,.105],'hfov':43,'render_width':1280,'samples':32}];(out/'views.json').write_text(json.dumps(views,indent=2));(out/'scope.json').write_text(json.dumps({'records':records,'helper_sha256':hashlib.sha256((root/'tools/infinigen/reference_scene_pipeline/native_toiletry_factory.py').read_bytes()).hexdigest(),'native_factory_sha256':hashlib.sha256((root/'modules/infinigen/infinigen/assets/objects/tableware/bottle.py').read_bytes()).hexdigest(),'room_integrated':False,'photorealism_accepted':False},indent=2));bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'));print('Saved configured studio',out,flush=True)
