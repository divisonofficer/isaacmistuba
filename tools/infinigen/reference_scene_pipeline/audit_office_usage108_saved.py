"""Saved native geometry, assembly poses and static desk-collision regression.
This bounded audit deliberately does not certify full navigation or modifiers.
"""
import bpy,collections,hashlib,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';P=D/'usage108_products';build=json.loads((D/'usage108_draft_build.json').read_text());S=Path(build['draft']);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert sha(S)==build['draft_sha256'];bpy.ops.wm.open_mainfile(filepath=str(S));errors=[]
def fingerprint(o):
 if o.type=='MESH':value=([tuple(v.co) for v in o.data.vertices],[tuple(p.vertices) for p in o.data.polygons],[[tuple(v.uv) for v in uv.data] for uv in o.data.uv_layers])
 elif o.type=='CURVE':value=(o.data.dimensions,o.data.resolution_u,o.data.bevel_depth,o.data.bevel_resolution,[(s.type,s.use_cyclic_u,[(tuple(p.co),tuple(p.handle_left),tuple(p.handle_right),p.radius,p.tilt) for p in s.bezier_points],[(tuple(p.co),p.radius,p.tilt) for p in s.points]) for s in o.data.splines])
 elif o.type=='EMPTY':value=('EMPTY',)
 else:raise ValueError('Unsupported owned assembly type:'+o.type)
 return hashlib.sha256(repr(value).encode()).hexdigest()
def world(o):
 assert not o.constraints,'Explicitly evaluate constrained assembly'
 return o.matrix_basis.copy() if o.parent is None else world(o.parent)@o.matrix_parent_inverse@o.matrix_basis
def tree(objects):
 points=[];faces=[]
 for o in objects:
  if o.type=='EMPTY':continue
  mesh=o.data if o.type=='MESH' else o.to_mesh()
  offset=len(points);matrix=world(o);points.extend(matrix@v.co for v in mesh.vertices);faces.extend(tuple(i+offset for i in f.vertices) for f in mesh.polygons)
  if o.type!='MESH':o.to_mesh_clear()
 return BVHTree.FromPolygons(points,faces)
chair_current={name:bpy.data.objects[name] for row in build['chair_changes'] for name in row['assembly_objects']};desk_keys={r['desk'] for r in build['station_states']};desks={o['program_key']:o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('program_key') in desk_keys};desk_names=[o.name for o in desks.values()];source_names=tuple(chair_current)+tuple(desk_names)
# Blender replaces dst.objects entries with loaded datablocks; don't alias the
# string-key list needed for matching the immutable original-source objects.
with bpy.data.libraries.load(build['source'],link=False) as (src,dst):dst.objects=list(source_names)
original=dict(zip(source_names,dst.objects));rows=[]
for change in build['chair_changes']:
 current=[chair_current[n] for n in change['assembly_objects']];baseline=[original[n] for n in change['assembly_objects']];identity=all(fingerprint(a)==fingerprint(b) for a,b in zip(current,baseline));root=bpy.data.objects[change['object']];expected=change['after_matrix'];pose_error=max(abs(world(root)[i][j]-expected[i][j]) for i in range(4) for j in range(4))
 base_root=original[change['object']];base_inverse=world(base_root).inverted();current_inverse=world(root).inverted();relative_error=max(abs((current_inverse@world(a))[i][j]-(base_inverse@world(b))[i][j]) for a,b in zip(current,baseline) for i in range(4) for j in range(4));key=change['key'].rsplit('_chair',1)[0];candidate_hits=len(tree(current).overlap(tree([desks[key]])));baseline_hits=len(tree(baseline).overlap(tree([original[desks[key].name]])))
 row={'key':change['key'],'native_geometry_uv_identical':identity,'root_pose_max_error':pose_error,'assembly_relative_pose_max_error':relative_error,'static_desk_triangle_hits_before':baseline_hits,'static_desk_triangle_hits_after':candidate_hits};row['pass']=identity and pose_error<2e-5 and relative_error<2e-5 and candidate_hits<=baseline_hits;rows.append(row)
 if not row['pass']:errors.append(change['key']+':pose/native geometry/static collision regression')
scope=json.loads((P/'review_scope.json').read_text());prop_rows=[]
for entry in scope['assets']:
 with bpy.data.libraries.load(str(P/'review_studio.blend'),link=False) as (src,dst):dst.objects=entry['objects']
 expected=collections.Counter(fingerprint(o) for o in dst.objects)
 for prop in build['native_props']:
  if prop['asset_id']!=entry['id']:continue
  actual=collections.Counter(fingerprint(bpy.data.objects[n]) for n in prop['objects']);ok=actual==expected;prop_rows.append({'station':prop['station'],'role':prop['role'],'asset_id':entry['id'],'native_geometry_uv_multiset_identical':ok})
  if not ok:errors.append(str(prop['station'])+':native prop changed')
assert len(rows)==24 and len(prop_rows)==24;assert sha(S)==build['draft_sha256'];report={'source':str(S),'source_sha256':sha(S),'chairs':rows,'props':prop_rows,'errors':errors,'bounded_static_checks_pass':not errors,'photorealism_accepted':False,'full_scene_navigation_certified':False,'scope':'Saved mesh data/UV identity, full separate-back relative poses, assigned root poses, static raw chair-versus-own-desk triangle regression. Evaluated modifiers, prop-to-device collision and full floor walking clearance still required.'};(D/'usage108_saved_audit.json').write_text(json.dumps(report,indent=2)+'\n');print('USAGE108_SAVED_AUDIT','PASS' if not errors else 'HOLD',json.dumps(errors),flush=True)
