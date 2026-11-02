"""Native detailed Movian product at native size; actual floor/props/chair gate before save."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import bounds,evaluated_geometry
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';S=B/'scene_candidate_r105.blend';O=B/'scene_candidate_r106.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();hs=sha(S);A=D/'real_table_candidates';contract=json.load(open(A/'warm_elsa_contract.json'));P=Path(contract['candidate']);assert sha(P)==contract['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(S));old=next(o for o in bpy.context.scene.objects if o.get('program_key')=='breakout_table');lo,hi=bounds(old);old_name=old.name;oldbox=[list(lo),list(hi)];props=[]
for o in list(bpy.context.scene.objects):
 if o.type!='MESH' or o==old or str(o.get('program_key','')).startswith('breakout_chair'):continue
 a,b=bounds(o)
 if a.x>=lo.x-.001 and b.x<=hi.x+.001 and a.y>=lo.y-.001 and b.y<=hi.y+.001 and a.z>=hi.z-.006 and b.z<hi.z+.5:props.append(o)
with bpy.data.libraries.load(str(P),link=False) as (a,b):b.objects=contract['objects']
parts=b.objects
native_basis={}
for o in parts:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();native=[]
for o in parts:
 matrix=o.matrix_world.copy();native_basis[o]=matrix.to_3x3().copy();o.parent=None;o.matrix_world=matrix;native.extend(matrix@v.co for v in o.data.vertices)
nlo=Vector([min(p[k] for p in native) for k in range(3)]);nhi=Vector([max(p[k] for p in native) for k in range(3)]);delta=Vector(((lo.x+hi.x-nlo.x-nhi.x)/2,(lo.y+hi.y-nlo.y-nhi.y)/2,0));floor=bpy.data.objects['kitchen_0/0.floor'];ev,me,pts=evaluated_geometry(floor);ft=BVHTree.FromPolygons(pts,[tuple(f.vertices) for f in me.polygons]);ev.to_mesh_clear();foot=[p+delta for p in native if p.z<nlo.z+1e-5];floor_hits=[ft.ray_cast(Vector((p.x,p.y,2)),Vector((0,0,-1)),3)[0] for p in foot];assert all(p is not None for p in floor_hits);delta.z=max(p.z for p in floor_hits)-nlo.z+.0003
for i,o in enumerate(parts):
 matrix=o.matrix_world.copy();matrix.translation+=delta;o.matrix_world=matrix;o.name=f'Office02_r106_real_Movian_table_part{i}';o['program_key']='breakout_table';o['reference_scene_owner']='commercial_office_floor_02';o['audit_kind']='furniture';o['native_product_source']='B07H8PNQXF';assert max(abs(o.matrix_world[r][c]-native_basis[o][r][c]) for r in range(3) for c in range(3))<1e-6
bpy.context.view_layer.update();newtop=max(bounds(o)[1].z for o in parts);shift=newtop-hi.z;prop_rows=[];prop_set=set(props)
for o in props:
 if o.parent in prop_set:continue
 matrix=o.matrix_world.copy();before=[list(v) for v in matrix];o.parent=None;matrix.translation.z+=shift;o.matrix_world=matrix;prop_rows.append({'object':o.name,'program_key':o.get('program_key'),'delta_z_m':shift,'old_matrix':before})
# Actual evaluated surface intersection, rather than overlap of empty bounding boxes.
def tree(objects):
 points=[];faces=[]
 for o in objects:
  ev,me,pts=evaluated_geometry(o);off=len(points);points.extend(pts);faces.extend(tuple(i+off for i in f.vertices) for f in me.polygons);ev.to_mesh_clear()
 return BVHTree.FromPolygons(points,faces)
tt=tree(parts);chairs=[o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).startswith('breakout_chair')];tests=[]
for o in chairs:
 count=len(tt.overlap(tree([o])));tests.append({'object':o.name,'intersecting_triangle_pairs':count})
planning={'source':str(S),'source_sha256':hs,'prototype':str(P),'prototype_sha256':sha(P),'old_table':old_name,'old_bbox_m':oldbox,'native_bbox_size_m':list(nhi-nlo),'native_unit_conversion_preserved':{o.name:[list(r) for r in native_basis[o]] for o in parts},'rigid_translation_m':list(delta),'floor_support_gap_m':.0003,'old_top_z_m':hi.z,'new_top_z_m':newtop,'prop_shifts':prop_rows,'chair_tests':tests,'parts':[o.name for o in parts],'photorealism_accepted':False};(D/'real_table_r106_planning.json').write_text(json.dumps(planning,indent=2));assert not any(r['intersecting_triangle_pairs'] for r in tests),tests
for child in list(old.children):
 matrix=child.matrix_world.copy();child.parent=None;child.matrix_world=matrix
bpy.data.objects.remove(old,do_unlink=True);bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==hs;meta=json.load(open(D/'realism_refinement_r105.json'));meta.update(source=str(S),source_sha256=hs,candidate=str(O),candidate_sha256=sha(O),change='Replace24face primitive breakout table with native detailed Movian product,rigid placement atnative dimensions. Authored honey optical finish retains native4Kmaps/UV. Actual floor support andchair triangle tests;tabletop props raised by measured top difference. No room/light/camera/cabinet edits.',real_table=planning,photorealism_accepted=False);(D/'realism_refinement_r106.json').write_text(json.dumps(meta,indent=2));print('SAVED106',sha(O),flush=True)
