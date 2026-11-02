"""Task-bounded checks for authored connectivity, actual routes, parking and new supports."""
import bpy,json,ast,math
from pathlib import Path
from mathutils import Vector
from shapely.geometry import box,LineString
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';plan=json.loads((B/'floor_plan_working_v22.json').read_text());rooms={k:box(*[ast.literal_eval(a) for a in ast.parse(v['shape'],mode='eval').body.args]) for k,v in plan['rooms'].items()};regions={**rooms,'outdoor:entry_deck':box(24,14.5,26.5,17),'outdoor:garage_walk':box(26.5,14,33.75,16.1)};graph={k:set() for k in regions};links=[]
for kind in ['doors','opens','entrance']:
 for key,item in plan[kind].items():
  line=LineString(ast.literal_eval(ast.parse(item['shape'],mode='eval').body.args[0]));touch=[k for k,p in regions.items() if p.boundary.intersection(line).length>.04]
  if len(touch)==2:links.append({'name':key,'nodes':touch});graph[touch[0]].add(touch[1]);graph[touch[1]].add(touch[0])
a,b='outdoor:entry_deck','outdoor:garage_walk';graph[a].add(b);graph[b].add(a);seen={'hallway_0/0'};stack=list(seen)
while stack:
 for node in graph[stack.pop()]:
  if node not in seen:seen.add(node);stack.append(node)
unreachable=sorted(set(rooms)-seen);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();obstructions=[];ground_errors=[];ground_count=0
routes={'house_to_garage':[(22.6,15.68),(24.35,15.68),(26.0,15.68),(27.2,15.68),(29.15,15.68),(29.15,14.5),(29.15,13.0)],'pantry_aisle':[(15.8,10.18),(19.7,10.18)],'pantry_kitchen':[(17.5,10.18),(17.5,8.5)],'family_dining_connection':[(15.8,9.6),(11.31,9.6),(11.31,12.2)],'laundry_entry':[(11.3,9.95),(9.6,9.95)],'courtyard_paths':[(9.2,8.6),(15.9,8.6),(15.9,4.6)]}
def ground_at(x,y,route):
 global ground_count
 hit,p,n,f,o,m=bpy.context.scene.ray_cast(dg,Vector((x,y,.60)),Vector((0,0,-1)),distance=1.0);ground_count+=1
 if not hit or abs(p.z-.14555)>.025:ground_errors.append({'route':route,'xy':[x,y],'object':o.name if o else None,'z':p.z if hit else None})
for name,points in routes.items():
 for i,(a,b) in enumerate(zip(points[:-1],points[1:])):
  start=Vector((*a,0));end=Vector((*b,0));d=(end-start).normalized();side=Vector((-d.y,d.x,0));length=(end-start).length
  for offset in [-.30,0,.30]:
   for height in [.40,1.0,1.95]:
    hit,p,n,f,o,m=bpy.context.scene.ray_cast(dg,start+side*offset+Vector((0,0,height)),d,distance=length)
    if hit:obstructions.append({'route':name,'segment':i,'offset':offset,'height':height,'object':o.name,'point':list(p)})
  for j in range(math.ceil(length/.2)+1):
   p=start.lerp(end,min(j*.2/length,1));ground_at(p.x,p.y,name)
