"""Read-only measured wall aperture and native door semantic parts for bathroom101."""
import bpy,json,sys,hashlib
from pathlib import Path
from mathutils import Vector
from shapely.geometry import Polygon,box
from shapely.ops import unary_union
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from physical_scene_geometry import evaluated_surface
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r130_draft.blend';before=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();o=bpy.data.objects['LiteDoorFactory(800570).spawn_asset(6)'];used={i for f in o.data.polygons for i in f.vertices};parts=[]
for a in o.data.attributes:
 if a.domain!='POINT' or a.data_type not in ['BOOLEAN','FLOAT','INT']:continue
 ids=[i for i in used if a.data[i].value>.5]
 if not ids:continue
 ps=[o.matrix_world@o.data.vertices[i].co for i in ids]
 parts.append({'name':a.name,'faced_vertices':len(ids),'bbox_m':[[min(p[k] for p in ps) for k in range(3)],[max(p[k] for p in ps) for k in range(3)]]})
wall=bpy.data.objects['bathroom_0/2.wall'];ps,tri,used=evaluated_surface(wall);x=2.8854653;polys=[]
for f in tri:
 pp=[ps[i] for i in f]
 if all(abs(p.x-x)<1e-4 for p in pp):
  q=Polygon([(p.y,p.z) for p in pp])
  if q.area>1e-10:polys.append(q)
assert polys
missing=box(3.005,.1195347,5.995,2.8).difference(unary_union(polys))
regions=[p for p in (missing.geoms if hasattr(missing,'geoms') else [missing]) if p.area>.1 and p.bounds[0]>3.01 and p.bounds[2]<5.99]
rows=[{'yz_bbox_m':list(p.bounds),'area_m2':p.area,'polygon_yz_m':list(p.exterior.coords)} for p in regions]
assert len(rows)==1, rows
assert hashlib.sha256(src.read_bytes()).hexdigest()==before
out={'source':str(src),'source_sha256':before,'object':o.name,'matrix_world':[list(r) for r in o.matrix_world],'parts':parts,'native_loose_vertices':[{ 'index':v.index,'world_m':list(o.matrix_world@v.co)} for v in o.data.vertices if v.index not in used],'actual_bathroom_inside_wall_face_x_m':x,'actual_apertures':rows,'scope':'Actual missing region of coplanar evaluated inside wall triangles; native semantic part faced vertices. No pose change or whole-body/door sweep certification.'}
(D/'bathroom130_native_door_measurement.json').write_text(json.dumps(out,indent=2));print('BATH130_NATIVE_MEASURE',rows,parts,flush=True)
