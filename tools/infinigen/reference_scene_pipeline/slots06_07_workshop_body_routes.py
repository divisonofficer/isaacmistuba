"""Read-only0.9m body routes using actual triangulated native surfaces and full body-height clipping.
U-shaped casing ngons must be triangulated; connecting all z-crossings invents a false portal bar.
"""
import bpy,json,sys,argparse
from pathlib import Path
from mathutils import Vector
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import Polygon,LineString,MultiPoint,box;from shapely.ops import unary_union
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_industrial_workshop_floor_06_48712506';rev=sys.argv[sys.argv.index('--')+1] if '--'in sys.argv else max(W.glob('furnished_*.blend'),key=lambda p:p.stat().st_mtime).stem.removeprefix('furnished_');src=W/f'furnished_{rev}.blend';bpy.ops.wm.open_mainfile(filepath=str(src));inv=json.loads((W/f'native_product_inventory_{rev}.json').read_text());prior={'body_routes':[]};pathfile=W/f'body_route_paths_{rev}.json';pathrows=json.loads(pathfile.read_text()) if pathfile.exists() else prior['body_routes'];bpy.context.view_layer.update()
def clip(ps,z,above):
 if not ps:return []
 result=[]
 for a,b in zip(ps,ps[1:]+ps[:1]):
  ina=a.z>=z if above else a.z<=z;inb=b.z>=z if above else b.z<=z
  if ina:result.append(a)
  if ina!=inb:result.append(a+(b-a)*((z-a.z)/(b.z-a.z)))
 return result
def skin(o):
 o.data.calc_loop_triangles();vs=[o.matrix_world@v.co for v in o.data.vertices];shapes=[]
 for tri in o.data.loop_triangles:
  ps=clip(clip([vs[i] for i in tri.vertices],.2,True),1.8,False)
  if len(ps)<2:continue
  xy=[p.xy for p in ps];p=Polygon(xy) if len(xy)>=3 else Polygon()
  if p.is_valid and p.area>1e-10:shapes.append(p.buffer(.001))
  elif len(set((v.x,v.y) for v in ps))>1:shapes.append(LineString(xy).buffer(.002))
 return unary_union(shapes)
arch=[o for o in bpy.data.objects if o.type=='MESH' and (o.name.endswith(('.wall','.exterior')) or 'WC_route_corrected_partition' in o.name or 'North_WC_source_program_partition' in o.name or o.name.startswith('Workshop_native_measured_') or 'DoorCasingFactory' in o.name)];arch_skin=[]
for o in arch:
 g=skin(o);arch_skin.append((o.name,g))
floors=[]
for o in bpy.data.objects:
 if o.type=='MESH' and o.name.endswith('.floor'):
  for p in o.data.polygons:
   q=Polygon([(o.matrix_world@o.data.vertices[i].co).xy for i in p.vertices])
   if q.is_valid and q.area>1e-8:floors.append(q)
floors=unary_union(floors);rows=[]
for r in pathrows:
 body_width=float(r.get('body_width_m',.9));corridor=LineString(r['center_polyline_m']).buffer(body_width/2,cap_style=1,join_style=1);fh=[];ah=[]
 for p in inv['products']:
  lo,hi=p['saved_mesh_bounds_xyz_m'];bb=box(lo[0],lo[1],hi[0],hi[1])
  if not bb.intersects(corridor):continue
  points=[bpy.data.objects[n].matrix_world@v.co for n in p['objects'] for v in bpy.data.objects[n].data.vertices];h=MultiPoint([v.xy for v in points if .1<=v.z<=1.8]).convex_hull
  area=h.intersection(corridor).area
  if area>1e-4:fh.append({'objects':p['objects'],'area_m2':area})
 for name,g in arch_skin:
  a=g.intersection(corridor).area
  if a>1e-4:ah.append({'object':name,'area_m2':a})
 unsupported=corridor.difference(floors.buffer(.002)).area;rows.append({'route':r['route'],'body_width_m':body_width,'center_polyline_m':r['center_polyline_m'],'fixture_convex_footprint_hits':fh,'actual_triangulated_arch_skin_hits':ah,'floor_unsupported_area_m2':unsupported,'pass':not fh and not ah and unsupported<.001})
doc={'source':str(src),'source_native_inventory':str(W/f'native_product_inventory_{rev}.json'),'native_door_aperture_evidence':'actual_openings_r2.json','native_sampled_sweep_evidence':'workshop_measured_entry_r3.json','rows':rows,'pass_body_routes':all(r['pass']for r in rows),'method':'Actual mesh.calc_loop_triangles;every arch triangle clipped toZ0.2..1.8m beforeXYprojection. U-ngon crossings never bridged across openings.0.9m capsule routes tested against actual skin and conservative native fixture hulls,plus actual floor union/thresholds.','limitations':['Surface projections plus conservative fixture hulls;not dynamichuman motion or accessibility certification','Door37pose sampledsweep evidence remains separate;continuous sweptsolids not claimed','Wholemain/private roomcirculation and sourcephotorealism not certified'],'photorealism_accepted':False};(W/f'actual_triangulated_body_routes_{rev}.json').write_text(json.dumps(doc,indent=2));print('ACTUAL_TRIANGULATED_BODY_ROUTES',doc['pass_body_routes'],rows,flush=True)
