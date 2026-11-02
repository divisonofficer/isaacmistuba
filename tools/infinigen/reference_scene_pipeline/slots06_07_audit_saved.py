import bpy,json,sys
from pathlib import Path
from mathutils import Vector
T=Path(__file__).parent;R=T.parents[2];sys.path.insert(0,str(R/'modules/infinigen'))
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages')
from shapely.geometry import Polygon,box,LineString,MultiPoint
from shapely.ops import unary_union
for scene,seed in [('industrial_workshop_floor_06',48712506),('large_restaurant_floor_07',48712507)]:
 D=R/'data/venue_refs/floor_plans_v3'/scene;W=R/'out/infinigen_v2'/f'kr_{scene}_{seed}';rev=max(W.glob('furnished_*.blend'),key=lambda p:p.stat().st_mtime).stem.removeprefix('furnished_');bpy.ops.wm.open_mainfile(filepath=str(W/f'furnished_{rev}.blend'));bpy.context.view_layer.update();inventory=json.loads((W/f'native_product_inventory_{rev}.json').read_text());floor_parts=[]
 for o in bpy.data.objects:
  if o.type=='MESH' and o.name.endswith('.floor'):
   for p in o.data.polygons:
    poly=Polygon([(o.matrix_world@o.data.vertices[i].co)[:2] for i in p.vertices])
    if poly.is_valid and poly.area>1e-8:floor_parts.append(poly)
 floors=unary_union(floor_parts);plan=json.loads((D/'floor_plan.json').read_text());import ast
 def line(e):return LineString(ast.literal_eval(ast.parse(e,mode='eval').body.args[0]))
 gates={f'{g}/{n}':line(v['shape']).buffer(.3,cap_style=2) for g in ['doors','opens','entrance'] for n,v in plan[g].items()};rows=[]
 for p in inventory['products']:
  points=[o.matrix_world@v.co for name in p['objects'] for o in [bpy.data.objects[name]] for v in o.data.vertices];hull=MultiPoint([(v.x,v.y) for v in points]).convex_hull;rows.append({'label':p['label'],'objects':p['objects'],'native_dimensions_xyz_m':p['native_dimensions_xyz_m'],'floor_support_z_error_m':p['floor_support_error_m'],'floor_footprint_outside_actual_mesh_m2':hull.difference(floors.buffer(.02)).area,'opening_strip_conflicts':[n for n,g in gates.items() if hull.intersection(g).area>.005]})
 result={'scene_id':scene,'blend':str(W/f'furnished_{rev}.blend'),'device':'CPU','product_count':len(rows),'actual_floor_mesh_area_m2':floors.area,'products':rows,'opening_conflict_count':sum(bool(x['opening_strip_conflicts']) for x in rows),'unsupported_footprint_count':sum(x['floor_footprint_outside_actual_mesh_m2']>.01 for x in rows),'pass':all(not x['opening_strip_conflicts'] and x['floor_footprint_outside_actual_mesh_m2']<.01 and abs(x['floor_support_z_error_m'])<.001 for x in rows),'limitations':['Conservative actual-mesh convex footprints and opening strips; not exact triangle furniture collision or door-swing proof','Full-room human circulation and source visual quality remain to inspect'],'photorealism_accepted':False};(W/f'saved_mesh_access_audit_{rev}.json').write_text(json.dumps(result,indent=2));print(scene,result['pass'],result['opening_conflict_count'],result['unsupported_footprint_count'],flush=True)
