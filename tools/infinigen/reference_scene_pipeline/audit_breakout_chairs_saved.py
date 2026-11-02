"""Saved native chair mesh/UV, support and bounded pairwise surface checks."""
import bpy,json,hashlib,sys,argparse
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--revision',required=True,type=int)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
m=json.loads((D/f'realism_refinement_r{a.revision}.json').read_text());source=Path(m['candidate'])
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(source)==m['candidate_sha256']
out=D/f'breakout_chairs_saved_audit_r{a.revision}.json';assert not out.exists()
bpy.ops.wm.open_mainfile(filepath=str(source));errors=[];rows=[]
for name in m['removed_breakout_legacy_objects']:
    if bpy.data.objects.get(name) is not None:errors.append('Legacy chair component remains:'+name)
def tree(objects):
    vertices=[];polygons=[]
    for obj in objects:
        offset=len(vertices);vertices.extend(obj.matrix_world@v.co for v in obj.data.vertices)
        polygons.extend(tuple(offset+i for i in p.vertices) for p in obj.data.polygons)
    return BVHTree.FromPolygons(vertices,polygons)
floor=tree([o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.endswith('.floor')])
groups=[]
for row in m['breakout_chair_records']:
    group=[bpy.data.objects[name] for name in row['parts']];groups.append(group)
    if row.get('furniture_contact_part'):
        representative=bpy.data.objects[row['furniture_contact_part']]
        if representative.get('audit_kind')!='furniture' or representative.get('program_key')!=row['role']:
            errors.append('Contact part semantic role:'+row['role'])
        if sum(obj.get('audit_kind')=='furniture' for obj in group)!=1:
            errors.append('Expected one furniture representative:'+row['role'])
    for obj in group:
        actual=hashlib.sha256(repr(([tuple(v.co) for v in obj.data.vertices],[tuple(p.vertices) for p in obj.data.polygons],[[tuple(x.uv) for x in layer.data] for layer in obj.data.uv_layers])).encode()).hexdigest()
        if actual!=row['part_geometry_sha256'][obj.name]:errors.append('Mesh/UV changed:'+obj.name)
        if any(abs(v-1)>1e-6 for v in obj.scale):errors.append('Non-native scale:'+obj.name)
    pos=group[0].matrix_world.translation
    hit=floor.ray_cast(Vector((pos.x,pos.y,1)),Vector((0,0,-1)),2)[0]
    z=min((o.matrix_world@v.co).z for o in group for v in o.data.vertices)
    gap=z-hit.z if hit is not None else None
    if gap is None or abs(gap)>1e-5:errors.append('Floor support:'+row['role'])
    table=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('program_key')=='breakout_table']
    intersections=len(tree(group).overlap(tree(table))) if table else -1
    if intersections!=0:errors.append('Table surface overlap:'+row['role'])
    rows.append({'role':row['role'],'parts':row['parts'],'floor_gap_m':gap,'table_surface_intersections':intersections})
for i,group in enumerate(groups):
    for other in groups[i+1:]:
        if tree(group).overlap(tree(other)):errors.append('Chair pair surface intersection')
if len(groups)!=4:errors.append('Expected four chair assemblies')
out.write_text(json.dumps({'source':str(source),'source_sha256':sha(source),'rows':rows,'errors':errors,'pass':not errors,
    'photorealism_accepted':False,'scope':'Exact saved native mesh/UV fingerprints,scale1,four floor support rays,four table and six chair-pair triangle surface checks. Not closed-volume containment, ergonomics, full door sweep or navigation certification.'},indent=2))
assert not errors,errors
print('BREAKOUT_CHAIRS_SAVED_AUDIT',flush=True)
