"""r7 direct review: landscape scale, daylight, monitor mesh, bedside symmetry."""
import bpy,bmesh,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
fixes=[];base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
# Remove the overlapping monitor components, retaining the native desk/keyboard.
desk=next(o for o in bpy.data.objects if o.get('ir_room')=='office_0/0' and 'OfficeDeskFactory' in o.name)
for o in list(bpy.data.objects):
 if 'PivotMonitorFaceFactory' in o.name:bpy.data.objects.remove(o,do_unlink=True)
bm=bmesh.new();bm.from_mesh(desk.data);seen=set();delete=[];components=0
for v in bm.verts:
 if v in seen:continue
 comp=[];todo=[v];seen.add(v)
 while todo:
  cur=todo.pop();comp.append(cur)
  for e in cur.link_edges:
   other=e.other_vert(cur)
   if other not in seen:seen.add(other);todo.append(other)
 if min(v.co.z for v in comp)>.79:delete.extend(comp);components+=1
bmesh.ops.delete(bm,geom=delete,context='VERTS');bm.to_mesh(desk.data);bm.free();desk.data.update()
black=pa._flat('pivot_r8_monitor_case',(.02,.022,.025),.65)
screen=pa._flat('pivot_r8_screen',(.025,.045,.065),.65)
monitor=pa._prims('PivotCleanMonitorFactory(1101).spawn_asset(1101)',[(black,[('box',(-.20,0,.80),(.20,.23,.025),(0,0,0)),('box',(-.21,0,.92),(.035,.04,.22),(0,0,0)),('box',(-.21,0,1.12),(.035,.60,.36),(0,0,0))]),(screen,[('box',(-.185,0,1.12),(.008,.565,.325),(0,0,0))])])
monitor.matrix_world=desk.matrix_world.copy();monitor['ir_room']='office_0/0'
fixes.append({'issue':'monitor overlap remained at bezel','action':'delete original upper connected components, replace with non-overlapping engine primitive display','components_removed':components})
# Clear only the two portable side tables, then build paired oak nightstands.
removed=[]
for o in list(bpy.data.objects):
 if o.type=='MESH' and o.parent is None and o.get('ir_room')=='bedroom_0/3' and any(k in o.name for k in ('Nightstand','TableFactory','SideTable','AboNight')):
  removed.append(o.name)
  for q in reversed([o,*o.children_recursive]):bpy.data.objects.remove(q,do_unlink=True)
oak=pa._flat('pivot_r8_bedside_oak',(.45,.30,.18),.65,wood=True)
shade=pa._flat('pivot_r8_lamp_linen',(.84,.78,.65),.85)
for i,x in enumerate((20.85,23.45)):
 o=pa._prims(f'PivotBedsideFactory({1110+i}).spawn_asset({1110+i})',[(oak,[('rbox',(x,22.10,.14754+.28),(.45,.45,.5),(0,0,0))]),(shade,[('cyl',(x,22.10,.14754+.82),(.13,.10,.25),(0,0,0))]),(black,[('cyl',(x,22.10,.14754+.62),(.015,.015,.24),(0,0,0))])]);o['ir_room']='bedroom_0/3'
fixes.append({'issue':'master side tables crowded one side','action':'paired oak nightstands outside bed footprint','removed':removed})
# Native cached foliage (real Infinigen geometry), at measured 1.6–2.2 m heights.
# No flowerpots are enlarged and no background image is used.
plants=sorted((ROOT/'data/plant_library').glob('plant_*.blend'));land=[]
for i,(x,y) in enumerate([(1,25),(5,25.5),(8.5,25),(11.5,25.5),(14.5,25),(17.5,25.5),(21,26),(24.5,26)]):
 with bpy.data.libraries.load(str(plants[i%len(plants)]),link=False) as (src,dst):dst.objects=[n for n in src.objects if n=='ir_plant']
 for o in dst.objects:
  if o:
   bpy.context.scene.collection.objects.link(o);o.name=f'PivotBoundaryPlantFactory({1120+i}).spawn_asset({1120+i})';bpy.context.view_layer.update()
   scale=(1.6+.2*(i%4))/max(o.dimensions.z,.01);o.scale*=scale;o.location=(x,y,.1);o['pivot_r8_landscape']=True;land.append({'name':o.name,'height_m':1.6+.2*(i%4)})
grass=pa._flat('pivot_r8_lawn',(.12,.20,.065),.95)
ground=pa._prims('PivotExternalGroundFactory(1150).spawn_asset(1150)',[(grass,[('box',(13,12,-.15),(70,70,.15),(0,0,0))])])
# Physical daytime sky with a soft sun; keep camera exposure stable for paired comparison.
s=bpy.context.scene
if not s.world:s.world=bpy.data.worlds.new('pivot_daylight')
s.world.use_nodes=True;nt=s.world.node_tree;nt.nodes.clear();out=nt.nodes.new('ShaderNodeOutputWorld');bg=nt.nodes.new('ShaderNodeBackground');sky=nt.nodes.new('ShaderNodeTexSky');sky.sky_type='NISHITA';sky.sun_elevation=math.radians(32);sky.sun_rotation=math.radians(70);sky.sun_disc=True;bg.inputs['Strength'].default_value=.18;nt.links.new(sky.outputs['Color'],bg.inputs['Color']);nt.links.new(bg.outputs[0],out.inputs[0])
fixes.append({'issue':'empty grey exterior and weak daylight','action':'real foliage library at human scale, exterior ground, Nishita daytime sky','plants':land})
bpy.context.view_layer.update();invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(x) or abs(x)>100 for x in o.dimensions)];assert not invalid,invalid
s['pivot_revision']='r8_direct_review';bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/scene_review_r8.blend'))
(base/'revision_r8.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'limitations':['Exterior plants are a placeholder shrub border, not mature surveyed trees.','Transparent glazing is still a layout-review approximation.','Sky and exposure need direct rerender verification.']},indent=2));print('PIVOT_R8_COMPLETE',flush=True)
