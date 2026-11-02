"""Real native framed slab/lever assembly, not a box furniture stand-in."""
import bpy,json,sys,hashlib
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'modules/infinigen'));from infinigen.assets.objects.elements.doors.base import BaseDoorFactory
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_flat_door_pilot';assert not D.exists();D.mkdir();S=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r92.blend';bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(S),link=False) as (src,dst):dst.materials=['office02_door_oak','DoorR74_satin_stainless','office02_charcoal']
body,metal,frame=dst.materials;assert all([body,metal,frame])
class Surface:
 def __init__(self,mat,split=False):self.mat=mat;self.split=split
 def apply(self,objects,**kwargs):
  group=objects if isinstance(objects,(list,tuple)) else [objects]
  for i,o in enumerate(group):
   if o is None:continue
   o.data.materials.clear();o.data.materials.append(frame if self.split and i==0 else self.mat)
   if self.split and i==1:
    uv=o.data.uv_layers.active or o.data.uv_layers.new(name='Veneer_physical_axes')
    for p in o.data.polygons:
     for li in p.loop_indices:
      v=o.data.vertices[o.data.loops[li].vertex_index].co
      uv.data[li].uv=(v.z,v.x) if abs(p.normal.y)>.5 else (v.z,v.y)
fac=BaseDoorFactory(48712502);fac.width=.95;fac.height=2.3;fac.depth=.045;fac.has_glass=False;fac.has_louver=False;fac.handle_type='lever';fac.handle_joint='hinge';fac.handle_info_dict={'handle_type':'lever'};fac.door_frame_style='full_frame_square';fac.door_orientation='left';fac.level_type='cylinder';fac.side_bevel=.0015;fac.auto_bevel.amount=.001;fac.surface=Surface(body,True);fac.handle_surface=Surface(metal)
o=fac.create_asset(apply=True);o.name='Office02_native_flat_leaf_full_frame_lever';bpy.context.view_layer.update();points=[o.matrix_world@Vector(v) for v in o.bound_box];lo=Vector([min(p[k] for p in points) for k in range(3)]);hi=Vector([max(p[k] for p in points) for k in range(3)]);o.location-=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));hardware=sum(1 for f in o.data.polygons if o.data.materials[f.material_index]==metal);assert hardware>100;nativefaces=len(o.data.polygons);bpy.ops.wm.save_as_mainfile(filepath=str(D/'asset.blend'))
bpy.ops.mesh.primitive_plane_add(size=20,location=(0,0,-.005));floor=bpy.context.object;m=bpy.data.materials.new('Neutral_door_studio_floor');m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.2,.2,.2,1);m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.7;floor.data.materials.append(m);w=bpy.data.worlds.new('Neutral_door_studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.2;bpy.context.scene.world=w
for name,loc,power,size in [('Key',(-2,-3,4),180,2.5),('Fill',(2,3,3),90,2)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;light=bpy.data.objects.new(name,d);bpy.context.scene.collection.objects.link(light);light.location=loc;light.rotation_euler=(Vector((0,0,1.1))-light.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'native_flat_door_front','location':[2.5,-3.5,1.7],'target':[0,0,1.15],'overview':True,'ortho_scale':3.8,'render_width':1024,'samples':32},{'name':'native_flat_door_back','location':[-2.5,3.5,1.7],'target':[0,0,1.15],'overview':True,'ortho_scale':3.8,'render_width':1024,'samples':32}];bpy.ops.wm.save_as_mainfile(filepath=str(D/'studio.blend'));(D/'views.json').write_text(json.dumps(views,indent=2)+'\n');(D/'provenance.json').write_text(json.dumps({'source_factory':'infinigen.assets.objects.elements.doors.base.BaseDoorFactory','seed':48712502,'requested_leaf_dimensions_m':[.95,.045,2.3],'actual_assembly_dimensions_m':list(hi-lo),'native_faces':nativefaces,'actual_hardware_material_faces':hardware,'material_source_scene':str(S),'materials':[body.name,metal.name,frame.name],'geometry':'Native complete square frame/slab/lever generation with edge bevel; BaseDoorFactory.make_panels returns none. No scene replacement yet.','leaf_uv':'Explicit verticalZ/horizontalX veneer chart,final wood direction must be checked against inherited material graph.','scope':'Standalone shape/material pilot only;native hardware presence not proof of hinge/latch manufacturing completeness or installed door fit/sweep/nav.','photorealism_accepted':False},indent=2)+'\n');print('NATIVE_FLAT_DOOR_PILOT_SAVED',nativefaces,hardware,flush=True)
