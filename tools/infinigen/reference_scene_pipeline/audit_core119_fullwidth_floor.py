"""Actual evaluated upward finish-floor faces under complete600mm route footprints."""
import bpy,json,sys,hashlib
from pathlib import Path
from shapely.geometry import Polygon,LineString
from shapely.ops import unary_union
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry,bounds
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'core119_route_volume_audit.json').read_text());src=Path(a['source']);assert hashlib.sha256(src.read_bytes()).hexdigest()==a['source_sha256'];bpy.ops.wm.open_mainfile(filepath=str(src));fz=bounds(bpy.data.objects['hallway_0/1.floor'])[1].z;polys=[];objects=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or not o.name.endswith('.floor'):continue
 lo,hi=bounds(o)
 if hi.z<fz-.003 or lo.z>fz+.003:continue
 ev,me,ps=evaluated_geometry(o);normalmatrix=ev.matrix_world.to_3x3().inverted().transposed();count=0
 for f in me.polygons:
  normal=(normalmatrix@f.normal).normalized();zs=[ps[i].z for i in f.vertices]
  if normal.z<.98 or min(zs)<fz-.003 or max(zs)>fz+.003:continue
  p=Polygon([(ps[i].x,ps[i].y) for i in f.vertices])
  if not p.is_valid:p=p.buffer(0)
  if p.area>1e-12:polys.append(p);count+=1
 ev.to_mesh_clear()
 if count:objects.append({'object':o.name,'upward_faces':count})
cover=unary_union(polys);rows=[]
for row in a['rows']:
 route=LineString(row['route_centres_xy_m']).buffer(.3,resolution=48);missing=route.difference(cover);rows.append({'unit':row['unit'],'route_area_m2':route.area,'actual_finish_floor_uncovered_area_m2':missing.area,'uncovered_bounds_xy_m':list(missing.bounds) if not missing.is_empty else None,'covered_within_0.01mm_numerical_seam_tolerance':cover.buffer(.00001).covers(route),'exact_cover':cover.covers(route)})
out={'source':str(src),'source_sha256':a['source_sha256'],'finish_z_m':fz,'objects':objects,'rows':rows,'both_routes_fullwidth_supported':all(x['covered_within_0.01mm_numerical_seam_tolerance'] for x in rows),'scope':'Entire planar600mm route footprint versus actual evaluated upward floor faces within3mm of finish height. No bbox floor proxies. Numerical seam tolerance0.01mm explicitly reported alongside exact uncovered area. Separate3D prism/door sweeps and whole10room circulation still required.','accepted':False};(d/'core119_fullwidth_floor_audit.json').write_text(json.dumps(out,indent=2));print('CORE119_FULLWIDTH_FLOOR',out['both_routes_fullwidth_supported'],[(x['unit'],x['actual_finish_floor_uncovered_area_m2']) for x in rows])
