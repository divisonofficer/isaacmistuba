"""Replace the inherited office-pantry flat sink plate with a recessed domestic bowl and curved tap."""
import bpy,bmesh,math,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
o=next(o for o in bpy.data.objects if o.name.startswith('PantryRunFactory') and o.get('ir_room')=='utility_0/1');bm=bmesh.new();bm.from_mesh(o.data);seen=set();remove=[];removed=[]
for start in list(bm.verts):
 if start in seen:continue
 stack=[start];seen.add(start);group=[]
 while stack:
  v=stack.pop();group.append(v)
  for edge in v.link_edges:
   other=edge.other_vert(v)
   if other not in seen:seen.add(other);stack.append(other)
 p=[o.matrix_world@v.co for v in group];bounds=[[min(v[k] for v in p),max(v[k] for v in p)] for k in range(3)];x,y,z=bounds
 if x[0]>17.05 and x[1]<17.85 and y[0]>10.60 and y[1]<11.34 and z[0]>1.04 and z[1]<1.70:remove+=group;removed.append(bounds)
assert removed,'Existing sink/tap was not located; do not create a second sink'
bmesh.ops.delete(bm,geom=remove,context='VERTS');bm.to_mesh(o.data);bm.free()
bpy.ops.mesh.primitive_cube_add(size=1,location=(17.45,11.04,1.025));c=bpy.context.object;c.dimensions=(.56,.40,.22);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);m=o.modifiers.new('true_recessed_pantry_sink','BOOLEAN');m.operation='DIFFERENCE';m.solver='EXACT';m.object=c;bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=m.name);bpy.data.objects.remove(c,do_unlink=True)
def box(c,s):return ('box',c,s,(0,0,0))
steel=bpy.data.materials['pivot_r14_brushed_hardware'];dark=bpy.data.materials['layout_v2_dark_frame'];parts=[box((17.45,11.04,.923),(.54,.38,.012))]+[box((x,11.04,1.005),(.012,.38,.164)) for x in [17.18,17.72]]+[box((17.45,y,1.005),(.54,.012,.164)) for y in [10.85,11.23]]+[box((17.45,y,1.091),(.58,.025,.014)) for y in [10.835,11.245]]+[box((x,11.04,1.091),(.025,.40,.014)) for x in [17.165,17.735]]
sink=pa._prims('PivotPantryV16_recessed_sink',[(steel,parts)]);sink['ir_room']='utility_0/1'
curve=bpy.data.curves.new('pantry_v16_gooseneck','CURVE');curve.dimensions='3D';curve.bevel_depth=.009;curve.bevel_resolution=4;points=[(17.45,11.29,1.09),(17.45,11.29,1.34)]+[(17.45,11.19+.10*math.cos(t),1.34+.10*math.sin(t)) for t in [i*math.pi/24 for i in range(25)]]+[(17.45,11.09,1.27)];sp=curve.splines.new('POLY');sp.points.add(len(points)-1)
for p,co in zip(sp.points,points):p.co=(*co,1)
tap=bpy.data.objects.new('PivotPantryV16_curved_black_tap',curve);bpy.context.scene.collection.objects.link(tap);curve.materials.append(dark);tap['ir_room']='utility_0/1'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v16';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_sink_v16.blend'));(B/'pantry_sink_stage_v16.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','old_sink_parts_removed':removed,'counter_recess_bounds':[[17.17,17.73],[10.84,11.24],[.915,1.135]],'changes':['Physical 16cm recessed bowl with rim, walls and bottom','Domestic curved black faucet instead of inherited white office bars'],'remaining':['Visual inspect both pantry cameras','Sink position, cabinet front and faucet support audit']},indent=2)+'\n');print('PIVOT_PANTRY_SINK_V16_SAVED',flush=True)
