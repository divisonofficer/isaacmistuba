"""Read-only native door body-height sections to disambiguate conservative hull diagnostics."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import LineString,MultiPoint,Polygon;from shapely.ops import unary_union
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';source=W/'furnished_r6_products.blend';bpy.ops.wm.open_mainfile(filepath=str(source));routes={k:Polygon(v) for k,v in json.loads((W/'wc_route_volume_audit_r6.json').read_text())['reserved_route_polygons_m'].items()};selected=['LiteDoorFactory(7067179).spawn_asset(2)','LiteDoorFactory(8664258).spawn_asset(4)','LiteDoorFactory(8664258).spawn_asset(5)'];rows=[]
for name in selected:
 o=bpy.data.objects[name];bpy.context.view_layer.update();vs=[o.matrix_world@v.co for v in o.data.vertices];sections=[]
 for z in [.5,1,1.5]:
  lines=[]
  for p in o.data.polygons:
   cs=[vs[i] for i in p.vertices];cross=[]
   for i,a in enumerate(cs):
    b=cs[(i+1)%len(cs)]
    if (a.z-z)*(b.z-z)<0:
     t=(z-a.z)/(b.z-a.z);cross.append((a.x+t*(b.x-a.x),a.y+t*(b.y-a.y)))
   if len(cross)>=2:lines.append(LineString(cross))
  geom=unary_union(lines);sections.append({'height_m':z,'cross_section_lines_m':[list(g.coords) for g in geom.geoms] if hasattr(geom,'geoms') else [list(geom.coords)],'route_section_10mm_buffer_intersection_m2':{k:geom.buffer(.01).intersection(r).area for k,r in routes.items() if geom.buffer(.01).intersection(r).area>1e-5}})
 casing=bpy.data.objects.get(name.replace('LiteDoorFactory','DoorCasingFactory'));rows.append({'door':name,'parent':o.parent.name if o.parent else None,'location_local':list(o.location),'rotation_local_euler':list(o.rotation_euler),'matrix_world':[list(r) for r in o.matrix_world],'bounds_xyz_m':[[min(v[k] for v in vs) for k in range(3)],[max(v[k] for v in vs) for k in range(3)]],'vertex_count':len(o.data.vertices),'polygon_count':len(o.data.polygons),'casing':casing.name if casing else None,'sections':sections})
(W/'native_wc_door_body_sections_r6.json').write_text(json.dumps({'source':str(source),'doors':rows,'scope':'Actual native mesh body-height sections,10mm diagnostic line buffer only; full solid/corridor+sweep proof not claimed','photorealism_accepted':False},indent=2));print('NATIVE_WC_DOOR_SECTIONS_SAVED',[(r['door'],r['sections'][1]['route_section_10mm_buffer_intersection_m2']) for r in rows],flush=True)
