"""Bounded physical route audit and authored connectivity; does not certify training export."""
import bpy,json,ast,math,collections
from pathlib import Path
from mathutils import Vector
from shapely.geometry import box,LineString
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
plan=json.loads((B/'floor_plan_working_v14.json').read_text());rooms={k:box(*[ast.literal_eval(a) for a in ast.parse(v['shape'],mode='eval').body.args]) for k,v in plan['rooms'].items()}
regions={**rooms,'outdoor:entry_deck':box(24,14.5,26.5,17),'outdoor:garage_walk':box(26.5,14,31.8,16.1)}
links=[];unmodeled=[]
for kind in ['doors','opens','entrance']:
 for key,item in plan[kind].items():
  line=LineString(ast.literal_eval(ast.parse(item['shape'],mode='eval').body.args[0]));touch=[k for k,p in regions.items() if p.boundary.intersection(line).length>.04]
  if len(touch)==2:links.append({'name':key,'nodes':touch})
  elif kind=='entrance':unmodeled.append({'name':key,'touches':touch})
links +=[{'name':'garage_open_service_door','nodes':['garage_0/0','outdoor:garage_walk']},{'name':'deck_to_garage_walk','nodes':['outdoor:entry_deck','outdoor:garage_walk']}]
graph={k:set() for k in regions}
for row in links:
 a,b=row['nodes'];graph[a].add(b);graph[b].add(a)
seen={'hallway_0/0'};stack=list(seen)
while stack:
 for n in graph[stack.pop()]:
  if n not in seen:seen.add(n);stack.append(n)
unreachable=sorted(set(rooms)-seen)
# Wide-body route through actual open doors and level rendered floor surfaces.
points=[(22.6,15.68),(24.35,15.68),(26.0,15.68),(27.2,15.68),(29.15,15.68),(29.15,14.5),(29.15,13.0)]
dg=bpy.context.evaluated_depsgraph_get();hits=[];ground=[]
for i,(a,b) in enumerate(zip(points[:-1],points[1:])):
 start=Vector((*a,0));end=Vector((*b,0));direction=(end-start).normalized();side=Vector((-direction.y,direction.x,0));distance=(end-start).length
 for width in [-.30,0,.30]:
  for height in [.40,1.0,1.95]:
   origin=start+side*width+Vector((0,0,height));hit,co,no,face,o,m=bpy.context.scene.ray_cast(dg,origin,direction,distance=distance)
   if hit:hits.append({'segment':i,'lateral_m':width,'height_z':height,'object':o.name,'point':list(co)})
 for j in range(math.ceil(distance/.2)+1):
  t=min(j*.2/distance,1);xy=start.lerp(end,t);origin=xy+Vector((0,0,.60));hit,co,no,face,o,m=bpy.context.scene.ray_cast(dg,origin,Vector((0,0,-1)),distance=1.0)
  ground.append({'segment':i,'xy':[xy.x,xy.y],'hit':hit,'object':o.name if o else None,'z':co.z if hit else None})
floors={o.name for o in bpy.data.objects if o.name.endswith('.floor')};expected={k+'.floor' for k in rooms};ground_errors=[x for x in ground if not x['hit'] or abs(x['z']-.14555)>.025]
result={'status':'pass' if not(unreachable or hits or ground_errors or floors!=expected) else 'fail','scope':'Authored room connectivity plus sampled 0.60m-wide, head-height route from main hall via actual porch/walk to garage. Not full navigation/training certification.','room_count':len(rooms),'expected_floors_match':floors==expected,'bedroom_count':sum(k.startswith('bedroom_') for k in rooms),'unreachable_indoor_rooms':unreachable,'connectivity_links':links,'unmodeled_other_exterior_entrances':unmodeled,'route_points':points,'body_width_m':.60,'obstructions':hits,'ground_errors':ground_errors,'ground_samples':ground}
(B/'access_audit_v17.json').write_text(json.dumps(result,indent=2)+'\n');print('PIVOT_ACCESS_AUDIT',result['status'],'obstructions',len(hits),'unreachable',unreachable,'ground_errors',len(ground_errors),flush=True)
