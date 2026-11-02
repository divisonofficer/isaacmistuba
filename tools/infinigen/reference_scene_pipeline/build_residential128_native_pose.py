"""Recover evaluated native studio transforms, without shape rescaling; preserve failed127."""
import bpy,json,math,sys,hashlib
from pathlib import Path
from mathutils import Matrix,Vector
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
D=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r127_draft.blend';dst=base/'scene_candidate_r128_draft.blend';assert not dst.exists();a=json.loads((D/'compact_media127_build.json').read_text());scope=json.loads((D/'native_media_products/scope.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src)
bpy.ops.wm.open_mainfile(filepath=a['native_studio']);bpy.context.view_layer.update();native={}
for e in scope['assets']:
 native[e['id']]=[{'matrix':[list(v) for v in bpy.data.objects[name].matrix_world],'geometry':mesh_geometry_hash(bpy.data.objects[name].data)} for name in e['objects']]
bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();unchanged={o.name:[list(v) for v in o.matrix_world] for o in bpy.context.scene.objects};rows=[]
for entry in a['products']:
 unit=entry['unit'];kind=entry['kind'];parts=[bpy.data.objects[n] for n in entry['objects']];R=Matrix.Rotation((-1 if unit==101 else 1)*math.pi/2,4,'Z')
 for o,s in zip(parts,native[entry['asset_id']]):
  assert mesh_geometry_hash(o.data)==s['geometry'];o.matrix_world=R@Matrix(s['matrix'])
 bpy.context.view_layer.update()
 def bounds():
  ps=[o.matrix_world@v.co for o in parts for v in o.data.vertices];return Vector([min(p[k] for p in ps) for k in range(3)]),Vector([max(p[k] for p in ps) for k in range(3)])
 lo,hi=bounds();expected=next(e['actual_dimensions_xyz_m'] for e in scope['assets'] if e['id']==entry['asset_id']);size=hi-lo;assert max(abs(size[i]-expected[j]) for i,j in [(0,1),(1,0),(2,2)])<1e-5,(kind,list(size),expected)
 back=(6.86 if kind=='console' else 6.8849653) if unit==101 else (14.64 if kind=='console' else 14.6150347);delta=Vector((back-(hi.x if unit==101 else lo.x),8.45-(lo.y+hi.y)/2,(.1145347 if kind=='console' else .95)-lo.z))
 for o in parts:o.matrix_world=Matrix.Translation(delta)@o.matrix_world
 bpy.context.view_layer.update();lo,hi=bounds();rows.append({'unit':unit,'kind':kind,'objects':entry['objects'],'bbox_m':[list(lo),list(hi)],'dimensions_xyz_m':list(hi-lo),'native_geometry_unchanged':all(mesh_geometry_hash(o.data)==s['geometry'] for o,s in zip(parts,native[entry['asset_id']]))})
names={n for e in a['products'] for n in e['objects']};assert all(unchanged[o.name]==[list(v) for v in o.matrix_world] for o in bpy.context.scene.objects if o.name not in names);bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before
(D/'compact_media128_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'native_studio':a['native_studio'],'rows':rows,'unrelated_matrices_unchanged':True,'root_cause':'Reading newly linked library matrix_world before dependency graph evaluation lost native X reorientation;127 TVs lay flat.128 uses world matrices captured from reopened evaluated studio, validates all three dimensions.','accepted':False,'post_save_validation_pending':True},indent=2));print('NATIVE128_SAVED',rows,flush=True)
