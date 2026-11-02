"""Reopened all-fixture geometry/support checks and bounded visual diagnostic cameras."""
import bpy,bmesh,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from wc_layout_checks import bounds,seat_measurement
from compact_wc_contract import mesh_geometry_hash
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';build=json.loads((d/'all_traps122_build.json').read_text());src=Path(build['candidate']);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert sha(src)==build['candidate_sha256']
bpy.ops.wm.open_mainfile(filepath=build['product']);p=bpy.data.objects['NativeFullTankWC100'];m=p.data.copy();m.transform(p.matrix_world);expected=mesh_geometry_hash(m)
bpy.ops.wm.open_mainfile(filepath=str(src));targets=sorted([o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')],key=lambda o:o['program_key']);assert len(targets)==10
rows=[];views=[]
# Only real evaluated floor surfaces provide support; report hit object and normal.
floors=[o for o in bpy.context.scene.objects if o.type=='MESH' and '.floor' in o.name and not o.hide_render];surfaces=[]
for o in floors:
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();me.calc_loop_triangles();pts=[ev.matrix_world@v.co for v in me.vertices];tree=BVHTree.FromPolygons(pts,[tuple(t.vertices) for t in me.loop_triangles],all_triangles=True);ev.to_mesh_clear();surfaces.append((o.name,tree))
for o in targets:
 lo,hi=bounds(o);seat=seat_measurement(o);bm=bmesh.new();bm.from_mesh(o.data);top={'boundary':sum(e.is_boundary for e in bm.edges),'nonmanifold':sum(not e.is_manifold for e in bm.edges)};bm.free();support=[]
 for fx in [.3,.5,.7]:
  for fy in [.3,.5,.7]:
   pos=Vector((lo.x+(hi.x-lo.x)*fx,lo.y+(hi.y-lo.y)*fy,lo.z+.02));hits=[]
   for name,tree in surfaces:
    hit,n,idx,dist=tree.ray_cast(pos,Vector((0,0,-1)),.15)
    if hit is not None and n.z>.8:hits.append((abs(lo.z-hit.z),lo.z-hit.z,name))
   best=min(hits) if hits else None;support.append({'gap_m':best[1] if best else None,'floor':best[2] if best else None})
 key=o['program_key'];identical=mesh_geometry_hash(o.data)==expected;row={'key':key,'object':o.name,'bbox_m':[list(lo),list(hi)],'world_dimensions_xyz_m':list(hi-lo),'seat_height_m':seat['seat_height_m'],'object_scale':list(o.scale),'native_derived_geometry_identical':identical,'topology':top,'support':support};row['bounded_pass']=identical and .40<=seat['seat_height_m']<=.42 and top=={'boundary':0,'nonmanifold':0} and all(x['gap_m'] is not None and abs(x['gap_m'])<.003 for x in support);rows.append(row)
 cam=o.matrix_world@Vector((.70,0,1.40));target=o.matrix_world@Vector((0,0,.48));views.append({'name':'wc122_'+key,'location':list(cam),'target':list(target),'hfov':85,'render_width':768,'samples':32})
result={'source':str(src),'source_sha256':sha(src),'rows':rows,'bounded_all_ten_pass':all(x['bounded_pass'] for x in rows),'scope':'Reopened actual ten raw meshes, evaluated seat heights/world bounds and90 upward-facing real-floor support rays. No door sweep/global path, hydraulic function, full shell self-intersection or photorealism acceptance. Diagnostic camera placement requires rendered visibility check.','accepted':False};(d/'all_traps122_saved_audit.json').write_text(json.dumps(result,indent=2));(d/'all_traps122_views.json').write_text(json.dumps(views,indent=2));changed={x['key'] for x in build['replaced']};(d/'all_traps122_baseline_views.json').write_text(json.dumps([v for v,o in zip(views,targets) if o['program_key'] in changed],indent=2));print('ALL122_AUDIT',result['bounded_all_ten_pass'],[(x['key'],x['bounded_pass']) for x in rows]);assert result['bounded_all_ten_pass']
