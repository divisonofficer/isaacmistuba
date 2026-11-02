"""Native detailed armchairs in both living rooms, no scale changes or proxies."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r107_draft.blend';dst=b/'scene_candidate_r108_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);p=r/'living108_armchair_products';scope=json.loads((p/'review_scope.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def points(o):return [o.matrix_world@v.co for v in o.data.vertices]
def bounds(ps):return Vector([min(v[k] for v in ps) for k in range(3)]),Vector([max(v[k] for v in ps) for k in range(3)])
def tree(o):return BVHTree.FromPolygons(points(o),[tuple(f.vertices) for f in o.data.polygons])
for unit,ident,x,y,yaw in [('101','HSSD_0df55741b2499a6d155ba54ec55199e85ed83386',4.65,8.05,-90),('102','HSSD_3aaccfa2eb2d93162748ffc157aa69bae0d4199c',16.85,8.05,90)]:
 row=next(v for v in scope['assets'] if v['id']==ident);names=tuple(row['objects'])
 with bpy.data.libraries.load(str(p/'review_studio.blend'),link=False) as (a,z):z.objects=list(names)
 objects=z.objects;assert all(objects)
 for o in objects:bpy.context.scene.collection.objects.link(o)
 bpy.context.view_layer.update();original={o:o.matrix_world.copy() for o in objects};lo,hi=bounds([v for o in objects for v in points(o)]);center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));rug=next(o for o in bpy.context.scene.objects if o.get('program_key')==unit+'_living_rug');rt=tree(rug);support=rt.ray_cast(Vector((x,y,1)),Vector((0,0,-1)),2)[0];assert support is not None;transform=Matrix.Translation(Vector((x,y,support.z)))@Matrix.Rotation(math.radians(yaw),4,'Z')@Matrix.Translation(-center)
 for i,o in enumerate(objects):o.parent=None;o.matrix_world=transform@original[o];o['program_key']=unit+'_living_armchair'+('' if i==0 else '_part'+str(i));o['original_asset_id']=ident;o['audit_kind']='furniture'
 bpy.context.view_layer.update();ps=[v for o in objects for v in points(o)];nlo,nhi=bounds(ps);assert all(abs(o.scale[k]-1)<1e-5 for o in objects for k in range(3));assert abs(nlo.z-support.z)<1e-5
 # All low foot points must lie on the same physical rug surface, preventing edge-straddling floats.
 contacts=[]
 for v in ps:
  if v.z>nlo.z+.002:continue
  hit=rt.ray_cast(Vector((v.x,v.y,v.z+.1)),Vector((0,0,-1)),.2)[0];assert hit is not None;gap=v.z-hit.z;assert -.0001<=gap<=.0021;contacts.append(gap)
 assert contacts
 checks=[]
 for o in bpy.context.scene.objects:
  if o in objects or o.type!='MESH' or o.get('audit_kind')!='furniture' or not str(o.get('program_key','')).startswith(unit+'_'):continue
  olo,ohi=bounds([o.matrix_world@Vector(v) for v in o.bound_box])
  if not all(nhi[k]>olo[k] and ohi[k]>nlo[k] for k in range(3)):continue
  t=tree(o);count=sum(len(tree(c).overlap(t)) for c in objects);checks.append({'object':o.name,'triangle_intersections':count});assert count==0,checks
 assert (nlo.x>.115 and nhi.x<6.885 if unit=='101' else nlo.x>14.615 and nhi.x<21.385);assert nlo.y>6.115 and nhi.y<9.385
 rows.append({'unit':unit,'native_asset':ident,'parts':names,'bbox_min_m':list(nlo),'bbox_max_m':list(nhi),'yaw_deg':yaw,'low_foot_samples':len(contacts),'max_foot_gap_m':max(contacts),'nearby_surface_checks':checks,'southern_clear_band_y_m':[6.115,float(nlo.y)]})
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(r/'living108_armchairs_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'chairs':rows,'scope':'Native geometry/UV retained rigid transform. Raw triangle collision and low-foot rug support checks; no whole-floor navigation/volume-containment/ergonomics or photo approval.','accepted':False},indent=2));print('LIVING108_ARMCHAIRS_SAVED')
