"""Two distinct native round coffee tables; rigid-only fit, real support, no photo approval."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r104_draft.blend';out=b/'scene_candidate_r107_draft.blend';assert not out.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_sha=sha(src);p=r/'living107_table_products';scope=json.loads((p/'review_scope.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def pts(o):return [o.matrix_world@v.co for v in o.data.vertices]
def bounds(ps):return Vector([min(v[k] for v in ps) for k in range(3)]),Vector([max(v[k] for v in ps) for k in range(3)])
def tree(o):return BVHTree.FromPolygons(pts(o),[tuple(f.vertices) for f in o.data.polygons])
for unit,ident in [('101','HSSD_0030aabddff541fbd378e38ae2d8597aecbfc757'),('102','HSSD_7baec79414bc85c8b7f452fd24e24fddeffd8592')]:
 old=next(o for o in bpy.context.scene.objects if o.get('program_key')==unit+'_living_coffee_table');olo,ohi=bounds(pts(old));center=(olo+ohi)/2;assert not old.children
 props=[]
 for o in bpy.context.scene.objects:
  if o.type!='MESH' or o==old:continue
  lo,hi=bounds([o.matrix_world@Vector(v) for v in o.bound_box])
  if olo.x<lo.x<=hi.x<ohi.x and olo.y<lo.y<=hi.y<ohi.y and ohi.z-.003<=lo.z<hi.z<ohi.z+.1:props.append(o)
 assert len(props)==1,(unit,[(o.name,o.get('program_key')) for o in props])
 row=next(x for x in scope['assets'] if x['id']==ident);names=tuple(row['objects'])
 with bpy.data.libraries.load(str(p/'review_studio.blend'),link=False) as (a,z):z.objects=list(names)
 objects=z.objects;assert all(objects);matrices={o:o.matrix_world.copy() for o in objects}
 for o in objects:bpy.context.scene.collection.objects.link(o);o.parent=None;o.matrix_world=matrices[o]
 bpy.context.view_layer.update();lo,hi=bounds([v for o in objects for v in pts(o)])
 rug=next(o for o in bpy.context.scene.objects if o.get('program_key')==unit+'_living_rug');support=tree(rug).ray_cast(Vector((center.x,center.y,1)),Vector((0,0,-1)),2)[0];assert support is not None
 delta=Vector((center.x-(lo.x+hi.x)/2,center.y-(lo.y+hi.y)/2,support.z-lo.z))
 for i,o in enumerate(objects):o.matrix_world=Matrix.Translation(delta)@matrices[o];o['program_key']=unit+'_living_coffee_table'+('' if i==0 else '_native_part'+str(i));o['original_asset_id']=ident;o['audit_kind']='furniture'
 bpy.context.view_layer.update();nlo,nhi=bounds([v for o in objects for v in pts(o)]);assert abs(nlo.z-support.z)<1e-5
 checks=[]
 for o in bpy.context.scene.objects:
  if o in objects or o==old or o in props or o==rug or o.type!='MESH' or o.get('audit_kind')!='furniture':continue
  if not str(o.get('program_key','')).startswith(unit+'_'):continue
  xlo,xhi=bounds([o.matrix_world@Vector(v) for v in o.bound_box])
  if not all(nhi[k]>xlo[k] and xhi[k]>nlo[k] for k in range(3)):continue
  t=tree(o);count=sum(len(tree(n).overlap(t)) for n in objects);checks.append({'object':o.name,'surface_intersections':count});assert count==0,(unit,checks)
 moved=[]
 for prop in props:
  plo,phi=bounds(pts(prop));pc=(plo+phi)/2;hits=[tree(o).ray_cast(Vector((pc.x,pc.y,2)),Vector((0,0,-1)),3)[0] for o in objects];hits=[v for v in hits if v is not None];assert hits
  target=max(v.z for v in hits);dz=target-plo.z+.001;prop.location.z+=dz;moved.append({'object':prop.name,'vertical_translation_m':dz,'bottom_gap_m':.001})
 removed=old.name;bpy.data.objects.remove(old,do_unlink=True);rows.append({'unit':unit,'asset':ident,'native_parts':names,'removed':removed,'world_bbox_min_m':list(nlo),'world_bbox_max_m':list(nhi),'native_extents_m':list(hi-lo),'translation_only_m':list(delta),'rug_support_z_m':support.z,'collision_checks':checks,'top_props':moved})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(src)==source_sha;(r/'living107_tables_build.json').write_text(json.dumps({'source':str(src),'source_sha256':source_sha,'candidate':str(out),'candidate_sha256':sha(out),'tables':rows,'scope':'Rigid-only native products, raw triangle furniture overlap checks, rug support and prop center support. Not full nav, closed-volume penetration or photo approval. Branch104 keeps105 basin HOLD out.','accepted':False},indent=2));print('LIVING107_TWO_TABLES_SAVED')
