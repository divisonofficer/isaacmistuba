"""Remove only measured coincident shared-plane coverage from one of two native walls."""
import bpy,bmesh,json,hashlib,sys,argparse
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
try:from shapely.geometry import Polygon
except ImportError:
 sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import Polygon
from shapely.ops import unary_union,triangulate
from shapely import make_valid
parser=argparse.ArgumentParser();parser.add_argument('--source-revision',type=int,default=84);parser.add_argument('--candidate-revision',type=int);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
root=Path(__file__).resolve().parents[3];ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';outdir=ref/(f'wall_dedup_r{args.candidate_revision}' if args.candidate_revision else 'private_chair84_wall_dedup_control');outdir.mkdir(exist_ok=True);out=base/f'scene_candidate_r{args.candidate_revision}.blend' if args.candidate_revision else outdir/'source.blend';assert not out.exists();src=base/f'scene_candidate_r{args.source_revision}.blend';digest=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();keep=bpy.data.objects['office_0/0.exterior'];cut=bpy.data.objects['office_0/1.exterior'];plane=5.5;eps=1e-5

def pieces(g):
 if g.is_empty:return []
 if g.geom_type=='Polygon':return [g]
 if hasattr(g,'geoms'):return [p for part in g.geoms for p in pieces(part)]
 return []
def flat_faces(o):
 rows=[]
 for f in o.data.polygons:
  vs=[o.matrix_world@o.data.vertices[i].co for i in f.vertices]
  if max(abs(p.y-plane) for p in vs)>eps:continue
  shape=make_valid(Polygon([(p.x,p.z) for p in vs]))
  if shape.area>1e-10:rows.append((f.index,shape,f.material_index,f.use_smooth,f.normal.copy()))
 return rows
left=flat_faces(keep);right=flat_faces(cut);assert left and right;cover=unary_union([s for _,s,*_ in left]);other=unary_union([s for _,s,*_ in right]);overlap=cover.intersection(other);assert overlap.area>.01,overlap.area
# Duplicate mesh data only; keep counterpart and every unrelated face, material, visibility and lighting unchanged.
cut.data=cut.data.copy();bm=bmesh.new();bm.from_mesh(cut.data);bm.faces.ensure_lookup_table();original_faces=list(bm.faces);changes=[];oldfaces=[];inverse=cut.matrix_world.inverted()
for index,shape,mat,smooth,normal in right:
 intersection=shape.intersection(cover)
 if intersection.area<1e-10:continue
 remaining=shape.difference(cover);triangles=[]
 for part in pieces(remaining):triangles.extend(t for t in triangulate(part) if part.covers(t) and t.area>1e-12)
 assert abs(sum(t.area for t in triangles)-remaining.area)<1e-7,(index,remaining.area,sum(t.area for t in triangles))
 for tri in triangles:
  verts=[bm.verts.new(inverse@Vector((x,plane,z))) for x,z in list(tri.exterior.coords)[:-1]];face=bm.faces.new(verts);face.material_index=mat;face.smooth=smooth;face.normal_update()
  if face.normal.dot(normal)<0:face.normal_flip()
 oldfaces.append(original_faces[index]);changes.append({'raw_face':index,'old_area_m2':shape.area,'removed_overlap_area_m2':intersection.area,'remaining_area_m2':remaining.area,'replacement_triangles':len(triangles)})
assert changes;bmesh.ops.delete(bm,geom=oldfaces,context='FACES_ONLY');bm.normal_update();bm.to_mesh(cut.data);bm.free();cut.data.update();bpy.context.view_layer.update();after=flat_faces(cut);newother=unary_union([s for _,s,*_ in after]);before_union=cover.union(other);after_union=cover.union(newother);delta=before_union.symmetric_difference(after_union).area;remaining_overlap=cover.intersection(newother).area;assert delta<1e-7 and remaining_overlap<1e-7,(delta,remaining_overlap)
# Exact black-pixel direction must now see one retained physical wall surface, not two opposing coincident hits.
origin=Vector((2.1,3.25,1.15));direction=Vector((.6075583,.7839553,-.1276204)).normalized();dg=bpy.context.evaluated_depsgraph_get();hits=[]
for o in [keep,cut]:
 ev=o.evaluated_get(dg);me=ev.to_mesh();tree=BVHTree.FromPolygons([o.matrix_world@v.co for v in me.vertices],[list(f.vertices) for f in me.polygons]);hit,normal,index,distance=tree.ray_cast(origin,direction,5)
 if hit is not None:hits.append({'object':o.name,'distance_m':distance,'normal':list(normal),'point':list(hit)})
 ev.to_mesh_clear()
near=[h for h in hits if abs(h['distance_m']-2.8700614)<.005];assert len(near)==1 and near[0]['object']==keep.name,hits
assert hashlib.sha256(src.read_bytes()).hexdigest()==digest;bpy.ops.wm.save_as_mainfile(filepath=str(out));scope={'controlled_base_revision':args.source_revision,'candidate_revision':args.candidate_revision,'source':str(src),'source_sha256':digest,'candidate':str(out),'candidate_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'change':'Geometry-only diagnostic: subtract measured coincident shared-plane coverage from office0/1 exterior, retain office0/0 counterpart. No wall hidden, no camera visibility/material/lighting change.','plane_world_y_m':plane,'kept_object':keep.name,'edited_object':cut.name,'overlap_before_m2':overlap.area,'overlap_after_m2':remaining_overlap,'combined_projected_surface_coverage_difference_m2':delta,'changes':changes,'black_pixel_direction_retained_hits':near,'photorealism_accepted':False,'scene_adopted':False,'scope':'Coverage preserved in this shared plane only; no global deduplication or whole-scene physical certification. Actual controlled RGB required.'};(outdir/'scope.json').write_text(json.dumps(scope,indent=2)+'\n');views=json.loads((ref/'private_chair84_wall_material_control/views.json').read_text());(outdir/'views.json').write_text(json.dumps(views,indent=2)+'\n');print('PRIVATE_WALL_DEDUP_CONTROL_SAVED',scope['overlap_before_m2'],flush=True)
