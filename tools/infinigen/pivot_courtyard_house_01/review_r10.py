"""Whole-house review fixes, physical glazing, life-size fixtures and cameras."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import ShowerEnclosureFactory
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';fixes=[]
def remove(o):
 for q in reversed([o,*o.children_recursive]):bpy.data.objects.remove(q,do_unlink=True)
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
# Correct plant root origins, not the lowest below-ground root vertex.
rigs=[o for o in bpy.data.objects if o.type=='EMPTY' and o.name.startswith('PivotMatureTreeRig')]
for i,rig in enumerate(rigs):
 rig.location.z=.1
 if i<5:
  factor=.78;rig.scale*=factor;rig.location.y+=5
# A grounded native tree replaces the oversized toy-like potted ficus in courtyard.
for o in list(bpy.data.objects):
 if o.name.startswith('FicusPlantFactory(703)'):remove(o)
for o in bpy.data.objects:
 if o.name.startswith('PivotGardenPlantFactory'):
  o.scale*=.70/max(o.dimensions.z,.01)
source=rigs[0];originals=[source,*source.children_recursive];mapping={}
for orig in originals:
 c=orig.copy();bpy.context.scene.collection.objects.link(c);mapping[orig]=c
for orig,c in mapping.items():
 c.parent=mapping.get(orig.parent);c.matrix_parent_inverse=orig.matrix_parent_inverse.copy();c.matrix_basis=orig.matrix_basis.copy()
new=mapping[source];new.name='PivotCourtyardTreeRig';ratio=3.3/(5.8*.78);new.scale*=ratio;new.location=(11.6,6.0,.145)
fixes.append({'issue':'tree roots appeared floating and courtyard planting overscaled','action':'align tree origin with soil; reduce foreground trees and move back; replace courtyard ficus with native 3.3m tree; reduce border plants to 0.7m'})
# Reconstruct a full-height shower in its own footprint rather than scaling its
# height to fit an XY packing constraint. Vanity is north; shower is south-east.
for o in list(bpy.data.objects):
 if o.get('ir_room')=='bathroom_0/4' and 'ShowerEnclosureFactory' in o.name:remove(o)
shower=ShowerEnclosureFactory(48713001).spawn_asset(1301);shower.location=(19.3,2.15,.14754);shower.rotation_euler.z=math.pi;shower['ir_room']='bathroom_0/4'
vanity=next(o for o in bpy.data.objects if o.get('ir_room')=='bathroom_0/4' and 'HomeVanityFactory' in o.name);vanity.scale.z=1
fixes.append({'issue':'guest shower was reduced to 1.435m, vanity reduced vertically, misleading fixture overlap in view','action':'full 2.1m native shower placed in southeast corner, full-height vanity restored; original XY footprints kept clear'})
# Remove the WC door leaf that actually intersects the cistern, close it in its
# existing source opening. Do not alter the room or door annotations.
old=bpy.data.objects.get('PanelDoorFactory(6575506).spawn_asset(5)')
if old:remove(old)
leaf=pa._flat('pivot_r10_residential_door',(.68,.65,.59),.7);dark=pa._flat('pivot_r10_charcoal',(.025,.028,.03),.5)
wcdoor=pa._prims('PivotWcClosedDoorFactory(1302).spawn_asset(1302)',[(leaf,[('box',(4.8,14.75,1.22),(.04,.83,2.14),(0,0,0))]),(dark,[('box',(4.84,14.5,1.13),(.025,.13,.025),(0,0,0))])]);wcdoor['pivot_door_state']='closed';wcdoor['pivot_source_opening']='wc_hall'
# Garage rack exceeded the ceiling (3.6m vs 2.8m). Place it at west wall and add
# an interior closed sectional door on east, as appropriate for a two-car garage.
rack=next(o for o in bpy.data.objects if o.get('ir_room')=='garage_0/0' and 'StorageRackFactory' in o.name);rack.rotation_euler.z=0;rack.scale.z*=2.15/3.6;rack.location=(17.2,6.5,.14754)
steel=pa._flat('pivot_r10_clean_metal',(.55,.57,.59),.34,1)
white=pa._flat('pivot_r10_garage_panel',(.69,.69,.66),.65)
parts=[('box',(21.82,6.5,.14754+.235+k*.46),(.045,4.15,.445),(0,0,0)) for k in range(5)]
gar=pa._prims('PivotSectionalGarageDoorFactory(1303).spawn_asset(1303)',[(white,parts),(steel,[('box',(21.76,sy,1.35),(.065,.055,2.45),(0,0,0)) for sy in (4.36,8.64)]),(dark,[('box',(21.765,6.5,.9),(.025,.32,.04),(0,0,0))])]);gar['ir_room']='garage_0/0';gar['pivot_door_state']='closed'
fixes.append({'issue':'garage rack taller than ceiling, garage type not legible','action':'rack now 2.15m at west wall, closed two-car sectional door at east wall'})
# Replace cached metallic materials carrying corrosion/noise intended for other
# venues, and calm oversized wood grain in this clean residential reference.
replaced=0
for o in bpy.data.objects:
 if o.type!='MESH':continue
 for sl in o.material_slots:
  if not sl.material:continue
  name=sl.material.name.lower()
  if ('black' not in name and any(k in name for k in ('ir_chrome','ir_steel','ir_kit_steel','ir_kit_fridge','ir_microwave_body','shader_galvanized_metal','shader_brushed_metal'))):sl.material=steel;replaced+=1
  elif name=='ir_office_door_leaf' or name=='ir_door_vision_glass':sl.material=leaf
  elif 'WindowFactory' in o.name and name=='ir_office_door_frame':sl.material=dark
for m in bpy.data.materials:
 if not m.use_nodes:continue
 if any(k in m.name for k in ('oak','pivot_ref_oak')):
  for n in m.node_tree.nodes:
   if n.type=='BUMP':n.inputs['Strength'].default_value*=.15;n.inputs['Distance'].default_value*=.25
# Restore physical refraction/reflection after the transparent layout-review pass.
m=bpy.data.materials.get('pivot_r6_clear_thin_glass')
if m:
 nt=m.node_tree;nt.nodes.clear();out=nt.nodes.new('ShaderNodeOutputMaterial');glass=nt.nodes.new('ShaderNodeBsdfGlass');glass.inputs['Color'].default_value=(.99,.995,1,1);glass.inputs['Roughness'].default_value=.015;glass.inputs['IOR'].default_value=1.45;nt.links.new(glass.outputs[0],out.inputs['Surface']);m.name='pivot_r10_physical_window_glass'
fixes.append({'issue':'grimy metal and exaggerated wood bump; layout-only glazing','action':'clean metal slots, subdued wood bump, charcoal window frames, physical Glass BSDF IOR 1.45','metal_slots_replaced':replaced})
# Consolidate all-space review; camera adjustments are recorded, not mislabelled
# as pixel-aligned comparisons.
run=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full';views=json.loads((run/'review_views_r9.json').read_text())+json.loads((run/'review_views_all_spaces.json').read_text())
updates={
'kitchen_reference_wide':([14.9,14.4,1.65],[13.3,9.8,1.1],80),
'bathroom_0-5_wide1':([25.3,18.65,1.6],[25.85,17.55,.8],90),
'closet_0-0_wide0':([21.3,18.3,1.65],[23.7,17.4,1.25],85),
'garage_0-0_wide0':([17.6,4.65,1.65],[21.3,6.8,1.2],85),
'hallway_0-0_wide0':([20.9,14.9,1.6],[23.6,15.7,1.1],80),
'utility_0-0_wide0':([8.4,9.65,1.6],[9.3,11.0,1.1],85),
'utility_0-1_wide0':([16.9,9.65,1.6],[18.8,10.95,1.15],85),
'bathroom_0-4_wide0':([18.25,3.55,1.65],[19.3,2.5,1.05],85),
'entry_deck_reference_wide':([26.25,14.85,1.65],[24.0,15.6,1.25],85),
'bedroom_0-2_wide1':([2.8,12.0,1.6],[1.7,13.5,1.0],85),
'living-room_0-0_wide0':([6.7,12.1,1.65],[9,15.2,1.2],85)}
for v in views:
 if v['name'] in updates:v['location'],v['target'],v['hfov']=updates[v['name']]
(run/'review_views_r10.json').write_text(json.dumps(views,indent=2))
bpy.context.view_layer.update();invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
sb=bounds(shower);vb=bounds(vanity);assert sb[1][1]<vb[1][0],(sb,vb)
assert bounds(rack)[2][1]<2.8
bpy.context.scene['pivot_revision']='r10_whole_house_review';bpy.ops.wm.save_as_mainfile(filepath=str(run/'scene_review_r10.blend'))
(base/'revision_r10.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'shower_bounds':sb,'vanity_bounds':vb,'garage_rack_bounds':bounds(rack),'camera_changes':updates,'camera_count':len(views),'limitations':['Procedural furnishings and landscape approximate generated reference styles, not surveyed real interiors','Absolute dimensions from screenshot remain estimated','Closed WC/guest/garage doors require state-aware navigation annotations before export']},indent=2));print('PIVOT_R10_COMPLETE',flush=True)
