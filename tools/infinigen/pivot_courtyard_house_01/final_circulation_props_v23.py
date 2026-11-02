"""Resolve laundry leaf crossing the new family aisle; fill the remaining upper pantry shelf gap."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';oak=bpy.data.materials['pivot_r16_residential_oak'];dark=bpy.data.materials['layout_v2_dark_frame']
old=bpy.data.objects['PanelDoorFactory(2248688).spawn_asset(6)'];pts=[old.matrix_world@Vector(v) for v in old.bound_box];low=min(v.z for v in pts);high=max(v.z for v in pts);height=high-low-.01;bpy.data.objects.remove(old,do_unlink=True)
def box(c,s):return ('box',c,s,(0,0,0))
hinge=bpy.data.objects.new('PivotLaundryV23_inward_hinge',None);bpy.context.scene.collection.objects.link(hinge);hinge.location=(10.49,10.35,low+.01);hinge.rotation_euler.z=math.radians(-88)
o=pa._prims('PivotLaundryV23_inward_door',[(oak,[box((0,-.395,height/2),(.045,.79,height))]),(dark,[box((x,-.65,1.0),(.025,.13,.025)) for x in [-.04,.04]])]);o.parent=hinge;o['ir_room']='utility_0/0';o['state']='open inward 88deg';o['source_opening']='laundry_family_dining'
# Upper pantry north shelf: every item sits on the actual 2.11504m support plane.
colors=[(.18,.24,.15),(.56,.44,.28),(.30,.12,.06)]
for i,c in enumerate(colors):
 m=pa._flat('pantry_v23_recipe_spine_'+str(i),c,.7);o=pa._prims('PivotPantryV23_recipe_'+str(i),[(m,[box((17.45+i*.07,11.15,2.22504),(.045,.14,.22))])]);o['ir_room']='utility_0/1'
# Supported open wooden bowl with fruit, rather than an opaque cylinder.
x,y,bottom=17.95,11.15,2.11504;profile=[(0,bottom),(.07,bottom),(.13,bottom+.065),(.118,bottom+.065),(.06,bottom+.012),(0,bottom+.012)];verts=[];faces=[];n=48
for rad,z in profile:verts.extend((x+rad*math.cos(k*math.tau/n),y+rad*math.sin(k*math.tau/n),z) for k in range(n))
for j in range(len(profile)-1):
 for k in range(n):faces.append((j*n+k,j*n+(k+1)%n,(j+1)*n+(k+1)%n,(j+1)*n+k))
me=bpy.data.meshes.new('pantry_v23_open_bowl');me.from_pydata(verts,[],faces);me.materials.append(oak);o=bpy.data.objects.new('PivotPantryV23_open_fruit_bowl',me);bpy.context.scene.collection.objects.link(o);o['ir_room']='utility_0/1'
for p in me.polygons:p.use_smooth=True
green=pa._flat('pantry_v23_fruit_green',(.18,.28,.035),.55);fruits=[('lsph',(x+.04*math.cos(k*math.tau/3),y+.04*math.sin(k*math.tau/3),bottom+.047),(.032,.032,.032),(0,0,0)) for k in range(3)]
o=pa._prims('PivotPantryV23_bowl_fruit',[(green,fruits)]);o['ir_room']='utility_0/1'
# Reuse actual woven basket and handle meshes; reference north shelf is no longer empty.
for name in ['PivotPantryV2_woven_basket_0','PivotStorageV5_pantry_basket_dark_handle_0']:
 src=bpy.data.objects[name];o=src.copy();bpy.context.scene.collection.objects.link(o);o.name='PivotPantryV23_north_'+name;o.matrix_world=Matrix.Translation(Vector((-.23,1.85,0)))@src.matrix_world;o['ir_room']='utility_0/1'
# Three supported pears on existing cutting board, aligned with reference domestic use.
parts=[];stems=[]
for x in [19.03,19.14,19.25]:
 parts.extend([('lsph',(x,9.42,1.11504),(.035,.035,.04),(0,0,0)),('lsph',(x,9.42,1.15504),(.021,.021,.034),(0,0,0))]);stems.append(('cyl',(x,9.42,1.19404),(.002,.001,.016),(0,0,0)))
o=pa._prims('PivotPantryV23_board_pears',[(green,parts),(oak,stems)]);o['ir_room']='utility_0/1'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v23';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v23.blend'));(B/'circulation_props_stage_v23.json').write_text(json.dumps({'status':'geometry_saved_repeat_physical_audit_pending','fix':'Laundry leaf formerly extended into the 0.60m family circulation route. New explicit hinge opens 88deg inward into clear laundry area; casing/opening retained.','door_height':height,'pantry_changes':['Upper shelf recipe books, supported open fruit bowl and woven basket','Pears on existing cutting board'],'remaining':['Repeat unchanged family route and add laundry entrance route','Full 37-camera render review','Final support and reference acceptance']},indent=2)+'\n');print('PIVOT_CIRCULATION_PROPS_V23_SAVED',flush=True)
