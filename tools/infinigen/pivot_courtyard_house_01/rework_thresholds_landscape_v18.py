"""Remove 45mm sill steps and reveal a distinct low grass/flower layer in the courtyard."""
import bpy,bmesh,json,math,sys,random
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';changes=[]
for name in ['PivotEntryV4_dark_frame','PivotGarageV17_service_frame']:
 o=bpy.data.objects[name];bm=bmesh.new();bm.from_mesh(o.data);seen=set();fixed=0
 for start in list(bm.verts):
  if start in seen:continue
  stack=[start];seen.add(start);group=[]
  while stack:
   v=stack.pop();group.append(v)
   for edge in v.link_edges:
    other=edge.other_vert(v)
    if other not in seen:seen.add(other);stack.append(other)
  lo=min(v.co.z for v in group);hi=max(v.co.z for v in group)
  if lo>.13 and hi<.21:
   for v in group:v.co.z=.14555+(v.co.z-lo)/(hi-lo)*.015
   fixed+=1
 assert fixed==1,(name,fixed)
 bm.to_mesh(o.data);bm.free();changes.append({'frame':name,'sill_top_z':.16055,'step_above_floor_m':.015})
bpy.data.objects['PivotEntryV4_physical_hinge'].location.z=.16555;bpy.data.objects['PivotGarageV17_service_hinge'].location.z=.16555
for v in bpy.data.objects['PivotGarageV17_service_leaf'].data.vertices:v.co.z*=2.13/2.14
for v in bpy.data.objects['PivotEntryV4_glazed_sidelight'].data.vertices:v.co.z=2.55-(2.55-v.co.z)*(2.55-.16055)/(2.55-.19)
# Expand actual soil to show grasses in front of the leafier mid shrubs.
bed=bpy.data.objects['PivotCourtyardV3_PlantingBeds']
for v in bed.data.vertices:
 if v.co.x>9.05:v.co.y=4.20+(v.co.y-4.20)*(5.18-4.20)/(4.84-4.20)
for o in bpy.data.objects:
 if o.name.startswith('PivotBorderV6_FarGrass_'):o.location.y+=.30
 if o.name.startswith(('PivotLeafyV9_far_shrub_','PivotLeafyV9_low_shrub_')) and o.location.x>14.65:o.location.x=14.65+(o.location.x-14.65)*.15
 if o.name.startswith('PivotLeafyV9_west_shrub_') and o.location.y>7.50:o.location.y=7.50
# Engine primitive flower stems/petals give the lower layer a separate readable form.
def material(n,c):
 m=bpy.data.materials.new(n);m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*c,1);p.inputs['Roughness'].default_value=.75;return m
leaf=bpy.data.materials['pantry_v2_leaf'];petal=material('courtyard_v18_cream_petals',(.82,.80,.70));pollen=material('courtyard_v18_pollen',(.53,.36,.08));rng=random.Random(48712818);stems=[];flowers=[];centers=[]
for x0 in [9.8,10.9,12.1,13.3,14.4]:
 for k in range(7):
  x=x0+rng.uniform(-.12,.12);y=5.0+rng.uniform(-.06,.06);h=rng.uniform(.21,.33);z=.17+h
  stems.append(('cyl',(x,y,.17+h/2),(.002,.0015,h),(0,0,0)))
  for j in range(3):stems.append(('sph',(x+(.012 if j%2 else -.012),y,.19+j*.045),(.025,.008,.004),(0,.15,j)))
  for j in range(5):
   a=j*math.tau/5;flowers.append(('sph',(x+.013*math.cos(a),y+.013*math.sin(a),z),(.015,.009,.004),(0,.12,a)))
  centers.append(('sph',(x,y,z+.003),(.006,.006,.004),(0,0,0)))
o=pa._prims('PivotCourtyardV18_low_flowering_border',[(leaf,stems),(petal,flowers),(pollen,centers)]);o['ir_room']='courtyard'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v18';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_thresholds_v18.blend'));(B/'thresholds_landscape_stage_v18.json').write_text(json.dumps({'status':'geometry_saved_route_and_visual_review_pending','thresholds':changes,'door_bottom_gap_to_threshold_m':.005,'door_bottom_above_floor_m':.020,'landscape_changes':['Fore-edge grass layer exposed in widened soil bed','Cream low flower clusters with stems/leaves','Far shrubs pulled away from east path','Last west shrub kept clear of north path'],'remaining':['Repeat route audit without widening tolerances','Original courtyard and entry visual review','Actual frame/leaf/glass collision and support checks']},indent=2)+'\n');print('PIVOT_THRESHOLDS_V18_SAVED',flush=True)