for x,y in [(24,15.68),(29.15,14.0)]:ground_at(x,y,'exact_door_threshold')
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];return [[min(v[k] for v in pts),max(v[k] for v in pts)] for k in range(3)]
def z(o):return bounds(bpy.data.objects[o])[2]
supports={};supports['rack_feet_on_floor']=abs(z('PivotGarageV21_grounded_shelf_feet')[0]-z('garage_0/0.floor')[1])<.003;supports['rack_on_feet']=abs(z('PivotLayoutV2_garage_residential_shelves')[0]-z('PivotGarageV21_grounded_shelf_feet')[1])<.003;supports['motor_hangers_reach_ceiling']=abs(z('PivotGarageV21_ceiling_supports')[1]-z('garage_0/0.ceiling')[0])<.004;supports['pantry_plinth_on_floor']=abs(z('PivotPantryV21_recessed_plinth')[0]-z('utility_0/1.floor')[1])<.003;supports['pantry_base_on_plinth']=z('PivotPantrySecondCounterFactory(2110).spawn_asset(2110)')[0]<=z('PivotPantryV21_recessed_plinth')[1]+.003
jar_gaps=[]
for o in bpy.data.objects:
 if o.type=='MESH' and ((o.name.startswith('PivotPantryV2_food_jar_') or o.name.startswith('PivotPantryV13_jar_')) and not o.name.endswith('_lid')):jar_gaps.append({'object':o.name,'bottom_gap_to_shelf_m':bounds(o)[2][0]-1.61504})
supports['all_jars_supported']=bool(jar_gaps) and all(abs(row['bottom_gap_to_shelf_m'])<.003 for row in jar_gaps)
soil=bounds(bpy.data.objects['PivotCourtyardV3_PlantingBeds']);supports['soil_beds_inside_courtyard_and_clear_paths']=soil[0][0]>=8 and soil[0][1]<15.35 and soil[1][0]>=4 and soil[1][1]<8.2
# Two 4.60m x 1.80m car bodies; explicit furniture AABBs, not a vehicle dynamics simulation.
parking=[[[27.70,32.30],[9.40,11.20],[.14555,1.69555]],[[27.70,32.30],[11.80,13.60],[.14555,1.69555]]];parking_hits=[];prefixes=('PivotLayoutV2_garage_residential_shelves','PivotLayoutV2_garage_bin_','PivotStorageV5_garage','PivotStorageV5_wall_tool','PivotStorageV5_hose','PivotGarageV21_grounded_shelf_feet','PivotGarageV12_tracks','PivotGarageV21_ceiling_supports','PivotSectionalGarageDoor','PivotGarageV17_service_leaf')
for o in bpy.data.objects:
 if o.type=='MESH' and o.name.startswith(prefixes):
  bb=bounds(o)
  for i,car in enumerate(parking):
   if all(min(bb[k][1],car[k][1])-max(bb[k][0],car[k][0])>.002 for k in range(3)):parking_hits.append({'bay':i,'object':o.name,'bounds':bb})
floors={o.name for o in bpy.data.objects if o.name.endswith('.floor')};expected={k+'.floor' for k in rooms};failed=[k for k,v in supports.items() if not v];result={'status':'pass' if not(unreachable or obstructions or ground_errors or failed or parking_hits or floors!=expected) else 'fail','scope':'Authored connectivity, five sampled 0.60m-wide routes at knee/torso/head heights, critical support bounds, and two static vehicle-body envelopes. Full image review and geometry packing remain independent requirements.','rooms':len(rooms),'bedrooms':sum(k.startswith('bedroom_') for k in rooms),'floor_names_match':floors==expected,'unreachable_indoor_rooms':unreachable,'routes':routes,'obstructions':obstructions,'ground_errors':ground_errors,'ground_samples':ground_count,'ground_step_tolerance_m':.025,'support_checks':supports,'failed_support_checks':failed,'jar_support_gaps':jar_gaps,'soil_bounds':soil,'parking_body_envelopes':parking,'parking_furniture_collisions':parking_hits,'not_certified':['Every possible mesh pair collision','Vehicle steering/door-opening simulation','Training dataset/GT promotion']};(B/'integrated_physical_audit_v26.json').write_text(json.dumps(result,indent=2)+'\n');print('PIVOT_INTEGRATED_AUDIT_V26',result['status'],'obstructions',len(obstructions),'ground_errors',len(ground_errors),'failed_supports',failed,'parking',parking_hits,flush=True)
assert result['status']=='pass','Integrated physical audit failed; inspect JSON before full rendering'
