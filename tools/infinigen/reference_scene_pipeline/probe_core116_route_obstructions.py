import bpy,json,sys
from pathlib import Path
from mathutils import Vector
from shapely.geometry import Point,LineString
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry,bounds
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'core116_route_volume_audit.json').read_text());bpy.ops.wm.open_mainfile(filepath=a['source']);rows=[]
for row in a['rows']:
 shape=LineString(row['route_centres_xy_m']).buffer(.3,resolution=48);loz,hiz=row['prism_z_bounds_m']
 for hit in row['collisions']:
  o=bpy.data.objects[hit['object']];ev,me,ps=evaluated_geometry(o);inside=[{'index':i,'world':list(p)} for i,p in enumerate(ps) if loz+1e-5<p.z<hiz-1e-5 and shape.contains(Point(p.x,p.y))];attrs=[{'name':x.name,'domain':x.domain,'type':x.data_type} for x in me.attributes];ev.to_mesh_clear();rows.append({'unit':row['unit'],'object':o.name,'matrix':[list(v) for v in o.matrix_world],'bounds':[list(x) for x in bounds(o)],'inside_points':inside,'attributes':attrs,'custom_properties':{k:str(v) for k,v in o.items()},'modifiers':[(m.name,m.type) for m in o.modifiers]})
(d/'core116_route_obstruction_probe.json').write_text(json.dumps(rows,indent=2));print([(x['object'],min(p['world'][2] for p in x['inside_points']),max(p['world'][2] for p in x['inside_points'])) for x in rows])
