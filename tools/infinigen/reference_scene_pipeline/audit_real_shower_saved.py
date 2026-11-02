"""Read-only installed shower checks on the saved candidate; no visual approval."""
import bpy,json,hashlib,sys,argparse
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
meta=json.loads((D/f'realism_refinement_r{a.revision}.json').read_text())
source=Path(meta['candidate']);sha=hashlib.sha256(source.read_bytes()).hexdigest()
assert sha==meta['candidate_sha256'];out=D/f'real_shower_saved_audit_r{a.revision}.json';assert not out.exists()
bpy.ops.wm.open_mainfile(filepath=str(source));row=meta['real_shower'];errors=[]
objects=[bpy.data.objects[n] for n in row['objects']]
def tree(items):
    points,polygons=[],[]
    for obj in items:
        ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();offset=len(points)
        points.extend(obj.matrix_world@v.co for v in mesh.vertices)
        polygons.extend(tuple(offset+i for i in f.vertices) for f in mesh.polygons)
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(points,polygons)
checks={'five_actual_parts':len(objects)==5,
        'kit_source_faces':sum(len(o.data.polygons) for o in objects[:4])==12002,
        'valve_source_faces':sum(len(o.data.polygons) for o in objects[4:])==row['valve_faces']}
points=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
lo=[min(p[k] for p in points) for k in range(3)];hi=[max(p[k] for p in points) for k in range(3)]
checks['saved_envelope']=all(abs(v-w)<1e-5 for vs,ws in zip([lo,hi],row['bounds']) for v,w in zip(vs,ws))
wall=tree([bpy.data.objects[row['wall']]]);gaps=[]
for point in points:
    if point.y<hi[1]-.0001:continue
    hit=wall.ray_cast(point-Vector((0,.002,0)),Vector((0,1,0)),.02)[0]
    if hit is None:errors.append('No wall behind rear mounting vertex')
    else:gaps.append(hit.y-point.y)
checks['rear_wall_mount_gap']=bool(gaps) and max(abs(g-row['wall_mount_gap_m']) for g in gaps)<.0002
assembly=tree(objects);collisions=[]
for old in row['obstacle_surface_checks']:
    count=len(assembly.overlap(tree([bpy.data.objects[old['object']]])))
    collisions.append({'object':old['object'],'triangle_surface_intersections':count})
    if count:errors.append('Surface intersection:'+old['object'])
for key,value in checks.items():
    if not value:errors.append(key)
out.write_text(json.dumps({'source':str(source),'source_sha256':sha,'checks':checks,
    'mount_vertex_count':len(gaps),'obstacle_surface_checks':collisions,'errors':errors,'pass':not errors,
    'scope':'Saved source face counts/envelope, rear-wall support rays and44 actual local obstacle surface checks. No closed-volume containment,plumbing/waterproofing/structural support/full nav or photographic acceptance.',
    'photorealism_accepted':False},indent=2))
print('SAVED_REAL_SHOWER_AUDIT',len(errors),flush=True);assert not errors,errors
