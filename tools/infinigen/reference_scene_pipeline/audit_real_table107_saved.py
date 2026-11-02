"""Verify actual saved native product, floor/chair surfaces and plate/apple support."""
import bpy,json,hashlib,sys,collections
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry,bounds
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';m=json.load(open(D/'realism_refinement_r107.json'));S=Path(m['candidate']);sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(S)==m['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(S));parts=[o for o in bpy.context.scene.objects if o.get('program_key')=='breakout_table'];assert len(parts)==1;table=parts[0];errors=[]
def signature(o):return hashlib.sha256(repr(([tuple(v.co) for v in o.data.vertices],[tuple(f.vertices) for f in o.data.polygons],[[tuple(p.uv) for p in uv.data] for uv in o.data.uv_layers])).encode()).hexdigest()
def geometry(o):
 ev,me,p=evaluated_geometry(o);faces=[tuple(f.vertices) for f in me.polygons];ev.to_mesh_clear();return p,faces
def tree(o):p,f=geometry(o);return BVHTree.FromPolygons(p,f)
actual=signature(table);basis=m['real_table']['native_unit_conversion_preserved'][table.name];assert max(abs(table.matrix_world[r][c]-basis[r][c]) for r in range(3) for c in range(3))<1e-6;lo,hi=bounds(table);assert max(abs((hi-lo)[i]-m['real_table']['native_bbox_size_m'][i]) for i in range(3))<1e-5;floor=tree(bpy.data.objects['kitchen_0/0.floor']);p,f=geometry(table);low=min(q.z for q in p);gaps=[]
for q in p:
 if q.z>low+1e-5:continue
 hit=floor.ray_cast(q+Vector((0,0,.01)),Vector((0,0,-1)),.03)[0];gaps.append(None if hit is None else q.z-hit.z)
assert all(g is not None and -.0001<=g<=.001 for g in gaps),gaps;tt=tree(table);chairtests=[]
for o in bpy.context.scene.objects:
 if o.type=='MESH' and str(o.get('program_key','')).startswith('breakout_chair'):
  count=len(tt.overlap(tree(o)));chairtests.append({'object':o.name,'triangle_overlap_count':count});assert count==0
rows=[]
for row in m['table_prop_support107']:
 o=bpy.data.objects[row['object']];support=bpy.data.objects[o['support_object']];st=tree(support);points,faces=geometry(o);low=min(q.z for q in points);sample=[q for q in points if q.z<low+.003];ds=[]
 for q in sample:
  hit=st.ray_cast(Vector((q.x,q.y,2)),Vector((0,0,-1)),3)[0]
  if hit is not None:ds.append(q.z-hit.z)
 overlaps=len(tree(o).overlap(st));assert ds and min(ds)>=-.0001 and min(ds)<.003 and overlaps==0,(o.name,ds,overlaps);rows.append({'object':o.name,'support':support.name,'lowest3mm_vertex_support_gap_range_m':[min(ds),max(ds)],'surface_triangle_overlaps':overlaps})
prototype=Path(m['real_table']['prototype']);assert sha(prototype)==m['real_table']['prototype_sha256'];contract=json.load(open(D/'real_table_candidates/warm_elsa_contract.json'))
with bpy.data.libraries.load(str(prototype),link=False) as (a,b):b.objects=contract['objects']
assert collections.Counter(signature(o) for o in b.objects)==collections.Counter([actual]);result={'source':str(S),'source_sha256':sha(S),'native_geometry_uv_identical':True,'native_unit_conversion_preserved':True,'bbox_size_m':list(hi-lo),'floor_support_gap_range_m':[min(gaps),max(gaps)],'chair_tests':chairtests,'tabletop_support':rows,'errors':errors,'pass':True,'photorealism_accepted':False,'scope':'Saved native geometry/UV andnative physical dimensions/linear transform,actual floor rays,12chair-part surface intersection checks,plate/apple actualsupport references/rays/surface tests. Not whole-room navigation orRGB approval.'};(D/'real_table_saved_audit_r107.json').write_text(json.dumps(result,indent=2));print('SAVED107_NATIVE_TABLE_AUDIT_PASS',flush=True)
