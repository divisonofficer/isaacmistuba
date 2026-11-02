"""Connect relocated garage to entry deck via actual service door and level exterior walk."""
import bpy,bmesh,json,math,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';cuts=[]
for name in ['garage_0/0.wall','garage_0/0.exterior','PivotLayoutV2_garage_closed_old_connections']:
 o=bpy.data.objects[name];bpy.ops.mesh.primitive_cube_add(size=1,location=(29.05,14,1.245));c=bpy.context.object;c.dimensions=(.96,.80,2.20);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);m=o.modifiers.new('garage_service_door_opening','BOOLEAN');m.operation='DIFFERENCE';m.solver='EXACT';m.object=c;bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=m.name);bpy.data.objects.remove(c,do_unlink=True)
 bm=bmesh.new();bm.from_mesh(o.data);caps=[]
 for f in bm.faces:
  co=o.matrix_world@f.calc_center_median();n=o.matrix_world.to_3x3()@f.normal
  if min(abs(co.y-13.6),abs(co.y-14.4))<.003 and abs(n.y)>.98 and 28.56<co.x<29.54 and .14<co.z<2.35:caps.append(f)
 cuts.append({'object':name,'surface_caps_removed':len(caps)});bmesh.ops.delete(bm,geom=caps,context='FACES');bm.to_mesh(o.data);bm.free()
stone=bpy.data.materials['pivot_r14_limestone'];dark=bpy.data.materials['layout_v2_dark_frame'];oak=bpy.data.materials['pivot_r16_residential_oak']
def box(c,s):return ('box',c,s,(0,0,0))
def create(n,groups,room):
 o=pa._prims('PivotGarageV17_'+n,groups);o['ir_room']=room;return o
create('external_walk',[(stone,[box((29.15,15.05,.035275),(5.30,2.10,.22055)),box((29.05,14.0,.035275),(1.1,.40,.22055))])],'exterior_access')
create('service_frame',[(dark,[box((x,14,1.245),(.045,.07,2.20)) for x in [28.57,29.53]]+[box((29.05,14,z),(.96,.07,.045)) for z in [.1675,2.3225]])],'garage_0/0')
hinge=bpy.data.objects.new('PivotGarageV17_service_hinge',None);bpy.context.scene.collection.objects.link(hinge);hinge.location=(28.61,14,.15555);hinge.rotation_euler.z=math.radians(80)
leaf=create('service_leaf',[(oak,[box((.43,0,1.07),(.86,.045,2.14))]),(dark,[box((.75,.035,1.04),(.035,.025,.16))])],'garage_0/0');leaf.parent=hinge;leaf['state']='open_outward_80deg'
# A 75-degree entrance leaf leaves a wider walking aperture while remaining visibly open.
bpy.data.objects['PivotEntryV4_physical_hinge'].rotation_euler.z=math.radians(75)
doorwood=oak.copy();doorwood.name='entry_v17_readable_oak'
for node in doorwood.node_tree.nodes:
 if node.type=='VALTORGB':node.color_ramp.elements[0].color=(.24,.14,.065,1);node.color_ramp.elements[1].color=(.37,.25,.13,1)
front=bpy.data.objects['PivotEntryV4_open_oak_pivot_door']
for slot in front.material_slots:
 if slot.material==oak:slot.material=doorwood
# Physical object coordinates prevent masonry noise stretching over the tall pier.
material=bpy.data.materials['entry_v11_limestone'];nodes=material.node_tree.nodes;tc=nodes.new('ShaderNodeTexCoord')
for node in list(nodes):
 if node.type=='TEX_NOISE':material.node_tree.links.new(tc.outputs['Object'],node.inputs['Vector'])
# Specific foyer door gap and new frame are physical geometry; no navigation promotion claim.
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v17';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_access_v17.blend'))
(B/'garage_access_stage_v17.json').write_text(json.dumps({'status':'geometry_saved_access_audit_pending','open_service_door':{'opening_x':[28.57,29.53],'wall_y':14,'clear_width_approx_m':.87,'state':'outward_80deg'},'walk_bounds':[26.5,14.0,31.8,16.1],'walk_top_z':.14555,'threshold_top_z':.14555,'cuts':cuts,'remaining':['Exterior same-level continuity and opened leaf clearance','Diagnostic rays through actual service opening','Supplemental exterior view','Whole-house navigation connectivity via outside walkway']},indent=2)+'\n');print('PIVOT_ACCESS_V17_SAVED',flush=True)
